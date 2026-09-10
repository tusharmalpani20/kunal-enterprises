"""Durable invalidation for changes that happen outside a voucher snapshot."""

import hashlib

import frappe
from frappe.utils import now_datetime


WORK_DOCTYPE = "Tally Reconciliation Work Item"
MAX_INCREMENTAL_WORK_ITEMS = 1000


def queue_available():
	return frappe.db.table_exists(WORK_DOCTYPE)


def enqueue_reference(reference, reason, voucher=None, source_company=None, full_reconciliation=False):
	"""Atomically coalesce a reconciliation invalidation and increment its generation."""
	if not _incremental_enabled():
		return None
	if getattr(frappe.flags, "in_tally_reconciliation", False):
		return None
	if getattr(frappe.flags, "in_tally_voucher_import", False):
		return None
	if not queue_available():
		return None

	source_company = (source_company or frappe.conf.get("tally_source_company") or "").strip()
	reference = (reference or "").strip()
	voucher = (voucher or "").strip()
	if not source_company or (not reference and not voucher and not full_reconciliation):
		return None

	kind = "full" if full_reconciliation else "scope"
	work_key = hashlib.sha256(f"{source_company}\0{kind}\0{reference}\0{voucher}".encode()).hexdigest()
	now = now_datetime()
	values = {
		"name": work_key,
		"owner": frappe.session.user or "Administrator",
		"modified_by": frappe.session.user or "Administrator",
		"now": now,
		"source_company": source_company,
		"reference_number": reference or None,
		"voucher": voucher or None,
		"reason": str(reason or "Reconciliation input changed")[:1000],
		"full_reconciliation": int(bool(full_reconciliation)),
	}
	frappe.db.multisql(
		{
			"mariadb": """
				INSERT INTO `tabTally Reconciliation Work Item`
					(name, owner, creation, modified, modified_by, docstatus, idx,
					 work_key, source_company, reference_number, voucher, reason,
					 generation, first_seen_at, last_seen_at, full_reconciliation)
				VALUES
					(%(name)s, %(owner)s, %(now)s, %(now)s, %(modified_by)s, 0, 0,
					 %(name)s, %(source_company)s, %(reference_number)s, %(voucher)s,
					 %(reason)s, 1, %(now)s, %(now)s, %(full_reconciliation)s)
				ON DUPLICATE KEY UPDATE
					modified = VALUES(modified), modified_by = VALUES(modified_by),
					reason = VALUES(reason), last_seen_at = VALUES(last_seen_at),
					generation = generation + 1
			""",
			"postgres": """
				INSERT INTO "tabTally Reconciliation Work Item"
					(name, owner, creation, modified, modified_by, docstatus, idx,
					 work_key, source_company, reference_number, voucher, reason,
					 generation, first_seen_at, last_seen_at, full_reconciliation)
				VALUES
					(%(name)s, %(owner)s, %(now)s, %(now)s, %(modified_by)s, 0, 0,
					 %(name)s, %(source_company)s, %(reference_number)s, %(voucher)s,
					 %(reason)s, 1, %(now)s, %(now)s, %(full_reconciliation)s)
				ON CONFLICT (name) DO UPDATE SET
					modified = EXCLUDED.modified, modified_by = EXCLUDED.modified_by,
					reason = EXCLUDED.reason, last_seen_at = EXCLUDED.last_seen_at,
					generation = "tabTally Reconciliation Work Item".generation + 1
			""",
		},
		values,
	)
	return work_key


def enqueue_full_reconciliation(reason, source_company=None):
	return enqueue_reference(
		None,
		reason,
		source_company=source_company,
		full_reconciliation=True,
	)


def claim_work(source_company, limit=MAX_INCREMENTAL_WORK_ITEMS):
	"""Read a generation-stamped work set; acknowledgement happens after success."""
	if not queue_available():
		return [], "work_queue_unavailable"
	count = frappe.db.count(WORK_DOCTYPE, {"source_company": source_company})
	rows = frappe.get_all(
		WORK_DOCTYPE,
		filters={"source_company": source_company},
		fields=[
			"name",
			"generation",
			"reference_number",
			"voucher",
			"reason",
			"full_reconciliation",
			"first_seen_at",
		],
		order_by="first_seen_at asc, name asc",
		limit_page_length=limit,
	)
	return rows, _work_problem(rows, count, limit)


def acknowledge_work(rows):
	"""Delete only the exact generation observed by this successful transaction."""
	for row in rows:
		frappe.db.delete(WORK_DOCTYPE, {"name": row.name, "generation": row.generation})


