"""Controlled backend action for the future portal assignment interface."""

import frappe
from frappe.utils import now_datetime

from kunal_enterprises.api.order_authorization import GODOWN_ASSIGNMENT_ROLES, effective_order_role
from kunal_enterprises.api.utils import create_success_response, handle_error_response


@frappe.whitelist(methods=["POST"])
def assign_godowns(order, assignments):
	"""Fill missing godowns by allocation row name; keep all requested quantities fixed."""
	savepoint = "assign_order_godowns"
	frappe.db.savepoint(savepoint)
	try:
		role = effective_order_role(
			GODOWN_ASSIGNMENT_ROLES,
			message="Godown Allocator, Owner, or Admin is required",
			title="Godown Assignment Permission Required",
		)
		order_doc = frappe.get_doc("Order", order, for_update=True)
		if order_doc.status in {"Cancelled", "Partially Closed"}:
			frappe.throw("Cancelled or Partially Closed orders cannot receive godown assignments")
		try:
			assignments = frappe.parse_json(assignments)
		except (ValueError, TypeError):
			frappe.throw("Assignments must be a valid JSON list")
		if not isinstance(assignments, list) or not assignments:
			frappe.throw("At least one godown assignment is required")
		rows = {row.name: row for row in order_doc.godown_allocations}
		seen = set()
		changes = []
		for assignment in assignments:
			if not isinstance(assignment, dict):
				frappe.throw("Each assignment must contain an allocation and godown")
			row_name = assignment.get("allocation")
			godown = assignment.get("godown")
			if not isinstance(row_name, str) or not isinstance(godown, str):
				frappe.throw("Allocation and godown must be record names")
			godown = godown.strip()
			if row_name not in rows or row_name in seen or not godown:
				frappe.throw("Each assignment needs a unique allocation from this order and an active godown")
			seen.add(row_name)
			row = rows[row_name]
			if row.godown:
				frappe.throw("Previously selected godowns cannot be changed")
			if not frappe.db.exists("Tally Godown", {"name": godown, "is_active": 1}):
				frappe.throw("Assigned godown must exist and be active")
			changes.append((row, godown))

		for row, godown in changes:
			row.godown = godown
		order_doc.flags.in_godown_assignment = True
		order_doc.save(ignore_permissions=True)
		frappe.get_doc({
			"doctype": "Order Status Log",
			"order": order_doc.name,
			"from_status": order_doc.status,
			"to_status": order_doc.status,
			"role": role,
			"note": "Godowns assigned by " + frappe.session.user + ": " + "; ".join(
				f"{row.item} ({row.requested_quantity:g}) → {godown} [allocation {row.name}]"
				for row, godown in changes
			),
			"created_at": now_datetime(),
		}).insert(ignore_permissions=True)
		frappe.db.release_savepoint(savepoint)
		return create_success_response("Godowns assigned", {
			"order": order_doc.name,
			"status": order_doc.status,
			"godown_assignment_pending": bool(order_doc.godown_assignment_pending),
		})
	except Exception as error:
		frappe.db.rollback(save_point=savepoint)
		return handle_error_response(error, "Unable to assign godowns")
