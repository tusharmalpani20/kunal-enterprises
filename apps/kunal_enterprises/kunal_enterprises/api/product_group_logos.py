import frappe

from kunal_enterprises.api.utils import create_success_response, handle_error_response


OWNER_ADMIN_ROLES = ("Owner", "Admin")


@frappe.whitelist(methods=["POST"])
def set_product_group_logo(group, file_url):
	try:
		_require_owner_admin()
		if not group:
			frappe.throw("group is required")
		if not file_url:
			frappe.throw("file_url is required")
		frappe.db.set_value(
			"Tally Stock Group", group, "product_group_logo", file_url,
			update_modified=False,
		)
		return create_success_response(
			"Logo attached",
			{"group": group, "product_group_logo": file_url},
		)
	except Exception as error:
		return handle_error_response(error, "Unable to set product group logo")


def _require_owner_admin():
	if frappe.session.user == "Administrator":
		return
	if not set(OWNER_ADMIN_ROLES).intersection(frappe.get_roles(frappe.session.user)):
		frappe.throw("Only Owner/Admin can manage product group logos", title="Owner/Admin Required")
