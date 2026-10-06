import frappe


BRANCH_EMPLOYEE_VISIBLE_STATUSES = ("Placed", "Processing", "Manual Review")
GLOBAL_ORDER_ROLES = {"System Manager", "Owner", "Admin"}
BRANCH_ORDER_ROLES = {"Branch Manager", "Branch Employee"}
GODOWN_ALLOCATOR_ROLE = "Godown Allocator"
GODOWN_ASSIGNMENT_CLOSED_STATUSES = ("Cancelled", "Partially Closed")


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))

	if roles.intersection(GLOBAL_ORDER_ROLES):
		return None

	closed_statuses = ", ".join(frappe.db.escape(status) for status in GODOWN_ASSIGNMENT_CLOSED_STATUSES)
	pending_condition = (
		f"({_table('Order')}.{_column('godown_assignment_pending')} = 1 "
		f"and {_table('Order')}.{_column('status')} not in ({closed_statuses}))"
	)
	allocator_condition = f"({_table('Order')}.{_column('status')} = 'Placed' or {pending_condition})"
	if not roles.intersection(BRANCH_ORDER_ROLES):
		return allocator_condition if GODOWN_ALLOCATOR_ROLE in roles else "1 = 0"

	user_sql = frappe.db.escape(user)
	status_condition = ""
	order_table = _table("Order")
	allocation_table = _table("Order Godown Allocation")
	mapping_table = _table("Branch Godown Mapping")
	branch_table = _table("Portal Branch")
	permission_table = _table("User Permission")
	if "Branch Employee" in roles and "Branch Manager" not in roles:
		statuses = ", ".join(frappe.db.escape(status) for status in BRANCH_EMPLOYEE_VISIBLE_STATUSES)
		status_condition = f"and {order_table}.{_column('status')} in ({statuses})"

	branch_condition = f"""
		exists (
			select 1
			from {allocation_table} allocation
			inner join {mapping_table} mapping
				on mapping.godown = allocation.godown
				and mapping.is_active = 1
			inner join {branch_table} branch
				on branch.name = mapping.portal_branch
				and branch.is_active = 1
			inner join {permission_table} permission
				on permission.allow = 'Portal Branch'
				and permission.for_value = mapping.portal_branch
				and permission.user = {user_sql}
			where allocation.parent = {order_table}.{_column('name')}
			{status_condition}
		)
	"""
	if GODOWN_ALLOCATOR_ROLE in roles:
		return f"({allocator_condition} or ({branch_condition}))"
	return branch_condition


def has_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))

	if roles.intersection(GLOBAL_ORDER_ROLES):
		return True

	if GODOWN_ALLOCATOR_ROLE in roles:
		# Allocation changes go through the guarded assignment API, never generic Desk writes.
		if permission_type not in (None, "read", "select"):
			return False
		if doc.status == "Placed" or (
			doc.get("godown_assignment_pending") and doc.status not in GODOWN_ASSIGNMENT_CLOSED_STATUSES
		):
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


def _table(doctype):
	quote = '"' if frappe.db.db_type == "postgres" else "`"
	return f"{quote}tab{doctype}{quote}"


def _column(fieldname):
	quote = '"' if frappe.db.db_type == "postgres" else "`"
	return f"{quote}{fieldname}{quote}"
