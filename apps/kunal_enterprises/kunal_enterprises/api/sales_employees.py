import frappe

from kunal_enterprises.api.token_verification import verify_token
from kunal_enterprises.api.utils import create_success_response, handle_error_response
from kunal_enterprises.kunal_enterprises.doctype.customer.customer import get_customer_access_checklist


@frappe.whitelist(allow_guest=True, methods=["GET"])
def allowed_customers(sales_employee, search=None, headers=None):
	try:
		token_error = _validate_sales_employee_token(sales_employee, headers)
		if token_error:
			return token_error
		sales_employee_doc = frappe.get_doc("Sales Employee", sales_employee)
		if sales_employee_doc.status != "Active":
			frappe.throw("Sales Employee is disabled", title="Sales Employee Access Required")

		customers = get_allowed_customers(sales_employee_doc, search)
		return create_success_response(
			"Allowed Customers",
			{
				"sales_employee": sales_employee,
				"customers": customers,
			},
		)
	except Exception as error:
		return handle_error_response(error, "Unable to load allowed Customers")


def get_allowed_customers(sales_employee, search=None):
	assigned_customers = [row.customer for row in sales_employee.assigned_customers if row.customer]
	filters = {
		"status": "Active",
	}
	if assigned_customers:
		filters["name"] = ("in", assigned_customers)

	customer_names = frappe.get_all(
		"Customer",
		filters=filters,
		pluck="name",
		order_by="customer_name asc",
	)

	search_text = (search or "").strip().lower()
	customers = []
	for customer_name in customer_names:
		customer = frappe.get_doc("Customer", customer_name)
		if not all(get_customer_access_checklist(customer).values()):
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
