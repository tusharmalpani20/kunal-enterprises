from unittest import TestCase
from unittest.mock import patch
from datetime import timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import get_system_timezone, now_datetime

from kunal_enterprises.integrations import sales_order_whatsapp as alerts
from kunal_enterprises.integrations.customer_contacts import normalize_phone
from kunal_enterprises.integrations.sales_order_whatsapp import format_message


class TestSalesOrderWhatsAppText(TestCase):
	def test_groups_quantities_by_dispatch_warehouse(self):
		url = 'https://portal.example.com/app/order/ORD-001'
		message = format_message('Salesperson', 'Example Customer', 'REF-001', 'Customer', [
			('Kukatpally', '21022 SF', 2, 'NOS'), ('Kukatpally', '21069 SF', 5, 'NOS'),
			('Goshamahal', '21022 SF', 1.5, 'NOS'), (None, '21317 MR+', 4, '')], url)
		self.assertIn('Customer: Example Customer\nOrder reference: REF-001\nPlaced by: Customer', message)
		self.assertIn('*Dispatch from Kukatpally*\n• 21022 SF — 2 NOS\n• 21069 SF — 5 NOS', message)
		self.assertIn('*Dispatch from Goshamahal*\n• 21022 SF — 1.5 NOS', message)
		self.assertIn('*Dispatch warehouse pending*\n• 21317 MR+ — 4', message)
		self.assertTrue(message.endswith(url))

	def test_long_orders_preserve_the_portal_link(self):
		url = 'https://portal.example.com/app/order/ORD-001'
		message = format_message('Salesperson', 'Example Customer', 'REF-001', 'Other salesperson',
			[('Godown', str(i) + ' item ' + 'x' * 160, 1, 'NOS') for i in range(100)], url)
		self.assertLessEqual(len(message), 4000)
		self.assertIn('More items are listed in the portal.', message)
		self.assertTrue(message.endswith(url))


