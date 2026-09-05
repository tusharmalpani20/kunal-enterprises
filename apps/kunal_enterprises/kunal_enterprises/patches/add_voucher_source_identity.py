"""Voucher numbers are display values; source company and GUID identify vouchers."""

import frappe


def execute():
	if frappe.db.db_type == "mariadb":
		indexes = frappe.db.sql("SHOW INDEX FROM `tabTally Voucher`", as_dict=True)
		for row in indexes:
			if row.Column_name == "voucher_number" and not row.Non_unique and row.Key_name != "PRIMARY":
				index = row.Key_name.replace("`", "``")
				frappe.db.sql(f"ALTER TABLE `tabTally Voucher` DROP INDEX `{index}`")
	else:
		constraints = frappe.db.sql(
			"""select tc.constraint_name from information_schema.table_constraints tc
			join information_schema.key_column_usage kcu on tc.constraint_name=kcu.constraint_name and tc.table_schema=kcu.table_schema
			where tc.table_name='tabTally Voucher' and tc.constraint_type='UNIQUE' and kcu.column_name='voucher_number' """,
			pluck=True,
		)
		for name in constraints:
			quoted = name.replace('"', '""')
			frappe.db.sql(f'ALTER TABLE "tabTally Voucher" DROP CONSTRAINT "{quoted}"')
	# Multiple legacy rows must remain possible until their source identities are verified.
	frappe.db.set_value("Tally Voucher", {"tally_guid": ""}, "tally_guid", None, update_modified=False)
	frappe.db.add_unique("Tally Voucher", ["source_company", "tally_guid"], "unique_tally_voucher_source")
