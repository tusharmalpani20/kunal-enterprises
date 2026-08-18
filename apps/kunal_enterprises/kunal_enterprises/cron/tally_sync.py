import hashlib
import json
import math

import frappe
from frappe.model.rename_doc import rename_doc
from frappe.utils import now_datetime


STOCK_SNAPSHOT_SOURCE_TABLE = "stock_godown_summary"
MASTER_SOURCE_TABLE = "tally_master_import"
VOUCHER_SOURCE_TABLE = "trn_voucher"

MASTER_NAME_FIELDS = {
	"Tally Unit": "unit_name",
	"Tally Godown": "godown_name",
	"Tally Stock Category": "category_name",
	"Tally Stock Group": "group_name",
	"Tally Item": "item_name",
	"Tally Customer Ledger": "client_code",
}


class IgnoredStockRowError(Exception):
	"""A source stock row that cannot be linked safely to Frappe masters."""


def sync_tally_masters(records=None):
	lock_name = "kunal_enterprises:tally_master_sync"
	if not _acquire_sync_lock(lock_name):
		frappe.throw("Tally master sync is already running")
	try:
		return _sync_tally_masters(records)
	finally:
		_release_sync_lock(lock_name)


def _sync_tally_masters(records=None):
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
	# Release Frappe's shared naming-series row before processing large batches.
	frappe.db.commit()

	records = records or {}
	master_rows = _flatten_master_records(records)
	processed = 0
	errors = 0

	for doctype, source_key in (
		("Tally Unit", "units"),
		("Tally Godown", "godowns"),
		("Tally Stock Category", "stock_categories"),
	):
		batch_processed, batch_errors = _sync_master_batch(doctype, records.get(source_key, []), run.name)
		processed += batch_processed
		errors += batch_errors

	group_paths, hierarchy_errors = _stock_group_paths(records.get("stock_groups", []), run.name)
	errors += hierarchy_errors
	if not hierarchy_errors:
		group_processed, group_errors = _sync_master_batch("Tally Stock Group", records.get("stock_groups", []), run.name)
		processed += group_processed
		errors += group_errors
		if group_processed:
			try:
				_apply_stock_group_hierarchy(group_paths)
			except Exception as error:
				errors += len(records.get("stock_groups", []))
				processed -= group_processed
				for record in records.get("stock_groups", []):
					_log_sync_error(run.name, record, error, MASTER_SOURCE_TABLE)

	for doctype, source_key in (("Tally Item", "items"), ("Tally Customer Ledger", "customer_ledgers")):
		batch_processed, batch_errors = _sync_master_batch(doctype, records.get(source_key, []), run.name)
		processed += batch_processed
		errors += batch_errors

	run.records_seen = len(master_rows)
	run.records_processed = processed
	run.errors_count = errors
	run.status = "Completed" if errors == 0 else "Completed With Errors"
	run.finished_at = now_datetime()
	run.save(ignore_permissions=True)
	return run


def sync_stock_snapshots(
	records=None,
	source_table=STOCK_SNAPSHOT_SOURCE_TABLE,
	snapshot_metadata=None,
	reconcile_missing=False,
):
	lock_name = "kunal_enterprises:tally_stock_sync"
	if not _acquire_sync_lock(lock_name):
		frappe.throw("Tally stock sync is already running")
	try:
		return _sync_stock_snapshots(records, source_table, snapshot_metadata, reconcile_missing)
	finally:
		_release_sync_lock(lock_name)


