import frappe


OWNER_ROLE = "Owner"
ADMIN_ROLE = "Admin"
BRANCH_MANAGER_ROLE = "Branch Manager"
BRANCH_EMPLOYEE_ROLE = "Branch Employee"

OWNER_ADMIN_ROLES = (OWNER_ROLE, ADMIN_ROLE)
BRANCH_ROLES = (BRANCH_MANAGER_ROLE, BRANCH_EMPLOYEE_ROLE)
ORDER_ROLE_PRIORITY = (OWNER_ROLE, ADMIN_ROLE, BRANCH_MANAGER_ROLE, BRANCH_EMPLOYEE_ROLE)


def effective_order_role(allowed_roles, role_hint=None, message="Required role is missing", title="Permission Required"):
	allowed_roles = tuple(allowed_roles)
	if frappe.session.user == "Administrator":
		if role_hint:
			if role_hint in allowed_roles:
				return role_hint
			frappe.throw(message, title=title)
		return _highest_priority_role(set(allowed_roles))

	user_roles = set(frappe.get_roles(frappe.session.user))
	if role_hint and role_hint not in user_roles:
		frappe.throw(message, title=title)

	effective_role = _highest_priority_role(user_roles.intersection(allowed_roles))
	if not effective_role:
		frappe.throw(message, title=title)
	return effective_role


def _highest_priority_role(roles):
	for role in ORDER_ROLE_PRIORITY:
		if role in roles:
			return role
	return None
