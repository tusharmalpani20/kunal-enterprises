"""Hold historical contributions until authoritative order details are imported.

Never populate the new matching field from the old Reference Number.
"""

import json

import frappe

from kunal_enterprises.integrations.order_details import order_candidates


def _already_observed_orders(raw_payload):
	try:
		payload = json.loads(raw_payload or "null")
		if not isinstance(payload, dict) or payload.get("order_details") is None or "order_number" not in payload:
			return False
		order_candidates(payload["order_details"], payload["order_number"])
		return True
	except (TypeError, ValueError):
		return False


def execute():
	for row in frappe.get_all(
		"Tally Voucher",
		fields=["name", "reference_number", "order_number", "source_pending_references", "source_status", "raw_source_payload"],
	):
		# An authoritative empty list legitimately has no scalar order number. Do not
		# resurrect historical reference holds when the patch is replayed after import.
		if row.order_number or _already_observed_orders(row.raw_source_payload):
			continue
		pending = set(json.loads(row.source_pending_references or "[]"))
		if row.reference_number:
			pending.add(row.reference_number)
		frappe.db.set_value("Tally Voucher", row.name, {
			"source_pending_references": json.dumps(sorted(pending)),
			"source_status": "Unverified",
			"source_error": "Order-number cutover requires an authoritative PostgreSQL order-details import",
			"reconciliation_state": "Manual Review",
		}, update_modified=False)
