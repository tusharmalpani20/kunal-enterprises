import frappe


KUNAL_OPERATIONS_WORKSPACE = "Kunal Operations"
KUNAL_ADMIN_WORKSPACE = "Kunal Admin"

OWNER_ROLE = "Owner"
ADMIN_ROLE = "Admin"
BRANCH_MANAGER_ROLE = "Branch Manager"
BRANCH_EMPLOYEE_ROLE = "Branch Employee"
SYSTEM_MANAGER_ROLE = "System Manager"


def limit_workspaces(bootinfo):
	filter_workspaces_for_user(bootinfo, frappe.session.user)


@frappe.whitelist()
def get_workspace_sidebar_items():
	from frappe.desk.desktop import get_workspace_sidebar_items as frappe_get_workspace_sidebar_items

	sidebar_items = frappe_get_workspace_sidebar_items()
	sidebar_items["pages"] = filter_workspace_pages_for_user(
		sidebar_items.get("pages"),
		frappe.session.user,
	)
	return sidebar_items


def filter_workspaces_for_user(bootinfo, user):
	bootinfo.allowed_workspaces = filter_workspace_pages_for_user(
		bootinfo.get("allowed_workspaces"),
		user,
	)


def filter_workspace_pages_for_user(pages, user):
	allowed_workspace_names = _allowed_workspace_names_for_user(user)
	if allowed_workspace_names is None:
		return pages or []

	return [
		workspace
		for workspace in (pages or [])
		if _workspace_name(workspace) in allowed_workspace_names
	]


def _allowed_workspace_names_for_user(user):
	if user in ("Administrator", "Guest"):
		return None

	roles = set(frappe.get_roles(user))
	if SYSTEM_MANAGER_ROLE in roles:
		return None
	if roles.intersection({OWNER_ROLE, ADMIN_ROLE}):
		return {KUNAL_OPERATIONS_WORKSPACE, KUNAL_ADMIN_WORKSPACE}
	if roles.intersection({BRANCH_MANAGER_ROLE, BRANCH_EMPLOYEE_ROLE}):
		return {KUNAL_OPERATIONS_WORKSPACE}
	return None


def _workspace_name(workspace):
	if isinstance(workspace, dict):
		return workspace.get("name")
	return getattr(workspace, "name", None)
