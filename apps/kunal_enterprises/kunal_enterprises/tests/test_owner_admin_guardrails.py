import frappe
from frappe.tests.utils import FrappeTestCase

from kunal_enterprises import hooks
from kunal_enterprises.permission_guards import owner_admin


class TestOwnerAdminAccountGuardrails(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = self._create_role_user("guard.owner@example.com", "Owner")
		self.admin = self._create_role_user("guard.admin@example.com", "Admin")
		self.branch_manager = self._create_role_user("guard.branch.manager@example.com", "Branch Manager")
		self.branch_employee = self._create_role_user("guard.branch.employee@example.com", "Branch Employee")
		self.branch = frappe.get_doc(
			{
				"doctype": "Portal Branch",
				"branch_name": "Guardrail Branch",
				"is_active": 1,
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_guard_hooks_are_registered_for_standard_account_doctypes(self):
		self.assertEqual(
			hooks.doc_events["User"]["before_save"],
			"kunal_enterprises.permission_guards.owner_admin.guard_user_write",
		)
		self.assertEqual(
			hooks.doc_events["Role Profile"]["before_save"],
			"kunal_enterprises.permission_guards.owner_admin.guard_role_profile_write",
		)
		self.assertEqual(
			hooks.doc_events["User Permission"]["before_save"],
			"kunal_enterprises.permission_guards.owner_admin.guard_user_permission_write",
		)
		self.assertEqual(
			hooks.override_whitelisted_methods["frappe.core.doctype.user.user.get_all_roles"],
			"kunal_enterprises.permission_guards.owner_admin.get_all_roles",
		)
		self.assertEqual(
			hooks.override_whitelisted_methods["frappe.core.doctype.user.user.get_role_profile"],
			"kunal_enterprises.permission_guards.owner_admin.get_role_profile",
		)
		self.assertEqual(
			hooks.override_whitelisted_methods["frappe.core.doctype.user.user.reset_password"],
			"kunal_enterprises.permission_guards.owner_admin.reset_password",
		)

	def test_role_lookup_methods_are_filtered_for_admin(self):
		frappe.set_user(self.admin.name)

		self.assertEqual(owner_admin.get_all_roles(), ["Admin", "Branch Manager", "Branch Employee"])
		self.assertEqual(
			[row.role for row in owner_admin.get_role_profile("Branch Employee")],
			["Branch Employee"],
		)
		with self.assertRaises(frappe.PermissionError):
			owner_admin.get_role_profile("Owner")

		original_form_dict = frappe.local.form_dict
		try:
			frappe.local.form_dict = frappe._dict(uid=self.branch_employee.name)
			self.assertEqual(owner_admin.get_roles(), ["Branch Employee"])
			frappe.local.form_dict = frappe._dict(uid=self.owner.name)
			with self.assertRaises(frappe.PermissionError):
				owner_admin.get_roles()
		finally:
			frappe.local.form_dict = original_form_dict

	def test_admin_cannot_create_or_mutate_owner_users(self):
		frappe.set_user(self.admin.name)

		with self.assertRaises(frappe.PermissionError):
			self._new_user("guard.new.owner@example.com", role_profile_name="Owner").insert(ignore_permissions=True)

		with self.assertRaises(frappe.PermissionError):
			self._new_user("guard.owner.role@example.com", roles=["Owner"]).insert(ignore_permissions=True)

		owner_doc = frappe.get_doc("User", self.owner.name)
		owner_doc.first_name = "Changed By Admin"
		with self.assertRaises(frappe.PermissionError):
			owner_doc.save(ignore_permissions=True)

		frappe.set_user("Administrator")
		non_owner = self._create_role_user("guard.target.admin@example.com", "Admin")
		frappe.set_user(self.admin.name)
		non_owner.append("roles", {"role": "Owner"})
		with self.assertRaises(frappe.PermissionError):
			non_owner.save(ignore_permissions=True)

	def test_admin_cannot_disable_or_delete_owner_users(self):
		frappe.set_user(self.admin.name)

		owner_doc = frappe.get_doc("User", self.owner.name)
		owner_doc.enabled = 0
		with self.assertRaises(frappe.PermissionError):
			owner_doc.save(ignore_permissions=True)

		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc("User", self.owner.name, ignore_permissions=True)

	def test_admin_cannot_trigger_owner_password_reset(self):
		frappe.set_user(self.admin.name)

		with self.assertRaises(frappe.PermissionError):
			owner_admin.reset_password(self.owner.name)

	def test_admin_cannot_trigger_unrelated_user_password_reset(self):
		frappe.set_user("Administrator")
		unrelated = self._create_role_user("guard.reset.unrelated@example.com", "Blogger")
		frappe.set_user(self.admin.name)

		with self.assertRaises(frappe.PermissionError):
			owner_admin.reset_password(unrelated.name)

	def test_branch_user_cannot_trigger_owner_password_reset(self):
		frappe.set_user(self.branch_manager.name)

		with self.assertRaises(frappe.PermissionError):
			owner_admin.reset_password(self.owner.name)

	def test_admin_can_create_edit_and_disable_non_owner_kunal_users(self):
		frappe.set_user(self.admin.name)

		branch_user = self._new_user(
			"guard.admin.created.branch@example.com",
			roles=["Branch Employee"],
		).insert(ignore_permissions=True)
		branch_user.first_name = "Admin Edited Branch"
		branch_user.enabled = 0
		branch_user.save(ignore_permissions=True)

		branch_user.reload()
		self.assertEqual(branch_user.first_name, "Admin Edited Branch")
		self.assertFalse(branch_user.enabled)

	def test_admin_cannot_assign_system_manager_or_manage_unrelated_users(self):
		frappe.set_user(self.admin.name)

		with self.assertRaises(frappe.PermissionError):
			self._new_user("guard.system.manager@example.com", roles=["System Manager"]).insert(ignore_permissions=True)

		frappe.set_user("Administrator")
		unrelated = self._create_role_user("guard.unrelated@example.com", "Blogger")
		frappe.set_user(self.admin.name)
		unrelated.first_name = "Changed By Admin"
		with self.assertRaises(frappe.PermissionError):
			unrelated.save(ignore_permissions=True)

	def test_owner_can_manage_owner_users_but_not_system_manager(self):
		frappe.set_user(self.owner.name)

		owner_user = self._new_user("guard.owner.created@example.com", role_profile_name="Owner").insert(
			ignore_permissions=True
		)
		self.assertEqual(owner_user.role_profile_name, "Owner")

		owner_user.first_name = "Owner Edited"
		owner_user.save(ignore_permissions=True)

		with self.assertRaises(frappe.PermissionError):
			self._new_user("guard.owner.system@example.com", roles=["System Manager"]).insert(ignore_permissions=True)

	def test_branch_roles_cannot_manage_users_even_with_ignored_docperm(self):
		frappe.set_user(self.branch_manager.name)

		with self.assertRaises(frappe.PermissionError):
			self._new_user("guard.branch.created@example.com", roles=["Branch Employee"]).insert(ignore_permissions=True)

		frappe.set_user("Administrator")
		target = self._create_role_user("guard.branch.target@example.com", "Branch Employee")
		frappe.set_user(self.branch_manager.name)
		target.first_name = "Changed By Branch"
		with self.assertRaises(frappe.PermissionError):
			target.save(ignore_permissions=True)

	def test_admin_user_permission_scope_is_limited_to_branch_users_and_portal_branch(self):
		frappe.set_user(self.admin.name)

		allowed_permission = frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": self.branch_employee.name,
				"allow": "Portal Branch",
				"for_value": self.branch.name,
				"apply_to_all_doctypes": 1,
			}
		).insert(ignore_permissions=True)
		self.assertEqual(allowed_permission.allow, "Portal Branch")

		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{
					"doctype": "User Permission",
					"user": self.owner.name,
					"allow": "Portal Branch",
					"for_value": self.branch.name,
					"apply_to_all_doctypes": 1,
				}
			).insert(ignore_permissions=True)

		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{
					"doctype": "User Permission",
					"user": self.branch_employee.name,
					"allow": "Customer",
					"for_value": "Any Customer",
					"apply_to_all_doctypes": 1,
				}
			).insert(ignore_permissions=True, ignore_links=True)

		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{
					"doctype": "User Permission",
					"user": self.admin.name,
					"allow": "Portal Branch",
					"for_value": self.branch.name,
					"apply_to_all_doctypes": 1,
				}
			).insert(ignore_permissions=True)

	def test_admin_and_owner_cannot_widen_kunal_role_profiles(self):
		frappe.set_user(self.admin.name)
		admin_profile = frappe.get_doc("Role Profile", "Admin")
		admin_profile.append("roles", {"role": "Owner"})
		with self.assertRaises(frappe.PermissionError):
			admin_profile.save(ignore_permissions=True)

		frappe.set_user(self.owner.name)
		owner_profile = frappe.get_doc("Role Profile", "Owner")
		owner_profile.append("roles", {"role": "System Manager"})
		with self.assertRaises(frappe.PermissionError):
			owner_profile.save(ignore_permissions=True)

	def _create_role_user(self, email, role):
		user = self._new_user(email).insert(ignore_permissions=True)
		user.append("roles", {"role": role})
		user.save(ignore_permissions=True)
		return user

	def _new_user(self, email, roles=None, role_profile_name=None):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"enabled": 1,
				"send_welcome_email": 0,
			}
		)
		if role_profile_name:
			user.role_profile_name = role_profile_name
		for role in roles or ():
			user.append("roles", {"role": role})
		return user
