"""Apply mirror observations while retaining accepted data when the source is uncertain."""

import hashlib
import json
from collections import defaultdict
from decimal import Decimal
from time import perf_counter

import frappe
from frappe.utils import get_datetime, now_datetime

from kunal_enterprises.integrations.voucher_contract import validate_snapshot
from kunal_enterprises.integrations.order_details import order_candidates
from kunal_enterprises.integrations.reconciliation_settings import RECONCILIATION_LOCK_SECONDS


HELD_REFRESH_BATCH_SIZE = 500


def configured_types():
	value = frappe.conf.get("tally_fulfillment_voucher_type_guids") or []
	if isinstance(value, str):
		value = json.loads(value)
	if not isinstance(value, list):
		frappe.throw(
			"tally_fulfillment_voucher_type_guids must be a JSON list of approved delivery-challan type GUIDs"
		)
	return set(value)


def import_snapshot(connection):
	from kunal_enterprises.integrations.voucher_mirror import read_mirror

	try:
		state, payloads = read_mirror(connection, frappe.conf.get("tally_source_company"))
		return apply_snapshot(state, payloads)
	except Exception as error:
		# The apply path has already rolled back its writes; retain an operational failure record.
		run = frappe.get_doc(
			dict(
				doctype="Tally Sync Run",
				sync_type="Vouchers",
				status="Failed",
				started_at=now_datetime(),
				finished_at=now_datetime(),
				source_table="trn_voucher",
				errors_count=1,
			)
		).insert(ignore_permissions=True)
		frappe.get_doc(
			dict(
				doctype="Tally Sync Error",
				sync_run=run.name,
				source_table="trn_voucher",
				error_message=str(error),
				raw_payload="{}",
				detected_at=now_datetime(),
			)
		).insert(ignore_permissions=True)
		frappe.db.commit()
		raise


def apply_snapshot(state, payloads):
	company = frappe.conf.get("tally_source_company")
	allowed = configured_types()
	validate_snapshot(state, payloads, company, allowed)
	with frappe.cache().lock(
		frappe.cache().make_key("kunal:portal-voucher-import"),
		timeout=RECONCILIATION_LOCK_SECONDS,
		blocking_timeout=0,
	):
		from kunal_enterprises.cron.reconciliation import assert_current_history

		assert_current_history()
		companies = set(
			frappe.get_all("Tally Voucher", filters={"source_company": ("!=", "")}, pluck="source_company")
		)
		if companies and companies != {company}:
			frappe.throw(
				"This site already imports another Tally company; changing source company requires an explicit migration"
			)
		latest = frappe.db.get_value(
			"Tally Sync Run",
			{"source_table": "trn_voucher", "sync_type": "Vouchers", "status": "Completed"},
			["source_refreshed_at", "source_metadata"],
			order_by="source_refreshed_at desc",
			as_dict=True,
		)
		if (
			latest
			and latest.source_refreshed_at
			and get_datetime(state["completed_at"]) < get_datetime(latest.source_refreshed_at)
		):
			frappe.throw("Refusing an older voucher snapshot")
		previous_metadata = json.loads(latest.source_metadata or "{}") if latest else {}
		state["period_changed"] = bool(
			previous_metadata.get("period_from")
			and (previous_metadata.get("period_from"), previous_metadata.get("period_to"))
			!= (state.get("period_from"), state.get("period_to"))
		)
		frappe.db.savepoint("portal_voucher_import")
		try:
			previous_import_flag = getattr(frappe.flags, "in_tally_voucher_import", False)
			frappe.flags.in_tally_voucher_import = True
			try:
				result = _apply_snapshot(state, payloads, company, allowed)
			finally:
				frappe.flags.in_tally_voucher_import = previous_import_flag
			# Publish changes and recalculated orders together while still holding the import lock.
			from kunal_enterprises.cron.reconciliation import _run_reconciliation
			from kunal_enterprises.integrations.tally_postgres import _serialize_run

			change_set = result.pop("_change_set")
			result["reconciliation"] = _serialize_run(_run_reconciliation(change_set=change_set))
			frappe.db.commit()
			return result
		except Exception:
			frappe.db.rollback(save_point="portal_voucher_import")
			raise


