"""Authenticated mobile requests and the controlled portal review/conversion boundary."""

import frappe
from frappe.utils import cint, now_datetime

from kunal_enterprises.api.orders import submit_order
from kunal_enterprises.api.product_groups import (
	_load_mobile_item_page,
	item_is_allowed,
	resolve_product_access,
)
from kunal_enterprises.api.token_verification import verify_token
from kunal_enterprises.api.utils import create_success_response, handle_error_response

MAX_TEXT_LENGTH = 5000
REVIEWER_ROLES = {"Owner", "Admin", "Order Coordinator"}


def _require_reviewer():
	if frappe.session.user == "Administrator":
		return
	if not REVIEWER_ROLES.intersection(frappe.get_roles(frappe.session.user)):
		frappe.throw("Owner, Admin, or Order Coordinator is required", frappe.PermissionError)


def _mobile_identity(customer=None, headers=None, sales_employee=None, allow_all_customers=False):
	"""Derive attribution from the token; employee requests always name a selected customer."""
	valid, identity = verify_token(headers)
	if not valid:
		return None, identity
	if identity["identity_type"] == "Customer":
		if sales_employee or (customer and customer != identity["identity"]):
			frappe.throw("Customer does not match the mobile token", frappe.PermissionError)
		return {"customer": identity["identity"], "sales_employee": None}, None
	if identity["identity_type"] != "Sales Employee" or (not customer and not allow_all_customers):
		frappe.throw("A selected Customer and valid mobile identity are required", frappe.PermissionError)
	if sales_employee and sales_employee != identity["identity"]:
		frappe.throw("Sales Employee does not match the mobile token", frappe.PermissionError)
	if customer:
		resolve_product_access(customer, identity["identity"])
	elif frappe.db.get_value("Sales Employee", identity["identity"], "status") != "Active":
		frappe.throw("Sales Employee is disabled", frappe.PermissionError)
	return {"customer": customer, "sales_employee": identity["identity"]}, None


def _employee_customer_names(employee, candidates):
	from kunal_enterprises.kunal_enterprises.doctype.customer.customer import has_sales_employee_order_access

	doc = frappe.get_doc("Sales Employee", employee)
	if doc.status != "Active":
		frappe.throw("Sales Employee is disabled", frappe.PermissionError)
	assigned = {row.customer for row in doc.assigned_customers if row.customer}
	return [name for name in set(candidates) if name and (not assigned or name in assigned)
		and has_sales_employee_order_access(frappe.get_doc("Customer", name))]


def _history_filters(identity):
	filters = {}
	if identity["customer"]:
		filters["customer"] = identity["customer"]
	if identity["sales_employee"]:
		filters["sales_employee"] = identity["sales_employee"]
		if not identity["customer"]:
			candidates = frappe.get_all("Quick Order Request", filters=filters, pluck="customer")
			filters["customer"] = ("in", _employee_customer_names(identity["sales_employee"], candidates))
	return filters


def _serialize(doc):
	return {
		"request": doc.name, "name": doc.name, "status": doc.status, "text": doc.text,
		"customer": doc.customer,
		"customer_name": frappe.db.get_value("Customer", doc.customer, "customer_name"),
		"order_source": doc.get("order_source") or "Customer", "sales_employee": doc.get("sales_employee"),
		"confirmation_datetime": str(doc.confirmation_datetime) if doc.confirmation_datetime else None,
		"order": doc.order, "portal_reference_number": doc.portal_reference_number,
		"rejection_reason": doc.rejection_reason if doc.status == "Rejected" else None,
	}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def submit(text, customer=None, headers=None, sales_employee=None):
	savepoint = "quick_order_submit"
	frappe.db.savepoint(savepoint)
	try:
		identity, error = _mobile_identity(customer, headers, sales_employee)
		if error:
			frappe.db.release_savepoint(savepoint)
			return error
		if not isinstance(text, str) or not text.strip() or len(text.strip()) > MAX_TEXT_LENGTH:
			frappe.throw(f"Quick Order text must contain between 1 and {MAX_TEXT_LENGTH} characters")
		doc = frappe.get_doc({"doctype": "Quick Order Request", "customer": identity["customer"],
			"order_source": "Sales Employee" if identity["sales_employee"] else "Customer",
			"sales_employee": identity["sales_employee"],
			"text": text.strip(), "status": "Pending Review"})
		doc.flags.in_quick_order_customer_submit = True
		doc.insert(ignore_permissions=True)
		response = create_success_response("Quick Order Request submitted", _serialize(doc), status_code=201)
		frappe.db.release_savepoint(savepoint)
		return response
	except Exception as error:
		frappe.db.rollback(save_point=savepoint)
		return handle_error_response(error, "Unable to submit Quick Order Request")


