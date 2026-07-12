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
		access = resolve_product_access(customer, sales_employee)
		if product_group not in access["visible_root_names"]:
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
			"is_active",
		],
			order_by="item_name asc",
		)
		item_rows = [row for row in item_rows if item_is_allowed(row, access)]
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
		access = resolve_product_access(customer, sales_employee)
		if not item_is_allowed(item_doc, access):
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

	if sales_employee_name:
		sales_employee = frappe.get_doc("Sales Employee", sales_employee_name)
		_validate_sales_employee_can_order_for_customer(sales_employee, customer.name)

	access = resolve_product_access(customer_name, sales_employee_name)
	allowed_names = access["visible_root_names"]
	if not allowed_names:
		return []

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


def resolve_product_access(customer_name, sales_employee_name=None):
	"""Return the effective hierarchy scope for a Customer/mobile ordering context."""
	customer = frappe.get_doc("Customer", customer_name)
	_validate_customer_can_order(customer)
	groups = _load_product_group_hierarchy()
	customer_grants = _group_grants(customer.product_group_access)
	customer_scope, customer_diagnostics = _expand_group_scope(
		customer_grants,
		groups,
		default_all=not customer_grants,
	)

	employee_scope = None
	employee_grants = None
	employee_diagnostics = []
	if sales_employee_name:
		sales_employee = frappe.get_doc("Sales Employee", sales_employee_name)
		_validate_sales_employee_can_order_for_customer(sales_employee, customer.name)
		employee_grants = _group_grants(sales_employee.product_group_access)
		if employee_grants:
			employee_scope, employee_diagnostics = _expand_group_scope(
				employee_grants,
				groups,
				default_all=False,
			)

	effective_scope = customer_scope if employee_scope is None else customer_scope.intersection(employee_scope)
	visible_root_names = _visible_root_names(effective_scope, groups)
	return {
		"groups": groups,
		"customer_grants": customer_grants,
		"employee_grants": employee_grants,
		"effective_group_names": effective_scope,
		"visible_root_names": visible_root_names,
		"diagnostics": customer_diagnostics + employee_diagnostics,
	}


def item_is_allowed(item, access):
	"""Check an item against a previously resolved product access scope."""
	if not item.get("is_active"):
		return False
	path = _active_group_path(
		item.get("immediate_stock_group") or item.get("root_stock_group"),
		access["groups"],
	)
	if not path or path[0] != item.get("root_stock_group"):
		return False
	return bool(set(path).intersection(access["effective_group_names"]))


def _load_product_group_hierarchy():
	return {
		row["name"]: row
		for row in frappe.get_all(
			"Tally Stock Group",
			fields=["name", "parent_stock_group", "root_stock_group", "is_root", "is_active"],
		)
	}


def _group_grants(rows):
	return {row.product_group for row in rows if row.product_group}


def _expand_group_scope(grants, groups, default_all=False):
	diagnostics = []
	if not grants:
		return (
			{name for name, group in groups.items() if group.is_active} if default_all else set(),
			diagnostics,
		)

	scope = set()
	for grant in grants:
		if grant not in groups or not groups[grant].is_active:
			diagnostics.append(f"Invalid or inactive Product Group grant: {grant}")
			continue
		for name in groups:
			path = _active_group_path(name, groups)
			if path and grant in path:
				scope.add(name)
	return scope, diagnostics


def _visible_root_names(scope, groups):
	roots = set()
	for name in scope:
		path = _active_group_path(name, groups)
		if path:
			root = groups.get(path[0])
			if root and root.is_root and root.is_active:
				roots.add(path[0])
	return sorted(roots)


def _active_group_path(start_group, groups, max_depth=100):
	if not start_group:
		return None
	path = []
	visited = set()
	current = start_group
	while current:
		if current in visited or len(path) >= max_depth:
			return None
		visited.add(current)
		group = groups.get(current)
		if not group or not group.is_active:
			return None
		path.append(current)
		current = group.parent_stock_group

	path.reverse()
	root = groups.get(path[0])
	if not root or not root.is_root:
		return None
	return path


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
