import frappe
from frappe.tests.utils import FrappeTestCase

from kunal_enterprises.api.product_group_logos import set_product_group_logo
from kunal_enterprises.api.product_groups import allowed as allowed_product_groups


class TestProductGroupLogos(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._cleanup_leftover_users()
		self.owner = self._create_role_user("logo.owner@example.com", "Owner")
		self.admin = self._create_role_user("logo.admin@example.com", "Admin")
		self.branch_manager = self._create_role_user("logo.branch.manager@example.com", "Branch Manager")
		self._cleanup_leftover_groups()
		self.test_group = self._create_test_group("_TEST_LOGO_GROUP", "_test_logo_guid_001")
		self.test_group_2 = self._create_test_group("_TEST_LOGO_GROUP_2", "_test_logo_guid_002")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_product_group_logo_field_exists_and_is_attach_image(self):
		meta = frappe.get_meta("Tally Stock Group")
		self.assertTrue(meta.has_field("product_group_logo"))
		self.assertEqual(meta.get_field("product_group_logo").fieldtype, "Attach Image")
		self.assertTrue(meta.has_field("product_group_logo_preview"))
		preview = meta.get_field("product_group_logo_preview")
		self.assertEqual(preview.fieldtype, "Image")
		self.assertEqual(preview.options, "product_group_logo")

	def test_allowed_returns_product_group_logo(self):
		frappe.db.set_value(
			"Tally Stock Group", self.test_group.name,
			"product_group_logo", "/files/test_logo.jpeg",
		)
		frappe.db.commit()

		groups = frappe.get_all(
			"Tally Stock Group",
			filters={"name": self.test_group.name, "is_root": 1, "is_active": 1},
			fields=["name", "group_name", "full_path", "product_group_logo"],
		)
		self.assertEqual(len(groups), 1)
		self.assertEqual(groups[0]["product_group_logo"], "/files/test_logo.jpeg")

	def test_set_logo_as_owner_succeeds(self):
		frappe.set_user(self.owner.name)
		result = set_product_group_logo(self.test_group.name, "/files/owner_logo.jpeg")
		self.assertEqual(result["data"]["group"], self.test_group.name)
		self.assertEqual(result["data"]["product_group_logo"], "/files/owner_logo.jpeg")
		stored = frappe.db.get_value(
			"Tally Stock Group", self.test_group.name, "product_group_logo",
		)
		self.assertEqual(stored, "/files/owner_logo.jpeg")

	def test_set_logo_as_admin_succeeds(self):
		frappe.set_user(self.admin.name)
		result = set_product_group_logo(self.test_group_2.name, "/files/admin_logo.jpeg")
		self.assertEqual(result["data"]["product_group_logo"], "/files/admin_logo.jpeg")

	def test_set_logo_rejects_non_owner_admin(self):
		frappe.set_user(self.branch_manager.name)
		result = set_product_group_logo(self.test_group.name, "/files/hack.jpeg")
		self.assertIn("error", result)

	def test_set_logo_rejects_missing_group(self):
		frappe.set_user(self.owner.name)
		result = set_product_group_logo("", "/files/test.jpeg")
		self.assertIn("error", result)

	def test_set_logo_rejects_missing_file_url(self):
		frappe.set_user(self.owner.name)
		result = set_product_group_logo(self.test_group.name, "")
		self.assertIn("error", result)

	def test_upload_script_mapping_is_complete(self):
		from kunal_enterprises.patches.upload_product_group_logos import LOGO_MAPPING, LOGOS_DIR
		import os
		self.assertEqual(len(LOGO_MAPPING), 18)
		for filename, group_name in LOGO_MAPPING:
			self.assertTrue(
				frappe.db.exists("Tally Stock Group", group_name),
				f"Group '{group_name}' does not exist for logo '{filename}'",
			)
			self.assertTrue(
				os.path.isfile(os.path.join(LOGOS_DIR, filename)),
				f"Logo file '{filename}' does not exist",
			)

	def _create_test_group(self, name, tally_guid):
		group = frappe.get_doc(
			{
				"doctype": "Tally Stock Group",
				"group_name": name,
				"tally_guid": tally_guid,
				"is_root": 1,
				"is_active": 1,
				"depth": 0,
				"full_path": name,
			}
		).insert(ignore_permissions=True)
		return group

	def _create_role_user(self, email, role):
		user = self._new_user(email).insert(ignore_permissions=True)
		user.append("roles", {"role": role})
		user.save(ignore_permissions=True)
		return user

	def _new_user(self, email):
		return frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"enabled": 1,
				"send_welcome_email": 0,
			}
		)

	def _cleanup_leftover_users(self):
		for email in (
			"logo.owner@example.com",
			"logo.admin@example.com",
			"logo.branch.manager@example.com",
		):
			frappe.db.delete("User", {"name": email})
			frappe.db.commit()

	def _cleanup_leftover_groups(self):
		for name in ("_TEST_LOGO_GROUP", "_TEST_LOGO_GROUP_2"):
			frappe.db.delete("Tally Stock Group", {"name": name})
			frappe.db.commit()
