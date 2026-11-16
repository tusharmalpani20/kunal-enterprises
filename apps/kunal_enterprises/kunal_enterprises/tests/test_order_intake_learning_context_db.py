"""Current source validity controls whether compact examples may be retrieved."""
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from kunal_enterprises.integrations.order_intake_learning_context import confirmed_learning
from kunal_enterprises.tests import test_order_intake_learning as learning_tests


class TestLearningContextValidity(FrappeTestCase):
	def setUp(self):
		# Reuse the established rollback-only Order/masters setup; it inserts no
		# real Order workflow, notification, PDF or external provider call.
		learning_tests.TestOrderIntakeLearning.setUp(self)

	def tearDown(self):
		frappe.set_user('Administrator')
		frappe.db.rollback()

	def snapshot(self, text='21317 MR from Local depot'):
		return dict(whatsapp_account=self.account.name, sender='919000000095', customer=self.customer.name,
			messages=[dict(name='CURRENT', content_type='text', message=text)])

	def test_current_order_cancellation_sender_and_master_validity(self):
		learning_tests.TestOrderIntakeLearning.confirm(self)
		result = confirmed_learning(self.snapshot())
		self.assertEqual({row['kind'] for row in result}, {'item', 'godown'})
		item_example = next(row for row in result if row['kind'] == 'item')
		self.assertEqual(item_example.get('label') or item_example['confirmed'], self.item.item_name)
		frappe.db.set_value('Tally Item', self.item.name, 'is_active', 0)
		self.assertEqual([row['kind'] for row in confirmed_learning(self.snapshot())], ['godown'])
		frappe.db.set_value('Tally Godown', self.godown.name, 'is_active', 0)
		self.assertEqual(confirmed_learning(self.snapshot()), [])
		frappe.db.set_value('Tally Item', self.item.name, 'is_active', 1)
		frappe.db.set_value('Tally Godown', self.godown.name, 'is_active', 1)
		frappe.db.set_value('Order Intake Request', self.request.name, 'sender_number', '919000000096')
		self.assertEqual(confirmed_learning(self.snapshot()), [])
		frappe.db.set_value('Order Intake Request', self.request.name, 'sender_number', '919000000095')
		frappe.db.set_value('Order', self.order.name, 'status', 'Cancelled')
		self.assertEqual(confirmed_learning(self.snapshot()), [])

	def test_handled_inquiry_evidence_stops_when_reopened_or_sender_changes(self):
		frappe.db.set_value('Order Intake Request', self.request.name,
			dict(status='Resolved', request_type='Stock Inquiry', processed_at=now_datetime(), reviewed_by='Administrator', order=None))
		frappe.get_doc(dict(doctype='Order Intake Match Evidence', name='OIME-' + uuid4().hex,
			kind='request_type', original_text='Stock availability for these sheets', selected_master='Stock Inquiry',
			whatsapp_account=self.account.name, sender='919000000095', source_request=self.request.name,
			was_corrected=1, suggested_value='Order', correction_reason='Only asking for stock', active=1)).db_insert()
		snapshot = self.snapshot('Stock availability for these sheets')
		self.assertEqual(confirmed_learning(snapshot)[0]['confirmed'], 'Stock Inquiry')
		frappe.db.set_value('Order Intake Request', self.request.name, 'status', 'Pending Review')
		self.assertEqual(confirmed_learning(snapshot), [])
		frappe.db.set_value('Order Intake Request', self.request.name, 'status', 'Resolved')
		frappe.db.set_value('Order Intake Request', self.request.name, 'sender_number', '919000000096')
		self.assertEqual(confirmed_learning(snapshot), [])

	def test_shared_multi_request_source_is_not_a_request_type_example(self):
		frappe.db.set_value('Order Intake Request', self.request.name,
			dict(status='Resolved', request_type='Stock Inquiry', processed_at=now_datetime(), reviewed_by='Administrator', order=None))
		frappe.get_doc(dict(doctype='Order Intake Match Evidence', name='OIME-' + uuid4().hex,
			kind='request_type', original_text='Stock availability for these sheets', selected_master='Stock Inquiry',
			whatsapp_account=self.account.name, sender='919000000095', source_request=self.request.name,
			was_corrected=1, suggested_value='Order', active=1)).db_insert()
		snapshot = self.snapshot('Stock availability for these sheets')
		self.assertTrue(confirmed_learning(snapshot))
		message = frappe.get_doc(dict(doctype='WhatsApp Message', name='learning-message-' + uuid4().hex,
			type='Incoming', whatsapp_account=self.account.name, message='Stock availability for these sheets', **{'from': '919000000095'}))
		message.db_insert()
		other = frappe.get_doc(dict(doctype='Order Intake Request', request_type='Stock Inquiry',
			whatsapp_account=self.account.name, sender_number='919000000095')).insert()
		for parent in (self.request.name, other.name):
			frappe.get_doc(dict(doctype='Order Intake Source Message', name=uuid4().hex,
				parent=parent, parenttype='Order Intake Request', parentfield='source_messages', message=message.name)).db_insert()
		self.assertEqual(confirmed_learning(snapshot), [])

	def test_edit_after_handling_stops_inquiry_evidence_until_confirmed_again(self):
		frappe.db.set_value('Order Intake Request', self.request.name,
			dict(status='Resolved', request_type='Stock Inquiry', processed_at=now_datetime(), reviewed_by='Administrator', order=None))
		frappe.get_doc(dict(doctype='Order Intake Match Evidence', name='OIME-' + uuid4().hex,
			kind='request_type', original_text='Stock availability for these sheets', selected_master='Stock Inquiry',
			whatsapp_account=self.account.name, sender='919000000095', source_request=self.request.name,
			was_corrected=1, suggested_value='Order', active=1)).db_insert()
		snapshot = self.snapshot('Stock availability for these sheets')
		self.assertTrue(confirmed_learning(snapshot))
		frappe.db.set_value('Order Intake Request', self.request.name, 'correction_reason', 'Changed after confirmation')
		self.assertEqual(confirmed_learning(snapshot), [])

	def test_incomplete_source_excerpt_is_not_classification_guidance(self):
		frappe.db.set_value('Order Intake Request', self.request.name,
			dict(status='Resolved', request_type='Stock Inquiry', processed_at=now_datetime(), reviewed_by='Administrator', order=None))
		evidence = frappe.get_doc(dict(doctype='Order Intake Match Evidence', name='OIME-' + uuid4().hex,
			kind='request_type', original_text='Stock availability for these sheets', message_excerpt='Stock availability for these sheets',
			selected_master='Stock Inquiry', whatsapp_account=self.account.name, sender='919000000095',
			source_request=self.request.name, was_corrected=1, suggested_value='Order', active=1, source_excerpt_truncated=1))
		evidence.db_insert()
		self.assertEqual(confirmed_learning(self.snapshot('Stock availability for these sheets')), [])
