"""Bulk full/incremental Tally voucher reconciliation engine."""

import hashlib
import json
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import timedelta
from time import perf_counter

import frappe
from frappe.utils import get_datetime, now_datetime

from kunal_enterprises.cron.fulfillment import evaluate_order
from kunal_enterprises.integrations.reconciliation_queue import acknowledge_work, claim_work
from kunal_enterprises.integrations.reconciliation_settings import (
	RECONCILIATION_LOCK_SECONDS,
	TALLY_JOB_TIMEOUT_SECONDS,
)


RECONCILIATION_ALGORITHM_VERSION = 1
DEFAULT_INCREMENTAL_SCOPE_RATIO = 0.5
DEFAULT_WORK_MAX_AGE_HOURS = 24
BATCH_SIZE = 500

VOUCHER_HEADER_FIELDS = [
	"name",
	"tally_guid",
	"source_company",
	"order_number",
	"reference_number",
	"source_pending_references",
	"source_status",
	"source_error",
	"fulfillment_eligible",
	"tally_party_guid",
	"reconciliation_state",
	"reconciliation_reason",
	"reconciled",
]


def run_reconciliation(
	commit=True,
	mode="full",
	references=None,
	voucher_names=None,
	order_names=None,
	trigger=None,
):
	"""Rebuild order totals in full mode unless an explicit safe scope is requested."""
	with frappe.cache().lock(
		frappe.cache().make_key("kunal:portal-voucher-import"),
		timeout=RECONCILIATION_LOCK_SECONDS,
		blocking_timeout=0,
	):
		assert_current_history()
		frappe.db.savepoint("order_reconciliation")
		try:
			change_set = {
				"references": set(references or []),
				"voucher_names": set(voucher_names or []),
				"order_names": set(order_names or []),
			}
			run = _run_reconciliation(change_set=change_set, requested_mode=mode, trigger=trigger)
			if commit:
				frappe.db.commit()
			return run
		except Exception:
			frappe.db.rollback(save_point="order_reconciliation")
			raise


def run_reconciliation_for_order(order_name, commit=True):
	order = frappe.get_doc("Order", order_name)
	return run_reconciliation(
		commit=commit,
		mode="incremental",
		references=[order.portal_reference_number],
		order_names=[order.name],
	)


def assert_current_history():
	"""Reject an old caller snapshot without committing or discarding pending writes."""
	filters = {
		"source_table": "trn_voucher",
		"sync_type": ("in", ["Vouchers", "Reconciliation"]),
		"status": ("in", ["Completed", "Completed With Errors"]),
	}
	run = frappe.qb.DocType("Tally Sync Run")
	query = (
		frappe.qb.from_(run)
		.select(run.name)
		.where(
			(run.source_table == "trn_voucher")
			& run.sync_type.isin(["Vouchers", "Reconciliation"])
			& run.status.isin(["Completed", "Completed With Errors"])
		)
		.orderby(run.creation, order=frappe.qb.desc)
		.orderby(run.name, order=frappe.qb.desc)
		.limit(1)
	)
	connection = frappe.db.get_connection()
	try:
		with connection.cursor() as cursor:
			cursor.execute(query.get_sql())
			row = cursor.fetchone()
			current = row[0] if row else None
	finally:
		connection.close()
	visible = frappe.db.get_value("Tally Sync Run", filters, "name", order_by="creation desc, name desc")
	if visible != current:
		frappe.throw("Voucher history changed; retry reconciliation or import in a fresh transaction")


