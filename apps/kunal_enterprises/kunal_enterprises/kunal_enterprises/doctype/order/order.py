import frappe
from frappe import _
from frappe.model.document import Document


class Order(Document):
	def validate(self):
		self._validate_confirmed_lines_are_immutable()
		self._validate_quantity_only_order()
		self._set_totals()

	def _validate_confirmed_lines_are_immutable(self):
		if self.is_new():
			return

		previous = self.get_doc_before_save()
		if not previous:
			return

		if self._requested_item_lines() != previous._requested_item_lines():
			frappe.throw(_("Confirmed order item lines cannot be edited"), frappe.ValidationError)

		if self._requested_godown_allocations() != previous._requested_godown_allocations():
			frappe.throw(_("Confirmed order godown allocations cannot be edited"), frappe.ValidationError)

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
			row.pending_quantity = row.requested_quantity - row.fulfilled_quantity
			if not row.status:
				row.status = self.status or "Placed"
		for row in self.godown_allocations:
			if row.requested_quantity <= 0:
				frappe.throw(_("Order Quantity must be positive"))
			row.fulfilled_quantity = row.fulfilled_quantity or 0
			row.pending_quantity = row.requested_quantity - row.fulfilled_quantity

	def _set_totals(self):
		self.total_item_count = len({row.item for row in self.items if row.item})
		self.total_quantity = sum(row.requested_quantity for row in self.items)
