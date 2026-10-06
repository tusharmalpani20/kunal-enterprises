"""Expose existing incomplete allocations without changing orders or their history."""

import frappe


def execute():
	for name in frappe.get_all("Order", pluck="name"):
		order = frappe.get_doc("Order", name)
		order._set_godown_assignment_pending()
		frappe.db.set_value(
			"Order", name, "godown_assignment_pending", order.godown_assignment_pending,
			update_modified=False,
		)
