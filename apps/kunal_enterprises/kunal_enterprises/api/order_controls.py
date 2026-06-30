import frappe
from frappe.utils import now_datetime

from kunal_enterprises.api.order_authorization import OWNER_ADMIN_ROLES, effective_order_role
from kunal_enterprises.api.utils import create_success_response, handle_error_response


@frappe.whitelist(methods=["POST"])
def cancel_order(order, role, note):
	try:
		order_doc, effective_role = _load_owner_admin_order(order, role)
		_transition_order(order_doc, "Cancelled", effective_role, note)
		return create_success_response("Order cancelled", {"order": order_doc.name, "status": order_doc.status})
	except Exception as error:
		return handle_error_response(error, "Unable to cancel order")


@frappe.whitelist(methods=["POST"])
def partially_close_order(order, role, note):
	try:
		order_doc, effective_role = _load_owner_admin_order(order, role)
		_transition_order(order_doc, "Partially Closed", effective_role, note)
		return create_success_response(
			"Order partially closed",
			{"order": order_doc.name, "status": order_doc.status},
		)
	except Exception as error:
		return handle_error_response(error, "Unable to partially close order")


@frappe.whitelist(methods=["POST"])
def resolve_manual_review(order, role, resolution_note):
	try:
		order_doc, effective_role = _load_owner_admin_order(order, role)
		if order_doc.status != "Manual Review":
			frappe.throw("Only Manual Review orders can be resolved", title="Invalid Order Status")
		if not (resolution_note or "").strip():
			frappe.throw("Resolution note is required", title="Resolution Note Required")
		_transition_order(order_doc, "Processing", effective_role, resolution_note)
		return create_success_response(
			"Manual Review resolved",
			{"order": order_doc.name, "status": order_doc.status},
		)
	except Exception as error:
		return handle_error_response(error, "Unable to resolve Manual Review")


@frappe.whitelist(methods=["POST"])
def mark_processing(order, role=None):
	try:
		order_doc, effective_role = _load_owner_admin_order(order, role)
		if order_doc.status != "Placed":
			frappe.throw("Only Placed orders can move to Processing", title="Invalid Order Status")
		_transition_order(order_doc, "Processing", effective_role, f"{effective_role} moved order to Processing")
		return create_success_response(
			"Order moved to Processing",
			{"order": order_doc.name, "status": order_doc.status},
		)
	except Exception as error:
		return handle_error_response(error, "Unable to move order to Processing")


def _load_owner_admin_order(order, role=None):
	effective_role = effective_order_role(
		OWNER_ADMIN_ROLES,
		role,
		"Only Owner/Admin can perform this order action",
		"Owner/Admin Required",
	)
	return frappe.get_doc("Order", order), effective_role


def _transition_order(order, to_status, role, note):
	from_status = order.status
	order.status = to_status
	order.save(ignore_permissions=True)
	frappe.get_doc(
		{
			"doctype": "Order Status Log",
			"order": order.name,
			"from_status": from_status,
			"to_status": to_status,
			"role": role,
			"note": note,
			"created_at": now_datetime(),
		}
	).insert(ignore_permissions=True)
