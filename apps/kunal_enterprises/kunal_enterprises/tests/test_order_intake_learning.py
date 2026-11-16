"""Only successful confirmed Orders contribute exact, scoped learning aliases."""
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from kunal_enterprises.integrations import order_intake_learning as learning


class TestOrderIntakeLearning(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.customer = frappe.get_doc(dict(doctype="Customer", customer_name="Learning " + uuid4().hex,
			business_legal_name="Synthetic learning customer", onboarding_source="Tally", tally_guid=uuid4().hex)).insert()
		self.group = frappe.get_doc(dict(doctype="Tally Stock Group", group_name="Learning " + uuid4().hex, is_root=1)).insert()
		self.item = frappe.get_doc(dict(doctype="Tally Item", item_name="Learning " + uuid4().hex, root_stock_group=self.group.name)).insert()
		self.godown = frappe.get_doc(dict(doctype="Tally Godown", godown_name="Learning " + uuid4().hex)).insert()
		self.account = frappe.get_doc(dict(doctype="WhatsApp Account", account_name="Learning " + uuid4().hex,
			phone_id=uuid4().hex, status="Active")).insert(ignore_permissions=True)
		self.request = frappe.get_doc(dict(doctype="Order Intake Request", customer=self.customer.name,
			whatsapp_account=self.account.name, sender_number="919000000095", customer_text="Synthetic alias",
			items=[dict(original_text="21317 MR", item=self.item.name, godown=self.godown.name, warehouse_text="Local depot", quantity=1)])).insert()
		# SQL-only fixture avoids the Order notification/PDF workflow. The learning
		# service still reloads real persisted root/child records under locks.
		self.order = frappe.get_doc(dict(doctype="Order", name="learning-order-" + uuid4().hex, customer=self.customer.name,
			status="Placed", confirmation_datetime=now_datetime(), items=[dict(item=self.item.name, item_name_at_order=self.item.item_name,
			requested_quantity=1, pending_quantity=1)], godown_allocations=[dict(item=self.item.name, godown=self.godown.name,
			requested_quantity=1, pending_quantity=1)]))
		self.order.db_insert()
		for table in ("items", "godown_allocations"):
			for row in self.order.get(table):
				row.parent = self.order.name
				row.db_insert()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def confirm(self):
		frappe.db.set_value("Order Intake Request", self.request.name, dict(status="Converted to Order", order=self.order.name))
		return learning.record_confirmation(self.request.name, self.order.name)

	def lookup(self, kind="item", text="21317 MR", **changes):
		args = dict(kind=kind, text=text, account=self.account.name, sender="+91 90000 00095", customer=self.customer.name)
		args.update(changes)
		return learning.lookup_confirmed(**args)

	def test_draft_and_forged_in_memory_confirmation_cannot_teach(self):
		self.request.status = "Converted to Order"; self.request.order = self.order.name
		with self.assertRaises(frappe.ValidationError):
			learning.record_confirmation(self.request, self.order)
		self.assertFalse(self.lookup()["candidates"])

	def test_confirmation_is_idempotent_and_scoped_to_chat_customer_and_exact_wording(self):
		self.assertGreater(self.confirm(), 0)
		self.assertEqual(learning.record_confirmation(self.request.name, self.order.name), 0)
		self.assertEqual(self.lookup(text=" 21317  mr ")["selected"], self.item.name)
		for changes in (dict(sender="919000000096"), dict(account="other-account"), dict(customer=None), dict(customer="other-customer"), dict(text="21317 MR+")):
			self.assertFalse(self.lookup(**changes)["candidates"])
		self.assertEqual(self.lookup("godown", "Local depot")["selected"], self.godown.name)

	def test_conflicting_confirmed_aliases_remain_ambiguous(self):
		other = frappe.get_doc(dict(doctype="Tally Item", item_name="Learning other " + uuid4().hex,
			root_stock_group=self.group.name)).insert()
		self.request.append("items", dict(original_text="21317 MR", item=other.name, quantity=1))
		self.request.save()
		row = self.order.append("items", dict(item=other.name, item_name_at_order=other.item_name,
			requested_quantity=1, pending_quantity=1))
		row.db_insert()
		self.confirm()
		result = self.lookup()
		self.assertEqual({row["name"] for row in result["candidates"]}, {self.item.name, other.name})
		self.assertIsNone(result["selected"])

	def test_reassigned_warehouse_does_not_keep_teaching_old_dispatch_pair(self):
		self.confirm()
		frappe.db.set_value("Order Godown Allocation", self.order.godown_allocations[0].name, "godown", "different-warehouse")
		self.assertFalse(self.lookup("godown", "Local depot")["candidates"])
		self.assertEqual(self.lookup()["selected"], self.item.name)

	def test_cancellation_excludes_evidence_even_before_hook_then_deactivates_audit_rows(self):
		self.confirm()
		frappe.db.set_value("Order", self.order.name, "status", "Cancelled")
		self.assertFalse(self.lookup()["candidates"])
		self.order.status = "Cancelled"
		learning.order_changed(self.order)
		self.assertEqual(frappe.db.count(learning.DT, {"source_order": self.order.name, "active": 1}), 0)
		self.assertGreater(frappe.db.count(learning.DT, {"source_order": self.order.name}), 0)

	def test_mismatched_order_item_or_godown_cannot_teach(self):
		frappe.db.set_value("Order Item", self.order.items[0].name, "item", "missing-item")
		with self.assertRaises(frappe.ValidationError):
			self.confirm()
		self.assertEqual(frappe.db.count(learning.DT, {"source_order": self.order.name}), 0)

	def test_ordinary_document_writes_and_deletes_are_rejected(self):
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(dict(doctype=learning.DT, kind="item", selected_master=self.item.name)).insert(ignore_permissions=True)
		self.confirm()
		name = frappe.db.get_value(learning.DT, {"source_order": self.order.name}, "name")
		doc = frappe.get_doc(learning.DT, name); doc.active = 0
		with self.assertRaises(frappe.PermissionError):
			doc.save(ignore_permissions=True)
		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc(learning.DT, name, ignore_permissions=True)

	def test_learning_and_confirmation_follow_caller_rollback(self):
		frappe.db.savepoint("before_learning")
		self.confirm()
		self.assertTrue(self.lookup()["selected"])
		frappe.db.rollback(save_point="before_learning")
		self.assertEqual(frappe.db.count(learning.DT, {"source_order": self.order.name}), 0)
		self.assertEqual(frappe.db.get_value("Order Intake Request", self.request.name, "status"), "Pending Review")

	def test_confirmed_evidence_prefills_a_new_draft_through_the_reviewer_api(self):
		from kunal_enterprises.api.order_intake_matching import match_request
		self.confirm()
		count=frappe.db.count(learning.DT)
		doc=frappe.get_doc(dict(doctype='Order Intake Request',customer=self.customer.name,
			whatsapp_account=self.account.name,sender_number='919000000095',
			items=[dict(original_text='21317 MR',warehouse_text='Local depot',quantity=2)])).insert()
		match_request(doc.name,str(doc.modified));doc.reload()
		self.assertEqual(doc.items[0].item,self.item.name)
		self.assertEqual(doc.items[0].godown,self.godown.name)
		self.assertEqual(doc.items[0].quantity,2)
		self.assertEqual(frappe.db.count(learning.DT),count)

	def feedback_source(self):
		source = frappe.get_doc(dict(doctype='WhatsApp Message', type='Incoming', whatsapp_account=self.account.name,
			**{'from': self.request.sender_number}, message='Please book 21317 MR, one sheet',
			message_id=uuid4().hex, content_type='text')).insert(ignore_permissions=True)
		self.request.append('source_messages', dict(message=source.name))
		self.request.save()
		return source

	def test_type_and_mapping_corrections_record_the_baseline_and_reasons_only_on_confirmation(self):
		import json
		self.feedback_source()
		frappe.db.set_value('Order Intake Request', self.request.name, dict(ai_initial_values=json.dumps(dict(
			request_type='Stock Inquiry', customer=None, items=[dict(row_key=self.request.items[0].row_key, item=None, godown=None)])),
			correction_reason='Customer confirmed purchase', request_type='Order'))
		self.assertEqual(frappe.db.count(learning.DT, {'source_request': self.request.name}), 0)
		self.confirm()
		rows = frappe.get_all(learning.DT, filters={'source_request': self.request.name},
			fields=['kind', 'selected_master', 'suggested_value', 'correction_reason', 'was_corrected', 'message_excerpt'])
		type_row = next(row for row in rows if row.kind == 'request_type')
		self.assertEqual(type_row.suggested_value, 'Stock Inquiry')
		self.assertEqual(type_row.selected_master, 'Order')
		self.assertEqual(type_row.correction_reason, 'Customer confirmed purchase')
		self.assertEqual(type_row.was_corrected, 1)
		self.assertIn('Please book', type_row.message_excerpt)
		self.assertTrue(next(row for row in rows if row.kind == 'item').was_corrected)
		self.assertEqual(learning.record_confirmation(self.request.name, self.order.name), 0)
		self.order.status = 'Cancelled'
		learning.order_changed(self.order)
		self.assertEqual(frappe.db.count(learning.DT, {'source_request': self.request.name, 'active': 1}), 0)

	def test_handled_inquiry_records_only_type_correction_and_rejects_fake_in_memory_state(self):
		import json
		from kunal_enterprises.integrations.order_intake_feedback import record_inquiry_confirmation
		self.feedback_source()
		self.request.status = 'Resolved'
		with self.assertRaises(frappe.ValidationError):
			record_inquiry_confirmation(self.request)
		frappe.db.set_value('Order Intake Request', self.request.name, dict(status='Resolved', request_type='Price Inquiry',
			processed_at=now_datetime(), reviewed_by='Administrator', correction_reason='Only asks current price',
			ai_initial_values=json.dumps(dict(request_type='Order'))))
		self.assertEqual(record_inquiry_confirmation(self.request.name), 1)
		self.assertEqual(record_inquiry_confirmation(self.request.name), 0)
		rows = frappe.get_all(learning.DT, filters={'source_request': self.request.name}, fields=['kind', 'source_order', 'selected_master'])
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].kind, 'request_type')
		self.assertEqual(rows[0].selected_master, 'Price Inquiry')
		self.assertFalse(rows[0].source_order)

	def test_inactive_items_and_godowns_are_not_reused_by_deterministic_learning(self):
		self.confirm()
		frappe.db.set_value('Tally Item', self.item.name, 'is_active', 0)
		self.assertFalse(self.lookup()['candidates'])
		frappe.db.set_value('Tally Item', self.item.name, 'is_active', 1)
		frappe.db.set_value('Tally Godown', self.godown.name, 'is_active', 0)
		self.assertFalse(self.lookup('godown', 'Local depot')['candidates'])
		self.assertEqual(self.lookup()['selected'], self.item.name)

	def test_rehandled_inquiry_replaces_old_feedback_and_return_to_baseline_clears_learning(self):
		import json
		from kunal_enterprises.integrations.order_intake_feedback import record_inquiry_confirmation
		self.feedback_source()
		frappe.db.set_value('Order Intake Request', self.request.name, dict(status='Resolved', request_type='Price Inquiry',
			processed_at=now_datetime(), reviewed_by='Administrator', correction_reason='Only asks current price',
			ai_initial_values=json.dumps(dict(request_type='Stock Inquiry'))))
		self.assertEqual(record_inquiry_confirmation(self.request.name), 1)
		first = frappe.db.get_value(learning.DT, {'source_request': self.request.name}, 'name')
		# A new handled event replaces its earlier correction, even if only the
		# reason or source text changed while the final inquiry type stayed equal.
		frappe.db.set_value('Order Intake Request', self.request.name, dict(processed_at=now_datetime(),
			correction_reason='Corrected explanation after re-review'))
		self.assertEqual(record_inquiry_confirmation(self.request.name), 1)
		self.assertEqual(frappe.db.get_value(learning.DT, first, 'active'), 0)
		active = frappe.get_all(learning.DT, filters={'source_request': self.request.name, 'active': 1}, fields=['correction_reason'])
		self.assertEqual(len(active), 1)
		self.assertEqual(active[0].correction_reason, 'Corrected explanation after re-review')
		self.assertEqual(record_inquiry_confirmation(self.request.name), 0)
		# Returning to the AI's original type is still a new confirmation and
		# must retire prior contradictory learning, without inventing a correction.
		frappe.db.set_value('Order Intake Request', self.request.name, dict(processed_at=now_datetime(), request_type='Stock Inquiry'))
		self.assertEqual(record_inquiry_confirmation(self.request.name), 0)
		self.assertEqual(frappe.db.count(learning.DT, {'source_request': self.request.name, 'active': 1}), 0)

	def test_truncated_type_source_remains_auditable_but_is_explicitly_marked(self):
		import json
		from kunal_enterprises.integrations.order_intake_feedback import record_inquiry_confirmation
		source = self.feedback_source()
		frappe.db.set_value('WhatsApp Message', source.name, 'message', 'Please book these sheets. ' + 'A' * 1100 + '\nDo not book; only checking availability.')
		frappe.db.set_value('Order Intake Request', self.request.name, dict(status='Resolved', request_type='Stock Inquiry',
			processed_at=now_datetime(), reviewed_by='Administrator', ai_initial_values=json.dumps(dict(request_type='Order'))))
		self.assertEqual(record_inquiry_confirmation(self.request.name), 1)
		row = frappe.db.get_value(learning.DT, {'source_request': self.request.name, 'kind': 'request_type'},
			['message_excerpt', 'source_excerpt_truncated'], as_dict=True)
		self.assertEqual(len(row.message_excerpt), 1000)
		self.assertEqual(row.source_excerpt_truncated, 1)
