import frappe


KUNAL_APP_ROLES = {"Owner", "Admin", "Branch Manager", "Branch Employee", "System Manager"}


def has_app_permission():
	if frappe.session.user == "Administrator":
		return True

	return bool(KUNAL_APP_ROLES.intersection(frappe.get_roles()))
