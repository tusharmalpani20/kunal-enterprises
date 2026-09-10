"""Add measured-path indexes used by bulk and incremental reconciliation."""

import frappe


def execute():
	if frappe.db.table_exists("Tally Voucher", cached=False):
		frappe.db.add_index(
			"Tally Voucher",
			["source_company", "order_number"],
			"tally_voucher_company_order",
		)
	if frappe.db.table_exists("Order Reconciliation Log", cached=False):
		index_name = "reconciliation_log_voucher_order_time"
		if not frappe.db.has_index("tabOrder Reconciliation Log", index_name):
			frappe.db.multisql(
				{
					"mariadb": f"""
						ALTER TABLE `tabOrder Reconciliation Log`
						ADD INDEX `{index_name}`
							(`voucher`, `order`, `created_at`, `creation`, `name`)
					""",
					"postgres": f"""
						CREATE INDEX "{index_name}" ON "tabOrder Reconciliation Log"
						("voucher", "order", "created_at", "creation", "name")
					""",
				}
			)
	if frappe.db.table_exists("Tally Reconciliation Work Item", cached=False):
		frappe.db.add_index(
			"Tally Reconciliation Work Item",
			["source_company", "first_seen_at"],
			"reconciliation_work_company_age",
		)
