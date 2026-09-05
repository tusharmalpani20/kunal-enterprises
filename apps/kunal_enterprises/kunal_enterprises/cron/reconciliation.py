import json
from collections import defaultdict

import frappe
from frappe.utils import now_datetime

from kunal_enterprises.cron.fulfillment import evaluate_order


def run_reconciliation(commit=True):
	"""Rebuild managed order totals, including previously completed/reviewed orders."""
	with frappe.cache().lock(
		frappe.cache().make_key("kunal:portal-voucher-import"), timeout=1800, blocking_timeout=0
	):
		assert_current_history()
		frappe.db.savepoint("order_reconciliation")
		try:
			run = _run_reconciliation()
			if commit:
				frappe.db.commit()
			return run
		except Exception:
			frappe.db.rollback(save_point="order_reconciliation")
			raise


def assert_current_history():
	"""Reject an old caller snapshot without committing or discarding its pending writes.

	The Redis lock serializes workers, but MariaDB repeatable reads can still retain
	a view created before the lock was acquired. A separate connection sees committed
	history without invalidating the caller snapshot. Call only while holding the lock.
	"""
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
	# A FOR UPDATE read can abort a stale MariaDB snapshot and discard pending work.
	# The existing Redis lock prevents another reconciliation from committing here.
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


def _run_reconciliation():
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
	voucher_refs = frappe.get_all("Tally Voucher", filters={"source_company": company}, pluck="name")
	vouchers = [frappe.get_doc("Tally Voucher", name) for name in voucher_refs]
	by_reference = defaultdict(list)
	for voucher in vouchers:
		if voucher.tally_guid:
			references = {voucher.reference_number}
			references.update(json.loads(voucher.source_pending_references or "[]"))
			for reference in references:
				by_reference[reference].append(voucher)

	order_names = set(frappe.get_all("Order", filters={"tally_reconciliation_managed": 1}, pluck="name"))
	for reference in by_reference:
		if reference:
			name = frappe.db.get_value("Order", {"portal_reference_number": reference}, "name")
			if name:
				order_names.add(name)
	# A reference transfer is indivisible: freeze both ends if either retains uncertain totals.
	legacy_by_reference = defaultdict(list)
	for legacy in frappe.get_all(
		"Tally Voucher", fields=["name", "tally_guid", "reconciled", "reference_number"]
	):
		if not legacy.tally_guid and legacy.reconciled:
			legacy_by_reference[legacy.reference_number].append(legacy)
	blocked = set(legacy_by_reference)
	for reference, linked in by_reference.items():
		if any(v.source_status == "Unverified" for v in linked):
			blocked.add(reference)
	changed = True
	while changed:
		changed = False
		for voucher in vouchers:
			references = {voucher.reference_number} | set(
				json.loads(voucher.source_pending_references or "[]")
			)
			references.discard(None)
			references.discard("")
			if references & blocked and not references <= blocked:
				blocked.update(references)
				changed = True
	processed_vouchers = set()
	errors = 0
	for name in sorted(order_names):
		order = frappe.get_doc("Order", name)
		linked = by_reference.get(order.portal_reference_number, [])
		customer = frappe.get_doc("Customer", order.customer)
		customer_guid = customer.get("tally_guid") or frappe.db.get_value(
			"Tally Customer Ledger", {"client_code": customer.client_code}, "tally_guid"
		)
		payloads = [_evaluation_voucher(v) for v in linked]
		result = evaluate_order(
			dict(
				reference=order.portal_reference_number,
				customer_guid=customer_guid,
				status=order.status,
				items={row.item: row.requested_quantity for row in order.items},
			),
			payloads,
		)

		previous_status = order.status
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
				)
				processed_vouchers.add(voucher.name)
			for voucher in legacy_by_reference.get(order.portal_reference_number, []):
				_log_if_changed(
					order.name,
					voucher.name,
					"Manual Review",
					"LEGACY_IDENTITY_REQUIRED",
					"Legacy fulfilled voucher needs a verified Tally GUID before totals can be rebuilt",
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
				if voucher.reference_number != order.portal_reference_number:
					continue
				reason = result["reasons"].get(voucher.tally_guid)
				state, code, message = _voucher_result(voucher, reason)
				_record_result(voucher, state, code, message, order.name)
				processed_vouchers.add(voucher.name)
				errors += int(bool(reason))
		order.tally_reconciliation_managed = 1
		order.save(ignore_permissions=True)
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

	for voucher in vouchers:
		if voucher.name not in processed_vouchers:
			if voucher.source_status == "Unverified":
				_record_result(voucher, "Manual Review", "SOURCE_UNVERIFIED", voucher.source_error)
				errors += 1
			elif voucher.source_status == "Removed":
				_record_result(
					voucher, "Removed", "SOURCE_REMOVED", "Voucher is removed, cancelled or optional in Tally"
				)
			elif not voucher.fulfillment_eligible:
				_record_result(
					voucher,
					"Ignored",
					"NOT_FULFILLMENT_TYPE",
					"Voucher type is not approved for dispatch fulfillment",
				)
			elif voucher.reference_number and frappe.db.exists(
				"Order", {"portal_reference_number": voucher.reference_number}
			):
				_record_result(
					voucher,
					"Manual Review",
					"LEGACY_IDENTITY_REQUIRED",
					"Resolve legacy source identity before applying fulfillment",
				)
			else:
				_record_result(
					voucher,
					"Unmatched",
					"NO_MATCHING_ORDER",
					"Portal reference is missing or does not identify an order",
				)
	# Release transfer history only after every affected order has been rebuilt atomically.
	for voucher in vouchers:
		references = set(json.loads(voucher.source_pending_references or "[]"))
		if references and not references & blocked:
			frappe.db.set_value(
				"Tally Voucher", voucher.name, "source_pending_references", "[]", update_modified=False
			)
	run.records_seen = len(vouchers)
	run.records_processed = len(vouchers)
	run.errors_count = errors
	run.status = "Completed With Errors" if errors else "Completed"
	run.finished_at = now_datetime()
	run.save(ignore_permissions=True)
	return run


def _evaluation_voucher(voucher):
	return dict(
		guid=voucher.tally_guid,
		reference=voucher.reference_number,
		party_guid=voucher.tally_party_guid,
		eligible=bool(voucher.fulfillment_eligible),
		source_status=voucher.source_status,
		source_error=voucher.source_error,
		lines=[
			dict(item=r.item, quantity=r.quantity, tracking_number=r.tracking_number) for r in voucher.lines
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


def _record_result(voucher, state, code, message, order=None):
	unchanged = voucher.reconciliation_state == state and voucher.reconciliation_reason == code
	voucher.reconciliation_state = state
	voucher.reconciliation_reason = code
	voucher.reconciliation_last_attempt = now_datetime()
	voucher.reconciled = int(state == "Matched")
	if not unchanged:
		voucher.save(ignore_permissions=True)
	_log_if_changed(
		order,
		voucher.name,
		"Manual Review" if state == "Manual Review" else "Matched" if state == "Matched" else "Skipped",
		code,
		message,
	)


def _log_if_changed(order, voucher, status, code, message):
	previous = frappe.db.get_value(
		"Order Reconciliation Log",
		{"order": order, "voucher": voucher},
		["status", "reason_code", "message"],
		order_by="created_at desc, creation desc",
		as_dict=True,
	)
	if previous and (previous.status, previous.reason_code, previous.message) == (status, code, message):
		return
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
