import frappe

from kunal_enterprises.api.token_verification import verify_token
from kunal_enterprises.api.utils import create_success_response, handle_error_response


CUSTOMER_EDITABLE_FIELDS = ["email_id", "date_of_birth", "date_of_anniversary"]


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_profile(identity_type, identity, headers=None):
	try:
		token_error = _validate_profile_token(identity_type, identity, headers)
		if token_error:
			return token_error
		if identity_type == "Customer":
			return create_success_response("Customer profile", _serialize_customer_profile(identity))
		if identity_type == "Sales Employee":
			return create_success_response("Sales Employee profile", _serialize_sales_employee_profile(identity))
		frappe.throw("Unsupported profile identity type")
	except Exception as error:
		return handle_error_response(error, "Unable to load profile")


@frappe.whitelist(allow_guest=True, methods=["POST"])
def update_customer_profile(customer, payload, headers=None):
	try:
		token_error = _validate_profile_token("Customer", customer, headers)
		if token_error:
			return token_error
		payload = frappe.parse_json(payload) or {}
		customer_doc = frappe.get_doc("Customer", customer)
		_validate_customer_profile_access(customer_doc)
		for fieldname in CUSTOMER_EDITABLE_FIELDS:
			if fieldname in payload:
				customer_doc.set(fieldname, payload.get(fieldname))
		customer_doc.save(ignore_permissions=True)
		return create_success_response("Customer profile updated", _serialize_customer_profile(customer_doc.name))
	except Exception as error:
		return handle_error_response(error, "Unable to update Customer profile")


def _serialize_customer_profile(customer):
	customer_doc = frappe.get_doc("Customer", customer)
	_validate_customer_profile_access(customer_doc)
	return {
		"identity_type": "Customer",
		"customer": customer_doc.name,
		"customer_name": customer_doc.customer_name,
		"business_legal_name": customer_doc.business_legal_name,
		"gstin": customer_doc.gstin,
		"mobile_number": customer_doc.mobile_number,
		"email_id": customer_doc.email_id,
		"date_of_birth": customer_doc.date_of_birth,
		"date_of_anniversary": customer_doc.date_of_anniversary,
		"status": customer_doc.status,
		"customer_app_access": bool(customer_doc.customer_app_access),
		"editable_fields": CUSTOMER_EDITABLE_FIELDS,
	}


def _serialize_sales_employee_profile(sales_employee):
	sales_employee_doc = frappe.get_doc("Sales Employee", sales_employee)
	_validate_sales_employee_profile_access(sales_employee_doc)
	return {
		"identity_type": "Sales Employee",
		"sales_employee": sales_employee_doc.name,
		"sales_employee_name": sales_employee_doc.sales_employee_name,
		"mobile_number": sales_employee_doc.mobile_number,
		"email_id": sales_employee_doc.email_id,
		"employee_code": sales_employee_doc.employee_code,
		"status": sales_employee_doc.status,
		"editable_fields": [],
	}


def _validate_customer_profile_access(customer):
	if not customer.customer_app_access:
		frappe.throw("Customer App Access is not active", title="Customer App Access Required")


def _validate_sales_employee_profile_access(sales_employee):
	if sales_employee.status != "Active":
		frappe.throw("Sales Employee is disabled", title="Sales Employee Access Required")


def _validate_profile_token(identity_type, identity, headers=None):
	resolved_headers = _resolve_headers(headers)
	if resolved_headers is None:
		return None

	is_valid, result = verify_token(resolved_headers)
	if not is_valid:
		return result

	if result["identity_type"] != identity_type or result["identity"] != identity:
		frappe.throw(f"Profile token identity does not match {identity_type}", title="Token Identity Mismatch")

	return None


def _resolve_headers(headers=None):
	if headers is not None:
		return headers

	request = getattr(frappe.local, "request", None)
	if request and getattr(request, "headers", None):
		return request.headers
	return None
