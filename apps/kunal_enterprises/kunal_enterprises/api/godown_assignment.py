"""Controlled allocation and stock preview for the portal assignment interface."""

import math
from collections import defaultdict
from decimal import Decimal, InvalidOperation

import frappe
from frappe.utils import cint, now_datetime

from kunal_enterprises.api.order_authorization import GODOWN_ASSIGNMENT_ROLES, effective_order_role
from kunal_enterprises.api.utils import create_success_response, handle_error_response


def _assignment_role():
	return effective_order_role(
		GODOWN_ASSIGNMENT_ROLES,
		message="Godown Allocator, Owner, or Admin is required",
		title="Godown Assignment Permission Required",
	)


def _ensure_assignable(order):
	if order.status in {"Cancelled", "Partially Closed"}:
		frappe.throw("Cancelled or Partially Closed orders cannot receive godown assignments")


def _ensure_editable(order):
	if order.status != "Placed":
		frappe.throw("Saved godown assignments can only be edited while the order is Placed")
	if any(row.fulfilled_quantity for row in list(order.items) + list(order.godown_allocations)):
		frappe.throw("Orders with historical fulfilled quantities cannot have saved assignments edited")


def _requested_by_item(order):
	requested = defaultdict(Decimal)
	for row in order.items:
		requested[row.item] += Decimal(str(row.requested_quantity))
	return requested


@frappe.whitelist(methods=["GET"])
def assignment_options(order, edit=0):
	"""Expose only the stock information needed to assign this order's missing godowns."""
	try:
		_assignment_role()
		order_doc = frappe.get_doc("Order", order)
		_ensure_assignable(order_doc)
		editing = bool(cint(edit))
		if editing:
			_ensure_editable(order_doc)
			current = defaultdict(lambda: defaultdict(Decimal))
			for row in order_doc.godown_allocations:
				if row.godown:
					current[row.item][row.godown] += Decimal(str(row.requested_quantity))
			rows = [frappe._dict(name=item, item=item, requested_quantity=float(quantity), fulfilled_quantity=0,
				current_allocations={godown: float(amount) for godown, amount in current[item].items()})
				for item, quantity in _requested_by_item(order_doc).items()]
		else:
			rows = [row for row in order_doc.godown_allocations if not row.godown]
		godowns = frappe.get_all("Tally Godown", filters={"is_active": 1},
			fields=["name", "godown_name"], order_by="godown_name asc, name asc")
		item_names = {row.item for row in rows}
		names = {row.name: row.item_name for row in frappe.get_all("Tally Item",
			filters={"name": ("in", tuple(item_names))}, fields=["name", "item_name"])} if item_names else {}
		stock = {}
		if item_names and godowns:
			filters = {"item": ("in", tuple(item_names)), "godown": ("in", tuple(row.name for row in godowns))}
			if frappe.conf.get("tally_source_company"):
				filters["source_company"] = frappe.conf.tally_source_company
			for snapshot in frappe.get_all("Tally Stock Snapshot", filters=filters,
				fields=["item", "godown", "quantity"], order_by="synced_at desc, creation desc, name desc"):
				stock.setdefault((snapshot.item, snapshot.godown), snapshot.quantity)
		return create_success_response("Godown assignment options", {
			"order": order_doc.name,
			"status": order_doc.status,
			"godown_assignment_pending": bool(order_doc.godown_assignment_pending),
			"editing": editing,
			"godowns": godowns,
			"allocations": [{
				"name": row.name, "item": row.item, "item_name": names.get(row.item, row.item),
				"quantity": row.requested_quantity, "fulfilled_quantity": row.fulfilled_quantity or 0,
				"can_split": not bool(row.fulfilled_quantity),
				**({"current_allocations": row.current_allocations} if editing else {}),
				"stock": {godown.name: stock.get((row.item, godown.name)) for godown in godowns},
			} for row in rows],
		})
	except Exception as error:
		return handle_error_response(error, "Unable to load godown assignment options")