def _run_reconciliation(change_set=None, requested_mode=None, trigger=None):
	started = perf_counter()
	timings = {}
	stats = defaultdict(int)
	stats["change_samples"] = []
	run = frappe.get_doc(
		dict(
			doctype="Tally Sync Run",
			sync_type="Reconciliation",
			status="Running",
			started_at=now_datetime(),
			source_table="trn_voucher",
		)
	).insert(ignore_permissions=True)
	company = frappe.conf.get("tally_source_company")
	if not company:
		frappe.throw("Configure tally_source_company before reconciliation")
	companies = set(
		frappe.get_all("Tally Voucher", filters={"source_company": ("!=", "")}, pluck="source_company")
	)
	if companies and companies != {company}:
		frappe.throw("Configured Tally company differs from existing voucher history")

	mark = perf_counter()
	headers = frappe.get_all(
		"Tally Voucher",
		filters={"source_company": company},
		fields=VOUCHER_HEADER_FIELDS,
		limit_page_length=0,
	)
	by_name = {row.name: row for row in headers}
	refs_for_voucher, by_reference = _reference_graph(headers)
	legacy_by_reference = _load_legacy_vouchers()
	protected_legacy_names = {
		voucher.name for vouchers in legacy_by_reference.values() for voucher in vouchers
	}
	scope_by_reference = _scope_graph_with_legacy(
		by_reference,
		refs_for_voucher,
		legacy_by_reference,
	)
	timings["header_load_ms"] = _elapsed_ms(mark)

	mark = perf_counter()
	claimed_work, queue_problem = claim_work(company)
	mode, fallback_reason, fingerprint = _select_mode(requested_mode, claimed_work, queue_problem)
	seed_references, seed_vouchers, seed_orders = _scope_seeds(change_set, claimed_work)
	seed_order_rows = _orders_by_name(seed_orders)
	seed_references.update(row.portal_reference_number for row in seed_order_rows if row.portal_reference_number)
	if mode == "full":
		selected_names = set(by_name)
		selected_references = {reference for references in refs_for_voucher.values() for reference in references}
	else:
		selected_names, selected_references = _expand_scope(
			seed_vouchers,
			seed_references,
			refs_for_voucher,
			scope_by_reference,
		)
		threshold = max(100, int(len(headers) * _scope_ratio()))
		if len(selected_names) > threshold:
			mode = "full"
			fallback_reason = "incremental_scope_threshold_exceeded"
			selected_names = set(by_name)
			selected_references = {
				reference for references in refs_for_voucher.values() for reference in references
			}
	timings["scope_expansion_ms"] = _elapsed_ms(mark)

	mark = perf_counter()
	if mode == "full":
		order_rows = frappe.get_all(
			"Order",
			filters={"tally_reconciliation_managed": 1},
			fields=["name", "portal_reference_number"],
			limit_page_length=0,
		)
	else:
		order_rows = []
	order_by_reference = {row.portal_reference_number: row.name for row in order_rows}
	for row in _orders_for_references(selected_references):
		order_by_reference[row.portal_reference_number] = row.name
	for row in seed_order_rows:
		order_by_reference[row.portal_reference_number] = row.name
	selected_references.update(reference for reference in order_by_reference if reference)
	order_names = set(order_by_reference.values())
	locked_order_versions = _lock_orders(order_names)
	timings["order_scope_ms"] = _elapsed_ms(mark)

	selected_headers = [by_name[name] for name in sorted(selected_names) if name in by_name]
	blocked = _blocked_references(selected_headers, refs_for_voucher, legacy_by_reference)
	line_parent_names = {
		voucher.name
		for reference, linked in by_reference.items()
		if reference in order_by_reference
		for voucher in linked
		if voucher.name in selected_names
	}
	mark = perf_counter()
	lines_by_parent = _load_voucher_lines(line_parent_names)
	for voucher in selected_headers:
		voucher.lines = lines_by_parent.get(voucher.name, [])
	timings["voucher_line_load_ms"] = _elapsed_ms(mark)

	mark = perf_counter()
	orders = [frappe.get_doc("Order", name) for name in sorted(order_names)]
	for order in orders:
		if get_datetime(order.modified) != get_datetime(locked_order_versions.get(order.name)):
			frappe.throw(f"Order {order.name} changed during reconciliation scope selection; retry")
	customer_guids = _load_customer_guids({order.customer for order in orders})
	timings["order_customer_load_ms"] = _elapsed_ms(mark)
	mark = perf_counter()
	log_cache = _load_latest_logs(selected_names | _legacy_names(legacy_by_reference, selected_references))
	timings["log_load_ms"] = _elapsed_ms(mark)

	processed_vouchers = set()
	errors = 0
	mark = perf_counter()
	with _internal_reconciliation_writes():
		for order in orders:
			linked = [
				voucher
				for voucher in by_reference.get(order.portal_reference_number, [])
				if voucher.name in selected_names
			]
			payloads = [_evaluation_voucher(voucher) for voucher in linked]
			result = evaluate_order(
				dict(
					reference=order.portal_reference_number,
					customer_guid=customer_guids.get(order.customer),
					status=order.status,
					items={row.item: row.requested_quantity for row in order.items},
				),
				payloads,
			)

			previous_status = order.status
			was_managed = bool(order.tally_reconciliation_managed)
			before_items = _order_item_state(order)
			if order.portal_reference_number in blocked:
				if order.status not in {"Cancelled", "Partially Closed"}:
					order.status = "Manual Review"
				for voucher in linked:
					_record_result(
						voucher,
						"Manual Review",
						"SOURCE_UNVERIFIED",
						"Related order quantities preserved until source data and legacy identity are resolved",
						order.name,
						log_cache,
						stats,
					)
					processed_vouchers.add(voucher.name)
				for voucher in legacy_by_reference.get(order.portal_reference_number, []):
					_log_if_changed(
						order.name,
						voucher.name,
						"Manual Review",
						"LEGACY_IDENTITY_REQUIRED",
						"Legacy fulfilled voucher needs a verified Tally GUID before totals can be rebuilt",
						log_cache,
						stats,
					)
				errors += 1
			else:
				order.status = result["status"]
				for row in order.items:
					row.fulfilled_quantity = result["fulfilled"][row.item]
					row.pending_quantity = max(float(row.requested_quantity) - row.fulfilled_quantity, 0)
					row.status = (
						"Completed"
						if row.pending_quantity == 0
						else "Partially Processed"
						if row.fulfilled_quantity
						else "Placed"
					)
				for voucher in linked:
					if voucher.order_number != order.portal_reference_number:
						continue
					reason = result["reasons"].get(voucher.tally_guid)
					state, code, message = _voucher_result(voucher, reason)
					_record_result(voucher, state, code, message, order.name, log_cache, stats)
					processed_vouchers.add(voucher.name)
					errors += int(bool(reason))

			order.tally_reconciliation_managed = 1
			after_items = _order_item_state(order)
			if previous_status != order.status or before_items != after_items or not was_managed:
				_append_change_sample(
					stats,
					{
						"doctype": "Order",
						"name": order.name,
						"from_status": previous_status,
						"to_status": order.status,
						"items_changed": before_items != after_items,
					},
				)
				order.save(ignore_permissions=True)
				stats["orders_written"] += 1
			if previous_status != order.status:
				frappe.get_doc(
					dict(
						doctype="Order Status Log",
						order=order.name,
						from_status=previous_status,
						to_status=order.status,
						role="Tally Sync",
						note="Recalculated from the accepted PostgreSQL voucher data",
						created_at=now_datetime(),
					)
				).insert(ignore_permissions=True)

		# These rows represent accepted historical fulfillment without a verified
		# source identity. Never rewrite their reconciled flag while they are acting
		# as the hold that prevents destructive recalculation.
		processed_vouchers.update(protected_legacy_names & selected_names)
		stats["legacy_vouchers_protected"] = len(protected_legacy_names & selected_names)

		for voucher in selected_headers:
			if voucher.name in processed_vouchers:
				continue
			if voucher.source_status == "Unverified":
				_record_result(
					voucher, "Manual Review", "SOURCE_UNVERIFIED", voucher.source_error, None, log_cache, stats
				)
				errors += 1
			elif voucher.source_status == "Removed":
				_record_result(
					voucher,
					"Removed",
					"SOURCE_REMOVED",
					"Voucher is removed, cancelled or optional in Tally",
					None,
					log_cache,
					stats,
				)
			elif not voucher.fulfillment_eligible:
				_record_result(
					voucher,
					"Ignored",
					"NOT_FULFILLMENT_TYPE",
					"Voucher type is not approved for dispatch fulfillment",
					None,
					log_cache,
					stats,
				)
			elif voucher.order_number and voucher.order_number in order_by_reference:
				_record_result(
					voucher,
					"Manual Review",
					"LEGACY_IDENTITY_REQUIRED",
					"Resolve legacy source identity before applying fulfillment",
					None,
					log_cache,
					stats,
				)
			else:
				_record_result(
					voucher,
					"Unmatched",
					"NO_MATCHING_ORDER",
					"Tally Order Number is missing or does not identify a portal order",
					None,
					log_cache,
					stats,
				)

		for voucher in selected_headers:
			references = _parse_pending(voucher)
			if references and not references & blocked:
				_append_change_sample(
					stats,
					{
						"doctype": "Tally Voucher",
						"name": voucher.name,
						"field": "source_pending_references",
						"from": sorted(references),
						"to": [],
					},
				)
				frappe.db.set_value(
					"Tally Voucher", voucher.name, "source_pending_references", "[]", update_modified=False
				)
				stats["pending_references_released"] += 1

		acknowledge_work(claimed_work)
	timings["evaluation_and_write_ms"] = _elapsed_ms(mark)

	run.records_seen = len(headers)
	run.records_processed = len(selected_headers)
	run.errors_count = errors
	run.status = "Completed With Errors" if errors else "Completed"
	run.finished_at = now_datetime()
	metadata = {
		"algorithm_version": RECONCILIATION_ALGORITHM_VERSION,
		"configuration_fingerprint": fingerprint,
		"mode": mode,
		"fallback_reason": fallback_reason,
		"trigger": trigger,
		"total_vouchers": len(headers),
		"scoped_vouchers": len(selected_headers),
		"scoped_references": len(selected_references),
		"scoped_orders": len(orders),
		"claimed_work_items": len(claimed_work),
		"oldest_work_age_seconds": _oldest_work_age_seconds(claimed_work),
		"worker_timeout_seconds": TALLY_JOB_TIMEOUT_SECONDS,
		"lock_lease_seconds": RECONCILIATION_LOCK_SECONDS,
		"errors_count": errors,
		"full_safety_changes_detected": (
			stats["orders_written"]
			+ stats["vouchers_written"]
			+ stats["pending_references_released"]
			+ stats["logs_inserted"]
			if requested_mode == "full"
			else 0
		),
		"stats": dict(stats),
		"timings_ms": timings,
		"total_ms": _elapsed_ms(started),
	}
	run.source_metadata = json.dumps(metadata, sort_keys=True)
	run.save(ignore_permissions=True)
	return run


