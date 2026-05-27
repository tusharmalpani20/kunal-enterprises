import frappe


BRANCH_EMPLOYEE_VISIBLE_STATUSES = ("Placed", "Processing", "Manual Review")
GLOBAL_ORDER_ROLES = {"System Manager", "Owner", "Admin"}
BRANCH_ORDER_ROLES = {"Branch Manager", "Branch Employee"}


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))

	if roles.intersection(GLOBAL_ORDER_ROLES):
		return None

	if not roles.intersection(BRANCH_ORDER_ROLES):
		return "1 = 0"

	user_sql = frappe.db.escape(user)
	status_condition = ""
	if "Branch Employee" in roles and "Branch Manager" not in roles:
		statuses = ", ".join(frappe.db.escape(status) for status in BRANCH_EMPLOYEE_VISIBLE_STATUSES)
		status_condition = f'and "tabOrder"."status" in ({statuses})'

	return f"""
		exists (
			select 1
			from "tabOrder Godown Allocation" allocation
			inner join "tabBranch Godown Mapping" mapping
				on mapping.godown = allocation.godown
				and mapping.is_active = 1
			inner join "tabPortal Branch" branch
				on branch.name = mapping.portal_branch
				and branch.is_active = 1
			inner join "tabUser Permission" permission
				on permission.allow = 'Portal Branch'
				and permission.for_value = mapping.portal_branch
				and permission.user = {user_sql}
			where allocation.parent = "tabOrder"."name"
			{status_condition}
		)
	"""


def has_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))

	if roles.intersection(GLOBAL_ORDER_ROLES):
		return True

	if not roles.intersection(BRANCH_ORDER_ROLES):
		return False

	if "Branch Employee" in roles and "Branch Manager" not in roles:
		if doc.status not in BRANCH_EMPLOYEE_VISIBLE_STATUSES:
			return False

	allowed_godowns = set(_allowed_godowns_for_user(user))
	if not allowed_godowns:
		return False

	return any(row.godown in allowed_godowns for row in doc.get("godown_allocations", []))


def _allowed_godowns_for_user(user):
	branches = [
		row.for_value
		for row in frappe.get_all(
			"User Permission",
			filters={"user": user, "allow": "Portal Branch"},
			fields=["for_value"],
		)
	]
	if not branches:
		return []

	return [
		row.godown
		for row in frappe.get_all(
			"Branch Godown Mapping",
			filters={"portal_branch": ("in", branches), "is_active": 1},
			fields=["godown"],
		)
	]