def _apply_snapshot(state, payloads, company, allowed):
	started = perf_counter()
	metrics = defaultdict(int)
	held_refresh_names = set()
	change_set = {"voucher_names": set(), "references": set(), "order_names": set()}
	mark = perf_counter()
	masters = {}
	for doctype, value_field in (
		("Tally Item", "name"),
		("Tally Godown", "name"),
		("Tally Customer Ledger", "client_code"),
	):
		masters[doctype] = {
			row.tally_guid: row[value_field]
			for row in frappe.get_all(doctype, fields=["tally_guid", value_field])
			if row.tally_guid
		}
	metrics["master_mapping_load_ms"] = _elapsed_ms(mark)
	mark = perf_counter()
	existing = frappe.get_all(
		"Tally Voucher", filters={"source_company": company}, fields=["name", "tally_guid"]
	)
	metrics["voucher_identity_load_ms"] = _elapsed_ms(mark)
	by_guid = {row.tally_guid: row.name for row in existing if row.tally_guid}
	seen = set()
	processed = 0
	for payload in payloads:
		guid = payload["guid"]
		seen.add(guid)
		eligible = payload.get("type_guid") in allowed
		if not eligible and guid not in by_guid:
			continue
		name = by_guid.get(guid)
		voucher = frappe.get_doc("Tally Voucher", name) if name else frappe.new_doc("Tally Voucher")
		if not name:
			voucher.name = "TV-" + hashlib.sha256(f"{company}:{guid}".encode()).hexdigest()[:32]
		old_references = _held_references(voucher) | {voucher.order_number}
		values, lines = _voucher_values(payload, state, eligible, masters)
		if not payload.get("type_guid") or (eligible and values["source_error"]):
			if not name:
				voucher.update(values)
				voucher.raw_source_payload = None
			changed = _hold(
				voucher,
				state,
				payload,
				values["source_error"]
				or "Voucher type is missing from PostgreSQL; previous quantities are preserved",
				refresh_unchanged=False,
			)
			metrics["held_vouchers_changed" if changed else "held_vouchers_refreshed"] += 1
			if not changed:
				held_refresh_names.add(voucher.name)
		else:
			source_changed = (
				voucher.raw_source_payload != values["raw_source_payload"]
				or voucher.source_status != "Active"
				or bool(voucher.fulfillment_eligible) != eligible
				or voucher.source_error != values["source_error"]
				or voucher.party_client_code != values["party_client_code"]
				or voucher.order_number != values["order_number"]
				or _mapped_lines(voucher.lines) != _mapped_lines(lines)
			)
			if not source_changed:
				metrics["active_vouchers_unchanged"] += 1
				processed += 1
				continue
			voucher.update(values)
			voucher.source_observation = values["raw_source_payload"]
			voucher.source_pending_references = json.dumps(
				sorted(r for r in old_references | {voucher.order_number} if r)
			)
			voucher.set("lines", [])
			for line in lines:
				voucher.append("lines", line)
			voucher.save(ignore_permissions=True, ignore_version=not source_changed)
			changed = True
			metrics["active_vouchers_changed"] += 1
		if changed:
			change_set["voucher_names"].add(voucher.name)
			change_set["references"].update(
				reference
				for reference in old_references
				| _held_references(voucher)
				| {voucher.order_number, payload.get("order_number")}
				if reference
			)
			for reference in old_references | {voucher.order_number, payload.get("order_number")}:
				order_name = _mark_order(reference)
				if order_name:
					change_set["order_names"].add(order_name)
		processed += 1

	for row in existing:
		if row.tally_guid not in seen:
			voucher = frappe.get_doc("Tally Voucher", row.name)
			changed = _hold(
				voucher,
				state,
				None,
				"Voucher is missing from PostgreSQL; deletion in Tally is unverified and previous quantities are preserved",
				refresh_unchanged=False,
			)
			metrics["held_vouchers_changed" if changed else "held_vouchers_refreshed"] += 1
			if not changed:
				held_refresh_names.add(voucher.name)
			if changed:
				change_set["voucher_names"].add(voucher.name)
				change_set["references"].update(_held_references(voucher) | {voucher.order_number})
				for reference in _held_references(voucher) | {voucher.order_number}:
					order_name = _mark_order(reference)
					if order_name:
						change_set["order_names"].add(order_name)

	mark = perf_counter()
	_bulk_refresh_held_vouchers(held_refresh_names, state)
	metrics["held_freshness_write_ms"] = _elapsed_ms(mark)
	metrics["held_freshness_batches"] = (
		len(held_refresh_names) + HELD_REFRESH_BATCH_SIZE - 1
	) // HELD_REFRESH_BATCH_SIZE
	metrics["apply_total_ms"] = _elapsed_ms(started)
	metadata = dict(state)
	metadata["apply_metrics"] = dict(metrics)
	run = frappe.get_doc(
		dict(
			doctype="Tally Sync Run",
			sync_type="Vouchers",
			status="Completed",
			started_at=now_datetime(),
			finished_at=now_datetime(),
			source_table="trn_voucher",
			records_seen=len(payloads),
			records_processed=processed,
			errors_count=0,
			source_snapshot_id=state["snapshot_id"],
			source_refreshed_at=state["completed_at"],
			snapshot_complete=0,
			source_metadata=json.dumps(metadata, default=str, sort_keys=True),
		)
	).insert(ignore_permissions=True)
	return {
		"run": run.name,
		"status": run.status,
		"records_processed": processed,
		"source_snapshot_id": state["snapshot_id"],
		"source_period_changed": state.get("period_changed", False),
		"_change_set": change_set,
	}


