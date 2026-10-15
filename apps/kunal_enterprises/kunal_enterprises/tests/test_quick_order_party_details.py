"""Fetched Quick Order party details and the upgrade backfill preserve request history."""
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from kunal_enterprises.api import quick_orders
from kunal_enterprises.api.token_verification import issue_token
from kunal_enterprises.patches import backfill_quick_order_party_details as backfill
from kunal_enterprises.tests.test_quick_orders import TestQuickOrders as Helpers


CUSTOMER_FETCHES = {
	'customer_name': 'customer_name',
	'customer_business_name': 'business_legal_name',
	'customer_code': 'client_code',
	'customer_mobile_number': 'mobile_number',
	'customer_gstin': 'gstin',
}
EMPLOYEE_FETCHES = {
	'sales_employee_name': 'sales_employee_name',
	'sales_employee_code': 'employee_code',
	'sales_employee_mobile_number': 'mobile_number',
}


class TestQuickOrderPartyDetails(FrappeTestCase):
	_create_product_group = Helpers._create_product_group
	_create_item = Helpers._create_item
	_create_active_customer = Helpers._create_active_customer
	setUp = Helpers.setUp
	tearDown = Helpers.tearDown
	_request = Helpers._request

	def _sales_request(self):
		employee = frappe.get_doc({'doctype': 'Sales Employee',
			'sales_employee_name': self.prefix + ' Employee', 'employee_code': self.prefix + uuid4().hex[:6],
			'mobile_number': str(int(uuid4().hex[:12], 16)), 'status': 'Active',
			'assigned_customers': [{'customer': self.customer.name}]}).insert()
		headers = {'Auth-Token': 'Bearer ' + issue_token('Sales Employee', employee.name)['access_token']}
		response = quick_orders.submit('Send three units', customer=self.customer.name, headers=headers)
		self.assertTrue(response['success'], response)
		return frappe.get_doc('Quick Order Request', response['data']['request']), employee

	def _assert_party_details(self, request, employee=None):
		customer = frappe.get_doc('Customer', request.customer)
		for target, source in CUSTOMER_FETCHES.items():
			self.assertEqual(request.get(target) or '', customer.get(source) or '', target)
		for target, source in EMPLOYEE_FETCHES.items():
			self.assertEqual(request.get(target) or '', employee.get(source) if employee else '', target)

	def test_new_customer_request_fetches_customer_only(self):
		# A populated master GSTIN exercises the optional fetched value too.
		frappe.db.set_value('Customer', self.customer.name, 'gstin', '36ABCDE1234F1Z5')
		request = self._request()
		self._assert_party_details(request)
		self.assertEqual(request.order_source, 'Customer')
		self.assertFalse(request.sales_employee)

	def test_new_sales_request_fetches_customer_and_employee_details(self):
		request, employee = self._sales_request()
		self._assert_party_details(request, employee)
		self.assertEqual(request.order_source, 'Sales Employee')
		self.assertEqual(request.sales_employee, employee.name)

	def test_backfill_populates_existing_lifecycle_states_without_changing_history(self):
		pending, employee = self._sales_request()
		rejected, rejected_employee = self._sales_request()
		self.assertTrue(quick_orders.reject(rejected.name, 'Unavailable')['success'])
		converted, converted_employee = self._sales_request()
		self.assertTrue(quick_orders.start_review(converted.name)['success'])
		response = quick_orders.convert(converted.name, [{'item': self.item.name, 'quantity': 3}])
		self.assertTrue(response['success'], response)
		customer_request = self._request()
		requests = [(pending, employee), (rejected, rejected_employee),
			(converted, converted_employee), (customer_request, None)]
		history_fields = ['name', 'customer', 'status', 'text', 'confirmation_datetime',
			'creation', 'modified', 'modified_by', 'order', 'portal_reference_number',
			'order_source', 'sales_employee', 'reviewed_by', 'review_started_at', 'rejection_reason']
		before = {}
		for request, _ in requests:
			frappe.db.set_value('Quick Order Request', request.name,
				{field: None for field in backfill.PARTY_DETAIL_FIELDS}, update_modified=False)
			before[request.name] = frappe.db.get_value('Quick Order Request', request.name, history_fields, as_dict=True)
		versions_before = frappe.db.count('Version', {'ref_doctype': 'Quick Order Request'})
		backfill.execute()
		for request, employee_doc in requests:
			request.reload()
			self._assert_party_details(request, employee_doc)
			self.assertEqual(frappe.db.get_value('Quick Order Request', request.name, history_fields, as_dict=True), before[request.name])
		self.assertEqual(frappe.db.count('Version', {'ref_doctype': 'Quick Order Request'}), versions_before)
		first_results = {request.name: frappe.db.get_value('Quick Order Request', request.name,
			list(backfill.PARTY_DETAIL_FIELDS) + history_fields, as_dict=True) for request, _ in requests}
		backfill.execute()
		for request, _ in requests:
			self.assertEqual(frappe.db.get_value('Quick Order Request', request.name,
				list(backfill.PARTY_DETAIL_FIELDS) + history_fields, as_dict=True), first_results[request.name])

	def test_party_fields_are_readonly_and_fetch_from_the_linked_master(self):
		meta = frappe.get_meta('Quick Order Request')
		for target, source in CUSTOMER_FETCHES.items():
			field = meta.get_field(target)
			self.assertTrue(field.read_only, target)
			self.assertEqual(field.fetch_from, 'customer.' + source, target)
		for target, source in EMPLOYEE_FETCHES.items():
			field = meta.get_field(target)
			self.assertTrue(field.read_only, target)
			self.assertEqual(field.fetch_from, 'sales_employee.' + source, target)
