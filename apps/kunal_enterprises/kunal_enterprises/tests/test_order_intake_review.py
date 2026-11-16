"""Review actions retain evidence and protect staff edits and access boundaries."""
import json
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from kunal_enterprises.tests import test_order_intake_ai as fixtures
from kunal_enterprises.tests.test_order_intake_ai import extraction
from kunal_enterprises.integrations.order_intake_ai_models import Group, Grouping


class TestOrderIntakeReview(FrappeTestCase):
	setUp = fixtures.TestOrderIntakeAI.setUp
	tearDown = fixtures.TestOrderIntakeAI.tearDown
	source = fixtures.TestOrderIntakeAI.source
	prepare = fixtures.TestOrderIntakeAI.prepare
	run_ai = fixtures.TestOrderIntakeAI.run_ai
	def test_review_update_preserves_selection_and_history_and_deduplicates(self):
		from kunal_enterprises.api.order_intake import review_update
		from kunal_enterprises.integrations import order_intake_ai as ai
		source = self.source(); anchor = self.prepare()
		created = self.run_ai(anchor, Grouping(groups=[Group(request_hint="Initial", message_ids=[source.name], target_request=None)], unresolved_message_ids=[]), [extraction(source.name)])["created"][0]
		late = self.source(); anchor = self.prepare()
		correction = extraction(late.name); correction.items[0].quantity = 7
		self.run_ai(anchor, Grouping(groups=[Group(request_hint="Correction", message_ids=[late.name], target_request=created)], unresolved_message_ids=[]), [correction])
		doc = frappe.get_doc("Order Intake Request", created)
		before = [{key: value for key, value in row.as_dict().items() if key not in {"modified", "modified_by"}} for row in doc.items]
		result = review_update(created, 0, str(doc.modified))
		doc.reload(); proposals = json.loads(doc.proposed_updates)
		self.assertEqual(result["pending"], 0)
		self.assertTrue(proposals[0]["reviewed_at"])
		self.assertEqual(proposals[0]["reviewed_by"], "Administrator")
		self.assertEqual([{key: value for key, value in row.as_dict().items() if key not in {"modified", "modified_by"}} for row in doc.items], before)
		self.assertEqual(review_update(created, 0, str(doc.modified))["pending"], 0)
		newest = self.source(); anchor = self.prepare()
		correction.items[0].source_message = newest.name
		self.run_ai(anchor, Grouping(groups=[Group(request_hint="Same correction", message_ids=[newest.name], target_request=created)],
			unresolved_message_ids=[]), [correction])
		doc.reload()
		self.assertEqual(len(json.loads(doc.proposed_updates)), 1)

	def test_review_update_rejects_stale_revision_and_unauthorized_user(self):
		from kunal_enterprises.api.order_intake import review_update
		doc = frappe.get_doc(dict(doctype="Order Intake Request")).insert()
		with self.assertRaises(frappe.TimestampMismatchError):
			review_update(doc.name, 0, "2000-01-01 00:00:00")
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			review_update(doc.name, 0, str(doc.modified))

	def test_late_sources_advance_received_time_without_changing_item_selections(self):
		first = self.source(); anchor = self.prepare()
		created = self.run_ai(anchor, Grouping(groups=[Group(request_hint="Initial", message_ids=[first.name], target_request=None)], unresolved_message_ids=[]), [extraction(first.name)])["created"][0]
		late = self.source()
		later = add_to_date(now_datetime(), minutes=2, as_datetime=True)
		frappe.db.set_value("WhatsApp Message", late.name, "intake_received_at", later)
		anchor = self.prepare()
		self.run_ai(anchor, Grouping(groups=[Group(request_hint="Late correction", message_ids=[late.name], target_request=created)], unresolved_message_ids=[]), [extraction(late.name)])
		doc = frappe.get_doc("Order Intake Request", created)
		self.assertEqual(doc.last_received_at, later)
		self.assertEqual(doc.items[0].quantity, 4)

	def test_single_message_multiple_orders_pass_distinct_scope_to_extraction(self):
		from kunal_enterprises.integrations import order_intake_ai as ai
		source = self.source(); anchor = self.prepare(); claim = ai._claim(anchor)
		grouping = Grouping(groups=[Group(request_hint=hint, message_ids=[source.name], target_request=None)
			for hint in ("Customer A laminate", "Customer B adhesive")], unresolved_message_ids=[])
		scopes = []
		def extract(config, payload, media, budget):
			hint = payload["request_scope"]; scopes.append(hint)
			result = extraction(source.name)
			result.customer_text = "Customer A" if "Customer A" in hint else "Customer B"
			result.items[0].original_text = "laminate" if "Customer A" in hint else "adhesive"
			return result
		with patch.object(ai, "group", return_value=grouping), patch.object(ai, "extract", side_effect=extract):
			result = ai.process(anchor, claim["token"], release_transaction=False)
		self.assertEqual(scopes, ["Customer A laminate", "Customer B adhesive"])
		docs = [frappe.get_doc("Order Intake Request", name) for name in result["created"]]
		self.assertEqual([d.items[0].original_text for d in docs], ["laminate", "adhesive"])
		self.assertEqual([d.customer_text for d in docs], ["Customer A", "Customer B"])
		# Closest-match prefill may resolve these labels against installed masters.
		# This regression checks scope separation, independent of master contents.

	def test_reviewed_history_does_not_consume_the_pending_update_limit(self):
		first = self.source(); anchor = self.prepare()
		created = self.run_ai(anchor, Grouping(groups=[Group(request_hint="Initial", message_ids=[first.name], target_request=None)], unresolved_message_ids=[]), [extraction(first.name)])["created"][0]
		doc = frappe.get_doc("Order Intake Request", created)
		doc.proposed_updates = json.dumps([dict(summary="Historical " + str(i), reviewed_at="2026-01-01", reviewed_by="Administrator") for i in range(50)])
		previous = frappe.flags.intake_ai_write
		try:
			frappe.flags.intake_ai_write = True; doc.save()
		finally:
			frappe.flags.intake_ai_write = previous
		late = self.source(); anchor = self.prepare()
		correction = extraction(late.name); correction.items[0].quantity = 7
		result = self.run_ai(anchor, Grouping(groups=[Group(request_hint="New correction", message_ids=[late.name], target_request=created)], unresolved_message_ids=[]), [correction])
		self.assertEqual(result["proposed"], [created])
		self.assertEqual(len(json.loads(doc.reload().proposed_updates)), 51)

	def test_manual_ai_authorizes_requests_discovered_after_preparation(self):
		from kunal_enterprises.api.order_intake_ai import process_sender
		from kunal_enterprises.integrations import order_intake_ai as ai
		from kunal_enterprises.kunal_enterprises.doctype.order_intake_request.order_intake_request import OrderIntakeRequest
		source = self.source(); self.prepare()
		doc = frappe.get_doc(dict(doctype="Order Intake Request", whatsapp_account=self.account.name,
			sender_number=self.sender, source_messages=[dict(message=source.name)])).insert()
		original = OrderIntakeRequest.check_permission
		def check(current, *args, **kwargs):
			if current.name == doc.name:
				frappe.throw("Synthetic restricted request", frappe.PermissionError)
			return original(current, *args, **kwargs)
		with patch.object(OrderIntakeRequest, "check_permission", check), patch.object(ai, "dispatch") as dispatch:
			with self.assertRaises(frappe.PermissionError):
				process_sender(self.account.name, self.sender)
		dispatch.assert_not_called()

	def test_merged_continuation_preserves_both_group_scopes(self):
		from kunal_enterprises.integrations import order_intake_ai as ai
		first = self.source(); anchor = self.prepare()
		created = self.run_ai(anchor, Grouping(groups=[Group(request_hint="Initial", message_ids=[first.name], target_request=None)], unresolved_message_ids=[]), [extraction(first.name)])["created"][0]
		late = self.source(); continuation = self.source(); anchor = self.prepare(); claim = ai._claim(anchor)
		groups = Grouping(groups=[Group(request_hint="Original order", message_ids=[continuation.name], target_request=created),
			Group(request_hint="Change quantity to seven", message_ids=[late.name], target_request=created)], unresolved_message_ids=[])
		scopes = []
		def extract(config, payload, media, budget):
			scopes.append(payload["request_scope"])
			correction = extraction(late.name); correction.items[0].quantity = 7
			return correction
		with patch.object(ai, "group", return_value=groups), patch.object(ai, "extract", side_effect=extract):
			result = ai.process(anchor, claim["token"], release_transaction=False)
		self.assertEqual(result["proposed"], [created])
		self.assertEqual(len(scopes), 1)
		self.assertIn("Original order", scopes[0])
		self.assertIn("Change quantity to seven", scopes[0])