def _select_mode(requested_mode, claimed_work, queue_problem):
	if requested_mode not in {None, "full", "incremental"}:
		frappe.throw(f"Unsupported reconciliation mode: {requested_mode}")
	fingerprint = _configuration_fingerprint()
	if requested_mode == "full":
		return "full", "explicit_full", fingerprint
	if not _incremental_enabled():
		return "full", "incremental_disabled", fingerprint
	if queue_problem:
		return "full", queue_problem, fingerprint
	if any(_truthy(row.full_reconciliation) for row in claimed_work):
		return "full", "full_work_item", fingerprint
	latest = frappe.db.get_value(
		"Tally Sync Run",
		{"sync_type": "Reconciliation", "status": ("in", ["Completed", "Completed With Errors"])},
		"source_metadata",
		order_by="creation desc, name desc",
	)
	try:
		latest = json.loads(latest or "{}")
	except (TypeError, ValueError):
		latest = {}
	if latest.get("algorithm_version") != RECONCILIATION_ALGORITHM_VERSION:
		return "full", "algorithm_version_changed", fingerprint
	if latest.get("configuration_fingerprint") != fingerprint:
		return "full", "configuration_changed", fingerprint
	cutoff = now_datetime() - timedelta(hours=_work_max_age_hours())
	if any(row.first_seen_at and get_datetime(row.first_seen_at) < cutoff for row in claimed_work):
		return "full", "stale_work_item", fingerprint
	return "incremental", None, fingerprint


