"""Audit regressions for long-lived requests and resolved AI attention markers."""
import json
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from kunal_enterprises.integrations import order_intake_ai as ai
from kunal_enterprises.integrations import order_intake_queue as queue
from kunal_enterprises.integrations.order_intake_ai_models import AIProblem, Group, Grouping
from kunal_enterprises.tests.test_order_intake_ai import extraction


class TestOrderIntakeAIAudit(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.account = frappe.get_doc(dict(doctype="WhatsApp Account", account_name="Deep audit " + uuid4().hex,
			phone_id=uuid4().hex, status="Active")).insert(ignore_permissions=True)
		self.sender = "919000000089"
		frappe.db.set_single_value("Order Intake Settings", "lookback_minutes", 120)
		frappe.db.set_single_value("Order Intake Settings", "deferred_retry_minutes", "5,15,60")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def source(self):
		return frappe.get_doc(dict(doctype="WhatsApp Message", type="Incoming", whatsapp_account=self.account.name,
			**{"from": self.sender}, message="21317 mr 4", message_id=uuid4().hex, content_type="text")).insert(ignore_permissions=True)

	def prepare(self):
		queue.dispatch_pending(force=True, account=self.account.name, sender=self.sender, inline=True, maintain=False)
		return frappe.db.get_value("WhatsApp Message", {"whatsapp_account": self.account.name,
			"intake_context_ids": ("is", "set"), "intake_prepare_state": "Context Ready", "intake_sender_key": self.sender}, "name")

	def run_success(self, anchor, sources):
		claim = ai._claim(anchor, force=True)
		self.assertEqual(claim["state"], "Queued")
		grouping = Grouping(groups=[Group(message_ids=[s.name for s in sources], target_request=None,
			request_hint="Audit request")], unresolved_message_ids=[])
		with patch.object(ai, "group", return_value=grouping), patch.object(ai, "extract", return_value=extraction(sources[0].name)):
			return ai.process(anchor, claim["token"], release_transaction=False)

	def test_large_related_request_is_not_silently_omitted(self):
		sources = [self.source() for _ in range(queue.MAX_MESSAGES + 1)]
		frappe.get_doc(dict(doctype="Order Intake Request", source="WhatsApp", whatsapp_account=self.account.name,
			sender_number=self.sender, source_messages=[dict(message=s.name) for s in sources])).insert(ignore_permissions=True)
		_, overflow = queue._open_requests(self.account.name, self.sender, [sources[0].name])
		self.assertTrue(overflow, "An oversized related request must stop automatic processing instead of disappearing")

	def test_successful_recovery_clears_only_ai_failure_attention(self):
		for original_note in ("", "Capture evidence conflict; review the original payload."):
			source = self.source(); anchor = self.prepare()
			if original_note:
				frappe.db.set_value("WhatsApp Message", source.name, dict(intake_status="Needs Attention", intake_attention=original_note))
			claim = ai._claim(anchor, force=True)
			with patch.object(ai, "group", side_effect=AIProblem("Check provider credentials")):
				ai.process(anchor, claim["token"], release_transaction=False)
			self.assertIn("AI:", source.reload().intake_attention)
			result = self.run_success(anchor, [source])
			self.assertEqual(result["state"], "Drafted")
			source.reload()
			self.assertEqual(source.intake_attention or "", original_note)
			self.assertEqual(source.intake_status, "Needs Attention" if original_note else "New")
			# Keep the following iteration in a different chat.
			self.sender = "919000000088"

	def test_later_resolved_context_clears_ai_unresolved_attention(self):
		first = self.source(); anchor = self.prepare(); claim = ai._claim(anchor)
		with patch.object(ai, "group", return_value=Grouping(groups=[], unresolved_message_ids=[first.name])):
			ai.process(anchor, claim["token"], release_transaction=False)
		self.assertEqual(first.reload().intake_status, "Needs Attention")
		second = self.source(); self.prepare()
		result = self.run_success(anchor, [first, second])
		self.assertEqual(result["state"], "Drafted")
		self.assertFalse(json.loads(first.reload().intake_ai_coverage)["unresolved"])
		self.assertFalse(first.intake_attention)
		self.assertEqual(first.intake_status, "New")

	def test_new_context_obeys_chat_backoff_but_explicit_retry_can_override_it(self):
		first = self.source(); anchor = self.prepare(); claim = ai._claim(anchor)
		ai._fail(anchor, claim["token"], "Provider temporarily unavailable", retry=True)
		previous_retry = first.reload().intake_ai_retry_at
		self.source(); self.prepare()
		self.assertEqual(ai._claim(anchor)["state"], "Retry")
		self.assertEqual(first.reload().intake_ai_retry_at, previous_retry)
		self.assertEqual(ai._claim(anchor, force=True)["state"], "Queued")

	def test_live_changed_contexts_do_not_starve_a_pending_chat(self):
		from frappe.utils import add_to_date, now_datetime
		busy = []
		for index in range(21):
			self.sender = "91900000" + str(index).zfill(4)
			message = self.source(); busy.append(message.name)
			frappe.db.set_value("WhatsApp Message", message.name, dict(
				intake_ai_state="Queued", intake_ai_lease_until=add_to_date(now_datetime(), minutes=10, as_datetime=True),
				intake_ai_prepared_digest="previous", intake_context_digest="changed", intake_prepare_state="Context Ready",
				intake_context_ids="{}", intake_prepared_at=add_to_date(now_datetime(), minutes=-5, as_datetime=True)))
		self.sender = "919000000087"
		self.source(); pending = self.prepare()
		frappe.db.set_single_value("Order Intake Settings", "processing_enabled", 1)
		result = ai.dispatch()
		self.assertIn(pending, [row["anchor"] for row in result["results"] if row["state"] == "Queued"])
		self.assertFalse(set(busy) & {row["anchor"] for row in result["results"]})

	def test_retry_escalation_survives_new_messages_and_a_changed_anchor(self):
		from frappe.utils import add_to_date, now_datetime
		for changed_anchor in (False, True):
			first = self.source(); anchor = self.prepare(); claim = ai._claim(anchor)
			ai._fail(anchor, claim["token"], "Provider unavailable", retry=True)
			frappe.db.set_value("WhatsApp Message", anchor, "intake_ai_retry_at", add_to_date(now_datetime(), minutes=-1, as_datetime=True))
			if changed_anchor:
				frappe.db.set_value("WhatsApp Message", first.name, "intake_received_at", add_to_date(now_datetime(), minutes=-121, as_datetime=True))
			second = self.source(); self.prepare()
			current = second.reload().intake_context_anchor
			claim = ai._claim(current)
			self.assertEqual(claim["state"], "Queued")
			self.assertEqual(frappe.db.get_value("WhatsApp Message", current, "intake_ai_attempts"), 2)
			ai._fail(current, claim["token"], "Still unavailable", retry=True)
			retry_at = frappe.db.get_value("WhatsApp Message", current, "intake_ai_retry_at")
			self.assertGreater(retry_at, add_to_date(now_datetime(), minutes=14, as_datetime=True))
			self.sender = "919000000086"

	def test_missing_receiving_account_does_not_break_stale_job_recovery(self):
		first = self.source(); anchor = self.prepare(); claim = ai._claim(anchor)
		frappe.db.delete("WhatsApp Account", {"name": self.account.name})
		ai._fail(anchor, claim["token"], "Worker expired", retry=True)
		self.assertEqual(first.reload().intake_ai_state, "Needs Attention")
		self.assertFalse(first.intake_ai_retry_at)
