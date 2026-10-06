import math

import frappe
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime


def _same_datetime(left, right):
	# Desk serializes datetime fields as strings; compare their values, not Python types.
	if not left or not right:
		return not left and not right
	return get_datetime(left) == get_datetime(right)


class QuickOrderRequest(Document):
	def validate(self):
		from kunal_enterprises.api.quick_orders import MAX_TEXT_LENGTH, _require_reviewer

		if self.is_new():
			if not self.flags.in_quick_order_customer_submit:
				frappe.throw("Quick Order Requests must be submitted by a Customer", frappe.PermissionError)
			if not isinstance(self.text, str):
				frappe.throw("Quick Order text must be a string")
			self.text = self.text.strip()
			if not self.text or len(self.text) > MAX_TEXT_LENGTH:
				frappe.throw(f"Quick Order text must contain between 1 and {MAX_TEXT_LENGTH} characters")
			if self.status != "Pending Review" or self.items or self.order:
				frappe.throw("New Quick Order Requests must be pending and cannot contain an order")
			self.confirmation_datetime = now_datetime()
			return

		_require_reviewer()
		previous = self.get_doc_before_save()
		if not previous:
			frappe.throw("Quick Order Request history is unavailable")
		for field in ("customer", "text"):
			if self.get(field) != previous.get(field):
				frappe.throw("Original Quick Order text and Customer identity cannot be changed")
		if not _same_datetime(self.confirmation_datetime, previous.confirmation_datetime):
			frappe.throw("Original Quick Order confirmation time cannot be changed")
		if self.status != previous.status and not self.flags.in_quick_order_transition:
			frappe.throw("Use the Quick Order review actions to change status")
		transitioning = self.status != previous.status and self.flags.in_quick_order_transition
		if self.reviewed_by != previous.reviewed_by:
			if not transitioning or self.reviewed_by != frappe.session.user:
				frappe.throw("Review attribution can only be set by a review action")
		if not _same_datetime(self.review_started_at, previous.review_started_at):
			if not transitioning or previous.status != "Pending Review" or self.status != "In Review":
				frappe.throw("The review start time cannot be changed")
		if self.rejection_reason != previous.rejection_reason:
			if not transitioning or self.status != "Rejected":
				frappe.throw("Rejection reason can only be set when rejecting a request")
		if (self.order, self.portal_reference_number) != (previous.order, previous.portal_reference_number):
			if not self.flags.in_quick_order_conversion or previous.order or self.status != "Converted to Order":
				frappe.throw("The converted Order link cannot be changed")
		if self.status != previous.status:
			allowed = {"Pending Review": {"In Review", "Rejected"}, "In Review": {"Converted to Order", "Rejected"}}
			if self.status not in allowed.get(previous.status, set()):
				frappe.throw("Invalid Quick Order review transition")
		if self.status == "Rejected" and not (self.rejection_reason or "").strip():
			frappe.throw("Rejection reason is required")
		if self.status == "Converted to Order":
			if not self.order or frappe.db.get_value("Order", self.order, "quick_order_request") != self.name:
				frappe.throw("A Converted Quick Order must link to its matching Order")
		fields = ("name", "item", "item_name", "quantity", "godown")
		before = [tuple(row.get(field) for field in fields) for row in previous.items]
		after = [tuple(row.get(field) for field in fields) for row in self.items]
		if before != after and previous.status != "In Review":
			frappe.throw("Order items can only be edited while the request is In Review")
		if before != after and self.status not in {"In Review", "Converted to Order"}:
			frappe.throw("Order items cannot be changed on a closed request")
		if self.status == "In Review":
			from kunal_enterprises.api.product_groups import item_is_allowed, resolve_product_access

			access = resolve_product_access(self.customer)
			for row in self.items:
				if not row.item or not math.isfinite(row.quantity or 0) or row.quantity <= 0:
					frappe.throw("Every selected item requires a finite positive quantity")
				item = frappe.get_doc("Tally Item", row.item)
				if not item_is_allowed(item, access):
					frappe.throw("Quick Order item is inactive or outside Customer Item Access")
				row.item_name = item.item_name
				if row.godown and not frappe.db.exists("Tally Godown", {"name": row.godown, "is_active": 1}):
					frappe.throw("Selected godown must be active")
