"""Index bounded retention queries without removing any history during migration."""

import frappe


def execute():
	for doctype, fields, name in [
		("Tally Sync Error", ["resolved", "resolved_at"], "sync_error_retention"),
		("Tally Sync Error", ["sync_run"], "sync_error_parent"),
		("Tally Sync Run", ["status", "finished_at"], "sync_run_retention"),
		("Tally Sync Run", ["sync_type", "status", "creation", "name"], "sync_run_checkpoint"),
		("Tally Stock Snapshot", ["source_sync_run"], "stock_snapshot_source_run"),
	]:
		if frappe.db.table_exists(doctype, cached=False):
			frappe.db.add_index(doctype, fields, name)