def _sync_stock_snapshots(records, source_table, snapshot_metadata, reconcile_missing):
	started_at = now_datetime()
	snapshot_metadata = snapshot_metadata or {}
	run = frappe.get_doc(
		{
			"doctype": "Tally Sync Run",
			"sync_type": "Stock",
			"status": "Running",
			"started_at": started_at,
			"source_table": source_table,
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()

	records = list(records or [])
	processed = 0
	errors = 0
	processed_keys = set()
	records_zeroed = 0
	quantities = []
	atomic_snapshot = bool(snapshot_metadata.get("snapshot_complete"))
	require_guids = atomic_snapshot and int(snapshot_metadata.get("contract_version") or 0) == 2
	savepoint = "tally_complete_stock_snapshot"
	ignored_row_errors = []
	fatal_row_errors = []
	unprotected_ignored_rows = 0
	if atomic_snapshot:
		frappe.db.savepoint(savepoint)

	for record in records:
		raw_quantity = record.get("quantity")
		if raw_quantity not in (None, ""):
			try:
				quantity = float(raw_quantity)
				if math.isfinite(quantity):
					quantities.append(quantity)
			except (TypeError, ValueError):
				pass
		try:
			processed_keys.add(_upsert_stock_snapshot(record, run.name, require_guids=require_guids))
			processed += 1
		except IgnoredStockRowError as error:
			errors += 1
			protected_key = _source_snapshot_key(record)
			if protected_key:
				processed_keys.add(protected_key)
			else:
				unprotected_ignored_rows += 1
			if atomic_snapshot:
				ignored_row_errors.append((record, error))
			else:
				_log_sync_error(run.name, record, error, source_table)
		except Exception as error:
			errors += 1
			if atomic_snapshot:
				fatal_row_errors.append((record, error))
			else:
				_log_sync_error(run.name, record, error, source_table)

	if atomic_snapshot and fatal_row_errors:
		frappe.db.rollback(save_point=savepoint)
		processed = 0
		processed_keys.clear()
		for record, error in ignored_row_errors + fatal_row_errors:
			_log_sync_error(run.name, record, error, source_table)
	elif atomic_snapshot:
		frappe.db.release_savepoint(savepoint)
		for record, error in ignored_row_errors:
			_log_sync_error(run.name, record, error, source_table)

	if (
		reconcile_missing
		and not fatal_row_errors
		and not unprotected_ignored_rows
		and snapshot_metadata.get("snapshot_complete")
	):
		records_zeroed = _reconcile_missing_stock_snapshots(run.name, processed_keys, snapshot_metadata, started_at)

	run.records_seen = len(records)
	run.records_processed = processed
	run.errors_count = errors
	run.negative_records = sum(1 for quantity in quantities if quantity < 0)
	run.zero_records = sum(1 for quantity in quantities if quantity == 0)
	run.records_zeroed = records_zeroed
	run.source_refreshed_at = snapshot_metadata.get("source_refreshed_at")
	run.source_as_on_date = snapshot_metadata.get("as_on_date")
	run.source_snapshot_id = snapshot_metadata.get("snapshot_id")
	run.snapshot_complete = int(bool(snapshot_metadata.get("snapshot_complete")))
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
	frappe.db.commit()

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


def _upsert_stock_snapshot(record, sync_run, require_guids=False):
	source_item = record.get("item")
	source_godown = record.get("godown")
	item_guid = _clean_guid(record.get("item_guid"))
	godown_guid = _clean_guid(record.get("godown_guid"))
	if not source_item:
		raise IgnoredStockRowError("Ignored stock snapshot row because item is missing")
	if not source_godown:
		raise IgnoredStockRowError("Ignored stock snapshot row because godown is missing")
	if require_guids:
		missing_guids = [
			fieldname for fieldname, value in (("item_guid", item_guid), ("godown_guid", godown_guid)) if not value
		]
		if missing_guids:
			raise IgnoredStockRowError(
				f"Ignored stock snapshot row because it is missing {', '.join(missing_guids)}"
			)
	quantity = _stock_quantity(record)
	if not item_guid and not frappe.db.exists("Tally Item", source_item):
		if record.get("source_item_exists") is False:
			raise IgnoredStockRowError(f"Stock snapshot item {source_item} is absent from mst_stock_item")
		if "source_item_parent" in record and record.get("source_item_parent") in (None, ""):
			raise IgnoredStockRowError(f"Stock snapshot item {source_item} has blank parent in mst_stock_item")
	item = _resolve_tally_reference("Tally Item", source_item, item_guid, error_class=IgnoredStockRowError)
	godown = _resolve_tally_reference(
		"Tally Godown",
		source_godown,
		godown_guid,
		require_active=True,
		error_class=IgnoredStockRowError,
	)
	item_guid = _clean_guid(frappe.db.get_value("Tally Item", item, "tally_guid"))
	godown_guid = _clean_guid(frappe.db.get_value("Tally Godown", godown, "tally_guid"))
	if not item_guid:
		raise IgnoredStockRowError(f"Tally Item {item} is missing tally_guid")
	if not godown_guid:
		raise IgnoredStockRowError(f"Tally Godown {godown} is missing tally_guid")
	snapshot_key = f"{item_guid}:{godown_guid}"
	existing_names = frappe.get_all(
		"Tally Stock Snapshot", filters={"tally_snapshot_key": snapshot_key}, pluck="name", limit_page_length=2
	)
	if not existing_names:
		existing_names = frappe.get_all(
			"Tally Stock Snapshot", filters={"item": item, "godown": godown}, pluck="name", limit_page_length=2
		)
	if len(existing_names) > 1:
		frappe.throw(f"Duplicate Tally Stock Snapshot for key {snapshot_key}")
	name = existing_names[0] if existing_names else None
	uom = record.get("uom")
	if not uom:
		uom = frappe.db.get_value("Tally Item", item, "uom")
	values = {
		"item": item,
		"godown": godown,
		"tally_snapshot_key": snapshot_key,
		"quantity": quantity,
		"uom": uom,
		"as_on_date": record.get("as_on_date"),
		"source_company": record.get("source_company"),
		"synced_at": record.get("synced_at") or now_datetime(),
		"source_sync_run": sync_run,
		"source_snapshot_id": record.get("source_snapshot_id"),
	}
	if name:
		frappe.db.set_value("Tally Stock Snapshot", name, values, update_modified=False)
	else:
		frappe.get_doc({"doctype": "Tally Stock Snapshot", **values}).insert(ignore_permissions=True)
	return snapshot_key


def _stock_quantity(record):
	raw_quantity = record.get("quantity")
	if raw_quantity in (None, ""):
		frappe.throw("Stock snapshot row is missing quantity")
	try:
		quantity = float(raw_quantity)
	except (TypeError, ValueError):
		frappe.throw(f"Stock snapshot row has invalid quantity {raw_quantity!r}")
	if not math.isfinite(quantity):
		frappe.throw(f"Stock snapshot row has non-finite quantity {raw_quantity!r}")
	return quantity


def _resolve_tally_reference(doctype, source_name, source_guid=None, require_active=False, error_class=None):
	if source_guid:
		filters = {"tally_guid": source_guid}
		if require_active:
			filters["is_active"] = 1
		resolved = frappe.db.get_value(doctype, filters, "name")
		if resolved:
			return resolved
		status = " or is inactive" if require_active else ""
		message = f"{doctype} GUID {source_guid} does not exist{status} (source name: {source_name})"
		if error_class:
			raise error_class(message)
		frappe.throw(message)

	filters = {"name": source_name}
	if require_active:
		filters["is_active"] = 1
	if frappe.db.exists(doctype, filters):
		return source_name
	status = " or is inactive" if require_active else ""
	message = f"{doctype} {source_name} does not exist{status}"
	if error_class:
		raise error_class(message)
	frappe.throw(message)


def _source_snapshot_key(record):
	item_guid = _clean_guid(record.get("item_guid"))
	godown_guid = _clean_guid(record.get("godown_guid"))
	if not item_guid and record.get("item"):
		item_guid = _clean_guid(frappe.db.get_value("Tally Item", record.get("item"), "tally_guid"))
	if not godown_guid and record.get("godown"):
		godown_guid = _clean_guid(frappe.db.get_value("Tally Godown", record.get("godown"), "tally_guid"))
	if item_guid and godown_guid:
		return f"{item_guid}:{godown_guid}"
	return None


def _clean_guid(value):
	if value is None:
		return None
	value = str(value).strip()
	return value or None


def _reconcile_missing_stock_snapshots(sync_run, processed_keys, snapshot_metadata, synced_at):
	source_company = snapshot_metadata.get("source_company")
	if not source_company:
		frappe.throw("Cannot reconcile missing stock rows without source_company")
	include_legacy_postgres_rows = int(snapshot_metadata.get("contract_version") == 2)

	stale_rows = frappe.db.sql(
		"""
		select snapshot.name, snapshot.tally_snapshot_key, snapshot.quantity
		from `tabTally Stock Snapshot` snapshot
		left join `tabTally Sync Run` source_run on source_run.name = snapshot.source_sync_run
		where source_run.source_table = %(source_table)s
			and (
				snapshot.source_company = %(source_company)s
				or %(include_legacy_postgres_rows)s = 1
			)
		""",
		{
			"source_company": source_company,
			"source_table": STOCK_SNAPSHOT_SOURCE_TABLE,
			"include_legacy_postgres_rows": include_legacy_postgres_rows,
		},
		as_dict=True,
	)
	stale_rows = [row for row in stale_rows if row.tally_snapshot_key not in processed_keys]
	for row in stale_rows:
		frappe.db.set_value(
			"Tally Stock Snapshot",
			row.name,
			{
				"quantity": 0,
				"as_on_date": snapshot_metadata.get("as_on_date"),
				"source_company": source_company,
				"synced_at": synced_at,
				"source_sync_run": sync_run,
				"source_snapshot_id": snapshot_metadata.get("snapshot_id"),
			},
			update_modified=False,
		)
	return sum(1 for row in stale_rows if float(row.quantity or 0) != 0)


def _upsert_tally_voucher(record):
	voucher_number = record.get("voucher_number")
	if not voucher_number:
		frappe.throw("Tally Voucher row is missing voucher_number")
	if not record.get("voucher_type"):
		frappe.throw("Tally Voucher row is missing voucher_type")
	if not record.get("party_client_code"):
		frappe.throw("Tally Voucher row is missing party_client_code")

	has_reference = bool(record.get("reference_number"))
	existing_voucher = frappe.get_doc("Tally Voucher", voucher_number) if frappe.db.exists("Tally Voucher", voucher_number) else None
	if not has_reference:
		reconciliation_state = "Unmatched"
		reconciled = 0
		reconciliation_reason = "MISSING_REFERENCE_NUMBER"
	elif existing_voucher and existing_voucher.reconciliation_state == "Unmatched":
		reconciliation_state = "Pending"
		reconciled = 0
		reconciliation_reason = None
	elif existing_voucher:
		reconciliation_state = existing_voucher.reconciliation_state or ("Matched" if existing_voucher.reconciled else "Pending")
		reconciled = int(existing_voucher.reconciled or 0)
		reconciliation_reason = existing_voucher.reconciliation_reason
	else:
		reconciliation_state = "Pending"
		reconciled = 0
		reconciliation_reason = None
	reconciliation_last_attempt = (
		existing_voucher.reconciliation_last_attempt
		if existing_voucher and reconciliation_state in {"Matched", "Manual Review"}
		else None
	)
	values = {
		"voucher_type": record.get("voucher_type"),
		"voucher_number": voucher_number,
		"reference_number": record.get("reference_number"),
		"party_client_code": record.get("party_client_code"),
		"tracking_number": record.get("tracking_number"),
		"voucher_date": record.get("voucher_date"),
		"reconciled": reconciled,
		"reconciliation_state": reconciliation_state,
		"reconciliation_last_attempt": reconciliation_last_attempt,
		"reconciliation_reason": reconciliation_reason,
		"lines": _voucher_lines(record),
	}
	if existing_voucher:
		voucher = existing_voucher
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
		source_item = line.get("item")
		source_godown = line.get("godown")
		if not source_item:
			frappe.throw("Tally Voucher Line row is missing item")
		if not source_godown:
			frappe.throw("Tally Voucher Line row is missing godown")
		item = _resolve_tally_reference("Tally Item", source_item, line.get("item_guid"))
		godown = _resolve_tally_reference(
			"Tally Godown", source_godown, line.get("godown_guid"), require_active=True
		)
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


def _sync_master_batch(doctype, records, sync_run):
	"""Synchronize a master doctype by immutable Tally GUID, including safe rename cycles."""
	valid_records = []
	errors = 0
	seen_guids = set()
	seen_names = set()
	name_field = MASTER_NAME_FIELDS[doctype]
	for record in records:
		name = record.get(name_field)
		guid = record.get("tally_guid")
		if not name or not guid:
			errors += 1
			_log_sync_error(sync_run, record, f"{doctype} row is missing {name_field} or tally_guid", MASTER_SOURCE_TABLE)
			continue
		if name in seen_names or guid in seen_guids:
			errors += 1
			_log_sync_error(sync_run, record, f"Duplicate source {doctype} name or tally_guid", MASTER_SOURCE_TABLE)
			continue
		seen_names.add(name)
		seen_guids.add(guid)
		valid_records.append(record)

	plans = []
	for record in valid_records:
		name = record[name_field]
		guid = record["tally_guid"]
		existing_name = frappe.db.get_value(doctype, {"tally_guid": guid}, "name")
		if not existing_name:
			name_match = frappe.db.get_value(doctype, {"name": name}, ["name", "tally_guid"], as_dict=True)
			if name_match:
				if name_match.tally_guid and name_match.tally_guid != guid:
					errors += 1
					_log_sync_error(sync_run, record, _name_guid_conflict(doctype, name, guid, name_match), MASTER_SOURCE_TABLE)
					continue
				existing_name = name_match.name
		plans.append({"record": record, "existing_name": existing_name, "original_name": existing_name})

	if errors:
		return 0, errors

	moving_guids = {
		plan["record"]["tally_guid"]
		for plan in plans
		if plan["existing_name"] and plan["existing_name"] != plan["record"][name_field]
	}
	for plan in plans:
		record = plan["record"]
		name = record[name_field]
		occupant = frappe.db.get_value(doctype, {"name": name}, ["name", "tally_guid"], as_dict=True)
		if occupant and occupant.name != plan["existing_name"] and occupant.tally_guid != record["tally_guid"] and occupant.tally_guid not in moving_guids:
			errors += 1
			_log_sync_error(
				sync_run,
				record,
				f"name_guid_conflict: {doctype} {name} belongs to GUID {occupant.tally_guid or '<missing>'}",
				MASTER_SOURCE_TABLE,
			)
	if errors:
		return 0, errors

	savepoint = f"tally_master_{hashlib.sha1(doctype.encode()).hexdigest()[:12]}"
	frappe.db.savepoint(savepoint)
	try:
		ledger_reference_renames = _prepare_ledger_reference_renames(plans) if doctype == "Tally Customer Ledger" else {}
		for plan in plans:
			if plan["existing_name"] and plan["existing_name"] != plan["record"][name_field]:
				temporary_name = _temporary_name(doctype, plan["record"]["tally_guid"])
				if frappe.db.exists(doctype, temporary_name):
					frappe.throw(f"Temporary rename target already exists: {temporary_name}")
				rename_doc(
					doctype,
					plan["existing_name"],
					temporary_name,
					force=True,
					ignore_permissions=True,
					rebuild_search=False,
				)
				plan["existing_name"] = temporary_name

		for plan in plans:
			record = plan["record"]
			name = record[name_field]
			if plan["existing_name"]:
				if plan["existing_name"] != name:
					rename_doc(
						doctype,
						plan["existing_name"],
						name,
						force=True,
						ignore_permissions=True,
						rebuild_search=False,
					)
				frappe.db.set_value(doctype, name, _master_values(doctype, record), update_modified=False)
			else:
				frappe.get_doc({"doctype": doctype, **_master_values(doctype, record)}).insert(ignore_permissions=True)
		if ledger_reference_renames:
			_finalize_ledger_reference_renames(ledger_reference_renames)
	except Exception as error:
		frappe.db.rollback(save_point=savepoint)
		for plan in plans:
			_log_sync_error(sync_run, plan["record"], error, MASTER_SOURCE_TABLE)
		return 0, len(plans)
	frappe.db.release_savepoint(savepoint)

	return len(plans), 0


def _master_values(doctype, record):
	values = {key: value for key, value in record.items() if not key.startswith("source_")}
	values["is_active"] = int(record.get("is_active", 1))
	if doctype == "Tally Stock Group":
		for fieldname in ("parent_stock_group", "root_stock_group", "is_root", "depth", "full_path"):
			values.pop(fieldname, None)
	return values


def _stock_group_paths(records, sync_run):
	by_name = {record.get("group_name"): record for record in records if record.get("group_name") and record.get("tally_guid")}
	errors = 0
	paths = {}

	def path_for(name, trail=None):
		trail = trail or []
		if name in trail:
			raise frappe.ValidationError(f"Stock Group hierarchy cycle: {' > '.join(trail + [name])}")
		record = by_name.get(name)
		if not record:
			raise frappe.ValidationError(f"Stock Group {name} is missing from source")
		parent = record.get("source_parent_group", record.get("parent_stock_group"))
		if parent and parent not in by_name:
			raise frappe.ValidationError(f"Stock Group {name} references missing parent {parent}")
		return (path_for(parent, trail + [name]) if parent else []) + [name]

	for name, record in by_name.items():
		try:
			paths[name] = path_for(name)
		except Exception as error:
			errors += 1
			_log_sync_error(sync_run, record, error, MASTER_SOURCE_TABLE)
	return paths, errors


def _apply_stock_group_hierarchy(paths):
	for name, path in paths.items():
		frappe.db.set_value(
			"Tally Stock Group",
			name,
			{
				"parent_stock_group": path[-2] if len(path) > 1 else None,
				"root_stock_group": path[0] if len(path) > 1 else None,
				"is_root": int(len(path) == 1),
				"depth": len(path) - 1,
				"full_path": " > ".join(path),
			},
			update_modified=False,
		)


def _prepare_ledger_reference_renames(plans):
	renames = {
		plan["original_name"]: plan["record"]["client_code"]
		for plan in plans
		if plan["original_name"] and plan["original_name"] != plan["record"]["client_code"]
	}
	if not renames:
		return {}

	old_codes = set(renames)
	for new_code in renames.values():
		customer_name = frappe.db.get_value("Customer", {"client_code": new_code}, "name")
		if customer_name and new_code not in old_codes:
			frappe.throw(f"Customer client_code conflict: {new_code} is already assigned to {customer_name}")

	temporary_codes = {}
	for old_code in renames:
		temporary_code = _temporary_data_value("customer_client_code", old_code)
		temporary_codes[old_code] = temporary_code
		frappe.db.sql("UPDATE `tabCustomer` SET client_code = %s WHERE client_code = %s", (temporary_code, old_code))
	return {"renames": renames, "temporary_codes": temporary_codes}


def _finalize_ledger_reference_renames(reference_renames):
	for old_code, new_code in reference_renames["renames"].items():
		temporary_code = reference_renames["temporary_codes"][old_code]
		frappe.db.sql("UPDATE `tabCustomer` SET client_code = %s WHERE client_code = %s", (new_code, temporary_code))
		frappe.db.sql("UPDATE `tabTally Voucher` SET party_client_code = %s WHERE party_client_code = %s", (new_code, old_code))
		frappe.db.sql(
			"UPDATE `tabSales Employee Assigned Customer` SET client_code = %s WHERE client_code = %s",
			(new_code, old_code),
		)


def _temporary_name(doctype, guid):
	digest = hashlib.sha1(f"{doctype}:{guid}".encode()).hexdigest()[:20]
	return f"__tally_{doctype.lower().replace(' ', '_')}_{digest}"


def _temporary_data_value(prefix, value):
	digest = hashlib.sha1(f"{prefix}:{value}".encode()).hexdigest()[:20]
	return f"__tally_{prefix}_{digest}"


def _name_guid_conflict(doctype, name, source_guid, existing):
	return (
		f"name_guid_conflict: {doctype} {name} has source GUID {source_guid} "
		f"but Frappe document {existing.name} has GUID {existing.tally_guid}"
	)


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
	if record.get("tally_guid"):
		return record.get("tally_guid")
	if record.get("item_guid") or record.get("godown_guid"):
		return f"{record.get('item_guid') or '<missing-item-guid>'}:{record.get('godown_guid') or '<missing-godown-guid>'}"
	item = record.get("item") or "<missing-item>"
	godown = record.get("godown") or "<missing-godown>"
	return f"{item}:{godown}"


def _acquire_sync_lock(lock_name):
	return bool(frappe.db.sql("SELECT GET_LOCK(%s, 0)", lock_name)[0][0])


def _release_sync_lock(lock_name):
	frappe.db.sql("SELECT RELEASE_LOCK(%s)", lock_name)