def _mark_order(reference):
	if reference:
		name = frappe.db.get_value("Order", {"portal_reference_number": reference}, "name")
		if name:
			frappe.db.set_value("Order", name, "tally_reconciliation_managed", 1, update_modified=False)
			return name
	return None


def _mapped_lines(lines):
	return [
		(
			line.get("item"),
			line.get("godown"),
			Decimal(str(line.get("quantity") or 0)),
			line.get("tracking_number") or "",
		)
		for line in lines
	]


def _voucher_values(payload, state, eligible, masters):
	lines = []
	errors = []
	for raw in payload.get("lines", []):
		if raw.get("quantity") is None:
			errors.append("Inventory quantity is missing from PostgreSQL")
			continue
		item = masters["Tally Item"].get(raw.get("item_guid"))
		godown = masters["Tally Godown"].get(raw.get("godown_guid"))
		if not item or not godown:
			errors.append("Inventory item or godown GUID is missing from imported masters")
			continue
		lines.append(
			{
				"item": item,
				"godown": godown,
				"quantity": raw.get("quantity"),
				"tracking_number": raw.get("tracking_number"),
			}
		)
	ledger = masters["Tally Customer Ledger"].get(payload.get("party_guid"))
	if eligible and not lines:
		errors.append("Voucher has no usable inventory lines")
	_, order_error = order_candidates(payload["order_details"], payload["order_number"])
	if eligible and order_error:
		errors.append(order_error)
	return dict(
		tally_guid=payload["guid"],
		source_company=state["source_company"],
		source_alterid=payload["alterid"],
		voucher_number=payload.get("voucher_number"),
		voucher_type="Delivery Challan" if eligible else "Other",
		tally_voucher_type_guid=payload.get("type_guid"),
		tally_party_guid=payload.get("party_guid"),
		order_number=payload.get("order_number"),
		party_client_code=ledger,
		voucher_date=_voucher_date(payload.get("voucher_date")),
		fulfillment_eligible=int(eligible),
		source_status="Active",
		source_error="; ".join(sorted(set(errors))),
		source_snapshot_id=state["snapshot_id"],
		source_refreshed_at=state["completed_at"],
		raw_source_payload=json.dumps(payload, default=str, sort_keys=True),
		reconciliation_state="Pending",
		reconciled=0,
	), lines


def _voucher_date(value):
	value = str(value or "")
	if len(value) == 8 and value.isdigit():
		return f"{value[:4]}-{value[4:6]}-{value[6:]}"
	return get_datetime(value).date() if value else None


def _elapsed_ms(mark):
	return round((perf_counter() - mark) * 1000, 2)


def _held_references(voucher):
	try:
		values = json.loads(voucher.source_pending_references or "[]")
	except (TypeError, ValueError):
		frappe.throw(f"Tally Voucher {voucher.name} has invalid source_pending_references JSON")
	if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
		frappe.throw(f"Tally Voucher {voucher.name} has invalid source_pending_references")
	return {value for value in values if value}


def _hold(voucher, state, payload, reason, refresh_unchanged=True):
	observation = json.dumps(payload, default=str, sort_keys=True) if payload is not None else "null"
	changed = (
		voucher.source_status != "Unverified"
		or voucher.source_observation != observation
		or voucher.source_error != reason
		or voucher.reconciliation_state != "Manual Review"
		or bool(voucher.reconciled)
	)
	references = _held_references(voucher) | {voucher.order_number}
	if payload:
		candidates, _ = order_candidates(payload["order_details"], payload["order_number"])
		references.update(candidates)
	pending_references = json.dumps(sorted(r for r in references if r))
	changed = changed or voucher.source_pending_references != pending_references
	voucher.source_pending_references = pending_references
	voucher.source_observation = observation
	voucher.source_status = "Unverified"
	voucher.source_error = reason
	voucher.source_snapshot_id = state["snapshot_id"]
	voucher.source_refreshed_at = state["completed_at"]
	voucher.reconciliation_state = "Manual Review"
	voucher.reconciled = 0
	if changed or voucher.is_new():
		voucher.save(ignore_permissions=True, ignore_version=not changed)
	elif refresh_unchanged:
		frappe.db.set_value(
			"Tally Voucher",
			voucher.name,
			{
				"source_snapshot_id": state["snapshot_id"],
				"source_refreshed_at": state["completed_at"],
			},
			update_modified=False,
		)
	return changed


def _bulk_refresh_held_vouchers(voucher_names, state):
	for chunk in _chunks(sorted(voucher_names), HELD_REFRESH_BATCH_SIZE):
		frappe.db.set_value(
			"Tally Voucher",
			{"name": ("in", chunk)},
			{
				"source_snapshot_id": state["snapshot_id"],
				"source_refreshed_at": state["completed_at"],
			},
			update_modified=False,
		)


def _chunks(values, size):
	for index in range(0, len(values), size):
		yield values[index : index + size]
