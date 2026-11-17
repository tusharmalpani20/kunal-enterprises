import frappe


KUNAL_APP_ROLES = {"Owner", "Admin", "Branch Manager", "Branch Employee", "Godown Allocator", "Order Coordinator", "System Manager", "Sales Portal User"}


def has_app_permission():
	if frappe.session.user == "Administrator":
		return True

	return bool(KUNAL_APP_ROLES.intersection(frappe.get_roles()))
