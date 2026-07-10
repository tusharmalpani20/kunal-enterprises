import frappe
from frappe.model.document import Document


class TallyCustomerLedger(Document):
	pass


@frappe.whitelist()
def get_mapped_customer(client_code):
	client_code = (client_code or "").strip()
	if not client_code:
		return None
	if not frappe.has_permission("Tally Customer Ledger", "read"):
		frappe.throw("Not permitted", frappe.PermissionError)

	return frappe.db.get_value(
		"Customer",
		{"client_code": client_code},
		["name", "customer_name", "business_legal_name", "status", "customer_app_access"],
		as_dict=True,
	)
