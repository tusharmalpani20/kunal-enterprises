import frappe
from frappe.utils import now_datetime


def run_reconciliation():
	run = frappe.get_doc(
		{
			"doctype": "Tally Sync Run",
			"sync_type": "Reconciliation",
			"status": "Running",
			"started_at": now_datetime(),
			"source_table": "trn_voucher",
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()

	vouchers = frappe.get_all(
		"Tally Voucher",
		filters={"reconciliation_state": "Pending"},
		fields=["name"],
		order_by="voucher_date asc, creation asc",
	)
	processed = 0
	errors = 0

	for voucher_ref in vouchers:
		try:
			voucher = frappe.get_doc("Tally Voucher", voucher_ref.name)
			state, reason = _reconcile_voucher(voucher)
			voucher.reconciliation_state = state
			voucher.reconciliation_reason = reason
			voucher.reconciliation_last_attempt = now_datetime()
			voucher.reconciled = int(state in {"Matched", "Manual Review"})
			voucher.save(ignore_permissions=True)
			processed += 1
		except Exception as error:
			errors += 1
			frappe.get_doc(
				{
					"doctype": "Tally Sync Error",
					"sync_run": run.name,
					"source_table": "trn_voucher",
					"source_key": voucher_ref.name,
					"error_message": str(error),
					"detected_at": now_datetime(),
				}
			).insert(ignore_permissions=True)

	run.records_seen = len(vouchers)
	run.records_processed = processed
	run.errors_count = errors
	run.status = "Completed" if errors == 0 else "Completed With Errors"
	run.finished_at = now_datetime()
	run.save(ignore_permissions=True)
	return run


def _reconcile_voucher(voucher):
	if not voucher.reference_number:
		_log_reconciliation(None, voucher.name, "Skipped", "MISSING_REFERENCE_NUMBER", "Voucher has no portal reference")
		return "Unmatched", "MISSING_REFERENCE_NUMBER"

	order_name = frappe.db.exists("Order", {"portal_reference_number": voucher.reference_number})
	if not order_name:
		_log_reconciliation(None, voucher.name, "Skipped", "NO_MATCHING_ORDER", "No matching Order")
		return "Unmatched", "NO_MATCHING_ORDER"

	if _delivery_challan_is_superseded_by_sales_invoice(voucher):
		_log_reconciliation(
			order_name,
			voucher.name,
			"Skipped",
			"SUPERSEDED_DELIVERY_CHALLAN",
			"Delivery Challan superseded by Sales Invoice for same tracking movement",
		)
		return "Matched", "SUPERSEDED_DELIVERY_CHALLAN"

	order = frappe.get_doc("Order", order_name)
	if _has_ambiguous_duplicate_movement(voucher):
		order.status = "Manual Review"
		order.save(ignore_permissions=True)
		_log_reconciliation(
			order.name,
			voucher.name,
			"Manual Review",
			"AMBIGUOUS_DUPLICATE_MOVEMENT",
			"Ambiguous duplicate movement for same tracking number and item quantities",
		)
		return "Manual Review", "AMBIGUOUS_DUPLICATE_MOVEMENT"

	customer_client_code = frappe.db.get_value("Customer", order.customer, "client_code")
	if customer_client_code != voucher.party_client_code:
		order.status = "Manual Review"
		order.save(ignore_permissions=True)
		_log_reconciliation(
			order.name,
			voucher.name,
			"Manual Review",
			"CUSTOMER_CLIENT_CODE_MISMATCH",
			f"Customer Client Code mismatch: portal customer {customer_client_code}, Tally party {voucher.party_client_code}",
		)
		return "Manual Review", "CUSTOMER_CLIENT_CODE_MISMATCH"

	fulfilled_by_item = {}
	for line in voucher.lines:
		fulfilled_by_item[line.item] = fulfilled_by_item.get(line.item, 0) + float(line.quantity or 0)

	ordered_items = {row.item for row in order.items}
	extra_items = sorted(set(fulfilled_by_item) - ordered_items)
	if extra_items:
		order.status = "Manual Review"
		order.save(ignore_permissions=True)
		_log_reconciliation(
			order.name,
			voucher.name,
			"Manual Review",
			"EXTRA_VOUCHER_ITEM",
			f"Extra unmatched item lines in voucher: {', '.join(extra_items)}",
		)
		return "Manual Review", "EXTRA_VOUCHER_ITEM"

	for item_row in order.items:
		new_fulfilled_quantity = fulfilled_by_item.get(item_row.item, 0)
		total_fulfilled_quantity = float(item_row.fulfilled_quantity or 0) + new_fulfilled_quantity
		if total_fulfilled_quantity > float(item_row.requested_quantity):
			order.status = "Manual Review"
			order.save(ignore_permissions=True)
			_log_reconciliation(
				order.name,
				voucher.name,
				"Manual Review",
				"OVER_FULFILLMENT",
				f"Over fulfillment for item {item_row.item}: fulfilled {total_fulfilled_quantity:g}, requested {item_row.requested_quantity:g}",
			)
			return "Manual Review", "OVER_FULFILLMENT"

	for item_row in order.items:
		new_fulfilled_quantity = fulfilled_by_item.get(item_row.item, 0)
		if not new_fulfilled_quantity:
			continue
		item_row.fulfilled_quantity = min(
			float(item_row.requested_quantity),
			float(item_row.fulfilled_quantity or 0) + new_fulfilled_quantity,
		)
		item_row.pending_quantity = max(float(item_row.requested_quantity) - item_row.fulfilled_quantity, 0)
		item_row.status = "Completed" if item_row.pending_quantity == 0 else "Partially Processed"

	_apply_order_status_from_items(order)
	order.save(ignore_permissions=True)
	_log_reconciliation(order.name, voucher.name, "Matched", "VOUCHER_QUANTITIES_APPLIED", "Voucher quantities applied")
	return "Matched", "VOUCHER_QUANTITIES_APPLIED"


def _apply_order_status_from_items(order):
	item_statuses = {row.status for row in order.items}
	if item_statuses == {"Completed"}:
		order.status = "Completed"
	elif "Partially Processed" in item_statuses or "Completed" in item_statuses:
		order.status = "Partially Processed"


def _delivery_challan_is_superseded_by_sales_invoice(voucher):
	if voucher.voucher_type != "Delivery Challan" or not voucher.tracking_number:
		return False

	candidates = frappe.get_all(
		"Tally Voucher",
		filters={
			"voucher_type": "Sales Invoice",
			"reference_number": voucher.reference_number,
			"party_client_code": voucher.party_client_code,
			"tracking_number": voucher.tracking_number,
		},
		fields=["name"],
	)
	voucher_signature = _voucher_movement_signature(voucher)
	for candidate in candidates:
		sales_invoice = frappe.get_doc("Tally Voucher", candidate.name)
		if _voucher_movement_signature(sales_invoice) == voucher_signature:
			return True
	return False


def _has_ambiguous_duplicate_movement(voucher):
	if not voucher.tracking_number:
		return False

	candidates = frappe.get_all(
		"Tally Voucher",
		filters={
			"reference_number": voucher.reference_number,
			"party_client_code": voucher.party_client_code,
			"tracking_number": voucher.tracking_number,
			"reconciled": 1,
			"name": ("!=", voucher.name),
		},
		fields=["name", "voucher_type"],
	)
	voucher_signature = _voucher_movement_signature(voucher)
	for candidate in candidates:
		if voucher.voucher_type == "Sales Invoice" and candidate.voucher_type == "Delivery Challan":
			continue
		duplicate = frappe.get_doc("Tally Voucher", candidate.name)
		if _voucher_movement_signature(duplicate) == voucher_signature:
			return True
	return False


def _voucher_movement_signature(voucher):
	return sorted(
		(
			line.item,
			line.godown,
			line.tracking_number or voucher.tracking_number,
			float(line.quantity or 0),
		)
		for line in voucher.lines
	)


def _log_reconciliation(order, voucher, status, reason_code, message):
	frappe.get_doc(
		{
			"doctype": "Order Reconciliation Log",
			"order": order,
			"voucher": voucher,
			"status": status,
			"reason_code": reason_code,
			"message": message,
			"created_at": now_datetime(),
		}
	).insert(ignore_permissions=True)
