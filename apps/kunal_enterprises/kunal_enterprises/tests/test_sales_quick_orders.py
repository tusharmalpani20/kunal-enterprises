"""Sales requests retain authenticated attribution and current customer access."""
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from kunal_enterprises.api import quick_orders, orders
from kunal_enterprises.api.token_verification import issue_token
from kunal_enterprises.tests.test_quick_orders import TestQuickOrders as Helpers


class TestSalesQuickOrders(FrappeTestCase):
	_create_product_group = Helpers._create_product_group
	_create_item = Helpers._create_item
	_create_active_customer = Helpers._create_active_customer
	setUp = Helpers.setUp
	tearDown = Helpers.tearDown

	def _employee(self, customers=None):
		doc = frappe.get_doc({'doctype': 'Sales Employee', 'sales_employee_name': self.prefix + uuid4().hex[:6],
			'employee_code': uuid4().hex, 'mobile_number': str(int(uuid4().hex[:12], 16)),
			'status': 'Active', 'assigned_customers': [{'customer': name} for name in (customers or [])]}).insert()
		headers = {'Auth-Token': 'Bearer ' + issue_token('Sales Employee', doc.name)['access_token']}
		return doc, headers

	def _submit(self, headers, customer=None):
		response = quick_orders.submit('Please send 3 units', customer=customer or self.customer.name, headers=headers)
		self.assertTrue(response['success'], response)
		return frappe.get_doc('Quick Order Request', response['data']['request'])

	def test_token_derives_source_and_customer_can_see_sales_request(self):
		employee, headers = self._employee([self.customer.name])
		doc = self._submit(headers)
		self.assertEqual((doc.order_source, doc.sales_employee), ('Sales Employee', employee.name))
		self.assertEqual(doc.sales_employee_name, employee.sales_employee_name)
		self.assertEqual(quick_orders.detail(doc.name, headers=headers)['data']['customer'], self.customer.name)
		self.assertEqual(quick_orders.detail(doc.name, headers=self.headers)['data']['order_source'], 'Sales Employee')
		self.assertEqual(quick_orders.history(headers=self.headers)['data']['requests'][0]['request'], doc.name)
		self.assertFalse(quick_orders.submit('text', headers=headers)['success'])
		self.assertFalse(quick_orders.submit('text', self.customer.name, headers=headers, sales_employee='spoof')['success'])
		self.assertFalse(quick_orders.submit('text', self.customer.name, headers=self.headers, sales_employee=employee.name)['success'])

	def test_other_employee_and_customer_scope_are_denied(self):
		employee, headers = self._employee([self.customer.name])
		doc = self._submit(headers)
		other_employee, other_headers = self._employee([self.customer.name])
		self.assertFalse(quick_orders.detail(doc.name, headers=other_headers)['success'])
		self.assertEqual(quick_orders.history(headers=other_headers)['data']['requests'], [])
		other = self._create_active_customer(str(int(uuid4().hex[:12], 16)), self.prefix + ' other')
		self.assertFalse(quick_orders.submit('text', other.name, headers=headers)['success'])
		self.assertFalse(quick_orders.detail(doc.name, customer=other.name, headers=headers)['success'])

	def test_all_customer_history_filters_revoked_access_before_pagination(self):
		other = self._create_active_customer(str(int(uuid4().hex[:12], 16)), self.prefix + ' other')
		employee, headers = self._employee([self.customer.name, other.name])
		first = self._submit(headers)
		second = self._submit(headers, other.name)
		page = quick_orders.history(headers=headers, limit=1)['data']
		self.assertTrue(page['has_more'])
		self.assertEqual(len(page['requests']), 1)
		employee.set('assigned_customers', [{'customer': other.name}]); employee.save()
		self.assertFalse(quick_orders.detail(first.name, headers=headers)['success'])
		page = quick_orders.history(headers=headers, limit=1)['data']
		self.assertEqual([row['request'] for row in page['requests']], [second.name])
		self.assertFalse(page['has_more'])
		self.assertFalse(quick_orders.submit('text', self.customer.name, headers=headers)['success'])
		frappe.db.set_value('Customer', other.name, 'status', 'Disabled')
		self.assertFalse(quick_orders.detail(second.name, headers=headers)['success'])
		self.assertEqual(quick_orders.history(headers=headers)['data']['requests'], [])

	def test_disabled_employee_cannot_submit_list_or_read(self):
		employee, headers = self._employee([self.customer.name])
		doc = self._submit(headers)
		frappe.db.set_value('Sales Employee', employee.name, 'status', 'Disabled')
		self.assertFalse(quick_orders.submit('text', self.customer.name, headers=headers)['success'])
		self.assertFalse(quick_orders.history(headers=headers)['success'])
		self.assertFalse(quick_orders.detail(doc.name, headers=headers)['success'])

	def test_attribution_is_immutable_and_conversion_keeps_sales_source_and_note(self):
		employee, headers = self._employee([self.customer.name])
		doc = self._submit(headers)
		self.assertTrue(quick_orders.start_review(doc.name)['success'])
		for field, value in [('order_source', 'Customer'), ('sales_employee', None)]:
			doc.reload(); doc.set(field, value)
			with self.assertRaises(frappe.ValidationError):
				doc.save()
		doc.reload()
		result = quick_orders.convert(doc.name, [{'item': self.item.name, 'quantity': 3}])
		self.assertTrue(result['success'], result)
		doc.reload(); order = frappe.get_doc('Order', doc.order)
		self.assertEqual((order.order_source, order.sales_employee), ('Sales Employee', employee.name))
		self.assertEqual(order.quick_order_request, doc.name)
		feed = orders.history(sales_employee=employee.name, headers=headers, include_quick_orders=1)['data']['orders']
		self.assertEqual([row['name'] for row in feed], [order.name])
		self.assertEqual(feed[0]['quick_order_request'], doc.name)
		detail = orders.detail(order.name, sales_employee=employee.name, headers=headers)
		self.assertTrue(detail['success'], detail)
		self.assertEqual(detail['data']['quick_order_text'], doc.text)
		self.assertEqual(orders.detail(order.name, customer=self.customer.name, headers=self.headers)['data']['quick_order_text'], doc.text)
		employee.set('assigned_customers', [{'customer': self._create_active_customer(str(int(uuid4().hex[:12], 16)), self.prefix + ' other').name}]); employee.save()
		self.assertFalse(orders.detail(order.name, sales_employee=employee.name, headers=headers)['success'])
		self.assertEqual(orders.history(sales_employee=employee.name, headers=headers, include_quick_orders=1)['data']['orders'], [])

	def test_conversion_revalidates_employee_access_and_product_scope(self):
		employee, headers = self._employee([self.customer.name])
		doc = self._submit(headers)
		self.assertTrue(quick_orders.start_review(doc.name)['success'])
		frappe.db.set_value('Sales Employee', employee.name, 'status', 'Disabled')
		self.assertFalse(quick_orders.convert(doc.name, [{'item': self.item.name, 'quantity': 3}])['success'])
		doc.reload(); self.assertFalse(doc.order)
		self.assertFalse(frappe.db.exists('Order', {'quick_order_request': doc.name}))

	def test_review_and_conversion_use_employee_product_scope(self):
		employee, headers = self._employee([self.customer.name])
		doc = self._submit(headers)
		self.assertTrue(quick_orders.start_review(doc.name)['success'])
		other_group = self._create_product_group(self.prefix + ' forbidden')
		employee.set('product_group_access', [{'product_group': other_group.name}]); employee.save()
		options = quick_orders.reviewer_options(doc.name)
		self.assertTrue(options['success'], options)
		self.assertNotIn(self.item.name, [row['name'] for row in options['data']['items']])
		self.assertFalse(quick_orders.convert(doc.name, [{'item': self.item.name, 'quantity': 3}])['success'])
		doc.reload(); self.assertFalse(doc.order)
		self.assertFalse(frappe.db.exists('Order', {'quick_order_request': doc.name}))
