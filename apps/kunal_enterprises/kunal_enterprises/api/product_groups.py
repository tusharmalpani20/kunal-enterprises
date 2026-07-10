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
			fields=[
				"name",
				"item_name",
				"immediate_stock_group",
				"root_stock_group",
				"uom",
				"total_closing_balance",
			],
			order_by="item_name asc",
		)
		_apply_godown_stock_totals(item_rows)
		_apply_mobile_summary_groups(item_rows)

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
		fields=["name", "group_name", "full_path", "product_group_logo"],
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


def _apply_mobile_summary_groups(item_rows):
	group_names = {
		group
		for item in item_rows
		for group in (item.get("immediate_stock_group"), item.get("root_stock_group"))
		if group
	}
	groups_by_name = _load_group_ancestors(group_names)

	for item in item_rows:
		summary_group = _nearest_mobile_summary_group(
			item.get("immediate_stock_group") or item.get("root_stock_group"),
			item.get("root_stock_group"),
			groups_by_name,
		)
		item["mobile_summary_group"] = summary_group.get("name") if summary_group else item.get("root_stock_group")
		item["mobile_summary_group_name"] = (
			summary_group.get("group_name") if summary_group else item.get("root_stock_group")
		)
		item["mobile_summary_group_logo"] = summary_group.get("product_group_logo") if summary_group else None


def _load_group_ancestors(group_names):
	pending = {name for name in group_names if name}
	groups_by_name = {}

	while pending:
		rows = frappe.get_all(
			"Tally Stock Group",
			filters={"name": ("in", tuple(pending))},
			fields=[
				"name",
				"group_name",
				"parent_stock_group",
				"root_stock_group",
				"product_group_logo",
				"show_as_mobile_summary_group",
			],
		)
		pending = set()
		for row in rows:
			groups_by_name[row["name"]] = row
			parent = row.get("parent_stock_group")
			if parent and parent not in groups_by_name:
				pending.add(parent)

	return groups_by_name


def _nearest_mobile_summary_group(start_group, root_group, groups_by_name):
	current = start_group
	visited = set()

	while current and current not in visited:
		visited.add(current)
		group = groups_by_name.get(current)
		if not group:
			break
		if group.get("show_as_mobile_summary_group"):
			return group
		current = group.get("parent_stock_group")

	return groups_by_name.get(root_group)


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