@frappe.whitelist(allow_guest=True, methods=["GET"])
def history(limit=20, offset=0, customer=None, headers=None, sales_employee=None):
	try:
		identity, error = _mobile_identity(customer, headers, sales_employee, allow_all_customers=True)
		if error:
			return error
		limit = min(max(cint(limit) or 20, 1), 100)
		offset = max(cint(offset), 0)
		filters = _history_filters(identity)
		rows = frappe.get_all("Quick Order Request", filters=filters,
			fields=["name", "customer", "order_source", "sales_employee", "status", "text", "confirmation_datetime", "order", "portal_reference_number", "rejection_reason"],
			order_by="confirmation_datetime desc, name desc", limit_start=offset, limit_page_length=limit + 1)
		has_more = len(rows) > limit
		return create_success_response("Quick Order Request history", {
			"requests": [_serialize(row) for row in rows[:limit]], "has_more": has_more,
			"next_offset": offset + limit if has_more else None,
		})
	except Exception as error:
		return handle_error_response(error, "Unable to load Quick Order Request history")


@frappe.whitelist(allow_guest=True, methods=["GET"])
def detail(request, customer=None, headers=None, sales_employee=None):
	try:
		identity, error = _mobile_identity(customer, headers, sales_employee, allow_all_customers=True)
		if error:
			return error
		doc = frappe.get_doc("Quick Order Request", request)
		if (identity["customer"] and doc.customer != identity["customer"]) or (identity["sales_employee"] and doc.sales_employee != identity["sales_employee"]):
			frappe.throw("This Quick Order Request belongs to another Customer", frappe.PermissionError)
		if identity["sales_employee"]:
			resolve_product_access(doc.customer, identity["sales_employee"])
		return create_success_response("Quick Order Request detail", _serialize(doc))
	except Exception as error:
		return handle_error_response(error, "Unable to load Quick Order Request")


@frappe.whitelist(methods=["POST"])
def start_review(request):
	savepoint = "quick_order_review"
	frappe.db.savepoint(savepoint)
	try:
		_require_reviewer()
		doc = frappe.get_doc("Quick Order Request", request, for_update=True)
		if doc.status != "Pending Review":
			frappe.throw("Only Pending Review requests can start review")
		doc.status = "In Review"
		doc.reviewed_by = frappe.session.user
		doc.review_started_at = now_datetime()
		doc.flags.in_quick_order_transition = True
		doc.save(ignore_permissions=True)
		response = create_success_response("Quick Order review started", _serialize(doc))
		frappe.db.release_savepoint(savepoint)
		return response
	except Exception as error:
		frappe.db.rollback(save_point=savepoint)
		return handle_error_response(error, "Unable to start Quick Order review")


@frappe.whitelist(methods=["POST"])
def reject(request, reason):
	savepoint = "quick_order_reject"
	frappe.db.savepoint(savepoint)
	try:
		_require_reviewer()
		doc = frappe.get_doc("Quick Order Request", request, for_update=True)
		if doc.status not in {"Pending Review", "In Review"}:
			frappe.throw("Only pending or in-review requests can be rejected")
		if not isinstance(reason, str) or not reason.strip():
			frappe.throw("Rejection reason is required")
		doc.rejection_reason = reason.strip()
		doc.reviewed_by = frappe.session.user
		doc.status = "Rejected"
		doc.flags.in_quick_order_transition = True
		doc.save(ignore_permissions=True)
		response = create_success_response("Quick Order Request rejected", _serialize(doc))
		frappe.db.release_savepoint(savepoint)
		return response
	except Exception as error:
		frappe.db.rollback(save_point=savepoint)
		return handle_error_response(error, "Unable to reject Quick Order Request")


