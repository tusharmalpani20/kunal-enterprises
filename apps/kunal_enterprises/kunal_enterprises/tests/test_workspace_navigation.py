import json
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from kunal_enterprises import hooks
from kunal_enterprises import desk_navigation


WORKSPACE_NAMES = {"Operation", "Admin"}
ADMIN_NAVIGATION_DOCTYPES = {"User", "Role", "Role Profile"}
WORKSPACE_METADATA = {
	"Operation": {
		"roles": {"Owner", "Admin", "Branch Manager", "Branch Employee"},
		"icon": "list",
		"indicator_color": "blue",
	},
	"Admin": {
		"roles": {"Owner", "Admin"},
		"icon": "setting-gear",
		"indicator_color": "",
	},
}

OPERATION_SHORTCUTS = {
	"Orders": {"link_to": "Order", "stats_filter": None},
	"Placed Orders": {"link_to": "Order", "stats_filter": [["Order", "status", "=", "Placed", False]]},
	"Processing Orders": {
		"link_to": "Order",
		"stats_filter": [["Order", "status", "=", "Processing", False]],
	},
	"Manual Review Orders": {
		"link_to": "Order",
		"stats_filter": [["Order", "status", "=", "Manual Review", False]],
	},
}

ADMIN_SHORTCUTS = {
	"Customers": {"link_to": "Customer", "stats_filter": None},
	"Pending Customers": {
		"link_to": "Customer",
		"stats_filter": [["Customer", "status", "=", "Pending Admin Review", False]],
	},
	"Active Customers": {"link_to": "Customer", "stats_filter": [["Customer", "status", "=", "Active", False]]},
	"Disabled Customers": {
		"link_to": "Customer",
		"stats_filter": [["Customer", "status", "=", "Disabled", False]],
	},
	"Sales Employees": {"link_to": "Sales Employee", "stats_filter": None},
	"Active Sales Employees": {
		"link_to": "Sales Employee",
		"stats_filter": [["Sales Employee", "status", "=", "Active", False]],
	},
	"Disabled Sales Employees": {
		"link_to": "Sales Employee",
		"stats_filter": [["Sales Employee", "status", "=", "Disabled", False]],
	},
	"Portal Branch": {"link_to": "Portal Branch", "stats_filter": None},
	"Users": {"link_to": "User", "stats_filter": None},
	"Role Profiles": {"link_to": "Role Profile", "stats_filter": None},
	"Roles": {"link_to": "Role", "stats_filter": None},
}

FORBIDDEN_WORKSPACE_TARGETS = {
	"Tally Customer Ledger",
	"Tally Godown",
	"Tally Item",
	"Tally Stock Category",
	"Tally Stock Group",
	"Tally Stock Snapshot",
	"Tally Sync Error",
	"Tally Sync Run",
	"Tally Unit",
	"Tally Voucher",
	"Tally Voucher Line",
	"Branch Godown Mapping",
	"Order Reconciliation Log",
	"Mobile OTP",
	"Mobile Auth Token",
	"Order Reference Sequence",
	"Order Item",
	"Order Godown Allocation",
	"Customer Product Group Access",
	"Sales Employee Assigned Customer",
	"Sales Employee Product Group Access",
	"User Permission",
}


