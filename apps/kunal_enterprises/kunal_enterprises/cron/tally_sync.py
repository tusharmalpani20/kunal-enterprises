import json

import frappe
from frappe.utils import now_datetime


STOCK_SNAPSHOT_SOURCE_TABLE = "rpt_stock_godown_balance"
MASTER_SOURCE_TABLE = "tally_master_import"
VOUCHER_SOURCE_TABLE = "trn_voucher"


def sync_tally_masters(records=None):
	started_at = now_datetime()
	run = frappe.get_doc(
		{
			"doctype": "Tally Sync Run",
			"sync_type": "Masters",
			"status": "Running",
			"started_at": started_at,
			"source_table": MASTER_SOURCE_TABLE,
		}
	).insert(ignore_permissions=True)

	records = records or {}
	master_rows = _flatten_master_records(records)
	processed = 0
	errors = 0

	for doctype, record in master_rows:
		try:
			_upsert_master_record(doctype, record)
			processed += 1
		except Exception as error:
			errors += 1
			_log_sync_error(run.name, record, error, MASTER_SOURCE_TABLE)

	run.records_seen = len(master_rows)
	run.records_processed = processed
	run.errors_count = errors
	run.status = "Completed" if errors == 0 else "Completed With Errors"
	run.finished_at = now_datetime()
	run.save(ignore_permissions=True)
	return run


def sync_stock_snapshots(records=None):
	started_at = now_datetime()
	run = frappe.get_doc(
		{
			"doctype": "Tally Sync Run",
			"sync_type": "Stock",
			"status": "Running",
			"started_at": started_at,
			"source_table": STOCK_SNAPSHOT_SOURCE_TABLE,
		}
	).insert(ignore_permissions=True)

	records = list(records or [])
	processed = 0
	errors = 0

	for record in records:
		try:
			_upsert_stock_snapshot(record, run.name)
			processed += 1
		except Exception as error:
			errors += 1
			_log_sync_error(run.name, record, error, STOCK_SNAPSHOT_SOURCE_TABLE)

	run.records_seen = len(records)
	run.records_processed = processed
	run.errors_count = errors
	run.status = "Completed" if errors == 0 else "Completed With Errors"
	run.finished_at = now_datetime()
	run.save(ignore_permissions=True)
	return run


def sync_tally_vouchers(records=None):
	started_at = now_datetime()
	run = frappe.get_doc(
		{
			"doctype": "Tally Sync Run",
			"sync_type": "Vouchers",
			"status": "Running",
			"started_at": started_at,
			"source_table": VOUCHER_SOURCE_TABLE,
		}
	).insert(ignore_permissions=True)

	records = list(records or [])
	processed = 0
	errors = 0

	for record in records:
		try:
			_upsert_tally_voucher(record)
			processed += 1
		except Exception as error:
			errors += 1
			_log_sync_error(run.name, record, error, VOUCHER_SOURCE_TABLE)

	run.records_seen = len(records)
	run.records_processed = processed
	run.errors_count = errors
	run.status = "Completed" if errors == 0 else "Completed With Errors"
	run.finished_at = now_datetime()
	run.save(ignore_permissions=True)
	return run


def _upsert_stock_snapshot(record, sync_run):
	item = record.get("item")
	godown = record.get("godown")
	if not item:
		frappe.throw("Stock snapshot row is missing item")
	if not godown:
		frappe.throw("Stock snapshot row is missing godown")
	if not frappe.db.exists("Tally Item", item):
		frappe.throw(f"Tally Item {item} does not exist")
	if not frappe.db.exists("Tally Godown", {"name": godown, "is_active": 1}):
		frappe.throw(f"Tally Godown {godown} does not exist or is inactive")

	name = f"{item}-{godown}"
	values = {
		"item": item,
		"godown": godown,
		"quantity": float(record.get("quantity") or 0),
		"uom": record.get("uom"),
		"as_on_date": record.get("as_on_date"),
		"source_company": record.get("source_company"),
		"synced_at": record.get("synced_at") or now_datetime(),
		"source_sync_run": sync_run,
	}
	if frappe.db.exists("Tally Stock Snapshot", name):
		frappe.db.set_value("Tally Stock Snapshot", name, values)
	else:
		frappe.get_doc({"doctype": "Tally Stock Snapshot", **values}).insert(ignore_permissions=True)