@frappe.whitelist(methods=["POST"])
def convert(request, allocations=None):
	savepoint = "quick_order_convert"
	frappe.db.savepoint(savepoint)
	try:
		_require_reviewer()
		doc = frappe.get_doc("Quick Order Request", request, for_update=True)
		if doc.status == "Converted to Order" and doc.order:
			response = create_success_response("Quick Order Request already converted", _serialize(doc))
			frappe.db.release_savepoint(savepoint)
			return response
		if doc.status != "In Review" or doc.order:
			frappe.throw("Only In Review requests without an Order can be converted")
		if allocations is None:
			allocations = [{"item": row.item, "quantity": row.quantity, "godown": row.godown} for row in doc.items]
		order = submit_order(doc.customer, allocations, sales_employee=doc.sales_employee)
		order.quick_order_request = doc.name
		order.flags.in_quick_order_conversion = True
		order.save(ignore_permissions=True)
		item_names = {row.item: row.item_name_at_order for row in order.items}
		doc.set("items", [{"item": row.item, "item_name": item_names[row.item], "quantity": row.requested_quantity, "godown": row.godown}
			for row in order.godown_allocations])
		doc.order = order.name
		doc.portal_reference_number = order.portal_reference_number
		doc.status = "Converted to Order"
		doc.reviewed_by = frappe.session.user
		doc.flags.in_quick_order_transition = True
		doc.flags.in_quick_order_conversion = True
		doc.save(ignore_permissions=True)
		response = create_success_response("Quick Order Request converted to Order", _serialize(doc))
		frappe.db.release_savepoint(savepoint)
		return response
	except Exception as error:
		frappe.db.rollback(save_point=savepoint)
		return handle_error_response(error, "Unable to convert Quick Order Request")


@frappe.whitelist(methods=["GET"])
def reviewer_options(request, search="", limit=60, offset=0):
	try:
		_require_reviewer()
		doc = frappe.get_doc("Quick Order Request", request)
		access = resolve_product_access(doc.customer, doc.sales_employee)
		limit = min(max(cint(limit) or 60, 1), 60)
		offset = max(cint(offset), 0)
		items = _load_mobile_item_page(access, search=str(search or "").strip(), limit=limit, offset=offset)
		items = [row for row in items if item_is_allowed(row, access)]
		return create_success_response("Quick Order review options", {
			"items": items[:limit], "has_more": len(items) > limit,
			"next_offset": offset + limit if len(items) > limit else None,
			"godowns": frappe.get_all("Tally Godown", filters={"is_active": 1},
				fields=["name", "godown_name"], order_by="godown_name asc, name asc"),
		})
	except Exception as error:
		return handle_error_response(error, "Unable to load Quick Order review options")


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def allowed_item_query(doctype, txt, searchfield, start, page_len, filters):
	_require_reviewer()
	filters = frappe.parse_json(filters) or {}
	doc = frappe.get_doc("Quick Order Request", filters.get("quick_order_request"))
	access = resolve_product_access(doc.customer, doc.sales_employee)
	limit = min(max(cint(page_len), 1), 60)
	rows = _load_mobile_item_page(access, search=txt or "", limit=limit, offset=max(cint(start), 0))
	return [[row.name, row.item_name] for row in rows[:limit] if item_is_allowed(row, access)]


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def allowed_godown_query(doctype, txt, searchfield, start, page_len, filters):
	_require_reviewer()
	filters = frappe.parse_json(filters) or {}
	frappe.get_doc("Quick Order Request", filters.get("quick_order_request"))
	rows = frappe.get_all("Tally Godown", filters={"is_active": 1, "godown_name": ("like", f"%{txt or ''}%")},
		fields=["name", "godown_name"], limit_start=max(cint(start), 0),
		limit_page_length=min(max(cint(page_len), 1), 60), order_by="godown_name asc, name asc")
	return [[row.name, row.godown_name] for row in rows]
