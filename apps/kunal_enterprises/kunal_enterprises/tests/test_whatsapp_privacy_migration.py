"""Shared attachment references and filename collisions survive privatization."""
from pathlib import Path
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from kunal_enterprises.patches import private_whatsapp_attachments as migration


class TestWhatsAppPrivacyMigration(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.account = frappe.get_doc({"doctype": "WhatsApp Account", "account_name": "Privacy " + uuid4().hex,
			"phone_id": uuid4().hex, "status": "Active"}).insert(ignore_permissions=True)
		self.message = frappe.get_doc({"doctype": "WhatsApp Message", "type": "Incoming", "whatsapp_account": self.account.name,
			"from": "919000000079", "message_id": uuid4().hex, "message": "Privacy fixture", "content_type": "document"}).insert(ignore_permissions=True)
		self.file = frappe.get_doc({"doctype": "File", "file_name": "privacy-" + uuid4().hex + ".txt",
			"attached_to_doctype": "WhatsApp Message", "attached_to_name": self.message.name,
			"attached_to_field": "attach", "is_private": 0, "content": "Private fixture " + uuid4().hex}).insert(ignore_permissions=True)
		frappe.db.set_value("WhatsApp Message", self.message.name, "attach", self.file.file_url)
		self.url = self.file.file_url
		self.public = Path(self.file.get_full_path())
		self.private = Path(frappe.get_site_path("private", "files", self.public.name))
		self.extra_paths = []

	def tearDown(self):
		frappe.db.rollback()
		self.public.unlink(missing_ok=True)
		self.private.unlink(missing_ok=True)
		for path in self.extra_paths:
			path.unlink(missing_ok=True)

	def test_shared_registered_business_reference_moves_with_message(self):
		group = frappe.get_doc({"doctype": "Tally Stock Group", "group_name": "Privacy " + uuid4().hex,
			"product_group_logo": self.url}).insert(ignore_permissions=True)
		migration.execute()
		self.message.reload(); group.reload(); self.file.reload()
		self.assertEqual(group.product_group_logo, self.message.attach)
		self.assertEqual(self.file.file_url, self.message.attach)
		self.assertTrue(self.file.is_private)
		self.assertFalse(self.public.exists())
		self.assertTrue(self.private.exists())
		migration.execute()

	def test_identical_private_target_is_reused_and_public_copy_removed(self):
		self.private.parent.mkdir(parents=True, exist_ok=True)
		self.private.write_bytes(self.public.read_bytes())
		self.extra_paths.append(self.private)
		migration.execute()
		self.assertFalse(self.public.exists())
		self.assertTrue(self.private.exists())
		self.assertEqual(frappe.db.get_value("WhatsApp Message", self.message.name, "attach"), "/private/files/" + self.private.name)

	def test_different_private_target_is_not_overwritten(self):
		self.private.parent.mkdir(parents=True, exist_ok=True)
		self.private.write_bytes(b"Unrelated existing file")
		self.extra_paths.append(self.private)
		with self.assertRaises(frappe.ValidationError):
			migration.execute()
		self.assertTrue(self.public.exists())
		self.assertEqual(self.private.read_bytes(), b"Unrelated existing file")
		self.assertEqual(frappe.db.get_value("WhatsApp Message", self.message.name, "attach"), self.url)

	def test_shared_public_setting_stops_before_moving_bytes(self):
		meta = frappe.get_meta("Website Settings")
		field = next(f.fieldname for f in meta.fields if f.fieldtype in {"Attach", "Attach Image"})
		frappe.db.set_single_value("Website Settings", field, self.url)
		with self.assertRaises(frappe.ValidationError):
			migration.execute()
		self.assertTrue(self.public.exists())
		self.assertEqual(frappe.db.get_value("WhatsApp Message", self.message.name, "attach"), self.url)
