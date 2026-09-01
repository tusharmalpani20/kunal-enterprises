import frappe

from kunal_enterprises.api.token_verification import verify_token
from kunal_enterprises.api.utils import create_success_response, handle_error_response
from kunal_enterprises.kunal_enterprises.doctype.customer.customer import (
	configured_tally_customer_parent_groups,
	get_active_tally_client_codes,
)


CUSTOMER_SEARCH_RESULT_LIMIT = 60


@frappe.whitelist(allow_guest=True, methods=["GET"])
def allowed_customers(sales_employee, search=None, headers=None, limit=CUSTOMER_SEARCH_RESULT_LIMIT):
	try:
		token_error = _validate_sales_employee_token(sales_employee, headers)
		if token_error:
			return token_error
		sales_employee_doc = frappe.get_doc("Sales Employee", sales_employee)
		if sales_employee_doc.status != "Active":
			frappe.throw("Sales Employee is disabled", title="Sales Employee Access Required")

		customers = get_allowed_customers(sales_employee_doc, search, limit=limit)
		return create_success_response(
			"Allowed Customers",
			{
				"sales_employee": sales_employee,
				"customers": customers,
			},
		)
	except Exception as error:
		return handle_error_response(error, "Unable to load allowed Customers")


def get_allowed_customers(sales_employee, search=None, limit=CUSTOMER_SEARCH_RESULT_LIMIT):
	assigned_customers = [row.customer for row in sales_employee.assigned_customers if row.customer]
	filters = {
		"status": "Active",
	}
	if assigned_customers:
		filters["name"] = ("in", assigned_customers)

	search_text = (search or "").strip()
	query_args = {
		"filters": filters,
		"fields": [
			"name",
			"customer_name",
			"business_legal_name",
			"client_code",
			"customer_app_access",
			"sales_employee_order_access",
			"admin_approved",
			"onboarding_source",
		],
		"order_by": "customer_name asc",
		"limit_start": 0,
		"limit_page_length": _coerce_customer_limit(limit),
	}
	if search_text:
		like_search = f"%{search_text}%"
		query_args["or_filters"] = [
			["Customer", "name", "like", like_search],
			["Customer", "customer_name", "like", like_search],
			["Customer", "business_legal_name", "like", like_search],
			["Customer", "client_code", "like", like_search],
		]

	customer_rows = frappe.get_all("Customer", **query_args)
	client_codes = {row.client_code for row in customer_rows if row.client_code}
	active_client_codes = get_active_tally_client_codes(client_codes)
	tally_customer_codes = {
		row.client_code for row in customer_rows if row.client_code and row.onboarding_source == "Tally"
	}
	active_tally_customer_codes = get_active_tally_client_codes(
		tally_customer_codes,
		parent_groups=configured_tally_customer_parent_groups(),
	)

	search_text = search_text.lower()
	customers = []
	for customer in customer_rows:
		active_code_set = (
			active_tally_customer_codes if customer.onboarding_source == "Tally" else active_client_codes
		)
		if not (
			(customer.sales_employee_order_access or customer.customer_app_access)
			and customer.admin_approved
			and customer.client_code in active_code_set
		):
			continue
		if search_text and not _customer_matches_search(customer, search_text):
			continue
		customers.append(
			{
				"customer": customer.name,
				"customer_name": customer.customer_name,
				"business_legal_name": customer.business_legal_name,
			}
		)

	return customers


def _coerce_customer_limit(limit):
	try:
		value = int(limit)
	except (TypeError, ValueError):
		value = CUSTOMER_SEARCH_RESULT_LIMIT
	return max(1, min(value, 100))


def _customer_matches_search(customer, search_text):
	return any(
		search_text in (value or "").lower()
		for value in (
			customer.name,
			customer.customer_name,
			customer.business_legal_name,
			customer.client_code,
		)
	)


def _validate_sales_employee_token(sales_employee, headers=None):
	resolved_headers = _resolve_headers(headers)
	if resolved_headers is None:
		return None

	is_valid, result = verify_token(resolved_headers)
	if not is_valid:
		return result

	if result["identity_type"] != "Sales Employee" or result["identity"] != sales_employee:
		frappe.throw("Allowed Customers token identity does not match Sales Employee", title="Token Identity Mismatch")

	return None


def _resolve_headers(headers=None):
	if headers is not None:
		return headers

	request = getattr(frappe.local, "request", None)
	if request and getattr(request, "headers", None):
		return request.headers
	return None
