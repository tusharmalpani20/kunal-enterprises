"""Move unambiguous early intake allocations into the single editable item table."""
import frappe


def execute():
	if not frappe.db.exists("DocType", "Order Intake Request"):
		return
	for name in frappe.get_all("Order Intake Request", filters={"layout_simplified": 0}, pluck="name"):
		doc = frappe.get_doc("Order Intake Request", name)
		# Validation performs the idempotent conversion and retains legacy evidence.
		doc.save(ignore_permissions=True)