def _scope_seeds(change_set, claimed_work):
	change_set = change_set or {}
	references = {reference for reference in change_set.get("references", set()) if reference}
	vouchers = {name for name in change_set.get("voucher_names", set()) if name}
	orders = {name for name in change_set.get("order_names", set()) if name}
	for row in claimed_work:
		if row.reference_number:
			references.add(row.reference_number)
		if row.voucher:
			vouchers.add(row.voucher)
	return references, vouchers, orders


def _reference_graph(headers):
	refs_for_voucher = {}
	by_reference = defaultdict(list)
	for voucher in headers:
		references = _voucher_references(voucher)
		refs_for_voucher[voucher.name] = references
		if voucher.tally_guid:
			for reference in references:
				by_reference[reference].append(voucher)
	return refs_for_voucher, by_reference


def _scope_graph_with_legacy(by_reference, refs_for_voucher, legacy_by_reference):
	scope_by_reference = defaultdict(list)
	names_by_reference = defaultdict(set)
	for reference, vouchers in by_reference.items():
		scope_by_reference[reference].extend(vouchers)
		names_by_reference[reference].update(voucher.name for voucher in vouchers)
	for reference, vouchers in legacy_by_reference.items():
		for voucher in vouchers:
			refs_for_voucher.setdefault(voucher.name, set()).add(reference)
			if voucher.name not in names_by_reference[reference]:
				scope_by_reference[reference].append(voucher)
				names_by_reference[reference].add(voucher.name)
	return scope_by_reference


