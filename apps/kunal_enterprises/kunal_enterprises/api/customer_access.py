import frappe

from kunal_enterprises.api.token_verification import verify_token
from kunal_enterprises.api.utils import create_success_response, handle_error_response
from kunal_enterprises.kunal_enterprises.doctype.customer.customer import get_access_status


@frappe.whitelist(allow_guest=True, methods=["GET"])
def status(customer, headers=None):
	try:
		token_error = _validate_customer_token(customer, headers)
		if token_error:
			return token_error
		return create_success_response(
			"Customer App Access status",
			get_access_status(customer),
		)
	except Exception as error:
		return handle_error_response(error, "Unable to load Customer App Access status")


def _validate_customer_token(customer, headers=None):
	resolved_headers = _resolve_headers(headers)
	if resolved_headers is None:
		return None

	is_valid, result = verify_token(resolved_headers)
	if not is_valid:
		return result

	if result["identity_type"] != "Customer" or result["identity"] != customer:
		frappe.throw("Customer App Access token identity does not match Customer", title="Token Identity Mismatch")

	return None


def _resolve_headers(headers=None):
	if headers is not None:
		return headers

	request = getattr(frappe.local, "request", None)
	if request and getattr(request, "headers", None):
		return request.headers
	return None
