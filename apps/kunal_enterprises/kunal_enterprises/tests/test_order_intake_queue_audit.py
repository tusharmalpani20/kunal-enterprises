"""Audit regressions for message evidence arriving after a prepared context."""
from uuid import uuid4
import frappe
from frappe.tests.utils import FrappeTestCase
from kunal_enterprises.integrations.order_intake_capture import preserve_raw


class TestOrderIntakeQueueAudit(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.account = frappe.get_doc({"doctype": "WhatsApp Account", "account_name": "Queue audit " + uuid4().hex,
			"status": "Active", "phone_id": uuid4().hex}).insert(ignore_permissions=True)
		self.message = {"id": uuid4().hex, "from": "919000000049", "type": "text", "text": {"body": "Two sheets"}}
		self.value = {"metadata": {"phone_number_id": self.account.phone_id}, "contacts": []}
		self.doc = frappe.get_doc({"doctype": "WhatsApp Message", "type": "Incoming", "whatsapp_account": self.account.name,
			"from": self.message["from"], "message_id": self.message["id"], "content_type": "text", "message": "Two sheets"}).insert(ignore_permissions=True)
		preserve_raw(self.doc, self.message, self.value, "queue-audit")
		frappe.db.set_value("WhatsApp Message", self.doc.name, "intake_prepare_state", "Context Ready")
		self.doc.reload()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_identical_redelivery_does_not_repeat_ready_work(self):
		preserve_raw(self.doc, self.message, self.value, "queue-audit")
		self.doc.reload()
		self.assertEqual(self.doc.intake_prepare_state, "Context Ready")

	def test_conflicting_raw_evidence_reopens_context_without_rewriting_original(self):
		self.message["text"]["body"] = "Three sheets"
		preserve_raw(self.doc, self.message, self.value, "queue-audit")
		self.doc.reload()
		self.assertEqual(self.doc.intake_prepare_state, "Pending")
		self.assertEqual(self.doc.intake_status, "Needs Attention")
		self.assertIn("Three sheets", self.doc.intake_legacy_evidence)
		self.assertIn("Two sheets", self.doc.intake_raw_payload)

	def test_late_raw_evidence_is_eligible_without_a_new_source_record(self):
		frappe.db.set_value("WhatsApp Message", self.doc.name, "intake_raw_payload", None)
		self.doc.reload()
		preserve_raw(self.doc, self.message, self.value, "queue-audit")
		self.doc.reload()
		self.assertEqual(self.doc.intake_prepare_state, "Pending")
		self.assertEqual(frappe.db.count("WhatsApp Message", {"message_id": self.message["id"]}), 1)

	def test_repeated_known_conflict_does_not_reschedule_unchanged_evidence(self):
		self.message["text"]["body"] = "Three sheets"
		preserve_raw(self.doc, self.message, self.value, "queue-audit")
		frappe.db.set_value("WhatsApp Message", self.doc.name, "intake_prepare_state", "Context Ready")
		self.doc.reload()
		preserve_raw(self.doc, self.message, self.value, "queue-audit")
		self.doc.reload()
		self.assertEqual(self.doc.intake_prepare_state, "Context Ready")

	def test_source_correction_updates_chat_key_and_reopens_context(self):
		self.doc.set("from", "919000000048")
		self.doc.save(ignore_permissions=True)
		self.assertEqual(self.doc.intake_sender_key, "919000000048")
		self.assertEqual(self.doc.intake_prepare_state, "Pending")

	def test_receiving_account_correction_updates_phone_and_event_key(self):
		other = frappe.get_doc({"doctype": "WhatsApp Account", "account_name": "Queue audit " + uuid4().hex,
			"status": "Active", "phone_id": uuid4().hex}).insert(ignore_permissions=True)
		before = self.doc.intake_event_key
		self.doc.whatsapp_account = other.name
		self.doc.save(ignore_permissions=True)
		self.assertEqual(self.doc.intake_phone_id, other.phone_id)
		self.assertNotEqual(self.doc.intake_event_key, before)
		self.assertEqual(self.doc.intake_prepare_state, "Pending")

	def test_late_evidence_checks_current_ready_state_instead_of_stale_webhook_object(self):
		self.doc.intake_prepare_state = "Queued"  # Snapshot read before worker completed.
		self.message["text"]["body"] = "Updated after worker lookup"
		preserve_raw(self.doc, self.message, self.value, "queue-audit")
		self.doc.reload()
		self.assertEqual(self.doc.intake_prepare_state, "Pending")

	def test_blocked_chats_do_not_starve_other_senders_at_dispatch_limit(self):
		from unittest.mock import patch
		from frappe.utils import now_datetime, add_to_date
		from kunal_enterprises.integrations import order_intake_queue as queue
		now = now_datetime()
		def source(sender, minutes):
			doc = frappe.get_doc({"doctype": "WhatsApp Message", "type": "Incoming", "whatsapp_account": self.account.name,
				"from": sender, "message_id": uuid4().hex, "content_type": "text", "message": "Audit only"}).insert(ignore_permissions=True)
			frappe.db.set_value("WhatsApp Message", doc.name, "intake_received_at", add_to_date(now, minutes=minutes, as_datetime=True))
			return doc
		for sender in ("919000000041", "919000000042"):
			source(sender, -5)
			queue._claim(self.account.name, sender, now, queue.settings())
			source(sender, -3)
		healthy = source("919000000043", -1)
		with patch.object(queue, "MAX_CHATS", 2):
			result = queue.dispatch_pending(force=True, account=self.account.name, now=now, inline=True)
		self.assertEqual(result["queued"], 1)
		self.assertEqual(healthy.reload().intake_prepare_state, "Context Ready")

	def test_preview_distinguishes_primary_messages_from_earlier_manual_evidence(self):
		from kunal_enterprises.api import order_intake_queue as api
		frappe.db.set_value("WhatsApp Message", self.doc.name, "intake_prepare_state", "Needs Attention")
		manual = api.preview(self.account.name, self.message["from"])
		self.assertEqual(manual["state"], "Needs Attention")
		new = frappe.get_doc({"doctype": "WhatsApp Message", "type": "Incoming", "whatsapp_account": self.account.name,
			"from": self.message["from"], "message_id": uuid4().hex, "content_type": "text", "message": "New continuation"}).insert(ignore_permissions=True)
		context = api.preview(self.account.name, self.message["from"])["context"]
		self.assertEqual(context["message_ids"], [new.name])
		self.assertEqual(context["manual_review_message_ids"], [self.doc.name])

	def test_related_draft_keeps_matching_unprepared_historical_source(self):
		from kunal_enterprises.integrations.order_intake_queue import build_context
		old = self.doc
		frappe.db.set_value("WhatsApp Message", old.name, {"intake_received_at": None, "intake_sender_key": None})
		current = frappe.get_doc({"doctype": "WhatsApp Message", "type": "Incoming", "whatsapp_account": self.account.name,
			"from": self.message["from"], "message_id": uuid4().hex, "content_type": "text", "message": "Continuation"}).insert(ignore_permissions=True)
		request = frappe.get_doc({"doctype": "Order Intake Request", "status": "Pending Review", "request_type": "Unclear",
			"source_messages": [{"message": old.name}, {"message": current.name}]}).insert(ignore_permissions=True)
		self.assertIn(request.name, [row["name"] for row in build_context([current])["open_requests"]])
		self.assertFalse(frappe.db.get_value("WhatsApp Message", old.name, "intake_received_at"))
		# Even imported/corrupt source ledgers must not pull a different chat.
		frappe.db.set_value("WhatsApp Message", old.name, "from", "919000000001")
		self.assertNotIn(request.name, [row["name"] for row in build_context([current])["open_requests"]])
