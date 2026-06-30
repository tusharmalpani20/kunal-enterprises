import frappe
from frappe.utils import now_datetime

from kunal_enterprises.api.order_authorization import BRANCH_ROLES, effective_order_role
from kunal_enterprises.api.utils import create_success_response, handle_error_response


BRANCH_EMPLOYEE_VISIBLE_STATUSES = ("Placed", "Processing", "Manual Review")


@frappe.whitelist(methods=["GET"])
def visible_orders(branch, role):
	try:
		effective_role = _require_branch_access(branch, role)

		godowns = _active_branch_godowns(branch)
		orders = [_serialize_order(order) for order in _get_visible_orders(godowns, effective_role)]
		return create_success_response("Branch visible orders", {"orders": orders})
	except Exception as error:
		return handle_error_response(error, "Unable to load branch orders")


@frappe.whitelist(methods=["POST"])
def mark_processing(branch, order, role):
	try:
		effective_role = _require_branch_access(branch, role, allowed_roles=BRANCH_ROLES)
		if not _order_is_visible_for_branch(order, branch, effective_role):
			frappe.throw("Order is not visible for this Branch", title="Branch Access Required")

		order_doc = frappe.get_doc("Order", order)
		if order_doc.status != "Placed":
			frappe.throw("Only Placed orders can move to Processing", title="Invalid Order Status")
		from_status = order_doc.status
		order_doc.status = "Processing"
		order_doc.save(ignore_permissions=True)
		_create_status_log(order_doc.name, from_status, order_doc.status, effective_role)
		return create_success_response(
			"Order moved to Processing",
			{"order": order_doc.name, "status": order_doc.status},
		)
	except Exception as error:
		return handle_error_response(error, "Unable to move order to Processing")


def _require_branch_access(branch, role, allowed_roles=("Branch Manager", "Branch Employee")):
	effective_role = effective_order_role(allowed_roles, role, "Branch role is required", "Branch Access Required")
	if not frappe.db.exists("Portal Branch", {"name": branch, "is_active": 1}):
		frappe.throw("Active Portal Branch is required", title="Branch Access Required")
	if not _current_user_has_branch_permission(branch):
		frappe.throw("User is not allowed for this Branch", title="Branch Access Required")
	return effective_role


def _current_user_has_branch_permission(branch):
	if frappe.session.user == "Administrator":
		return True
	return bool(
		frappe.db.exists(
			"User Permission",
			{
				"user": frappe.session.user,
				"allow": "Portal Branch",
				"for_value": branch,
			},
		)
	)


def _create_status_log(order, from_status, to_status, role):
	frappe.get_doc(
		{
			"doctype": "Order Status Log",
			"order": order,
			"from_status": from_status,
			"to_status": to_status,
			"role": role,
			"note": f"{role} moved visible order to Processing",
			"created_at": now_datetime(),
		}
	).insert(ignore_permissions=True)


def _active_branch_godowns(branch):
	return [
		row.godown
		for row in frappe.get_all(
			"Branch Godown Mapping",
			filters={"portal_branch": branch, "is_active": 1},
			fields=["godown"],
		)
	]


def _get_visible_orders(godowns, role):
	if not godowns:
		return []

	status_filter = ""
	values = {"godowns": tuple(godowns)}
	if role == "Branch Employee":
		status_filter = 'and o.status in %(statuses)s'
		values["statuses"] = BRANCH_EMPLOYEE_VISIBLE_STATUSES
	order_table = _table("Order")
	allocation_table = _table("Order Godown Allocation")

	return frappe.db.sql(
		f"""
		select distinct
			o.name,
			o.portal_reference_number,
			o.status,
			o.confirmation_datetime,
			o.total_item_count,
			o.total_quantity
		from {order_table} o
		inner join {allocation_table} allocation
			on allocation.parent = o.name
		where allocation.godown in %(godowns)s
			{status_filter}
		order by o.confirmation_datetime desc, o.name desc
		""",
		values,
		as_dict=True,
	)


def _order_is_visible_for_branch(order, branch, role):
	godowns = _active_branch_godowns(branch)
	if not godowns:
		return False
	status_filter = ""
	values = {"order": order, "godowns": tuple(godowns)}
	if role == "Branch Employee":
		status_filter = 'and o.status in %(statuses)s'
		values["statuses"] = BRANCH_EMPLOYEE_VISIBLE_STATUSES
	order_table = _table("Order")
	allocation_table = _table("Order Godown Allocation")

	return bool(
		frappe.db.sql(
			f"""
			select o.name
			from {order_table} o
			inner join {allocation_table} allocation
				on allocation.parent = o.name
			where o.name = %(order)s
				and allocation.godown in %(godowns)s
				{status_filter}
			limit 1
			""",
			values,
		)
	)


def _table(doctype):
	quote = '"' if frappe.db.db_type == "postgres" else "`"
	return f"{quote}tab{doctype}{quote}"


def _serialize_order(order):
	serialized = {
		**order,
		"confirmation_datetime": str(order.confirmation_datetime) if order.confirmation_datetime else None,
		"display_status": "Under Review" if order.status == "Manual Review" else order.status,
	}
	if order.status == "Manual Review":
		reason = _latest_manual_review_reason(order.name)
		serialized["manual_review_reason"] = reason.get("message")
		serialized["manual_review_reason_code"] = reason.get("reason_code")
	return serialized


def _latest_manual_review_reason(order):
	return frappe.db.get_value(
		"Order Reconciliation Log",
		{"order": order, "status": "Manual Review"},
		["reason_code", "message"],
		order_by="created_at desc, name desc",
		as_dict=True,
	) or {}