class TestSalesOrderWhatsAppDispatch(FrappeTestCase):
	def setUp(self):
		frappe.set_user('Administrator')
		self.tag = 'alert-' + uuid4().hex[:14]
		self.customer = frappe.get_doc(dict(doctype='Customer', customer_name=self.tag,
			business_legal_name=self.tag, mobile_number='7' + str(uuid4().int)[:9])).insert()
		group = frappe.get_doc(dict(doctype='Tally Stock Group', group_name=self.tag, is_root=1)).insert()
		self.item = frappe.get_doc(dict(doctype='Tally Item', item_name=self.tag, root_stock_group=group.name, uom='NOS')).insert()
		self.godown = frappe.get_doc(dict(doctype='Tally Godown', godown_name=self.tag, is_active=1)).insert()
		frappe.db.set_value('WhatsApp Account', {'is_default_outgoing': 1}, 'is_default_outgoing', 0)
		self.account = self.account_record(True)
		self.portal = patch.dict(frappe.conf, {'sales_portal_url': 'https://portal.example.com'})
		self.portal.start()
		self.addCleanup(self.portal.stop)
		# Keep fixtures in the test transaction, and run the worker explicitly.
		publisher = patch.object(alerts, '_publish')
		publisher.start()
		self.addCleanup(publisher.stop)

	def tearDown(self):
		frappe.db.rollback()

	def employee(self, *, assigned=True, muted=False):
		doc = frappe.get_doc(dict(doctype='Sales Employee', sales_employee_name=self.tag,
			mobile_number='8' + str(uuid4().int)[:9], status='Active',
			assigned_customers=[dict(customer=self.customer.name)] if assigned else []))
		if muted:
			doc.sales_order_whatsapp_opt_out = 1
		return doc.insert()

	def account_record(self, default=False):
		key = uuid4().hex
		return frappe.get_doc(dict(doctype='WhatsApp Account', account_name=self.tag + key[:6],
			phone_id=str(int(key[:12], 16)), status='Active', is_default_outgoing=default,
			allow_auto_read_receipt=0)).insert(ignore_permissions=True)

	def order(self, placer=None):
		return frappe.get_doc(dict(doctype='Order', portal_reference_number=uuid4().hex,
			order_source='Sales Employee' if placer else 'Customer', customer=self.customer.name,
			sales_employee=placer.name if placer else None, status='Placed', confirmation_datetime=now_datetime(),
			items=[dict(item=self.item.name, item_name_at_order='21022 SF', requested_quantity=5, unit='NOS')],
			godown_allocations=[dict(item=self.item.name, godown=self.godown.name, requested_quantity=2)],
		)).insert(ignore_permissions=True)

	def message(self, employee, hours=1, account=None, direction='Incoming'):
		account = account or self.account
		number = normalize_phone(employee.mobile_number)
		message_id = uuid4().hex
		sent = now_datetime() - timedelta(hours=hours)
		payload = {'metadata': {'phone_number_id': account.phone_id}, 'message': {'id': message_id,
			'from': number, 'type': 'text', 'timestamp': str(int(sent.replace(tzinfo=ZoneInfo(get_system_timezone())).timestamp()))}}
		message = frappe.get_doc(dict(doctype='WhatsApp Message', type=direction, whatsapp_account=account.name,
			content_type='text', message_id=message_id, intake_original_type='text', intake_phone_id=account.phone_id,
			intake_sender_key=number, intake_sent_at=sent, intake_raw_payload=frappe.as_json(payload)))
		message.db_insert()
		return message

	def queued(self, order):
		return frappe.get_all(alerts.NOTIFICATION, filters={'order': order.name},
			fields=['name', 'recipient_sales_employee'], order_by='name')

	def run_dispatch(self, name):
		with patch.object(frappe.db, 'commit'):
			alerts.dispatch(name)
		return frappe.get_doc(alerts.NOTIFICATION, name)

	def test_new_orders_target_assignments_except_placer_without_requiring_portal_users(self):
		placer = self.employee()
		colleague = self.employee()
		self.employee(assigned=False)
		self.employee(muted=True)
		customer_order = self.order()
		self.assertEqual({row.recipient_sales_employee for row in self.queued(customer_order)}, {placer.name, colleague.name})
		placed = self.order(placer)
		alerts.queue_order(placed)
		self.assertEqual([row.recipient_sales_employee for row in self.queued(placed)], [colleague.name])
		self.assertFalse(colleague.portal_user)

	def test_dispatch_uses_only_recent_incoming_messages_on_default_outgoing_account(self):
		employee = self.employee()
		self.message(employee, account=self.account_record())
		self.message(employee, hours=25)
		self.message(employee, direction='Outgoing')
		with patch.object(alerts, '_send_text') as send:
			order = self.order()
			skipped = self.run_dispatch(self.queued(order)[0].name)
			self.assertEqual(skipped.status, 'Skipped')
			self.assertIn('within the last 24 hours', skipped.skip_reason)
			send.assert_not_called()
			self.message(employee)
			order = self.order()
			send.return_value = uuid4().hex
			pending = self.queued(order)[0].name
			self.assertEqual(self.run_dispatch(pending).status, 'Sent')
			self.assertEqual(self.run_dispatch(pending).status, 'Sent')
			send.assert_called_once()
			account, phone, text = send.call_args.args
			self.assertEqual(account.name, self.account.name)
			self.assertEqual(phone, normalize_phone(employee.mobile_number))
			self.assertIn('• 21022 SF — 2 NOS', text)
			self.assertIn('*Dispatch warehouse pending*\n• 21022 SF — 3 NOS', text)
			self.assertTrue(text.endswith('https://portal.example.com/app/order/' + order.name))
			self.assertFalse(frappe.db.get_value(alerts.NOTIFICATION, pending, 'order_pdf'))
			self.assertTrue(frappe.db.exists('WhatsApp Message', {'message_id': send.return_value, 'type': 'Outgoing'}))

	def test_opt_out_after_placement_skips_the_notification(self):
		employee = self.employee()
		self.message(employee)
		order = self.order()
		employee.sales_order_whatsapp_opt_out = 1
		employee.save()
		with patch.object(alerts, '_send_text') as send:
			self.assertEqual(self.run_dispatch(self.queued(order)[0].name).status, 'Skipped')
			send.assert_not_called()

	def test_corrected_message_routing_does_not_open_the_window(self):
		employee = self.employee()
		other_account = self.account_record()
		reassigned = self.message(employee, account=other_account)
		frappe.db.set_value('WhatsApp Message', reassigned.name,
			dict(whatsapp_account=self.account.name, intake_phone_id=self.account.phone_id))
		other_sender = self.message(self.employee(assigned=False))
		frappe.db.set_value('WhatsApp Message', other_sender.name,
			'intake_sender_key', normalize_phone(employee.mobile_number))
		pending = self.queued(self.order())[0].name
		with patch.object(alerts, '_send_text') as send:
			self.assertEqual(self.run_dispatch(pending).status, 'Skipped')
			send.assert_not_called()

	def test_changed_customer_does_not_reuse_the_queued_alert(self):
		employee = self.employee()
		self.message(employee)
		order = self.order()
		pending = self.queued(order)[0].name
		customer = frappe.get_doc(dict(doctype='Customer', customer_name=self.tag+' other',
			business_legal_name=self.tag+' other', mobile_number='7'+str(uuid4().int)[:9])).insert()
		employee.append('assigned_customers', {'customer': customer.name})
		employee.save()
		order.customer = customer.name
		order.save()
		with patch.object(alerts, '_send_text') as send:
			result = self.run_dispatch(pending)
			self.assertEqual(result.status, 'Skipped')
			self.assertEqual(result.skip_reason, 'Customer changed after the Order was placed.')
			send.assert_not_called()

	def test_window_must_be_open_at_placement_and_when_dispatched(self):
		employee = self.employee()
		with patch.object(alerts, 'now_datetime', return_value=now_datetime() - timedelta(hours=2)):
			placed_before_contact = self.order()
		self.message(employee)
		expired_employee = self.employee()
		self.message(expired_employee, hours=25)
		with patch.object(alerts, 'now_datetime', return_value=now_datetime() - timedelta(hours=23)):
			placed_before_expiry = self.order()
		with patch.object(alerts, '_send_text') as send:
			self.assertEqual(self.run_dispatch(self.queued(placed_before_contact)[0].name).status, 'Skipped')
			row = next(row for row in self.queued(placed_before_expiry) if row.recipient_sales_employee == expired_employee.name)
			self.assertEqual(self.run_dispatch(row.name).status, 'Skipped')
			send.assert_not_called()

	def test_uncertain_provider_outcome_is_not_automatically_resent(self):
		employee = self.employee()
		self.message(employee)
		pending = self.queued(self.order())[0].name
		with patch.object(alerts, '_send_text', side_effect=alerts.requests.Timeout) as send:
			self.assertEqual(self.run_dispatch(pending).status, 'Failed')
			self.assertEqual(self.run_dispatch(pending).status, 'Failed')
			send.assert_called_once()

	def test_replacing_number_does_not_redirect_a_queued_alert(self):
		employee = self.employee()
		order = self.order()
		employee.mobile_number = '8' + str(uuid4().int)[:9]
		employee.save()
		self.message(employee)
		with patch.object(alerts, '_send_text') as send:
			result = self.run_dispatch(self.queued(order)[0].name)
			self.assertEqual(result.status, 'Skipped')
			self.assertIn('number changed', result.skip_reason)
			send.assert_not_called()

	def test_transport_uses_only_plain_text_on_the_graph_messages_endpoint(self):
		self.account.url = 'https://graph.facebook.com'
		self.account.version = 'v22.0'
		with patch.object(self.account, 'get_password', return_value='test-token'), patch.object(alerts.requests, 'post') as post:
			post.return_value.__enter__.return_value.status_code = 200
			post.return_value.__enter__.return_value.json.return_value = {'messages': [{'id': 'test-id'}]}
			self.assertEqual(alerts._send_text(self.account, '919000000095', 'Order alert'), 'test-id')
			post.assert_called_once()
			self.assertEqual(post.call_args.args[0], f'https://graph.facebook.com/v22.0/{self.account.phone_id}/messages')
			self.assertEqual(post.call_args.kwargs['json'], {'messaging_product': 'whatsapp', 'to': '919000000095',
				'type': 'text', 'text': {'body': 'Order alert', 'preview_url': False}})
			self.assertFalse(post.call_args.kwargs['allow_redirects'])
