from collections import defaultdict
from decimal import Decimal, InvalidOperation
from math import isclose

import frappe
from frappe import _
from frappe.model.document import Document


class Order(Document):
	def validate(self):
		self._validate_cancellation_reason()
		self._validate_confirmed_lines_are_immutable()
		self._validate_quantity_only_order()
		self._set_godown_assignment_pending()
		if self.status == "Processing" and self.godown_assignment_pending:
			frappe.throw(_("Assign a godown to every requested quantity before Processing"))
		self._set_totals()

	def validate_processing_godowns(self):
		"""Portal transitions recheck master activity; historical Tally quantities remain valid."""
		self._set_godown_assignment_pending()
		if self.godown_assignment_pending:
			frappe.throw(_("Assign a godown to every requested quantity before Processing"))
		godowns = {row.godown for row in self.godown_allocations}
		active = set(frappe.get_all("Tally Godown",
			filters={"name": ("in", tuple(godowns)), "is_active": 1}, pluck="name"))
		if godowns != active:
			frappe.throw(_("Every requested quantity must reference an active godown before Processing"))

	def _validate_cancellation_reason(self):
		if self.cancellation_reason:
			self.cancellation_reason = self.cancellation_reason.strip()
		previous = None if self.is_new() else self.get_doc_before_save()
		entering_cancelled = self.status == "Cancelled" and (
			previous is None or previous.status != "Cancelled"
		)
		if entering_cancelled and not self.cancellation_reason:
			frappe.throw(_("Cancellation reason is required"), frappe.ValidationError)

	def _validate_confirmed_lines_are_immutable(self):
		if self.is_new():
			return

		previous = self.get_doc_before_save()
		if not previous:
			return

		if self._requested_item_lines() != previous._requested_item_lines():
			frappe.throw(_("Confirmed order item lines cannot be edited"), frappe.ValidationError)

		if self.flags.in_godown_reassignment:
			self._validate_placed_reassignment(previous)
			return

		if self._requested_godown_allocations() != previous._requested_godown_allocations():
			if self.flags.in_godown_assignment:
				self._validate_missing_godowns_only(previous)
				return
			frappe.throw(_("Confirmed order godown allocations cannot be edited"), frappe.ValidationError)

	def _validate_placed_reassignment(self, previous):
		from kunal_enterprises.api.godown_assignment import _ensure_editable, _requested_by_item, _validated_splits
		from kunal_enterprises.api.order_authorization import GODOWN_ASSIGNMENT_ROLES, effective_order_role

		effective_order_role(GODOWN_ASSIGNMENT_ROLES)
		_ensure_editable(previous)
		_ensure_editable(self)
		requested = _requested_by_item(previous)
		allocations = defaultdict(list)
		for row in self.godown_allocations:
			allocations[row.item].append({"godown": row.godown, "quantity": row.requested_quantity})
		if allocations.keys() != requested.keys():
			frappe.throw(_("Every requested item must have its complete godown distribution"))
		for item, quantity in requested.items():
			_validated_splits({"splits": allocations[item]},
				frappe._dict(requested_quantity=quantity, fulfilled_quantity=0))

	def _validate_missing_godowns_only(self, previous):
		from kunal_enterprises.api.order_authorization import GODOWN_ASSIGNMENT_ROLES, effective_order_role

		effective_order_role(GODOWN_ASSIGNMENT_ROLES)
		if previous.status in {"Cancelled", "Partially Closed"} or self.status != previous.status:
			frappe.throw(_("Godown assignment cannot change status or modify explicitly closed orders"))
		old_rows = {row.name: row for row in previous.godown_allocations}
		groups = defaultdict(list)
		for row in self.godown_allocations:
			source = row.flags.get("godown_split_source") or row.name
			if source not in old_rows:
				frappe.throw(_("Godown assignment cannot introduce unrelated allocations"))
			groups[source].append(row)
		if groups.keys() != old_rows.keys():
			frappe.throw(_("Godown assignment cannot remove requested allocations"))
		for name, old in old_rows.items():
			rows = groups[name]
			if old.godown:
				fields = ("name", "item", "godown", "requested_quantity", "fulfilled_quantity",
					"pending_quantity", "stock_shown_at_order_time", "stock_snapshot_at")
				if len(rows) != 1 or any(old.get(field) != rows[0].get(field) for field in fields):
					frappe.throw(_("Previously selected godown allocations cannot be changed"))
				continue
			if len(rows) > 1 and old.fulfilled_quantity:
				frappe.throw(_("An allocation with fulfilled quantity cannot be split"))
			if not any(row.name == old.name for row in rows):
				frappe.throw(_("Godown assignment must retain each original allocation record"))
			if len(rows) > 1 and (
				any(not row.godown for row in rows) or len({row.godown for row in rows}) != len(rows)
			):
				frappe.throw(_("Split godowns must be non-empty and unique within each allocation"))
			total = Decimal(0)
			for row in rows:
				if row.item != old.item or row.fulfilled_quantity != old.fulfilled_quantity:
					frappe.throw(_("Godown assignment cannot change items or fulfilled quantities"))
				try:
					quantity = Decimal(str(row.requested_quantity))
					if not quantity.is_finite() or quantity <= 0:
						raise ValueError()
				except (InvalidOperation, ValueError):
					frappe.throw(_("Split quantities must be finite and positive"))
				if quantity.normalize().as_tuple().exponent < -9:
					frappe.throw(_("Split quantities support at most nine decimal places"))
				total += quantity
			if total != Decimal(str(old.requested_quantity)):
				frappe.throw(_("Godown assignment must preserve each original requested quantity"))

	def _set_godown_assignment_pending(self):
		requested = defaultdict(float)
		allocated = defaultdict(float)
		for row in self.items:
			requested[row.item] += row.requested_quantity
		for row in self.godown_allocations:
			if not row.godown:
				self.godown_assignment_pending = 1
				return
			allocated[row.item] += row.requested_quantity
		# Include legacy orders with missing/partial allocations in the Processing gate.
		self.godown_assignment_pending = int(
			requested.keys() != allocated.keys()
			or any(not isclose(quantity, allocated[item], rel_tol=1e-9, abs_tol=1e-9)
				for item, quantity in requested.items())
		)

	def _requested_item_lines(self):
		return tuple((row.item, row.requested_quantity) for row in self.items)

	def _requested_godown_allocations(self):
		return tuple((row.item, row.godown, row.requested_quantity) for row in self.godown_allocations)

	def _validate_quantity_only_order(self):
		if not self.items:
			frappe.throw(_("Order must contain at least one item"))
		for row in self.items:
			if row.requested_quantity <= 0:
				frappe.throw(_("Order Quantity must be positive"))
			row.fulfilled_quantity = row.fulfilled_quantity or 0
			row.pending_quantity = max(row.requested_quantity - row.fulfilled_quantity, 0)
			if not row.status:
				row.status = self.status or "Placed"
		for row in self.godown_allocations:
			if row.requested_quantity <= 0:
				frappe.throw(_("Order Quantity must be positive"))
			row.fulfilled_quantity = row.fulfilled_quantity or 0
			row.pending_quantity = max(row.requested_quantity - row.fulfilled_quantity, 0)

	def _set_totals(self):
		self.total_item_count = len({row.item for row in self.items if row.item})
		self.total_quantity = sum(row.requested_quantity for row in self.items)
