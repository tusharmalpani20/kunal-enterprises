"""Customer identity, review lifecycle, conversion atomicity and linked Order access."""
from uuid import uuid4
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from kunal_enterprises.api import quick_orders
from kunal_enterprises.api.orders import submit_order
from kunal_enterprises.api.token_verification import issue_token
from kunal_enterprises.tests.test_foundation import TestOrderSubmission as Helpers
from kunal_enterprises.kunal_enterprises.doctype.quick_order_request.quick_order_request import QuickOrderRequest


class TestQuickOrders(FrappeTestCase):
	_create_product_group = Helpers._create_product_group
	_create_item = Helpers._create_item
	_create_active_customer = Helpers._create_active_customer
	_create_role_user = Helpers._create_role_user

	def setUp(self):
		frappe.set_user('Administrator')
		self.prefix = 'Quick ' + uuid4().hex[:10]
		group = self._create_product_group(self.prefix)
		self.item = self._create_item(self.prefix, group.name)
		self.customer = self._create_active_customer(str(int(uuid4().hex[:12], 16)), self.prefix)
		self.headers = {'Auth-Token': 'Bearer ' + issue_token('Customer', self.customer.name)['access_token']}
		self.godown = frappe.get_doc({'doctype': 'Tally Godown', 'godown_name': self.prefix, 'is_active': 1}).insert()

	def tearDown(self):
		frappe.set_user('Administrator')
		frappe.db.rollback()

	def _request(self):
		response = quick_orders.submit('  Please send three units  ', headers=self.headers)
		self.assertTrue(response['success'], response)
		return frappe.get_doc('Quick Order Request', response['data']['request'])

	def _review(self):
		doc = self._request()
		response = quick_orders.start_review(doc.name)
		self.assertTrue(response['success'], response)
		doc.reload()
		doc.append('items', {'item': self.item.name, 'quantity': 3})
		doc.save()
		return doc

	def test_customer_text_submission_and_scoped_history(self):
		doc = self._request()
		self.assertEqual(doc.text, 'Please send three units')
		self.assertEqual(doc.status, 'Pending Review')
		self.assertFalse(doc.items)
		self.assertEqual(quick_orders.detail(doc.name, headers=self.headers)['data']['request'], doc.name)
		self.assertEqual(quick_orders.history(headers=self.headers)['data']['requests'][0]['request'], doc.name)
		for text in ('', 'x' * 5001, {'text': 'hello'}):
			self.assertFalse(quick_orders.submit(text, headers=self.headers)['success'])
		self.assertFalse(quick_orders.submit('hello', customer='another-customer', headers=self.headers)['success'])

	def test_html_looking_customer_text_preserves_literal_original(self):
		text = '<b>Item A</b>\n<script>literal</script>'
		response = quick_orders.submit('  ' + text + '  ', headers=self.headers)
		self.assertTrue(response['success'], response)
		self.assertEqual(response['data']['text'], text)
		self.assertEqual(quick_orders.detail(response['data']['request'], headers=self.headers)['data']['text'], text)

	def test_token_identity_and_other_customer_detail_denied(self):
		doc = self._request()
		other = self._create_active_customer(str(int(uuid4().hex[:12], 16)), self.prefix + ' other')
		headers = {'Auth-Token': 'Bearer ' + issue_token('Customer', other.name)['access_token']}
		self.assertFalse(quick_orders.detail(doc.name, headers=headers)['success'])
		self.assertEqual(quick_orders.history(headers=headers)['data']['requests'], [])
		self.assertFalse(quick_orders.submit('hello', headers={})['success'])
		with patch.object(quick_orders, 'verify_token', return_value=(True, {'identity_type': 'Sales Employee', 'identity': 'employee'})):
			self.assertFalse(quick_orders.submit('hello')['success'])

	def test_pending_items_and_original_text_cannot_be_changed(self):
		doc = self._request()
		doc.append('items', {'item': self.item.name, 'quantity': 3})
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		doc.reload()
		doc.text = 'rewritten request'
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_review_reject_and_closed_audit_fields_are_immutable(self):
		doc = self._review()
		self.assertFalse(quick_orders.reject(doc.name, ' ')['success'])
		self.assertTrue(quick_orders.reject(doc.name, 'Unavailable')['success'])
		for field, value in [('rejection_reason', 'rewritten'), ('reviewed_by', 'Guest'), ('review_started_at', None)]:
			doc.reload()
			doc.set(field, value)
			with self.assertRaises(frappe.ValidationError):
				doc.save()
		self.assertFalse(quick_orders.convert(doc.name)['success'])

	def test_role_guard_denies_review_and_queries(self):
		doc = self._request()
		user = self._create_role_user(self.prefix.replace(' ', '').lower() + '@example.com', 'Godown Allocator')
		frappe.set_user(user.name)
		self.assertFalse(quick_orders.start_review(doc.name)['success'])
		self.assertFalse(quick_orders.reject(doc.name, 'reason')['success'])
		self.assertFalse(quick_orders.convert(doc.name)['success'])
		self.assertFalse(quick_orders.reviewer_options(doc.name)['success'])

	def test_conversion_optional_godown_bidirectional_link_and_idempotency(self):
		doc = self._review()
		response = quick_orders.convert(doc.name)
		self.assertTrue(response['success'], response)
		doc.reload()
		order = frappe.get_doc('Order', doc.order)
		self.assertEqual(order.quick_order_request, doc.name)
		self.assertEqual(order.total_quantity, 3)
		self.assertTrue(order.godown_assignment_pending)
		self.assertEqual(order.status, 'Placed')
		self.assertEqual(doc.status, 'Converted to Order')
		self.assertEqual(doc.portal_reference_number, order.portal_reference_number)
		self.assertEqual(doc.text, 'Please send three units')
		self.assertEqual(quick_orders.convert(doc.name)['data']['order'], order.name)
		self.assertEqual(frappe.db.count('Order', {'quick_order_request': doc.name}), 1)

	def test_conversion_failure_rolls_back_created_order_and_links(self):
		doc = self._review()
		before = frappe.db.count('Order', {'customer': self.customer.name})
		original_save = QuickOrderRequest.save
		def fail_final_save(request_doc, *args, **kwargs):
			if request_doc.status == 'Converted to Order':
				raise frappe.ValidationError('deliberate failure after Order creation')
			return original_save(request_doc, *args, **kwargs)
		with patch.object(QuickOrderRequest, 'save', fail_final_save):
			self.assertFalse(quick_orders.convert(doc.name)['success'])
		doc.reload()
		self.assertEqual(doc.status, 'In Review')
		self.assertFalse(doc.order)
		self.assertEqual(frappe.db.count('Order', {'customer': self.customer.name}), before)

	def test_conversion_requires_review_and_valid_quantities(self):
		doc = self._request()
		self.assertFalse(quick_orders.convert(doc.name, [{'item': self.item.name, 'quantity': 3}])['success'])
		self.assertTrue(quick_orders.start_review(doc.name)['success'])
		for allocations in ([], [{'item': self.item.name, 'quantity': -1}], [{'item': self.item.name, 'quantity': float('inf')}]):
			self.assertFalse(quick_orders.convert(doc.name, allocations)['success'])
		self.assertFalse(frappe.db.get_value('Quick Order Request', doc.name, 'order'))

	def test_coordinator_reads_only_converted_order_and_cannot_write(self):
		doc = self._review()
		user = self._create_role_user(self.prefix.replace(' ', '').lower() + '@example.com', 'Order Coordinator')
		frappe.set_user(user.name)
		response = quick_orders.convert(doc.name)
		self.assertTrue(response['success'], response)
		linked = frappe.get_doc('Order', response['data']['order'])
		frappe.set_user('Administrator')
		unrelated = submit_order(self.customer.name, [{'item': self.item.name, 'quantity': 1}])
		for status in ('Processing', 'Cancelled'):
			# Read policy is independent of the controller's status-transition APIs.
			frappe.db.set_value('Order', linked.name, 'status', status)
			frappe.db.set_value('Order', unrelated.name, 'status', status)
			linked = frappe.get_doc('Order', linked.name)
			unrelated = frappe.get_doc('Order', unrelated.name)
			frappe.set_user(user.name)
			self.assertTrue(linked.has_permission('read'))
			self.assertFalse(linked.has_permission('write'))
			self.assertFalse(unrelated.has_permission('read'))
			self.assertIn(linked.name, frappe.get_list('Order', pluck='name'))
			self.assertNotIn(unrelated.name, frappe.get_list('Order', pluck='name'))
			frappe.set_user('Administrator')

	def test_active_godown_and_customer_item_queries(self):
		doc = self._request()
		inactive = frappe.get_doc({'doctype': 'Tally Godown', 'godown_name': self.prefix + ' inactive', 'is_active': 0}).insert()
		options = quick_orders.reviewer_options(doc.name, search=self.prefix)
		self.assertTrue(options['success'], options)
		self.assertIn(self.item.name, [row['name'] for row in options['data']['items']])
		self.assertIn(self.godown.name, [row['name'] for row in options['data']['godowns']])
		self.assertNotIn(inactive.name, [row['name'] for row in options['data']['godowns']])
		filters = {'quick_order_request': doc.name}
		self.assertIn(self.item.name, [row[0] for row in quick_orders.allowed_item_query('Tally Item', self.prefix, 'name', 0, 20, filters)])
		self.assertNotIn(inactive.name, [row[0] for row in quick_orders.allowed_godown_query('Tally Godown', self.prefix, 'name', 0, 20, filters)])

	def test_coordinator_link_validation_uses_select_permission_without_generic_read(self):
		from frappe.client import validate_link
		user = self._create_role_user(self.prefix.replace(' ', '').lower() + '@example.com', 'Order Coordinator')
		frappe.set_user(user.name)
		self.assertEqual(validate_link('Tally Item', self.item.name, fields=['item_name'])['name'], self.item.name)
		self.assertEqual(validate_link('Tally Godown', self.godown.name, fields=['godown_name'])['name'], self.godown.name)
		self.assertFalse(self.item.has_permission('read'))
		self.assertFalse(self.godown.has_permission('read'))

	def test_inactive_and_outside_customer_access_items_cannot_be_saved_or_converted(self):
		doc = self._review()
		frappe.db.set_value('Tally Item', self.item.name, 'is_active', 0)
		doc.reload()
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		self.assertFalse(quick_orders.convert(doc.name)['success'])
		frappe.db.set_value('Tally Item', self.item.name, 'is_active', 1)
		other_group = self._create_product_group(self.prefix + ' other')
		self.customer.append('product_group_access', {'product_group': other_group.name})
		self.customer.save()
		doc.reload()
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		self.assertFalse(quick_orders.convert(doc.name)['success'])

	def test_generic_order_link_forgery_is_rejected(self):
		doc = self._review()
		order = submit_order(self.customer.name, [{'item': self.item.name, 'quantity': 1}])
		order.quick_order_request = doc.name
		with self.assertRaises(frappe.ValidationError):
			order.save(ignore_permissions=True)

	def test_desk_serialized_datetime_fields_allow_review_item_save(self):
		doc = self._review()
		payload = frappe.parse_json(frappe.as_json(doc.as_dict()))
		self.assertIsInstance(payload['confirmation_datetime'], str)
		self.assertIsInstance(payload['review_started_at'], str)
		payload['items'][0]['quantity'] = 4
		desk_doc = frappe.get_doc(payload)
		desk_doc.save()
		self.assertEqual(desk_doc.items[0].quantity, 4)
		payload = frappe.parse_json(frappe.as_json(desk_doc.as_dict()))
		payload['confirmation_datetime'] = '2000-01-01 00:00:00'
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(payload).save()

	def test_generic_desk_json_cannot_supply_internal_transition_flags(self):
		from frappe.desk.form.save import savedocs
		doc = self._request()
		payload = doc.as_dict()
		payload.update({'status': 'In Review', 'reviewed_by': 'Administrator',
			'flags': {'in_quick_order_transition': True, 'in_quick_order_conversion': True}})
		with self.assertRaises(frappe.ValidationError):
			savedocs(frappe.as_json(payload), 'Save')
		self.assertEqual(frappe.db.get_value('Quick Order Request', doc.name, 'status'), 'Pending Review')

	def test_closed_request_child_labels_and_identities_are_immutable(self):
		doc = self._review()
		self.assertTrue(quick_orders.convert(doc.name)['success'])
		for field, value in [('item_name', 'falsified product'), ('name', 'new-quick-order-request-item-forged')]:
			doc.reload()
			payload = frappe.parse_json(frappe.as_json(doc.as_dict()))
			payload['items'][0][field] = value
			with self.assertRaises(frappe.ValidationError):
				frappe.get_doc(payload).save()

	def test_unified_history_shared_pagination_and_customer_isolation(self):
		from kunal_enterprises.api.orders import history
		request_one = self._request()
		order_one = submit_order(self.customer.name, [{'item': self.item.name, 'quantity': 1}])
		request_two = self._request()
		order_two = submit_order(self.customer.name, [{'item': self.item.name, 'quantity': 2}])
		for doc in (request_one, order_one, request_two, order_two):
			frappe.db.set_value(doc.doctype, doc.name, 'confirmation_datetime', '2026-01-01 12:00:00')
		other = self._create_active_customer(str(int(uuid4().hex[:12], 16)), self.prefix + ' other')
		other_headers = {'Auth-Token': 'Bearer ' + issue_token('Customer', other.name)['access_token']}
		self.assertTrue(quick_orders.submit('other private text', headers=other_headers)['success'])
		expected = sorted([doc.name for doc in (request_one, order_one, request_two, order_two)], reverse=True)
		first = history(headers=self.headers, include_quick_orders=1, limit=2)['data']
		second = history(headers=self.headers, include_quick_orders=1, limit=2, offset=2)['data']
		self.assertEqual([row['name'] for row in first['orders'] + second['orders']], expected)
		self.assertEqual({row['entry_type'] for row in first['orders'] + second['orders']}, {'order', 'quick_order'})
		self.assertTrue(first['has_more']); self.assertEqual(first['next_offset'], 2)
		self.assertFalse(second['has_more']); self.assertIsNone(second['next_offset'])
		self.assertEqual(len(history(self.customer.name, headers=self.headers)['data']['orders']), 2)
		self.assertFalse(history(other.name, headers=self.headers, include_quick_orders=1)['success'])

	def test_unified_history_conversion_has_one_entry_and_customer_detail_original_text(self):
		from kunal_enterprises.api.orders import history, detail
		doc = self._review()
		self.assertTrue(quick_orders.convert(doc.name)['success'])
		doc.reload()
		rows = history(headers=self.headers, include_quick_orders=1)['data']['orders']
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]['entry_type'], 'order')
		self.assertEqual(rows[0]['quick_order_request'], doc.name)
		data = detail(doc.order, self.customer.name, headers=self.headers)['data']
		self.assertEqual(data['quick_order_request'], doc.name)
		self.assertEqual(data['quick_order_text'], doc.text)
		self.assertNotIn('quick_order_text', detail(doc.order, self.customer.name)['data'])

	def test_unified_history_requires_customer_token(self):
		from kunal_enterprises.api.orders import history
		self.assertFalse(history(self.customer.name, include_quick_orders=1, headers={})['success'])
		with patch.object(quick_orders, 'verify_token', return_value=(True, {'identity_type': 'Sales Employee', 'identity': 'employee'})):
			self.assertFalse(history(self.customer.name, sales_employee='employee', include_quick_orders=1)['success'])