def _expand_scope(seed_vouchers, seed_references, refs_for_voucher, by_reference):
	selected_vouchers = set(seed_vouchers)
	selected_references = set(seed_references)
	queue = deque(selected_references)
	for name in list(selected_vouchers):
		for reference in refs_for_voucher.get(name, set()):
			if reference not in selected_references:
				selected_references.add(reference)
				queue.append(reference)
	while queue:
		reference = queue.popleft()
		for voucher in by_reference.get(reference, []):
			if voucher.name not in selected_vouchers:
				selected_vouchers.add(voucher.name)
			for linked_reference in refs_for_voucher.get(voucher.name, set()):
				if linked_reference not in selected_references:
					selected_references.add(linked_reference)
					queue.append(linked_reference)
	return selected_vouchers, selected_references


def _blocked_references(vouchers, refs_for_voucher, legacy_by_reference):
	blocked = set()
	for reference, legacy_vouchers in legacy_by_reference.items():
		if reference:
			blocked.add(reference)
		for voucher in legacy_vouchers:
			blocked.update(_parse_pending(voucher))
	for voucher in vouchers:
		if voucher.source_status == "Unverified":
			blocked.update(refs_for_voucher.get(voucher.name, set()))
	changed = True
	while changed:
		changed = False
		for voucher in vouchers:
			references = refs_for_voucher.get(voucher.name, set())
			if references & blocked and not references <= blocked:
				blocked.update(references)
				changed = True
	return blocked


def _load_legacy_vouchers():
	legacy_by_reference = defaultdict(list)
	for legacy in frappe.get_all(
		"Tally Voucher",
		fields=[
			"name",
			"tally_guid",
			"reconciled",
			"reference_number",
			"order_number",
			"source_pending_references",
		],
		limit_page_length=0,
	):
		if not legacy.tally_guid and legacy.reconciled:
			for reference in {
				legacy.reference_number,
				legacy.order_number,
				*_parse_pending(legacy),
			}:
				if reference:
					legacy_by_reference[reference].append(legacy)
	return legacy_by_reference


def _legacy_names(legacy_by_reference, references):
	return {
		voucher.name for reference in references for voucher in legacy_by_reference.get(reference, [])
	}


def _orders_for_references(references):
	rows = []
	for chunk in _chunks(sorted(reference for reference in references if reference)):
		rows.extend(
			frappe.get_all(
				"Order",
				filters={"portal_reference_number": ("in", chunk)},
				fields=["name", "portal_reference_number"],
				limit_page_length=0,
			)
		)
	return rows


def _orders_by_name(names):
	rows = []
	for chunk in _chunks(sorted(names)):
		rows.extend(
			frappe.get_all(
				"Order",
				filters={"name": ("in", chunk)},
				fields=["name", "portal_reference_number"],
				limit_page_length=0,
			)
		)
	return rows


def _lock_orders(order_names):
	order_table = frappe.qb.DocType("Order")
	versions = {}
	for chunk in _chunks(sorted(order_names)):
		rows = (
			frappe.qb.from_(order_table)
			.select(order_table.name, order_table.modified)
			.where(order_table.name.isin(chunk))
			.orderby(order_table.name)
			.for_update()
		).run(as_dict=True)
		versions.update({row.name: row.modified for row in rows})
	return versions


def _load_voucher_lines(parent_names):
	lines = defaultdict(list)
	for chunk in _chunks(sorted(parent_names)):
		for row in frappe.get_all(
			"Tally Voucher Line",
			filters={"parent": ("in", chunk), "parenttype": "Tally Voucher", "parentfield": "lines"},
			fields=["parent", "item", "quantity", "tracking_number", "idx"],
			order_by="parent asc, idx asc",
			limit_page_length=0,
		):
			lines[row.parent].append(row)
	return lines