def invalidate_order(doc, method=None):
	if _internal_write():
		return
	previous = doc.get_doc_before_save()
	current_inputs = _order_inputs(doc)
	previous_inputs = _order_inputs(previous) if previous else None
	if method != "on_trash" and previous_inputs == current_inputs:
		return
	for reference in {doc.portal_reference_number, getattr(previous, "portal_reference_number", None)}:
		if reference:
			enqueue_reference(reference, f"Order inputs changed ({method or 'save'})")


def invalidate_customer(doc, method=None):
	if _internal_write():
		return
	previous = doc.get_doc_before_save()
	before = (getattr(previous, "tally_guid", None), getattr(previous, "client_code", None)) if previous else None
	after = (doc.get("tally_guid"), doc.get("client_code"))
	if method != "on_trash" and before == after:
		return
	for reference in frappe.get_all(
		"Order",
		filters={"customer": doc.name, "tally_reconciliation_managed": 1},
		pluck="portal_reference_number",
	):
		enqueue_reference(reference, f"Customer Tally identity changed ({method or 'save'})")


def invalidate_voucher(doc, method=None):
	if _internal_write() or getattr(frappe.flags, "in_tally_voucher_import", False):
		return
	previous = doc.get_doc_before_save()
	references = {
		doc.get("order_number"),
		doc.get("reference_number"),
		getattr(previous, "order_number", None),
		getattr(previous, "reference_number", None),
	} | _pending_references(doc) | _pending_references(previous)
	for reference in references:
		enqueue_reference(
			reference,
			f"Tally Voucher changed outside source import ({method or 'save'})",
			voucher=doc.name,
			source_company=doc.get("source_company"),
		)
	if not doc.get("order_number") and not getattr(previous, "order_number", None):
		enqueue_reference(
			None,
			f"Unmatched Tally Voucher changed outside source import ({method or 'save'})",
			voucher=doc.name,
			source_company=doc.get("source_company"),
		)


def invalidate_voucher_delete(doc, method=None):
	if _internal_write() or getattr(frappe.flags, "in_tally_voucher_import", False):
		return
	for reference in {
		doc.get("order_number"),
		doc.get("reference_number"),
		*list(_pending_references(doc)),
	}:
		enqueue_reference(
			reference,
			f"Tally Voucher was deleted outside source import ({method or 'delete'})",
			source_company=doc.get("source_company"),
		)


def invalidate_voucher_line(doc, method=None):
	"""Cover exceptional direct child-row writes outside the source-managed parent save."""
	if _internal_write() or getattr(frappe.flags, "in_tally_voucher_import", False) or not doc.parent:
		return
	if not frappe.db.exists("Tally Voucher", doc.parent):
		return
	invalidate_voucher(frappe.get_doc("Tally Voucher", doc.parent), method=method or "line change")


def invalidate_master(doc, method=None):
	if _internal_write() or getattr(frappe.flags, "in_tally_master_import", False):
		return
	enqueue_full_reconciliation(f"{doc.doctype} changed outside Tally master import ({method or 'save'})")


def invalidate_master_rename(doc, method=None, *args, **kwargs):
	invalidate_master(doc, method="rename")


def _internal_write():
	return bool(getattr(frappe.flags, "in_tally_reconciliation", False))


def _incremental_enabled():
	value = frappe.conf.get("tally_incremental_reconciliation_enabled")
	return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _work_problem(rows, count, limit):
	if count > limit:
		return "work_queue_limit_exceeded"
	for row in rows:
		try:
			generation = int(row.generation)
		except (TypeError, ValueError):
			return "malformed_work_item"
		is_full = str(row.full_reconciliation or "").strip().lower() in {"1", "true", "yes", "on"}
		has_scope = bool(str(row.reference_number or "").strip() or str(row.voucher or "").strip())
		if generation < 1 or (not is_full and not has_scope):
			return "malformed_work_item"
	return None


def _order_inputs(doc):
	if not doc:
		return None
	return (
		doc.get("portal_reference_number"),
		doc.get("customer"),
		doc.get("status"),
		tuple((row.item, str(row.requested_quantity)) for row in doc.get("items", [])),
	)


def _pending_references(doc):
	if not doc:
		return set()
	try:
		values = frappe.parse_json(doc.get("source_pending_references") or "[]")
	except (TypeError, ValueError):
		frappe.throw(f"Tally Voucher {doc.name} has invalid source_pending_references JSON")
	if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
		frappe.throw(f"Tally Voucher {doc.name} has invalid source_pending_references")
	return {value for value in values if value}
