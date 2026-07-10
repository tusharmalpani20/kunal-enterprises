"""Add database-level uniqueness after the nullable Tally identity fields exist."""

import frappe


IDENTITY_FIELDS = (
	("Tally Unit", "tally_guid", "unique_tally_unit_guid"),
	("Tally Godown", "tally_guid", "unique_tally_godown_guid"),
	("Tally Stock Category", "tally_guid", "unique_tally_stock_category_guid"),
	("Tally Stock Group", "tally_guid", "unique_tally_stock_group_guid"),
	("Tally Item", "tally_guid", "unique_tally_item_guid"),
	("Tally Customer Ledger", "tally_guid", "unique_tally_customer_ledger_guid"),
	("Tally Stock Snapshot", "tally_snapshot_key", "unique_tally_snapshot_key"),
)


def execute():
	for doctype, fieldname, constraint_name in IDENTITY_FIELDS:
		if not frappe.db.has_column(doctype, fieldname):
			continue
		frappe.db.sql(f"UPDATE `tab{doctype}` SET `{fieldname}` = NULL WHERE `{fieldname}` = ''")
		duplicates = frappe.db.sql(
			f"""
			SELECT `{fieldname}`
			FROM `tab{doctype}`
			WHERE `{fieldname}` IS NOT NULL
			GROUP BY `{fieldname}`
			HAVING COUNT(*) > 1
			""",
			pluck=True,
		)
		if duplicates:
			frappe.throw(f"Cannot add {constraint_name}; duplicate values: {', '.join(duplicates[:10])}")
		if not _has_unique_constraint(doctype, fieldname):
			frappe.db.add_unique(doctype, [fieldname], constraint_name)

	if frappe.db.has_column("Tally Voucher", "reconciliation_state"):
		frappe.db.sql(
			"""
			UPDATE `tabTally Voucher`
			SET reconciliation_state = CASE
				WHEN reconciled = 1 THEN 'Matched'
				WHEN COALESCE(reference_number, '') = '' THEN 'Unmatched'
				ELSE 'Pending'
			END
			WHERE COALESCE(reconciliation_state, '') = '' OR reconciled = 1
			"""
		)


def _has_unique_constraint(doctype, fieldname):
	rows = frappe.db.sql(f"SHOW INDEX FROM `tab{doctype}`", as_dict=True)
	return any(not row.Non_unique and row.Column_name == fieldname for row in rows)
