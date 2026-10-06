import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from kunal_enterprises import desk_navigation
from kunal_enterprises.api import permission
from kunal_enterprises.permission_guards import owner_admin
from kunal_enterprises.permission_query_conditions import orders


class GodownAllocatorPermissionTests(unittest.TestCase):
	def _doc(self, pending, status="Placed", godown="Other Godown"):
		return frappe._dict(godown_assignment_pending=pending, status=status,
			godown_allocations=[SimpleNamespace(godown=godown)])

	def test_allocator_reads_pending_orders_but_has_no_arbitrary_write(self):
		with patch.object(orders.frappe, "get_roles", return_value=["Godown Allocator"]):
			self.assertTrue(orders.has_permission(self._doc(1), user="allocator", permission_type="read"))
			self.assertTrue(orders.has_permission(self._doc(0), user="allocator", permission_type="read"))
			self.assertFalse(orders.has_permission(self._doc(0, status="Processing"), user="allocator", permission_type="read"))
			self.assertFalse(orders.has_permission(self._doc(1), user="allocator", permission_type="write"))
			self.assertFalse(orders.has_permission(self._doc(1), user="allocator", permission_type="delete"))
			for status in ("Cancelled", "Partially Closed"):
				self.assertFalse(orders.has_permission(self._doc(1, status=status), user="allocator"))

	def test_closed_pending_orders_retain_normal_branch_manager_visibility(self):
		with (
			patch.object(orders.frappe, "get_roles", return_value=["Branch Manager", "Godown Allocator"]),
			patch.object(orders, "_allowed_godowns_for_user", return_value=["Own Godown"]),
		):
			for status in ("Cancelled", "Partially Closed"):
				self.assertFalse(orders.has_permission(self._doc(1, status=status), user="allocator"))
				self.assertTrue(orders.has_permission(self._doc(1, status=status, godown="Own Godown"), user="allocator"))

	def test_branch_allocator_can_read_pending_cross_branch_and_assigned_own_branch(self):
		with (
			patch.object(orders.frappe, "get_roles", return_value=["Branch Employee", "Godown Allocator"]),
			patch.object(orders, "_allowed_godowns_for_user", return_value=["Own Godown"]),
		):
			self.assertTrue(orders.has_permission(self._doc(1), user="allocator", permission_type="read"))
			self.assertTrue(orders.has_permission(self._doc(0, godown="Own Godown"), user="allocator"))
			self.assertFalse(orders.has_permission(self._doc(0, status="Processing"), user="allocator"))
			self.assertFalse(orders.has_permission(self._doc(0, status="Completed", godown="Own Godown"), user="allocator"))
			self.assertFalse(orders.has_permission(self._doc(1), user="allocator", permission_type="write"))

	def test_allocator_list_scope_includes_pending_without_branch_grant(self):
		db = SimpleNamespace(db_type="mariadb", escape=lambda value: repr(value))
		with (
			patch.object(orders.frappe, "get_roles", return_value=["Godown Allocator"]),
			patch.object(orders.frappe, "db", db),
		):
			query = orders.get_permission_query_conditions("allocator")
		self.assertEqual(query, "(`tabOrder`.`status` = 'Placed' or (`tabOrder`.`godown_assignment_pending` = 1 and `tabOrder`.`status` not in ('Cancelled', 'Partially Closed')))")

	def test_mixed_role_list_scope_keeps_branch_scope_and_pending_scope(self):
		db = SimpleNamespace(db_type="postgres", escape=lambda value: repr(value))
		with (
			patch.object(orders.frappe, "get_roles", return_value=["Branch Employee", "Godown Allocator"]),
			patch.object(orders.frappe, "db", db),
		):
			query = orders.get_permission_query_conditions("allocator")
		self.assertIn('"tabOrder"."godown_assignment_pending" = 1 and "tabOrder"."status" not in', query)
		self.assertIn("permission.user = 'allocator'", query)
		self.assertIn('"tabOrder"."status" in', query)

	def test_allocator_gets_app_and_only_operations_workspace(self):
		with (
			patch.object(permission.frappe, "get_roles", return_value=["Godown Allocator"]),
			patch.object(permission.frappe, "session", SimpleNamespace(user="allocator")),
		):
			self.assertTrue(permission.has_app_permission())
			self.assertEqual(desk_navigation.filter_workspace_pages_for_user(
				[{"name": "Operation"}, {"name": "Admin"}, {"name": "Users"}], "allocator"
			), [{"name": "Operation"}])

	def test_admin_can_assign_allocator_without_becoming_owner(self):
		with (
			patch.object(owner_admin, "_actor_class", return_value="Admin"),
			patch.object(owner_admin.frappe, "session", SimpleNamespace(user="admin")),
			patch.object(owner_admin.frappe.local, "flags", frappe._dict(in_test=False), create=True),
		):
			self.assertIn("Godown Allocator", owner_admin.get_all_roles())
			self.assertNotIn("Owner", owner_admin.get_all_roles())

	def test_role_profiles_and_workspace_publish_the_allocation_workflow(self):
		fixtures = Path(__file__).parents[1] / "kunal_enterprises" / "fixtures"
		profiles = {row["name"]: row for row in json.loads((fixtures / "role_profile.json").read_text())}
		for name in ("Owner", "Admin", "Godown Allocator"):
			self.assertIn("Godown Allocator", {row["role"] for row in profiles[name]["roles"]})
		self.assertEqual({row["role"] for row in profiles["Godown Allocator"]["roles"]}, {"Godown Allocator"})
		workspaces = {row["name"]: row for row in json.loads((fixtures / "workspace.json").read_text())}
		self.assertIn("Godown Allocator", {row["role"] for row in workspaces["Operation"]["roles"]})
		self.assertNotIn("Godown Allocator", {row["role"] for row in workspaces["Admin"]["roles"]})
		shortcut = next(row for row in workspaces["Operation"]["shortcuts"] if row["label"] == "Pending Godown Assignment")
		self.assertEqual(shortcut["link_to"], "Order")
		self.assertEqual(json.loads(shortcut["stats_filter"]), [
			["Order", "godown_assignment_pending", "=", 1, False],
			["Order", "status", "not in", ["Cancelled", "Partially Closed"], False],
		])


if __name__ == "__main__":
	unittest.main()
