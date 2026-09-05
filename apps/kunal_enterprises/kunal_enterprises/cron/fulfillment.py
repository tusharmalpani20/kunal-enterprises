"""Calculate dispatch fulfillment from current vouchers, never from prior totals."""

from decimal import Decimal, InvalidOperation


def evaluate_order(order, vouchers):
	requested = {item: Decimal(str(qty)) for item, qty in order["items"].items()}
	fulfilled = dict.fromkeys(requested, Decimal(0))
	reasons = {}
	contributions = {}
	seen = set()
	movements = {}
	for voucher in vouchers:
		guid = voucher["guid"]
		if guid in seen:
			raise ValueError(f"Duplicate voucher identity: {guid}")
		seen.add(guid)
		if voucher.get("reference") != order["reference"] or not voucher.get("eligible"):
			continue
		if voucher.get("source_status") == "Removed":
			continue
		if voucher.get("source_error") or voucher.get("source_status") != "Active":
			reasons[guid] = voucher.get("source_error") or "Source voucher is not complete"
			continue
		if not order.get("customer_guid") or voucher.get("party_guid") != order["customer_guid"]:
			reasons[guid] = "Customer ledger GUID does not match the order customer"
			continue
		quantities = {}
		signature = []
		for line in voucher.get("lines", []):
			item = line.get("item")
			try:
				quantity = Decimal(str(line.get("quantity")))
				if not quantity.is_finite() or quantity >= 0:
					raise ValueError()
			except (InvalidOperation, ValueError):
				reasons[guid] = "Delivery quantity must be a finite outward stock movement"
				break
			if item not in requested:
				reasons[guid] = f"Voucher item is not requested: {item}"
				break
			quantities[item] = quantities.get(item, Decimal(0)) - quantity
			signature.append((item, -quantity, line.get("tracking_number") or ""))
		if not quantities and guid not in reasons:
			reasons[guid] = "Voucher has no usable inventory lines"
		if guid in reasons:
			continue
		contributions[guid] = quantities
		if signature and all(row[2] for row in signature):
			movement = tuple(sorted(signature))
			movements.setdefault(movement, []).append(guid)

	for guids in movements.values():
		if len(guids) > 1:
			for guid in guids:
				reasons[guid] = "Multiple challans describe the same tracking movement; verify in Tally"
	for guid, quantities in contributions.items():
		if guid in reasons:
			continue
		for item, quantity in quantities.items():
			fulfilled[item] += quantity
	for item, quantity in fulfilled.items():
		if quantity > requested[item]:
			for guid, quantities in contributions.items():
				if item in quantities:
					reasons[guid] = (
						f"Over fulfillment for {item}: {quantity} dispatched, {requested[item]} requested"
					)

	status = order["status"]
	if status not in {"Cancelled", "Partially Closed"}:
		if reasons:
			status = "Manual Review"
		elif requested and all(fulfilled[item] >= qty for item, qty in requested.items()):
			status = "Completed"
		elif any(fulfilled.values()):
			status = "Partially Processed"
		else:
			status = "Placed" if status == "Placed" else "Processing"
	return {
		"status": status,
		"fulfilled": {item: float(qty) for item, qty in fulfilled.items()},
		"reasons": reasons,
	}
