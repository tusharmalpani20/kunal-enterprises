from datetime import timedelta

import frappe
import jwt
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime

from kunal_enterprises.kunal_enterprises.doctype.customer.customer import get_customer_access_checklist
from kunal_enterprises.api.utils import create_success_response, handle_error_response


TOKEN_EXPIRY_DAYS = 365


def issue_token(identity_type, identity):
	now = now_datetime()
	expires_at = add_to_date(now, days=TOKEN_EXPIRY_DAYS)
	token_doc = frappe.get_doc(
		{
			"doctype": "Mobile Auth Token",
			"identity_type": identity_type,
			"identity": identity,
			"status": "Active",
			"issued_at": now,
			"expires_at": expires_at,
		}
	).insert(ignore_permissions=True)
	access_token = jwt.encode(
		{
			"token_id": token_doc.name,
			"identity_type": identity_type,
			"identity": identity,
			"exp": get_datetime(expires_at) + timedelta(seconds=1),
		},
		_get_secret(),
		algorithm="HS256",
	)
	token_doc.access_token = access_token
	token_doc.save(ignore_permissions=True)
	return {
		"access_token": access_token,
		"token": token_doc.name,
		"identity_type": identity_type,
		"identity": identity,
		"expires_at": expires_at,
	}


@frappe.whitelist(allow_guest=True)
def current_session(headers=None):
	is_valid, result = verify_token(headers)
	if not is_valid:
		return result

	data = {
		"identity_type": result["identity_type"],
		"identity": result["identity"],
	}
	if result["identity_type"] == "Customer":
		data["customer"] = result["identity"]
	else:
		data["sales_employee"] = result["identity"]

	return create_success_response("Current mobile session loaded", data)


@frappe.whitelist(allow_guest=True)
def revoke_token(headers=None):
	is_valid, result = verify_token(headers)
	if not is_valid:
		return result

	token_doc = frappe.get_doc("Mobile Auth Token", result["token"])
	token_doc.status = "Revoked"
	token_doc.revoked_at = now_datetime()
	token_doc.save(ignore_permissions=True)

	return create_success_response(
		"Mobile token revoked",
		{
			"token": token_doc.name,
			"status": token_doc.status,
		},
	)


def verify_token(headers=None):
	try:
		access_token = _extract_bearer_token(headers)
		if not access_token:
			frappe.throw(_("Invalid or inactive token"))

		payload = jwt.decode(access_token, _get_secret(), algorithms=["HS256"])
		token_id = payload.get("token_id")
		if not token_id:
			frappe.throw(_("Invalid or inactive token"))

		token_doc = frappe.get_doc("Mobile Auth Token", token_id)
		if token_doc.status != "Active" or token_doc.access_token != access_token:
			frappe.throw(_("Invalid or inactive token"))

		if token_doc.expires_at and get_datetime(token_doc.expires_at) < now_datetime():
			token_doc.status = "Expired"
			token_doc.save(ignore_permissions=True)
			frappe.throw(_("Invalid or inactive token"))

		if not _identity_has_current_access(token_doc.identity_type, token_doc.identity):
			frappe.throw(_("Invalid or inactive token"))

		token_doc.last_verified_at = now_datetime()
		token_doc.save(ignore_permissions=True)
		return True, {
			"token": token_doc.name,
			"identity_type": token_doc.identity_type,
			"identity": token_doc.identity,
		}
	except Exception as error:
		return False, handle_error_response(
			error,
			"Invalid or inactive token",
			status_code=401,
		)


def _extract_bearer_token(headers):
	headers = _resolve_headers(headers)
	auth_header = headers.get("Auth-Token") or headers.get("Authorization") or ""
	if auth_header.startswith("Bearer "):
		return auth_header.removeprefix("Bearer ").strip()
	return auth_header.strip()


def _resolve_headers(headers=None):
	if headers is not None:
		return dict(headers or {})

	request = getattr(frappe.local, "request", None)
	if request and getattr(request, "headers", None):
		return dict(request.headers or {})
	return {}


def _identity_has_current_access(identity_type, identity):
	if identity_type == "Customer":
		customer = frappe.get_doc("Customer", identity)
		checklist = get_customer_access_checklist(customer)
		return all(checklist.values())
	if identity_type == "Sales Employee":
		sales_employee = frappe.get_doc("Sales Employee", identity)
		return sales_employee.status == "Active"
	return False


def _get_secret():
	return frappe.conf.get("encryption_key") or frappe.conf.get("secret_key") or "kunal-enterprises-dev-secret"