def _load_customer_guids(customer_names):
	customers = []
	for chunk in _chunks(sorted(customer_names)):
		customers.extend(
			frappe.get_all(
				"Customer",
				filters={"name": ("in", chunk)},
				fields=["name", "tally_guid", "client_code"],
				limit_page_length=0,
			)
		)
	codes = {row.client_code for row in customers if not row.tally_guid and row.client_code}
	ledger_guids = {}
	for chunk in _chunks(sorted(codes)):
		ledger_guids.update(
			{
				row.client_code: row.tally_guid
				for row in frappe.get_all(
					"Tally Customer Ledger",
					filters={"client_code": ("in", chunk)},
					fields=["client_code", "tally_guid"],
					limit_page_length=0,
				)
			}
		)
	return {row.name: row.tally_guid or ledger_guids.get(row.client_code) for row in customers}


def _load_latest_logs(voucher_names):
	latest = {}
	for chunk in _chunks(sorted(voucher_names)):
		placeholders = ", ".join(["%s"] * len(chunk))
		rows = frappe.db.multisql(
			{
			"mariadb": f"""
					SELECT order_name, voucher, status, reason_code, message
					FROM (
						SELECT COALESCE(`order`, '') AS order_name,
							voucher, status, reason_code, message,
							ROW_NUMBER() OVER (
								PARTITION BY voucher, COALESCE(`order`, '')
								ORDER BY created_at DESC, creation DESC, name DESC
							) AS row_number
						FROM `tabOrder Reconciliation Log`
						WHERE voucher IN ({placeholders})
					) ranked
					WHERE row_number = 1
				""",
			"postgres": f"""
					SELECT order_name, voucher, status, reason_code, message
					FROM (
						SELECT COALESCE("order", '') AS order_name,
							voucher, status, reason_code, message,
							ROW_NUMBER() OVER (
								PARTITION BY voucher, COALESCE("order", '')
								ORDER BY created_at DESC, creation DESC, name DESC
							) AS row_number
						FROM "tabOrder Reconciliation Log"
						WHERE voucher IN ({placeholders})
					) ranked
					WHERE row_number = 1
				""",
			},
			tuple(chunk),
			as_dict=True,
		)
		for row in rows:
			latest[(row.order_name or "", row.voucher)] = (row.status, row.reason_code, row.message)
	return latest


def _evaluation_voucher(voucher):
	return dict(
		guid=voucher.tally_guid,
		reference=voucher.order_number,
		party_guid=voucher.tally_party_guid,
		eligible=bool(voucher.fulfillment_eligible),
		source_status=voucher.source_status,
		source_error=voucher.source_error,
		lines=[
			dict(item=row.item, quantity=row.quantity, tracking_number=row.tracking_number)
			for row in voucher.lines
		],
	)


def _voucher_result(voucher, reason):
	if voucher.source_status == "Removed":
		return "Removed", "SOURCE_REMOVED", "Voucher is removed, cancelled or optional in Tally"
	if not voucher.fulfillment_eligible:
		return "Ignored", "NOT_FULFILLMENT_TYPE", "Voucher type is not approved for dispatch fulfillment"
	if reason:
		return "Manual Review", "FULFILLMENT_VALIDATION", reason
	return "Matched", "CURRENT_QUANTITIES_APPLIED", "Current dispatch quantities included in order totals"


def _record_result(voucher, state, code, message, order, log_cache, stats):
	reconciled = int(state == "Matched")
	unchanged = (
		voucher.reconciliation_state == state
		and voucher.reconciliation_reason == code
		and int(voucher.reconciled or 0) == reconciled
	)
	if not unchanged:
		_append_change_sample(
			stats,
			{
				"doctype": "Tally Voucher",
				"name": voucher.name,
				"from_state": voucher.reconciliation_state,
				"to_state": state,
				"from_reason": voucher.reconciliation_reason,
				"to_reason": code,
			},
		)
		doc = frappe.get_doc("Tally Voucher", voucher.name)
		doc.reconciliation_state = state
		doc.reconciliation_reason = code
		doc.reconciliation_last_attempt = now_datetime()
		doc.reconciled = reconciled
		doc.save(ignore_permissions=True)
		voucher.reconciliation_state = state
		voucher.reconciliation_reason = code
		voucher.reconciled = reconciled
		stats["vouchers_written"] += 1
	_log_if_changed(
		order,
		voucher.name,
		"Manual Review" if state == "Manual Review" else "Matched" if state == "Matched" else "Skipped",
		code,
		message,
		log_cache,
		stats,
	)