class TestWorkspaceNavigation(FrappeTestCase):
	def test_workspace_fixture_is_registered(self):
		workspace_fixture = self._workspace_fixture_config()

		self.assertIsNotNone(workspace_fixture)
		self.assertEqual(
			workspace_fixture["filters"],
			[["name", "in", ["Operation", "Admin"]]],
		)

	def test_boot_session_workspace_filter_is_registered(self):
		self.assertEqual(
			hooks.boot_session,
			["kunal_enterprises.desk_navigation.limit_workspaces"],
		)
		self.assertEqual(
			hooks.override_whitelisted_methods["frappe.desk.desktop.get_workspace_sidebar_items"],
			"kunal_enterprises.desk_navigation.get_workspace_sidebar_items",
		)

	def test_app_launcher_permission_hook_is_importable_and_callable(self):
		app_detail = hooks.add_to_apps_screen[0]

		has_permission = frappe.get_attr(app_detail["has_permission"])

		self.assertTrue(callable(has_permission))
		self.assertIsInstance(has_permission(), bool)

	def test_workspace_fixture_contains_expected_records_and_metadata(self):
		workspaces = self._workspace_fixtures()

		self.assertEqual(set(workspaces), WORKSPACE_NAMES)
		for workspace_name, expected in WORKSPACE_METADATA.items():
			self.assert_workspace_metadata(workspaces[workspace_name], expected)

	def test_workspace_shortcuts_match_approved_scope(self):
		workspaces = self._workspace_fixtures()

		self.assert_workspace_shortcuts(workspaces["Operation"], OPERATION_SHORTCUTS)
		self.assert_workspace_shortcuts(workspaces["Admin"], ADMIN_SHORTCUTS)

	def test_admin_workspace_targets_have_read_only_owner_admin_permissions(self):
		custom_docperms = self._custom_docperm_fixtures()

		for doctype in ADMIN_NAVIGATION_DOCTYPES:
			for role in ("Owner", "Admin"):
				permission = custom_docperms.get((doctype, role, 0))
				self.assertIsNotNone(permission, f"Missing {role} read permission for {doctype}")
				self.assertEqual(permission["read"], 1)
				self.assertEqual(permission["write"], 0)
				self.assertEqual(permission["create"], 0)
				self.assertEqual(permission["delete"], 0)

	def test_admin_navigation_permissions_preserve_builtin_administrator_actions(self):
		custom_docperms = self._custom_docperm_fixtures()

		for doctype in ADMIN_NAVIGATION_DOCTYPES:
			permission = custom_docperms.get((doctype, "Administrator", 0))
			self.assertIsNotNone(permission, f"Missing Administrator permission for {doctype}")
			self.assertEqual(permission["read"], 1)
			self.assertEqual(permission["write"], 1)
			self.assertEqual(permission["create"], 1)
			self.assertEqual(permission["delete"], 1)

	def test_user_role_fields_preserve_builtin_administrator_permlevel_access(self):
		custom_docperms = self._custom_docperm_fixtures()

		permission = custom_docperms.get(("User", "Administrator", 1))
		self.assertIsNotNone(permission, "Missing Administrator permission for User permlevel 1")
		self.assertEqual(permission["read"], 1)
		self.assertEqual(permission["write"], 1)
		self.assertEqual(permission["create"], 0)
		self.assertEqual(permission["delete"], 0)

	def test_boot_workspace_filter_keeps_only_kunal_workspaces_for_kunal_roles(self):
		self.assert_workspace_filter(
			["Owner"],
			["Operation", "Admin"],
		)
		self.assert_workspace_filter(
			["Admin"],
			["Operation", "Admin"],
		)
		self.assert_workspace_filter(
			["Branch Manager"],
			["Operation"],
		)
		self.assert_workspace_filter(
			["Branch Employee"],
			["Operation"],
		)

	def test_boot_workspace_filter_does_not_touch_system_manager_or_unrelated_users(self):
		all_workspaces = ["Operation", "Admin", "Users", "Website", "Tools"]

		self.assert_workspace_filter(["System Manager"], all_workspaces)
		self.assert_workspace_filter(["Blogger"], all_workspaces)

	def test_sidebar_api_filter_uses_same_kunal_role_rules(self):
		all_workspaces = ["Operation", "Admin", "Users", "Website", "Tools"]

		self.assert_workspace_page_filter(["Owner"], all_workspaces, ["Operation", "Admin"])
		self.assert_workspace_page_filter(["Admin"], all_workspaces, ["Operation", "Admin"])
		self.assert_workspace_page_filter(["Branch Manager"], all_workspaces, ["Operation"])
		self.assert_workspace_page_filter(["Branch Employee"], all_workspaces, ["Operation"])

	def test_workspace_content_references_existing_unique_shortcuts(self):
		for workspace in self._workspace_fixtures().values():
			shortcut_labels = [shortcut["label"] for shortcut in workspace["shortcuts"]]
			self.assertEqual(len(shortcut_labels), len(set(shortcut_labels)))

			content = json.loads(workspace["content"])
			content_ids = [block["id"] for block in content]
			self.assertEqual(len(content_ids), len(set(content_ids)))
			content_shortcuts = [
				block["data"]["shortcut_name"]
				for block in content
				if block["type"] == "shortcut"
			]
			self.assertEqual(set(content_shortcuts), set(shortcut_labels))

	def test_workspace_records_are_imported_to_site(self):
		for workspace_name in WORKSPACE_NAMES:
			self.assertTrue(frappe.db.exists("Workspace", workspace_name))

	def assert_workspace_metadata(self, workspace, expected):
		self.assertEqual(workspace["label"], workspace["name"])
		self.assertEqual(workspace["title"], workspace["name"])
		self.assertIn(workspace.get("module"), (None, ""))
		self.assertEqual(workspace.get("parent_page") or "", "")
		self.assertEqual(workspace.get("for_user") or "", "")
		self.assertEqual(workspace["public"], 1)
		self.assertEqual(workspace["is_hidden"], 0)
		self.assertEqual(workspace.get("icon"), expected["icon"])
		self.assertEqual(workspace.get("indicator_color") or "", expected["indicator_color"])
		self.assertEqual({row["role"] for row in workspace["roles"]}, expected["roles"])
		self.assertIsInstance(json.loads(workspace["content"]), list)

	def assert_workspace_shortcuts(self, workspace, expected_shortcuts):
		shortcuts = {shortcut["label"]: shortcut for shortcut in workspace["shortcuts"]}
		self.assertEqual(set(shortcuts), set(expected_shortcuts))

		for label, expected in expected_shortcuts.items():
			shortcut = shortcuts[label]
			self.assertEqual(shortcut["type"], "DocType")
			self.assertEqual(shortcut["link_to"], expected["link_to"])
			self.assertEqual(shortcut["doc_view"], "List")
			self.assertNotIn(shortcut["link_to"], FORBIDDEN_WORKSPACE_TARGETS)
			self.assertNotIn(shortcut["label"], FORBIDDEN_WORKSPACE_TARGETS)
			self.assertEqual(self._parse_stats_filter(shortcut.get("stats_filter")), expected["stats_filter"])

	def _workspace_fixture_config(self):
		for fixture in hooks.fixtures:
			doctype = fixture.get("dt") or fixture.get("doctype")
			if doctype == "Workspace":
				return fixture
		return None

	def _workspace_fixtures(self):
		fixture_path = Path(__file__).parents[1] / "fixtures" / "workspace.json"
		with fixture_path.open() as fixture_file:
			return {workspace["name"]: workspace for workspace in json.load(fixture_file)}

	def _custom_docperm_fixtures(self):
		fixture_path = Path(__file__).parents[1] / "fixtures" / "custom_docperm.json"
		with fixture_path.open() as fixture_file:
			return {
				(permission["parent"], permission["role"], permission["permlevel"]): permission
				for permission in json.load(fixture_file)
			}

	def _parse_stats_filter(self, value):
		if value in (None, "", "[]"):
			return None
		return json.loads(value)

	def assert_workspace_filter(self, roles, expected_workspaces):
		bootinfo = frappe._dict(
			allowed_workspaces=[
				frappe._dict(name=name)
				for name in ("Operation", "Admin", "Users", "Website", "Tools")
			]
		)
		original_get_roles = frappe.get_roles
		try:
			frappe.get_roles = lambda user=None: roles
			desk_navigation.filter_workspaces_for_user(bootinfo, "test@example.com")
		finally:
			frappe.get_roles = original_get_roles

		self.assertEqual(
			[workspace.name for workspace in bootinfo.allowed_workspaces],
			expected_workspaces,
		)

	def assert_workspace_page_filter(self, roles, workspace_names, expected_workspaces):
		pages = [frappe._dict(name=name) for name in workspace_names]
		original_get_roles = frappe.get_roles
		try:
			frappe.get_roles = lambda user=None: roles
			filtered_pages = desk_navigation.filter_workspace_pages_for_user(pages, "test@example.com")
		finally:
			frappe.get_roles = original_get_roles

		self.assertEqual([page.name for page in filtered_pages], expected_workspaces)
