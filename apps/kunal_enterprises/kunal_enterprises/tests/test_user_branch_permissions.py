import json
from pathlib import Path

import frappe
from frappe.desk.form.load import getdoc
from frappe.core.doctype.user_permission.user_permission import get_user_permissions
from frappe.tests.utils import FrappeTestCase

from kunal_enterprises import hooks
from kunal_enterprises.api.user_branch_permissions import get_user_branches, set_user_branches
from kunal_enterprises.permission_query_conditions.orders import has_permission as order_has_permission


class TestUserBranchPermissions(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = self._create_role_user("branch.assign.owner@example.com", "Owner")
		self.admin = self._create_role_user("branch.assign.admin@example.com", "Admin")
		self.branch_manager = self._create_role_user("branch.assign.manager@example.com", "Branch Manager")
		self.branch_employee = self._create_role_user("branch.assign.employee@example.com", "Branch Employee")
		self.non_kunal_user = self._create_role_user("branch.assign.unrelated@example.com", "Blogger")
		self.branch_a = self._create_branch("Branch Assignment A")
		self.branch_b = self._create_branch("Branch Assignment B")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_user_form_script_is_registered_for_existing_user_doctype(self):
		self.assertEqual(hooks.doctype_js["User"], "public/js/user.js")

	def test_user_form_script_removes_email_account_actions(self):
		script = self._user_form_script()

		self.assertIn("disable_user_email_delivery(frm)", script)
		self.assertIn("remove_email_account_actions(frm)", script)
		self.assertIn('frm.remove_custom_button(__("Create User Email"))', script)
		self.assertIn('frm.remove_custom_button(__("Reset Password"), __("Password"))', script)

	def test_user_form_script_renders_branch_assignment_table(self):
		script = self._user_form_script()

		self.assertIn("render_branch_assignment_table", script)
		self.assertIn("data-branch-action", script)
		self.assertIn('__("Assign")', script)
		self.assertIn('__("Unassign")', script)
		self.assertNotIn('fieldtype: "MultiSelectList"', script)

	def test_user_form_script_shows_branch_button_only_for_branch_users(self):
		script = self._user_form_script()

		self.assertIn("can_manage_target_branches(frm)", script)
		self.assertIn("BRANCH_ASSIGNABLE_ROLES", script)
		self.assertIn("GLOBAL_USER_ROLES", script)
		self.assertIn("if (!data.can_edit) {", script)

	def test_owner_and_admin_can_open_guarded_kunal_user_forms(self):
		self.assertTrue(
			frappe.has_permission(
				"User",
				ptype="read",
				doc=frappe.get_doc("User", self.branch_manager.name),
				user=self.owner.name,
			)
		)
		self.assertTrue(
			frappe.has_permission(
				"User",
				ptype="read",
				doc=frappe.get_doc("User", self.branch_employee.name),
				user=self.admin.name,
			)
		)
		self.assertFalse(
			frappe.has_permission(
				"User",
				ptype="read",
				doc=frappe.get_doc("User", self.owner.name),
				user=self.admin.name,
			)
		)

	def test_owner_can_load_branch_user_form_docinfo(self):
		frappe.set_user(self.owner.name)

		getdoc("User", self.branch_manager.name)

		self.assertEqual(frappe.response["docs"][0].name, self.branch_manager.name)

	def test_owner_can_assign_replace_and_deduplicate_branch_permissions(self):
		frappe.set_user(self.owner.name)

		first_result = set_user_branches(self.branch_manager.name, [self.branch_a.name, self.branch_b.name])
		second_result = set_user_branches(
			self.branch_manager.name,
			json.dumps([self.branch_a.name, self.branch_a.name]),
		)

		self.assertEqual(first_result["branches"], [self.branch_a.name, self.branch_b.name])
		self.assertEqual(second_result["branches"], [self.branch_a.name])
		self.assertEqual(second_result["created"], 0)
		self.assertEqual(second_result["deleted"], 1)
		self.assertEqual(
			self._portal_branch_permissions(self.branch_manager.name),
			[self.branch_a.name],
		)

	def test_get_user_branches_returns_assignment_table_rows(self):
		frappe.set_user(self.owner.name)
		set_user_branches(self.branch_manager.name, [self.branch_a.name])

		result = get_user_branches(self.branch_manager.name)
		branches_by_name = {row["name"]: row for row in result["branch_options"]}

		self.assertEqual(result["branches"], [self.branch_a.name])
		self.assertTrue({self.branch_a.name, self.branch_b.name}.issubset(branches_by_name))
		self.assertTrue(branches_by_name[self.branch_a.name]["assigned"])
		self.assertFalse(branches_by_name[self.branch_b.name]["assigned"])
		self.assertTrue(branches_by_name[self.branch_a.name]["is_active"])

	def test_admin_can_assign_branch_users_but_cannot_view_or_mutate_owner_users(self):
		frappe.set_user(self.admin.name)

		result = set_user_branches(self.branch_employee.name, [self.branch_a.name])

		self.assertEqual(result["branches"], [self.branch_a.name])
		self.assertEqual(self._portal_branch_permissions(self.branch_employee.name), [self.branch_a.name])
		with self.assertRaises(frappe.PermissionError):
			get_user_branches(self.owner.name)
		with self.assertRaises(frappe.PermissionError):
			set_user_branches(self.owner.name, [self.branch_b.name])

	def test_global_and_non_kunal_target_users_cannot_be_branch_scoped(self):
		frappe.set_user(self.owner.name)

		owner_info = get_user_branches(self.owner.name)
		admin_info = get_user_branches(self.admin.name)

		self.assertTrue(owner_info["is_global_user"])
		self.assertFalse(owner_info["can_edit"])
		self.assertTrue(admin_info["is_global_user"])
		self.assertFalse(admin_info["can_edit"])
		with self.assertRaises(frappe.PermissionError):
			set_user_branches(self.owner.name, [self.branch_a.name])
		with self.assertRaises(frappe.PermissionError):
			set_user_branches(self.admin.name, [self.branch_a.name])
		with self.assertRaises(frappe.PermissionError):
			get_user_branches(self.non_kunal_user.name)

	def test_branch_roles_and_guest_cannot_call_branch_assignment_api(self):
		frappe.set_user(self.branch_manager.name)

		with self.assertRaises(frappe.PermissionError):
			get_user_branches(self.branch_employee.name)
		with self.assertRaises(frappe.PermissionError):
			set_user_branches(self.branch_employee.name, [self.branch_a.name])

		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			get_user_branches(self.branch_employee.name)
		with self.assertRaises(frappe.PermissionError):
			set_user_branches(self.branch_employee.name, [self.branch_a.name])

	def test_invalid_and_new_inactive_branches_are_rejected(self):
		inactive_branch = self._create_branch("Branch Assignment Inactive", is_active=0)
		frappe.set_user(self.owner.name)

		with self.assertRaises(frappe.ValidationError):
			set_user_branches(self.branch_employee.name, ["Missing Branch"])
		with self.assertRaises(frappe.ValidationError):
			set_user_branches(self.branch_employee.name, [inactive_branch.name])

	def test_existing_inactive_branch_assignment_can_be_removed(self):
		inactive_branch = self._create_branch("Branch Assignment Remove Inactive", is_active=0)
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": self.branch_employee.name,
				"allow": "Portal Branch",
				"for_value": inactive_branch.name,
				"apply_to_all_doctypes": 1,
			}
		).insert(ignore_permissions=True)
		frappe.set_user(self.owner.name)

		current = get_user_branches(self.branch_employee.name)
		result = set_user_branches(self.branch_employee.name, [])

		self.assertEqual(current["branches"], [inactive_branch.name])
		self.assertEqual(result["branches"], [])
		self.assertEqual(self._portal_branch_permissions(self.branch_employee.name), [])

	def test_removing_branch_with_multiple_permission_rows_deletes_each_row_once(self):
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": self.branch_employee.name,
				"allow": "Portal Branch",
				"for_value": self.branch_a.name,
				"apply_to_all_doctypes": 1,
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": self.branch_employee.name,
				"allow": "Portal Branch",
				"for_value": self.branch_a.name,
				"apply_to_all_doctypes": 0,
				"applicable_for": "Order",
			}
		).insert(ignore_permissions=True)
		frappe.set_user(self.owner.name)

		result = set_user_branches(self.branch_employee.name, [])

		self.assertEqual(result["deleted"], 2)
		self.assertEqual(self._portal_branch_permissions(self.branch_employee.name), [])

	def test_unrelated_user_permissions_are_preserved_and_cache_is_cleared(self):
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": self.branch_employee.name,
				"allow": "User",
				"for_value": self.branch_employee.name,
				"apply_to_all_doctypes": 0,
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": self.branch_employee.name,
				"allow": "Portal Branch",
				"for_value": self.branch_a.name,
				"apply_to_all_doctypes": 1,
			}
		).insert(ignore_permissions=True)
		get_user_permissions(self.branch_employee.name)
		self.assertIsNotNone(frappe.cache.hget("user_permissions", self.branch_employee.name))
		frappe.set_user(self.owner.name)

		result = set_user_branches(self.branch_employee.name, [])

		self.assertEqual(result["deleted"], 1)
		self.assertTrue(
			frappe.db.exists(
				"User Permission",
				{
					"user": self.branch_employee.name,
					"allow": "User",
					"for_value": self.branch_employee.name,
				},
			)
		)
		self.assertIsNone(frappe.cache.hget("user_permissions", self.branch_employee.name))

	def test_updated_branch_assignments_drive_order_visibility(self):
		godown_a = self._create_godown("Branch Assignment Godown A")
		godown_b = self._create_godown("Branch Assignment Godown B")
		self._create_mapping(self.branch_a.name, godown_a.name)
		self._create_mapping(self.branch_b.name, godown_b.name)
		order_a = frappe._dict(
			status="Placed",
			godown_allocations=[frappe._dict(godown=godown_a.name)],
		)
		order_b = frappe._dict(
			status="Placed",
			godown_allocations=[frappe._dict(godown=godown_b.name)],
		)
		frappe.set_user(self.owner.name)

		set_user_branches(self.branch_manager.name, [self.branch_a.name, self.branch_b.name])
		self.assertTrue(order_has_permission(order_a, user=self.branch_manager.name))
		self.assertTrue(order_has_permission(order_b, user=self.branch_manager.name))

		set_user_branches(self.branch_manager.name, [self.branch_a.name])
		self.assertTrue(order_has_permission(order_a, user=self.branch_manager.name))
		self.assertFalse(order_has_permission(order_b, user=self.branch_manager.name))

	def _create_role_user(self, email, role):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"enabled": 1,
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		user.add_roles(role)
		return user

	def _user_form_script(self):
		script_path = Path(__file__).parents[1] / "public" / "js" / "user.js"
		return script_path.read_text()

	def _create_branch(self, branch_name, is_active=1):
		return frappe.get_doc(
			{
				"doctype": "Portal Branch",
				"branch_name": branch_name,
				"is_active": is_active,
			}
		).insert(ignore_permissions=True)

	def _create_godown(self, godown_name):
		return frappe.get_doc(
			{
				"doctype": "Tally Godown",
				"godown_name": godown_name,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)

	def _create_mapping(self, branch, godown):
		return frappe.get_doc(
			{
				"doctype": "Branch Godown Mapping",
				"portal_branch": branch,
				"godown": godown,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)

	def _portal_branch_permissions(self, user):
		return [
			row.for_value
			for row in frappe.get_all(
				"User Permission",
				filters={"user": user, "allow": "Portal Branch"},
				fields=["for_value"],
				order_by="for_value asc",
			)
		]