def _log_if_changed(order, voucher, status, code, message, log_cache, stats):
	key = (order or "", voucher)
	value = (status, code, message)
	previous = log_cache.get(key)
	if previous == value:
		return
	_append_change_sample(
		stats,
		{
			"doctype": "Order Reconciliation Log",
			"order": order,
			"voucher": voucher,
			"from": list(previous) if previous else None,
			"to": list(value),
		},
	)
	frappe.get_doc(
		dict(
			doctype="Order Reconciliation Log",
			order=order,
			voucher=voucher,
			status=status,
			reason_code=code,
			message=message,
			created_at=now_datetime(),
		)
	).insert(ignore_permissions=True)
	log_cache[key] = value
	stats["logs_inserted"] += 1


def _configuration_fingerprint():
	allowed = frappe.conf.get("tally_fulfillment_voucher_type_guids") or []
	if isinstance(allowed, str):
		allowed = json.loads(allowed)
	if not isinstance(allowed, list):
		frappe.throw("tally_fulfillment_voucher_type_guids must be a JSON list")
	payload = {
		"algorithm_version": RECONCILIATION_ALGORITHM_VERSION,
		"source_company": frappe.conf.get("tally_source_company"),
		"fulfillment_type_guids": sorted(str(value) for value in allowed),
	}
	return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _incremental_enabled():
	return _truthy(frappe.conf.get("tally_incremental_reconciliation_enabled"))


def _scope_ratio():
	try:
		value = float(frappe.conf.get("tally_incremental_full_threshold") or DEFAULT_INCREMENTAL_SCOPE_RATIO)
	except (TypeError, ValueError):
		return DEFAULT_INCREMENTAL_SCOPE_RATIO
	return min(max(value, 0.05), 1.0)


def _work_max_age_hours():
	try:
		return max(int(frappe.conf.get("tally_reconciliation_work_max_age_hours") or DEFAULT_WORK_MAX_AGE_HOURS), 1)
	except (TypeError, ValueError):
		return DEFAULT_WORK_MAX_AGE_HOURS


def _oldest_work_age_seconds(rows):
	first_seen = [get_datetime(row.first_seen_at) for row in rows if row.first_seen_at]
	if not first_seen:
		return 0
	return max(int((now_datetime() - min(first_seen)).total_seconds()), 0)


def _append_change_sample(stats, value, limit=50):
	if len(stats["change_samples"]) < limit:
		stats["change_samples"].append(value)


def _truthy(value):
	return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _voucher_references(voucher):
	order_number = getattr(voucher, "order_number", None)
	reference_number = getattr(voucher, "reference_number", None)
	references = {order_number} if order_number else set()
	if not voucher.tally_guid and reference_number:
		references.add(reference_number)
	return references | _parse_pending(voucher)


def _parse_pending(voucher):
	try:
		values = json.loads(getattr(voucher, "source_pending_references", None) or "[]")
	except (TypeError, ValueError):
		frappe.throw(
			f"Tally Voucher {getattr(voucher, 'name', '<unknown>')} has invalid source_pending_references JSON"
		)
	if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
		frappe.throw(
			f"Tally Voucher {getattr(voucher, 'name', '<unknown>')} has invalid source_pending_references"
		)
	return {value for value in values if value}


def _order_item_state(order):
	return [
		(row.name, float(row.fulfilled_quantity or 0), float(row.pending_quantity or 0), row.status)
		for row in order.items
	]


def _chunks(values, size=BATCH_SIZE):
	values = list(values)
	for index in range(0, len(values), size):
		yield values[index : index + size]


def _elapsed_ms(mark):
	return round((perf_counter() - mark) * 1000, 2)


@contextmanager
def _internal_reconciliation_writes():
	previous = getattr(frappe.flags, "in_tally_reconciliation", False)
	frappe.flags.in_tally_reconciliation = True
	try:
		yield
	finally:
		frappe.flags.in_tally_reconciliation = previous