def _upsert_tally_voucher(record):
	voucher_number = record.get("voucher_number")
	if not voucher_number:
		frappe.throw("Tally Voucher row is missing voucher_number")
	if not record.get("voucher_type"):
		frappe.throw("Tally Voucher row is missing voucher_type")
	if not record.get("reference_number"):
		frappe.throw("Tally Voucher row is missing reference_number")
	if not record.get("party_client_code"):
		frappe.throw("Tally Voucher row is missing party_client_code")

	values = {
		"voucher_type": record.get("voucher_type"),
		"voucher_number": voucher_number,
		"reference_number": record.get("reference_number"),
		"party_client_code": record.get("party_client_code"),
		"tracking_number": record.get("tracking_number"),
		"voucher_date": record.get("voucher_date"),
		"reconciled": 0,
		"lines": _voucher_lines(record),
	}
	if frappe.db.exists("Tally Voucher", voucher_number):
		voucher = frappe.get_doc("Tally Voucher", voucher_number)
		voucher.update(values)
		voucher.set("lines", [])
		for line in values["lines"]:
			voucher.append("lines", line)
		voucher.save(ignore_permissions=True)
	else:
		frappe.get_doc({"doctype": "Tally Voucher", **values}).insert(ignore_permissions=True)


def _voucher_lines(record):
	lines = []
	for line in record.get("lines", []):
		item = line.get("item")
		godown = line.get("godown")
		if not item:
			frappe.throw("Tally Voucher Line row is missing item")
		if not godown:
			frappe.throw("Tally Voucher Line row is missing godown")
		if not frappe.db.exists("Tally Item", item):
			frappe.throw(f"Tally Item {item} does not exist")
		if not frappe.db.exists("Tally Godown", {"name": godown, "is_active": 1}):
			frappe.throw(f"Tally Godown {godown} does not exist or is inactive")
		lines.append(
			{
				"item": item,
				"godown": godown,
				"quantity": float(line.get("quantity") or 0),
				"tracking_number": line.get("tracking_number") or record.get("tracking_number"),
			}
		)
	if not lines:
		frappe.throw("Tally Voucher row must include at least one line")
	return lines


def _flatten_master_records(records):
	return (
		[("Tally Unit", record) for record in records.get("units", [])]
		+ [("Tally Godown", record) for record in records.get("godowns", [])]
		+ [("Tally Stock Category", record) for record in records.get("stock_categories", [])]
		+ [("Tally Stock Group", record) for record in records.get("stock_groups", [])]
		+ [("Tally Item", record) for record in records.get("items", [])]
		+ [("Tally Customer Ledger", record) for record in records.get("customer_ledgers", [])]
	)


def _upsert_master_record(doctype, record):
	name_field = {
		"Tally Unit": "unit_name",
		"Tally Godown": "godown_name",
		"Tally Stock Category": "category_name",
		"Tally Stock Group": "group_name",
		"Tally Item": "item_name",
		"Tally Customer Ledger": "client_code",
	}[doctype]
	name = record.get(name_field)
	if not name:
		frappe.throw(f"{doctype} row is missing {name_field}")

	values = {**record, "is_active": int(record.get("is_active", 1))}
	if frappe.db.exists(doctype, name):
		frappe.db.set_value(doctype, name, values)
	else:
		frappe.get_doc({"doctype": doctype, **values}).insert(ignore_permissions=True)


def _log_sync_error(sync_run, record, error, source_table):
	frappe.get_doc(
		{
			"doctype": "Tally Sync Error",
			"sync_run": sync_run,
			"source_table": source_table,
			"source_key": _source_key(record),
			"error_message": str(error),
			"raw_payload": json.dumps(record, default=str, sort_keys=True),
			"detected_at": now_datetime(),
		}
	).insert(ignore_permissions=True)


def _source_key(record):
	if record.get("voucher_number"):
		return record.get("voucher_number")
	item = record.get("item") or "<missing-item>"
	godown = record.get("godown") or "<missing-godown>"
	return f"{item}:{godown}"