def _validated_splits(assignment, row):
	if "splits" in assignment:
		if "godown" in assignment:
			frappe.throw("Provide either a godown or splits, not both")
		splits = assignment["splits"]
		if not isinstance(splits, list) or not splits:
			frappe.throw("Each allocation requires at least one split")
	else:
		splits = [{"godown": assignment.get("godown"), "quantity": row.requested_quantity}]
	if len(splits) > 1 and row.fulfilled_quantity:
		frappe.throw("An allocation with fulfilled quantity cannot be split; assign its entire quantity to one godown")
	seen = set()
	result = []
	total = Decimal(0)
	for split in splits:
		if not isinstance(split, dict) or not isinstance(split.get("godown"), str):
			frappe.throw("Each split needs an active godown record name and quantity")
		godown = split["godown"].strip()
		if not godown or godown in seen:
			frappe.throw("Split godowns must be non-empty and unique within each allocation")
		seen.add(godown)
		try:
			if isinstance(split.get("quantity"), bool):
				raise ValueError()
			quantity = Decimal(str(split.get("quantity")))
			if not quantity.is_finite() or quantity <= 0 or not math.isfinite(float(quantity)) or float(quantity) <= 0:
				raise ValueError()
		except (InvalidOperation, ValueError, TypeError, OverflowError):
			frappe.throw("Split quantities must be finite and positive")
		# Frappe Float columns are decimal(21,9); independent DB rounding would break conservation.
		if quantity.normalize().as_tuple().exponent < -9:
			frappe.throw("Split quantities support at most nine decimal places")
		if Decimal(str(float(quantity))) != quantity:
			frappe.throw("Split quantity precision exceeds the supported numeric representation")
		if not frappe.db.exists("Tally Godown", {"name": godown, "is_active": 1}):
			frappe.throw("Assigned godown must exist and be active")
		total += quantity
		result.append((godown, float(quantity)))
	if total != Decimal(str(row.requested_quantity)):
		frappe.throw("Split quantities must add up exactly to the original unassigned quantity")
	return result


@frappe.whitelist(methods=["POST"])
def assign_godowns(order, assignments):
	"""Assign complete rows or split their exact unassigned quantities across godowns."""
	savepoint = "assign_order_godowns"
	frappe.db.savepoint(savepoint)
	try:
		role = _assignment_role()
		order_doc = frappe.get_doc("Order", order, for_update=True)
		_ensure_assignable(order_doc)
		try:
			assignments = frappe.parse_json(assignments)
		except (ValueError, TypeError):
			frappe.throw("Assignments must be a valid JSON list")
		if not isinstance(assignments, list) or not assignments:
			frappe.throw("At least one godown assignment is required")
		rows = {row.name: row for row in order_doc.godown_allocations}
		plans = {}
		for assignment in assignments:
			if not isinstance(assignment, dict) or not isinstance(assignment.get("allocation"), str):
				frappe.throw("Each assignment must contain an allocation record name")
			row_name = assignment["allocation"]
			if row_name not in rows or row_name in plans:
				frappe.throw("Each assignment needs a unique allocation from this order")
			row = rows[row_name]
			if row.godown:
				frappe.throw("Previously selected godowns cannot be changed")
			plans[row_name] = _validated_splits(assignment, row)

		new_rows = []
		notes = []
		for row in list(order_doc.godown_allocations):
			if row.name not in plans:
				new_rows.append(row)
				continue
			source_name = row.name
			original = row.as_dict()
			for index, (godown, quantity) in enumerate(plans[source_name]):
				if index:
					values = dict(original)
					values.pop("name", None)
					new = order_doc.append("godown_allocations", values)
				else:
					new = row
				new.godown = godown
				new.requested_quantity = quantity
				# The controller conserves each source row separately; this provenance is not persisted.
				new.flags.godown_split_source = source_name
				new_rows.append(new)
				notes.append(f"{row.item} ({quantity:g}) → {godown} [allocation {source_name}]")
		order_doc.set("godown_allocations", new_rows)
		for index, row in enumerate(order_doc.godown_allocations, 1):
			row.idx = index
		order_doc.flags.in_godown_assignment = True
		order_doc.save(ignore_permissions=True)
		frappe.get_doc({
			"doctype": "Order Status Log", "order": order_doc.name,
			"from_status": order_doc.status, "to_status": order_doc.status, "role": role,
			"note": "Godowns assigned by " + frappe.session.user + ": " + "; ".join(notes),
			"created_at": now_datetime(),
		}).insert(ignore_permissions=True)
		frappe.db.release_savepoint(savepoint)
		return create_success_response("Godowns assigned", {
			"order": order_doc.name, "status": order_doc.status,
			"godown_assignment_pending": bool(order_doc.godown_assignment_pending),
		})
	except Exception as error:
		frappe.db.rollback(save_point=savepoint)
		return handle_error_response(error, "Unable to assign godowns")


