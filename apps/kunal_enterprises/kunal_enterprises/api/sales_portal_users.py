"""Restricted admin lookup for one-to-one Sales Employee portal logins."""

import frappe
from frappe.utils import cint


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def available_users(doctype, txt, searchfield, start, page_len, filters=None):
	if not frappe.has_permission("Sales Employee", ptype="write"):
		frappe.throw("Sales Employee write permission is required.", frappe.PermissionError)
	filters = frappe.parse_json(filters) if isinstance(filters, str) else filters or {}
	employee = filters.get("sales_employee") or ""
	if employee:
		frappe.get_doc("Sales Employee", employee).check_permission("write")
	# Role profiles expand into the User's Has Role rows on save, matching
	# frappe.get_roles used by link validation and live permission checks.
	sql = """
		SELECT u.name, u.full_name, u.email FROM `tabUser` u
		WHERE u.enabled=1 AND u.user_type='System User'
		AND EXISTS (SELECT 1 FROM `tabHas Role` r
			WHERE r.parent=u.name AND r.parenttype='User' AND r.role='Sales Portal User')
		AND NOT EXISTS (SELECT 1 FROM `tabSales Employee` e
			WHERE e.portal_user=u.name AND e.name<>%(employee)s)
		AND (u.name LIKE %(txt)s OR u.full_name LIKE %(txt)s OR u.email LIKE %(txt)s)
		ORDER BY u.full_name, u.name LIMIT %(limit)s OFFSET %(start)s
	"""
	return frappe.db.multisql({"mariadb": sql, "postgres": sql.replace('`', '"')},
		dict(employee=employee, txt="%" + (txt or "") + "%",
			limit=max(1, min(cint(page_len), 200)), start=max(0, cint(start))))
