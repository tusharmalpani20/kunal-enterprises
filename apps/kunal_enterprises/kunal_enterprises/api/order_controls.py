import frappe
from frappe.utils import now_datetime

from kunal_enterprises.api.utils import create_success_response, handle_error_response


OWNER_ADMIN_ROLES = ("Owner", "Admin")


@frappe.whitelist(methods=["POST"])
def cancel_order(order, role, note):
	try:
		order_doc = _load_owner_admin_order(order, role)
		_transition_order(order_doc, "Cancelled", role, note)
		return create_success_response("Order cancelled", {"order": order_doc.name, "status": order_doc.status})
	except Exception as error:
		return handle_error_response(error, "Unable to cancel order")


@frappe.whitelist(methods=["POST"])
def partially_close_order(order, role, note):
	try:
		order_doc = _load_owner_admin_order(order, role)
		_transition_order(order_doc, "Partially Closed", role, note)
		return create_success_response(
			"Order partially closed",
			{"order": order_doc.name, "status": order_doc.status},
		)
	except Exception as error:
		return handle_error_response(error, "Unable to partially close order")


@frappe.whitelist(methods=["POST"])
def resolve_manual_review(order, role, resolution_note):
	try:
		order_doc = _load_owner_admin_order(order, role)
		if order_doc.status != "Manual Review":
			frappe.throw("Only Manual Review orders can be resolved", title="Invalid Order Status")
		if not (resolution_note or "").strip():
			frappe.throw("Resolution note is required", title="Resolution Note Required")
		_transition_order(order_doc, "Processing", role, resolution_note)
		return create_success_response(
			"Manual Review resolved",
			{"order": order_doc.name, "status": order_doc.status},
		)
	except Exception as error:
		return handle_error_response(error, "Unable to resolve Manual Review")


def _load_owner_admin_order(order, role):
	if role not in OWNER_ADMIN_ROLES or not _current_user_has_role(role):
		frappe.throw("Only Owner/Admin can perform this order action", title="Owner/Admin Required")
	return frappe.get_doc("Order", order)


def _current_user_has_role(role):
	if frappe.session.user == "Administrator":
		return True
	return role in frappe.get_roles(frappe.session.user)


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
