"""Regression tests for intake evidence, outgoing retries and historical attachment privacy."""
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from kunal_enterprises.tests import test_foundation as foundation
from kunal_enterprises.permission_guards.whatsapp import retry_failed
from kunal_enterprises.patches.private_whatsapp_attachments import execute as privatize


class TestOrderIntakeSecurity(FrappeTestCase):
	def test_collapsed_intake_section_does_not_contain_original_message_fields(self):
		meta = frappe.get_meta("WhatsApp Message", cached=False)
		fields = [field.fieldname for field in meta.fields]
		boundary = fields.index("intake_details")
		original = frappe.get_doc("DocType", "WhatsApp Message")
		for field in original.fields:
			self.assertLess(fields.index(field.fieldname), boundary, field.fieldname)
		section = meta.get_field("intake_details")
		self.assertTrue(section.collapsible)
		self.assertEqual(section.depends_on, 'eval:doc.type == "Incoming"')
		for field in meta.fields[boundary + 1:]:
			if field.fieldname.startswith("intake_"):
				self.assertNotIn(field.fieldtype, ("Section Break", "Tab Break"))

	def setUp(self):
		frappe.set_user("Administrator")
		self.account = frappe.get_doc({"doctype": "WhatsApp Account", "account_name": "Security test " + uuid4().hex,
			"status": "Active", "phone_id": uuid4().hex, "intake_app_secret": "synthetic-signing-secret"}).insert(ignore_permissions=True)
		self.message = frappe.get_doc({"doctype": "WhatsApp Message", "type": "Incoming", "from": "919000000079",
			"whatsapp_account": self.account.name, "message": "Original source", "message_id": uuid4().hex, "content_type": "text"}).insert(ignore_permissions=True)
		self.users = {}

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def as_role(self, role):
		frappe.set_user("Administrator")
		if role not in self.users:
			self.users[role] = foundation.TestOrderSubmission._create_role_user(self, "security-" + uuid4().hex + "@example.com", role).name
		frappe.set_user(self.users[role])

	def test_owner_admin_cannot_change_server_managed_evidence_or_job_flags(self):
		for role in ("Owner", "Admin"):
			self.as_role(role)
			for field, value in (("intake_raw_payload", '{"fake":true}'), ("intake_status", "Duplicate"),
				("intake_prepare_state", "Context Ready"), ("intake_job_token", "forged")):
				doc = frappe.get_doc("WhatsApp Message", self.message.name)
				doc.set(field, value)
				with self.assertRaises(frappe.PermissionError):
					doc.save()

	def test_payload_flags_cannot_bypass_evidence_guard(self):
		self.as_role("Owner")
		payload = frappe.get_doc("WhatsApp Message", self.message.name).as_dict()
		payload.update(intake_status="Duplicate", flags={"intake_service_write": True})
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(payload).save()

	def test_new_api_message_cannot_supply_fake_capture_metadata(self):
		self.as_role("Admin")
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc({"doctype": "WhatsApp Message", "type": "Incoming", "from": "919000000079",
				"whatsapp_account": self.account.name, "content_type": "text", "message": "Manual source",
				"intake_raw_payload": '{"fake":true}', "intake_received_at": "2000-01-01 00:00:00"}).insert()

	def test_coordinator_cannot_see_app_secret(self):
		self.as_role("Order Coordinator")
		doc = frappe.get_doc("WhatsApp Account", self.account.name)
		doc.apply_fieldlevel_read_permissions()
		self.assertFalse(doc.as_dict().get("intake_app_secret"))

	def test_coordinator_cannot_trigger_bulk_endpoint_or_worker_resend(self):
		# Direct db fixture avoids creating recipients or triggering any send.
		batch = frappe.get_doc({"doctype": "Bulk WhatsApp Message", "name": "audit-bulk-" + uuid4().hex})
		batch.db_insert()
		self.as_role("Order Coordinator")
		with patch.object(frappe, "enqueue_doc", side_effect=AssertionError("Must not enqueue outgoing messages")):
			for call in (lambda: retry_failed(batch.name), lambda: frappe.get_doc("Bulk WhatsApp Message", batch.name).retry_failed(),
				lambda: frappe.get_doc("Bulk WhatsApp Message", batch.name).resend_single_message(self.message.name)):
				with self.assertRaises(frappe.PermissionError):
					call()

	def test_existing_public_attachment_becomes_private_and_references_survive(self):
		file = frappe.get_doc({"doctype": "File", "file_name": "privacy-audit-" + uuid4().hex + ".txt", "is_private": 0,
			"attached_to_doctype": "WhatsApp Message", "attached_to_name": self.message.name, "attached_to_field": "attach", "content": b"synthetic privacy audit"}).insert(ignore_permissions=True)
		old_url = file.file_url
		frappe.db.set_value("WhatsApp Message", self.message.name, "attach", old_url)
		request = frappe.get_doc({"doctype": "Order Intake Request", "request_type": "Unclear", "status": "Pending Review",
			"attachments": [{"reference_type": "File", "file": old_url, "source_message": self.message.name}]}).insert(ignore_permissions=True)
		privatize(); privatize()
		file.reload(); self.message.reload(); request.reload()
		self.assertTrue(file.is_private)
		self.assertTrue(file.file_url.startswith("/private/files/"))
		self.assertEqual(self.message.attach, file.file_url)
		self.assertEqual(request.attachments[0].file, file.file_url)
		self.assertEqual(request.status, "Pending Review")

	def test_migration_restores_india_default_for_whitespace_country_code(self):
		from kunal_enterprises.integrations.order_intake_schema import setup
		frappe.db.set_single_value("Order Intake Settings", "default_country_calling_code", "   ")
		setup()
		self.assertEqual(frappe.db.get_single_value("Order Intake Settings", "default_country_calling_code"), "+91")

	def test_captured_provider_id_and_direction_cannot_be_changed_by_owner_or_admin(self):
		for role in ("Owner", "Admin"):
			self.as_role(role)
			for field, value in (("message_id", "replacement-provider-id"), ("type", "Outgoing")):
				doc = frappe.get_doc("WhatsApp Message", self.message.name)
				doc.set(field, value)
				with self.assertRaises(frappe.PermissionError):
					doc.save()
			stored = frappe.get_doc("WhatsApp Message", self.message.name)
			self.assertEqual(stored.message_id, self.message.message_id)
			self.assertEqual(stored.type, "Incoming")

	def test_captured_message_still_accepts_normal_label_and_status_updates(self):
		self.as_role("Owner")
		doc = frappe.get_doc("WhatsApp Message", self.message.name)
		doc.label = "Reviewed source"
		doc.status = "marked as read"
		doc.save()
		self.assertEqual(doc.label, "Reviewed source")
		self.assertEqual(doc.message_id, self.message.message_id)