def _distribution_summary(rows):
	return "; ".join(
		f"{row.item} ({row.requested_quantity:g}) → {row.godown or 'Not assigned'} [allocation {row.name}]"
		for row in rows
	)


@frappe.whitelist(methods=["POST"])
def replace_assignments(order, assignments):
	"""Replace the complete distribution while the request is still Placed and unfulfilled."""
	savepoint = "replace_order_godowns"
	frappe.db.savepoint(savepoint)
	try:
		role = _assignment_role()
		order_doc = frappe.get_doc("Order", order, for_update=True)
		_ensure_editable(order_doc)
		try:
			assignments = frappe.parse_json(assignments)
		except (ValueError, TypeError):
			frappe.throw("Assignments must be a valid JSON list")
		if not isinstance(assignments, list) or not assignments:
			frappe.throw("Provide the complete godown distribution for every requested item")
		requested = _requested_by_item(order_doc)
		plans = {}
		for assignment in assignments:
			if not isinstance(assignment, dict) or not isinstance(assignment.get("item"), str):
				frappe.throw("Each assignment needs a requested item record name and splits")
			item = assignment["item"]
			if item not in requested or item in plans or "splits" not in assignment:
				frappe.throw("Each requested item must appear exactly once with its complete splits")
			plans[item] = _validated_splits(assignment,
				frappe._dict(requested_quantity=requested[item], fulfilled_quantity=0))
		if plans.keys() != requested.keys():
			frappe.throw("Provide the complete godown distribution for every requested item")

		original_rows = list(order_doc.godown_allocations)
		before = _distribution_summary(original_rows)
		used = set()
		new_rows = []
		for item, splits in plans.items():
			for godown, quantity in splits:
				retained = next((row for row in original_rows if row.name not in used
					and row.item == item and row.godown == godown), None)
				if retained:
					# Stock evidence belongs to the original item/godown, even if its distribution changes.
					used.add(retained.name)
					retained.requested_quantity = quantity
					new_rows.append(retained)
				else:
					new_rows.append(order_doc.append("godown_allocations", {
						"item": item, "godown": godown, "requested_quantity": quantity,
						"fulfilled_quantity": 0, "pending_quantity": quantity,
						"stock_shown_at_order_time": 0, "stock_snapshot_at": None,
					}))
		order_doc.set("godown_allocations", new_rows)
		for index, row in enumerate(order_doc.godown_allocations, 1):
			row.idx = index
		order_doc.flags.in_godown_reassignment = True
		order_doc.save(ignore_permissions=True)
		frappe.get_doc({
			"doctype": "Order Status Log", "order": order_doc.name,
			"from_status": "Placed", "to_status": "Placed", "role": role,
			"note": "Godown assignments edited by " + frappe.session.user
				+ ". Before: " + before + ". After: " + _distribution_summary(order_doc.godown_allocations),
			"created_at": now_datetime(),
		}).insert(ignore_permissions=True)
		frappe.db.release_savepoint(savepoint)
		return create_success_response("Godown assignments updated", {
			"order": order_doc.name, "status": order_doc.status,
			"godown_assignment_pending": bool(order_doc.godown_assignment_pending),
		})
	except Exception as error:
		frappe.db.rollback(save_point=savepoint)
		return handle_error_response(error, "Unable to update godown assignments")
