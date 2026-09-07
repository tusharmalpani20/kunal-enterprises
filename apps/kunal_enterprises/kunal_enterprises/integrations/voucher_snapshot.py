"""Apply mirror observations while retaining accepted data when the source is uncertain."""

import hashlib
import json
from decimal import Decimal

import frappe
from frappe.utils import get_datetime, now_datetime

from kunal_enterprises.integrations.voucher_contract import validate_snapshot
from kunal_enterprises.integrations.order_details import order_candidates


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
		frappe.cache().make_key("kunal:portal-voucher-import"), timeout=1800, blocking_timeout=0
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
			result = _apply_snapshot(state, payloads, company, allowed)
			# Publish changes and recalculated orders together while still holding the import lock.
			from kunal_enterprises.cron.reconciliation import _run_reconciliation
			from kunal_enterprises.integrations.tally_postgres import _serialize_run

			result["reconciliation"] = _serialize_run(_run_reconciliation())
			frappe.db.commit()
			return result
		except Exception:
			frappe.db.rollback(save_point="portal_voucher_import")
			raise


def _apply_snapshot(state, payloads, company, allowed):
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
	existing = frappe.get_all(
		"Tally Voucher", filters={"source_company": company}, fields=["name", "tally_guid"]
	)
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
			_hold(
				voucher,
				state,
				payload,
				values["source_error"]
				or "Voucher type is missing from PostgreSQL; previous quantities are preserved",
			)
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
		for reference in old_references | {voucher.order_number, payload.get("order_number")}:
			_mark_order(reference)
		processed += 1

	for row in existing:
		if row.tally_guid not in seen:
			voucher = frappe.get_doc("Tally Voucher", row.name)
			_hold(
				voucher,
				state,
				None,
				"Voucher is missing from PostgreSQL; deletion in Tally is unverified and previous quantities are preserved",
			)
			_mark_order(voucher.order_number)

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
			source_metadata=json.dumps(state, default=str, sort_keys=True),
		)
	).insert(ignore_permissions=True)
	return {
		"run": run.name,
		"status": run.status,
		"records_processed": processed,
		"source_snapshot_id": state["snapshot_id"],
		"source_period_changed": state.get("period_changed", False),
	}


def _mark_order(reference):
	if reference:
		name = frappe.db.get_value("Order", {"portal_reference_number": reference}, "name")
		if name:
			frappe.db.set_value("Order", name, "tally_reconciliation_managed", 1, update_modified=False)


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


def _held_references(voucher):
	return set(json.loads(voucher.source_pending_references or "[]"))


def _hold(voucher, state, payload, reason):
	observation = json.dumps(payload, default=str, sort_keys=True) if payload is not None else "null"
	changed = (
		voucher.source_status != "Unverified"
		or voucher.source_observation != observation
		or voucher.source_error != reason
	)
	references = _held_references(voucher) | {voucher.order_number}
	if payload:
		candidates, _ = order_candidates(payload["order_details"], payload["order_number"])
		references.update(candidates)
	voucher.source_pending_references = json.dumps(sorted(r for r in references if r))
	voucher.source_observation = observation
	voucher.source_status = "Unverified"
	voucher.source_error = reason
	voucher.source_snapshot_id = state["snapshot_id"]
	voucher.source_refreshed_at = state["completed_at"]
	voucher.reconciliation_state = "Manual Review"
	voucher.reconciled = 0
	voucher.save(ignore_permissions=True, ignore_version=not changed)
	for reference in references:
		_mark_order(reference)
