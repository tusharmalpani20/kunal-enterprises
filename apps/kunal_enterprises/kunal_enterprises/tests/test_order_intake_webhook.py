"""The webhook preserves incoming events in WhatsApp Message, including parser failures."""
import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
import frappe
from frappe.tests.utils import FrappeTestCase
from kunal_enterprises.integrations import order_intake_webhook as receiver


class TestOrderIntakeWebhook(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.account = frappe.get_doc({"doctype": "WhatsApp Account", "account_name": "Intake " + uuid4().hex,
			"phone_id": uuid4().hex, "status": "Active", "business_id": "audit-business", "intake_app_secret": "synthetic-app-secret"}).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def message(self, text="Review order"):
		return {"id": "audit-" + uuid4().hex, "from": "919000000001", "timestamp": "1794391200",
			"type": "text", "text": {"body": text}}

	def payload(self, messages, phone=None):
		return frappe._dict(object="whatsapp_business_account", entry=[{"id": "audit-business", "changes": [
			{"field": "messages", "value": {"metadata": {"phone_number_id": phone or self.account.phone_id},
				"messages": messages, "contacts": [{"wa_id": "919000000001", "profile": {"name": "Audit sender"}}]}}]}])

	def call(self, payload, parser, signature=None, signed_payload=None):
		raw = json.dumps(signed_payload or payload, sort_keys=True).encode()
		if signature is None:
			signature = "sha256=" + hmac.new(b"synthetic-app-secret", raw, hashlib.sha256).hexdigest()
		request = SimpleNamespace(method="POST", headers={"X-Hub-Signature-256": signature}, get_data=lambda **kwargs: raw)
		with patch.object(frappe.local, "request", request, create=True), \
			patch.object(frappe.local, "form_dict", payload, create=True), \
			patch.object(receiver, "upstream_webhook", side_effect=parser) as upstream:
			receiver.webhook()
			self.assertIs(frappe.local.form_dict, payload)
			return upstream.call_count

	def save_source(self):
		value = frappe.local.form_dict.entry[0]["changes"][0]["value"]
		message = value["messages"][0]
		frappe.get_doc({"doctype": "WhatsApp Message", "type": "Incoming", "from": message["from"],
			"message": message["text"]["body"], "content_type": "text", "message_id": message["id"],
			"whatsapp_account": self.account.name, "profile_name": value["contacts"][0]["profile"]["name"]}).insert(ignore_permissions=True)

	def receipt(self, message):
		return frappe.get_doc("WhatsApp Message", {"message_id": message["id"], "whatsapp_account": self.account.name})

	def test_parser_failure_creates_one_incoming_record_with_raw_evidence(self):
		message = self.message()
		def fail():
			raise ValueError("source parser failure")
		self.call(self.payload([message]), fail)
		doc = self.receipt(message)
		self.assertEqual(doc.intake_status, "Needs Attention")
		self.assertIn("Review order", doc.intake_raw_payload)
		self.assertEqual(doc.type, "Incoming")

	def test_media_is_preserved_and_queued_without_synchronous_download(self):
		message = self.message()
		message.update(type="document", document={"id": "media-123", "filename": "order.pdf", "caption": "Please supply"})
		self.call(self.payload([message]), lambda: None)
		doc = self.receipt(message)
		self.assertEqual(doc.intake_status, "New")
		self.assertEqual(doc.intake_media_state, "Queued")
		self.assertEqual(doc.intake_media_id, "media-123")

	def test_repeat_delivery_does_not_parse_or_create_again(self):
		message = self.message()
		payload = self.payload([message])
		self.call(payload, self.save_source)
		self.assertEqual(self.call(payload, self.save_source), 0)
		self.assertEqual(frappe.db.count("WhatsApp Message", {"message_id": message["id"]}), 1)
		self.assertEqual(self.receipt(message).intake_status, "New")

	def test_unmapped_phone_rejects_without_default_account_or_acknowledgment(self):
		message = self.message()
		with self.assertRaises(frappe.ValidationError):
			self.call(self.payload([message], phone=uuid4().hex), self.save_source)
		self.assertFalse(frappe.db.exists("WhatsApp Message", {"message_id": message["id"]}))

	def test_every_message_and_entry_survives_one_parser_failure(self):
		messages = [self.message(str(i)) for i in range(3)]
		payload = self.payload(messages[:2])
		payload.entry.extend(self.payload(messages[2:]).entry)
		def parser():
			message = frappe.local.form_dict.entry[0]["changes"][0]["value"]["messages"][0]
			if message["id"] == messages[1]["id"]:
				raise ValueError("bad message")
			self.save_source()
		self.assertEqual(self.call(payload, parser), 3)
		self.assertEqual([self.receipt(m).intake_status for m in messages], ["New", "Needs Attention", "New"])

	def test_storage_failure_is_not_acknowledged(self):
		with patch.object(receiver, "preserve_raw", side_effect=RuntimeError("storage unavailable")):
			with self.assertRaises(RuntimeError):
				self.call(self.payload([self.message()]), self.save_source)

	def test_unsupported_message_is_readable_and_html_escaped(self):
		message = self.message()
		message.update(type="contacts", contacts=[{"name": {"formatted_name": "<script>bad</script>"}}])
		self.call(self.payload([message]), lambda: None)
		doc = self.receipt(message)
		self.assertEqual(doc.content_type, "contact")
		self.assertNotIn("<script>", doc.message)
		self.assertIn("<script>", doc.intake_raw_payload)

	def test_native_location_with_zero_coordinates_is_retained(self):
		message = self.message()
		message.update(type="location", location={"latitude": 0, "longitude": 0, "name": "Origin"})
		self.call(self.payload([message]), lambda: None)
		doc = self.receipt(message)
		self.assertTrue(doc.intake_has_location)
		self.assertEqual(doc.intake_latitude, 0)

	def test_conflicting_id_preserves_both_payloads_on_one_message(self):
		message = self.message()
		self.call(self.payload([message]), self.save_source)
		message["text"]["body"] = "Different order"
		self.call(self.payload([message]), self.save_source)
		doc = self.receipt(message)
		self.assertIn("Review order", doc.intake_raw_payload)
		self.assertIn("Different order", doc.intake_legacy_evidence)
		self.assertEqual(doc.intake_status, "Needs Attention")

	def test_get_verification_uses_existing_handler(self):
		with patch.object(frappe.local, "request", SimpleNamespace(method="GET"), create=True), \
			patch.object(receiver, "upstream_webhook", return_value="challenge"):
			self.assertEqual(receiver.webhook(), "challenge")

	def test_historical_source_is_initialized_on_redelivery(self):
		message = self.message()
		self.call(self.payload([message]), self.save_source)
		doc = self.receipt(message)
		frappe.db.set_value("WhatsApp Message", doc.name, {"intake_received_at": None, "intake_sender_key": None, "intake_status": None})
		self.assertEqual(self.call(self.payload([message]), self.save_source), 0)
		doc.reload()
		self.assertTrue(doc.intake_received_at)
		self.assertEqual(doc.intake_sender_key, message["from"])
		self.assertEqual(doc.intake_status, "New")

	def test_bad_status_does_not_roll_back_incoming_messages_in_same_batch(self):
		message = self.message()
		payload = self.payload([message])
		payload.entry[0]["changes"].insert(0, {"field": "messages", "value": {"statuses": [{"id": "not-local", "status": "delivered"}]}})
		def parser():
			value = frappe.local.form_dict.entry[0]["changes"][0]["value"]
			if "statuses" in value:
				raise frappe.DoesNotExistError("unknown status")
			self.save_source()
		self.call(payload, parser)
		self.assertTrue(self.receipt(message).intake_raw_payload)
		self.assertTrue(frappe.db.exists("WhatsApp Notification Log", {"template": "Webhook status needs review"}))

	def test_missing_or_wrong_signature_is_rejected_before_parser_or_writes(self):
		for signature in ("", "sha256=" + "0" * 64):
			message = self.message()
			with self.assertRaises(frappe.PermissionError):
				self.call(self.payload([message]), self.save_source, signature=signature)
			self.assertFalse(frappe.db.exists("WhatsApp Message", {"message_id": message["id"]}))

	def test_signed_body_is_authoritative_over_form_parameters(self):
		signed = self.message("Signed content")
		forged = self.message("Forged query parameters")
		self.call(self.payload([forged]), self.save_source, signed_payload=self.payload([signed]))
		self.assertTrue(self.receipt(signed).intake_raw_payload)
		self.assertFalse(frappe.db.exists("WhatsApp Message", {"message_id": forged["id"]}))

	def test_missing_app_secret_fails_closed(self):
		from frappe.utils.password import remove_encrypted_password
		remove_encrypted_password("WhatsApp Account", self.account.name, "intake_app_secret")
		message = self.message()
		with self.assertRaises(frappe.PermissionError):
			self.call(self.payload([message]), self.save_source)
		self.assertFalse(frappe.db.exists("WhatsApp Message", {"message_id": message["id"]}))

	def test_each_account_in_the_payload_must_validate_signature(self):
		other = frappe.get_doc({"doctype": "WhatsApp Account", "account_name": "Other app " + uuid4().hex,
			"phone_id": uuid4().hex, "business_id": "other-business", "intake_app_secret": "different-secret"}).insert(ignore_permissions=True)
		first, second = self.message(), self.message()
		payload = self.payload([first])
		entry = self.payload([second], phone=other.phone_id).entry[0]
		entry["id"] = "other-business"
		payload.entry.append(entry)
		with self.assertRaises(frappe.PermissionError):
			self.call(payload, self.save_source)
		self.assertFalse(frappe.db.exists("WhatsApp Message", {"message_id": first["id"]}))
