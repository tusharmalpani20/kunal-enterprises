import frappe

from kunal_enterprises.api.token_verification import verify_token
from kunal_enterprises.api.utils import create_success_response, handle_error_response


@frappe.whitelist(allow_guest=True, methods=["GET"])
def allowed(customer, sales_employee=None, headers=None):
	try:
		token_error = _validate_product_token(customer, sales_employee, headers)
		if token_error:
			return token_error
		product_groups = get_allowed_product_groups(customer, sales_employee)
		return create_success_response(
			"Allowed Product Groups",
			{
				"customer": customer,
				"sales_employee": sales_employee,
				"product_groups": product_groups,
			},
		)
	except Exception as error:
		return handle_error_response(error, "Unable to load allowed Product Groups")


@frappe.whitelist(allow_guest=True, methods=["GET"])
def items(customer, product_group, sales_employee=None, headers=None):
	try:
		token_error = _validate_product_token(customer, sales_employee, headers)
		if token_error:
			return token_error
		allowed_group_names = {group["name"] for group in get_allowed_product_groups(customer, sales_employee)}
		if product_group not in allowed_group_names:
			frappe.throw("Product Group is not allowed", title="Product Group Access Required")

		item_rows = frappe.get_all(
			"Tally Item",
			filters={
				"root_stock_group": product_group,
				"is_active": 1,
			},
			fields=["name", "item_name", "root_stock_group", "uom", "total_closing_balance"],
			order_by="item_name asc",
		)
		_apply_godown_stock_totals(item_rows)

		return create_success_response(
			"Allowed Items",
			{
				"customer": customer,
				"sales_employee": sales_employee,
				"product_group": product_group,
				"items": item_rows,
			},
		)
	except Exception as error:
		return handle_error_response(error, "Unable to load allowed items")


@frappe.whitelist(allow_guest=True, methods=["GET"])
def item_stock(customer, item, sales_employee=None, headers=None):
	try:
		token_error = _validate_product_token(customer, sales_employee, headers)
		if token_error:
			return token_error
		item_doc = frappe.get_doc("Tally Item", item)
		allowed_group_names = {group["name"] for group in get_allowed_product_groups(customer, sales_employee)}
		if item_doc.root_stock_group not in allowed_group_names:
			frappe.throw("Item is not allowed", title="Item Access Required")

		snapshots = frappe.get_all(
			"Tally Stock Snapshot",
			filters={"item": item},
			fields=["name", "item", "godown", "quantity", "uom", "as_on_date", "synced_at"],
			order_by="godown asc",
		)
		return create_success_response(
			"Item stock by godown",
			{
				"customer": customer,
				"sales_employee": sales_employee,
				"item": item,
				"stock_is_advisory": True,
				"godowns": snapshots,
			},
		)
	except Exception as error:
		return handle_error_response(error, "Unable to load item stock by godown")


def get_allowed_product_groups(customer_name, sales_employee_name=None):
	customer = frappe.get_doc("Customer", customer_name)
	_validate_customer_can_order(customer)

	customer_groups = _child_product_groups(customer.product_group_access)
	employee_groups = None

	if sales_employee_name:
		sales_employee = frappe.get_doc("Sales Employee", sales_employee_name)
		_validate_sales_employee_can_order_for_customer(sales_employee, customer.name)
		employee_groups = _child_product_groups(sales_employee.product_group_access)

	allowed_names = _resolve_allowed_group_names(customer_groups, employee_groups)

	return frappe.get_all(
		"Tally Stock Group",
		filters={
			"name": ("in", allowed_names),
			"is_root": 1,
			"is_active": 1,
		},
		fields=["name", "group_name", "full_path"],
		order_by="group_name asc",
	)


def _apply_godown_stock_totals(item_rows):
	item_names = [row["name"] for row in item_rows]
	if not item_names:
		return

	snapshot_rows = frappe.get_all(
		"Tally Stock Snapshot",
		filters={"item": ("in", item_names)},
		fields=["item", "quantity"],
	)
	totals = {}
	for row in snapshot_rows:
		totals[row["item"]] = totals.get(row["item"], 0) + (row.get("quantity") or 0)

	for item in item_rows:
		if item["name"] in totals:
			item["total_closing_balance"] = totals[item["name"]]


def _validate_product_token(customer, sales_employee=None, headers=None):
	resolved_headers = _resolve_headers(headers)
	if resolved_headers is None:
		return None

	is_valid, result = verify_token(resolved_headers)
	if not is_valid:
		return result

	if sales_employee:
		if result["identity_type"] != "Sales Employee" or result["identity"] != sales_employee:
			frappe.throw("Product access token identity does not match Sales Employee", title="Token Identity Mismatch")
	elif result["identity_type"] != "Customer" or result["identity"] != customer:
		frappe.throw("Product access token identity does not match Customer", title="Token Identity Mismatch")

	return None


def _resolve_headers(headers=None):
	if headers is not None:
		return headers

	request = getattr(frappe.local, "request", None)
	if request and getattr(request, "headers", None):
		return request.headers
	return None


def _validate_customer_can_order(customer):
	if not customer.customer_app_access:
		frappe.throw("Customer App Access is not active", title="Customer App Access Required")


def _validate_sales_employee_can_order_for_customer(sales_employee, customer_name):
	if sales_employee.status != "Active":
		frappe.throw("Sales Employee is disabled", title="Sales Employee Access Required")

	assigned_customers = [row.customer for row in sales_employee.assigned_customers if row.customer]
	if assigned_customers and customer_name not in assigned_customers:
		frappe.throw("Sales Employee is not assigned to this Customer", title="Customer Assignment Required")


def _child_product_groups(rows):
	return {row.product_group for row in rows if row.product_group}


def _resolve_allowed_group_names(customer_groups, employee_groups=None):
	active_root_groups = set(
		frappe.get_all(
			"Tally Stock Group",
			filters={"is_root": 1, "is_active": 1},
			pluck="name",
		)
	)

	if customer_groups:
		allowed = active_root_groups.intersection(customer_groups)
	else:
		allowed = set(active_root_groups)

	if employee_groups is not None:
		if employee_groups:
			allowed = allowed.intersection(employee_groups)

	return sorted(allowed)
