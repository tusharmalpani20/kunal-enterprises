from collections import defaultdict
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

		if self._requested_godown_allocations() != previous._requested_godown_allocations():
			if self.flags.in_godown_assignment:
				self._validate_missing_godowns_only(previous)
				return
			frappe.throw(_("Confirmed order godown allocations cannot be edited"), frappe.ValidationError)

	def _validate_missing_godowns_only(self, previous):
		from kunal_enterprises.api.order_authorization import GODOWN_ASSIGNMENT_ROLES, effective_order_role

		effective_order_role(GODOWN_ASSIGNMENT_ROLES)
		if previous.status in {"Cancelled", "Partially Closed"} or self.status != previous.status:
			frappe.throw(_("Godown assignment cannot change status or modify explicitly closed orders"))
		old_rows = previous.godown_allocations
		new_rows = self.godown_allocations
		if len(old_rows) != len(new_rows):
			frappe.throw(_("Godown assignment cannot change requested allocations"))
		for old, new in zip(old_rows, new_rows):
			if (old.name, old.item, old.requested_quantity) != (new.name, new.item, new.requested_quantity):
				frappe.throw(_("Godown assignment cannot change requested allocations"))
			if old.godown and old.godown != new.godown:
				frappe.throw(_("Previously selected godowns cannot be changed"))

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
