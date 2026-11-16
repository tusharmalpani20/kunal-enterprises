"""WhatsApp reviewers can inspect messages without credentials or write-side actions."""
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_account.whatsapp_account import WhatsAppAccount
from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_message.whatsapp_message import WhatsAppMessage

from kunal_enterprises.api import order_intake_capture as intake_api
from kunal_enterprises.tests import test_foundation as foundation


class TestWhatsAppPermissions(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.users = {}
		self.account = frappe.get_doc({"doctype": "WhatsApp Account", "account_name": "Permission audit " + uuid4().hex,
			"status": "Active", "phone_id": uuid4().hex,
			"token": "synthetic-test-token", "webhook_verify_token": "synthetic-test-verifier"}).insert(ignore_permissions=True)
		self.message = frappe.get_doc({"doctype": "WhatsApp Message", "type": "Incoming",
			"from": "919000000039", "message": "Permission test only", "message_id": uuid4().hex,
			"content_type": "text", "whatsapp_account": self.account.name}).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def as_role(self, role):
		frappe.set_user("Administrator")
		if role not in self.users:
			self.users[role] = foundation.TestOrderSubmission._create_role_user(
				self, "wa-permission-" + uuid4().hex + "@example.com", role).name
		frappe.set_user(self.users[role])

	def test_owner_and_admin_can_manage_without_deleting(self):
		for role in ("Owner", "Admin"):
			self.as_role(role)
			for doctype in ("WhatsApp Message", "WhatsApp Account", "WhatsApp Settings"):
				with self.subTest(role=role, doctype=doctype):
					for permission in ("read", "select", "write"):
						self.assertTrue(frappe.has_permission(doctype, permission), permission)
					self.assertFalse(frappe.has_permission(doctype, "delete"))
			for doctype in ("WhatsApp Message", "WhatsApp Account"):
				self.assertTrue(frappe.has_permission(doctype, "create"))

	def test_coordinator_can_read_and_select_but_not_write_create_or_delete(self):
		self.as_role("Order Coordinator")
		for doctype in ("WhatsApp Message", "WhatsApp Account", "WhatsApp Settings"):
			with self.subTest(doctype=doctype):
				for permission in ("read", "select"):
					self.assertTrue(frappe.has_permission(doctype, permission), permission)
				for permission in ("write", "create", "delete"):
					self.assertFalse(frappe.has_permission(doctype, permission), permission)
		self.assertEqual(intake_api.coverage_status(self.account.name)["incoming_count"], 1)

	def test_unrelated_roles_do_not_gain_whatsapp_access(self):
		for role in ("Branch Manager", "Branch Employee", "Godown Allocator"):
			self.as_role(role)
			for doctype in ("WhatsApp Message", "WhatsApp Account", "WhatsApp Settings"):
				with self.subTest(role=role, doctype=doctype):
					self.assertFalse(frappe.has_permission(doctype, "read"))
					self.assertFalse(frappe.has_permission(doctype, "write"))

	def test_coordinator_account_serialization_excludes_credentials(self):
		self.as_role("Order Coordinator")
		doc = frappe.get_doc("WhatsApp Account", self.account.name)
		doc.check_permission("read")
		doc.apply_fieldlevel_read_permissions()
		serialized = doc.as_dict()
		self.assertFalse(serialized.get("token"))
		self.assertFalse(serialized.get("webhook_verify_token"))
		self.assertEqual(serialized.get("account_name"), self.account.account_name)

	def test_owner_admin_can_read_and_edit_credential_fields(self):
		for role in ("Owner", "Admin"):
			self.as_role(role)
			doc = frappe.get_doc("WhatsApp Account", self.account.name)
			self.assertIn(1, doc.get_permlevel_access("read"))
			self.assertIn(1, doc.get_permlevel_access("write"))
			doc.apply_fieldlevel_read_permissions()
			self.assertEqual(doc.webhook_verify_token, "synthetic-test-verifier")

	def test_coordinator_cannot_edit_account_or_existing_message(self):
		self.as_role("Order Coordinator")
		for doc in (frappe.get_doc("WhatsApp Account", self.account.name), frappe.get_doc("WhatsApp Message", self.message.name)):
			with self.assertRaises(frappe.PermissionError):
				doc.save()

	def test_coordinator_cannot_invoke_integration_write_actions(self):
		self.as_role("Order Coordinator")
		with patch.object(WhatsAppAccount, "subscribe_app", side_effect=AssertionError("Must not call Meta")), \
			patch("kunal_enterprises.permission_guards.whatsapp.make_post_request", side_effect=AssertionError("Must not call Meta")):
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc("WhatsApp Account", self.account.name).subscribe_app()
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc("WhatsApp Message", self.message.name).send_read_receipt()

	def test_owner_admin_write_actions_delegate_only_after_permission_check(self):
		for role in ("Owner", "Admin"):
			self.as_role(role)
			with patch.object(WhatsAppAccount, "subscribe_app", return_value={"success": True}) as subscribe, \
				patch("kunal_enterprises.permission_guards.whatsapp.make_post_request", return_value={"success": True}) as read_receipt:
				self.assertEqual(frappe.get_doc("WhatsApp Account", self.account.name).subscribe_app(), {"success": True})
				self.assertTrue(frappe.get_doc("WhatsApp Message", self.message.name).send_read_receipt())
				subscribe.assert_called_once()
				read_receipt.assert_called_once()

	def test_repeated_permission_setup_preserves_system_manager_access(self):
		from kunal_enterprises.permission_guards.whatsapp import setup
		frappe.set_user("Administrator")
		def manager_rows():
			return {dt: [p.as_dict() for p in frappe.get_meta(dt).permissions if p.role == "System Manager"]
				for dt in ("WhatsApp Message", "WhatsApp Account", "WhatsApp Settings")}
		before = manager_rows()
		setup()
		setup()
		for doctype, rows in before.items():
			after = manager_rows()[doctype]
			self.assertEqual(len(after), len(rows))
			for original, current in zip(rows, after):
				for permission in ("permlevel", "read", "write", "create", "delete", "select"):
					self.assertEqual(current.get(permission), original.get(permission), (doctype, permission))

	def test_read_receipt_uses_persisted_identity_and_preserves_concurrent_media_updates(self):
		self.as_role('Owner')
		browser = frappe.get_doc(frappe.parse_json(self.message.as_json()))
		browser.whatsapp_account = 'forged-browser-account'
		browser.message_id = 'forged-browser-message-id'
		browser.intake_status = 'Duplicate'
		def sent(url, **kwargs):
			self.assertIn('/' + self.account.phone_id + '/messages', url)
			self.assertEqual(frappe.parse_json(kwargs['data'])['message_id'], self.message.message_id)
			# Simulate a download finishing while Meta responds.
			frappe.db.set_value('WhatsApp Message', self.message.name,
				dict(intake_media_state='Downloaded', intake_media_note='Completed', attach='/private/files/completed.pdf'), update_modified=False)
			return {'success': True}
		with patch('kunal_enterprises.permission_guards.whatsapp.make_post_request', side_effect=sent) as network:
			self.assertTrue(browser.send_read_receipt())
			network.assert_called_once()
		stored = frappe.get_doc('WhatsApp Message', self.message.name)
		self.assertEqual(stored.status, 'marked as read')
		self.assertEqual(stored.intake_media_state, 'Downloaded')
		self.assertEqual(stored.attach, '/private/files/completed.pdf')
		self.assertNotEqual(stored.intake_status, 'Duplicate')
		self.assertEqual(browser.message_id, self.message.message_id)

	def test_read_receipt_dispatch_requires_post(self):
		from frappe.handler import is_valid_http_method
		fn = frappe.get_doc('WhatsApp Message', self.message.name).send_read_receipt.__func__
		with patch.object(frappe.local, 'request', frappe._dict(method='GET'), create=True):
			with self.assertRaises(frappe.PermissionError):
				is_valid_http_method(fn)
		with patch.object(frappe.local, 'request', frappe._dict(method='POST'), create=True):
			is_valid_http_method(fn)
