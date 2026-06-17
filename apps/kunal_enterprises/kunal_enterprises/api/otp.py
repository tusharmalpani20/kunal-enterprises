import json
import secrets

import frappe
from frappe import _
from frappe.utils import cint, now_datetime, time_diff_in_seconds

from kunal_enterprises.api.token_verification import issue_token
from kunal_enterprises.api.utils import create_success_response, handle_error_response

OTP_COOLDOWN_SECONDS = 45
OTP_EXPIRY_SECONDS = 300
OTP_PURPOSES = {
	"Customer": "Customer Signup",
	"Sales Employee": "Sales Employee Login",
}
OTP_TYPES = {
	"Customer Signup": "Account Creation",
	"Customer Verification": "Account Verification",
	"Sales Employee Login": "Login",
}


@frappe.whitelist(allow_guest=True)
def start_customer_signup(payload):
	try:
		payload = frappe.parse_json(payload) or {}
		mobile_number = (payload.get("mobile_number") or "").strip()
		if not mobile_number:
			frappe.throw(_("Mobile Number is required"))

		sales_employee = frappe.db.exists("Sales Employee", {"mobile_number": mobile_number})
		if sales_employee:
			frappe.throw(
				_("This mobile number is already in use"),
				title=_("Duplicate Mobile Login Identity"),
			)

		rejected_customer = frappe.db.exists(
			"Customer",
			{
				"mobile_number": mobile_number,
				"status": "Rejected",
			},
		)
		if rejected_customer:
			frappe.throw(
				_("This mobile number is not available for signup"),
				title=_("Rejected Customer Exists"),
			)

		existing_customer = frappe.db.exists("Customer", {"mobile_number": mobile_number})
		if existing_customer:
			frappe.throw(
				_("This mobile number is already in use"),
				title=_("Duplicate Customer"),
			)

		pending_payload = _pending_customer_payload(payload, mobile_number)
		_validate_pending_customer_payload(pending_payload)
		otp = _issue_otp(
			mobile_number,
			"Customer Signup",
			otp_type="Account Creation",
			pending_payload=pending_payload,
		)

		return create_success_response(
			"Customer signup started",
			{
				"pending_otp": otp.name,
				"status": "Pending OTP",
				"next_step": "verify_otp",
				"cooldown_seconds": OTP_COOLDOWN_SECONDS,
				"expires_in_seconds": OTP_EXPIRY_SECONDS,
			},
			status_code=201,
		)
	except Exception as error:
		return handle_error_response(
			error,
			"Unable to start customer signup",
			status_code=409,
		)


@frappe.whitelist(allow_guest=True)
def send_otp(mobile_number, identity_type):
	try:
		mobile_number = (mobile_number or "").strip()
		purpose = _purpose_for_identity(identity_type)
		_validate_otp_identity(mobile_number, identity_type)
		otp_type = _otp_type_for_identity(mobile_number, identity_type, purpose)
		_issue_otp(mobile_number, purpose, otp_type=otp_type)

		return create_success_response("OTP sent", _otp_response(mobile_number, identity_type, purpose, otp_type))
	except Exception as error:
		return handle_error_response(
			error,
			"Unable to send OTP",
			status_code=400,
		)


@frappe.whitelist(allow_guest=True)
def resend_otp(mobile_number, identity_type):
	try:
		mobile_number = (mobile_number or "").strip()
		purpose = _purpose_for_identity(identity_type)
		_validate_otp_identity(mobile_number, identity_type)
		_wait_for_cooldown(mobile_number, purpose)
		otp_type = _otp_type_for_identity(mobile_number, identity_type, purpose)
		_issue_otp(mobile_number, purpose, otp_type=otp_type)

		return create_success_response("OTP resent", _otp_response(mobile_number, identity_type, purpose, otp_type))
	except Exception as error:
		return handle_error_response(
			error,
			"Unable to resend OTP",
			status_code=429,
		)


@frappe.whitelist(allow_guest=True)
def verify_customer_otp(mobile_number, otp_code):
	try:
		mobile_number = (mobile_number or "").strip()
		otp_code = (otp_code or "").strip()
		if not mobile_number or not otp_code:
			frappe.throw(_("Mobile Number and OTP Code are required"))

		otp_name = frappe.db.exists(
			"Mobile OTP",
			{
				"mobile_number": mobile_number,
				"otp_code": otp_code,
				"purpose": "Customer Signup",
				"status": "Open",
			},
		)
		if not otp_name:
			frappe.throw(_("Invalid or expired OTP Code"))

		otp = frappe.get_doc("Mobile OTP", otp_name)
		now = now_datetime()
		customer_name = frappe.db.exists("Customer", {"mobile_number": mobile_number})
		if customer_name:
			customer = frappe.get_doc("Customer", customer_name)
		else:
			customer = _create_customer_from_pending_otp(otp, now)
		customer.mobile_verified = 1
		customer.mobile_verified_at = now
		if customer.status == "Pending OTP":
			customer.status = "Pending Admin Review"
		customer.save(ignore_permissions=True)

		data = {
			"customer": customer.name,
			"status": customer.status,
			"customer_app_access": bool(customer.customer_app_access),
		}
		if customer.customer_app_access:
			data.update(issue_token("Customer", customer.name))

		_mark_otp_verified(otp_name, now)
		return create_success_response("Customer mobile number verified", data)
	except Exception as error:
		return handle_error_response(
			error,
			"Unable to verify customer OTP",
			status_code=401,
		)


@frappe.whitelist(allow_guest=True)
def verify_sales_employee_otp(mobile_number, otp_code):
	try:
		mobile_number = (mobile_number or "").strip()
		otp_code = (otp_code or "").strip()
		if not mobile_number or not otp_code:
			frappe.throw(_("Mobile Number and OTP Code are required"))

		sales_employee_name = frappe.db.exists("Sales Employee", {"mobile_number": mobile_number})
		if not sales_employee_name:
			frappe.throw(_("Sales Employee was not found for this mobile number"))

		sales_employee = frappe.get_doc("Sales Employee", sales_employee_name)
		if sales_employee.status != "Active":
			frappe.throw(_("Disabled Sales Employee cannot log in"))

		otp_name = frappe.db.exists(
			"Mobile OTP",
			{
				"mobile_number": mobile_number,
				"otp_code": otp_code,
				"purpose": "Sales Employee Login",
				"status": "Open",
			},
		)
		if not otp_name:
			frappe.throw(_("Invalid or expired OTP Code"))

		now = now_datetime()
		was_mobile_verified = bool(sales_employee.mobile_verified)
		sales_employee.mobile_verified = 1
		sales_employee.mobile_verified_at = now
		sales_employee.save(ignore_permissions=True)

		data = {
			"sales_employee": sales_employee.name,
			"status": sales_employee.status,
			"mobile_verified": True,
			"verification_completed": not was_mobile_verified,
		}
		data.update(issue_token("Sales Employee", sales_employee.name))

		_mark_otp_verified(otp_name, now)
		return create_success_response("Sales Employee mobile number verified", data)
	except Exception as error:
		return handle_error_response(
			error,
			"Unable to verify sales employee OTP",
			status_code=401,
		)


def _otp_response(mobile_number, identity_type, purpose, otp_type=None):
	otp_type = otp_type or _otp_type_for_identity(mobile_number, identity_type, purpose)
	return {
		"mobile_number": mobile_number,
		"identity_type": identity_type,
		"purpose": purpose,
		"otp_type": otp_type,
		"mobile_verification_required": otp_type == "Account Verification",
		"cooldown_seconds": OTP_COOLDOWN_SECONDS,
		"expires_in_seconds": OTP_EXPIRY_SECONDS,
		"next_step": "verify_otp",
	}


def _purpose_for_identity(identity_type):
	identity_type = (identity_type or "").strip()
	if identity_type not in OTP_PURPOSES:
		frappe.throw(_("Unsupported OTP identity type"))
	return OTP_PURPOSES[identity_type]


def _validate_otp_identity(mobile_number, identity_type):
	if not mobile_number:
		frappe.throw(_("Mobile Number is required"))

	if identity_type == "Customer":
		customer_name = frappe.db.exists("Customer", {"mobile_number": mobile_number})
		if not customer_name:
			if not frappe.db.exists(
				"Mobile OTP",
				{
					"mobile_number": mobile_number,
					"purpose": "Customer Signup",
					"otp_type": "Account Creation",
					"status": "Open",
				},
			):
				frappe.throw(_("Customer was not found for this mobile number"))
			return
		customer = frappe.get_doc("Customer", customer_name)
		if customer.status in ("Rejected", "Disabled"):
			frappe.throw(_("Customer cannot receive OTP in current status"))
		return

	if identity_type == "Sales Employee":
		sales_employee_name = frappe.db.exists("Sales Employee", {"mobile_number": mobile_number})
		if not sales_employee_name:
			frappe.throw(_("Sales Employee was not found for this mobile number"))
		sales_employee = frappe.get_doc("Sales Employee", sales_employee_name)
		if sales_employee.status != "Active":
			frappe.throw(_("Disabled Sales Employee cannot log in"))
		return

	frappe.throw(_("Unsupported OTP identity type"))


def _wait_for_cooldown(mobile_number, purpose):
	open_otp = frappe.db.get_value(
		"Mobile OTP",
		{
			"mobile_number": mobile_number,
			"purpose": purpose,
			"status": "Open",
		},
		["name", "modified"],
		as_dict=True,
		order_by="modified desc",
	)
	if not open_otp:
		return

	elapsed_seconds = cint(time_diff_in_seconds(now_datetime(), open_otp.modified))
	if elapsed_seconds < OTP_COOLDOWN_SECONDS:
		remaining_seconds = OTP_COOLDOWN_SECONDS - elapsed_seconds
		frappe.throw(_("Please wait {0} seconds before requesting another OTP").format(remaining_seconds))


def _issue_otp(mobile_number, purpose, otp_type=None, pending_payload=None):
	if pending_payload is None:
		pending_payload = _latest_open_pending_payload(mobile_number, purpose)

	for otp_name in frappe.get_all(
		"Mobile OTP",
		filters={
			"mobile_number": mobile_number,
			"purpose": purpose,
			"status": "Open",
		},
		pluck="name",
	):
		frappe.db.set_value("Mobile OTP", otp_name, "status", "Expired")

	otp_code = f"{secrets.randbelow(10000):04d}"
	otp_type = otp_type or _otp_type_for_purpose(purpose)
	return frappe.get_doc(
		{
			"doctype": "Mobile OTP",
			"mobile_number": mobile_number,
			"otp_code": otp_code,
			"purpose": purpose,
			"otp_type": otp_type,
			"status": "Open",
			"provider": "frappe_whatsapp",
			"provider_status": "Queued",
			"request_payload": json.dumps(
				{
					"event": "Mobile OTP",
					"purpose": purpose,
					"otp_type": otp_type,
					"mobile_number": mobile_number,
					"otp_code": otp_code,
				},
				sort_keys=True,
			),
			"pending_payload": json.dumps(pending_payload, sort_keys=True) if pending_payload else None,
			"provider_response": json.dumps(
				{
					"provider": "frappe_whatsapp",
					"status": "Queued",
					"retry_count": 0,
					"message": "Queued for WhatsApp OTP dispatch",
				},
				sort_keys=True,
			),
		}
	).insert(ignore_permissions=True)


def _otp_type_for_purpose(purpose):
	return OTP_TYPES.get(purpose, "Account Verification")


def _otp_type_for_identity(mobile_number, identity_type, purpose):
	if identity_type == "Sales Employee":
		sales_employee_name = frappe.db.exists("Sales Employee", {"mobile_number": mobile_number})
		if sales_employee_name and not frappe.db.get_value("Sales Employee", sales_employee_name, "mobile_verified"):
			return "Account Verification"
		return "Login"
	if identity_type == "Customer" and frappe.db.exists("Customer", {"mobile_number": mobile_number}):
		return "Account Verification"
	return _otp_type_for_purpose(purpose)


def _pending_customer_payload(payload, mobile_number):
	return {
		"customer_name": (payload.get("customer_name") or "").strip(),
		"business_legal_name": (payload.get("business_legal_name") or "").strip(),
		"gstin": (payload.get("gstin") or "").strip().upper(),
		"mobile_number": mobile_number,
		"email_id": (payload.get("email_id") or "").strip().lower(),
		"date_of_birth": payload.get("date_of_birth"),
		"date_of_anniversary": payload.get("date_of_anniversary"),
	}


def _validate_pending_customer_payload(pending_payload):
	for fieldname, label in (("email_id", _("Email ID")), ("gstin", _("GSTIN"))):
		value = pending_payload.get(fieldname)
		if not value:
			continue

		duplicate_customer = frappe.db.exists("Customer", {fieldname: value})
		if duplicate_customer:
			frappe.throw(
				_("{0} is already in use").format(label),
				title=_("Duplicate Customer Identity"),
			)


def _latest_open_pending_payload(mobile_number, purpose):
	latest_open_otp = frappe.db.get_value(
		"Mobile OTP",
		{
			"mobile_number": mobile_number,
			"purpose": purpose,
			"status": "Open",
		},
		"pending_payload",
		order_by="modified desc",
	)
	if latest_open_otp:
		return frappe.parse_json(latest_open_otp)
	return None


def _create_customer_from_pending_otp(otp, verified_at):
	if otp.otp_type != "Account Creation":
		frappe.throw(_("Customer was not found for this mobile number"))
	if not otp.pending_payload:
		frappe.throw(_("Customer signup details were not found for this OTP"))

	pending_payload = frappe.parse_json(otp.pending_payload)
	customer = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": pending_payload.get("customer_name"),
			"business_legal_name": pending_payload.get("business_legal_name"),
			"gstin": pending_payload.get("gstin"),
			"mobile_number": pending_payload.get("mobile_number"),
			"email_id": pending_payload.get("email_id"),
			"date_of_birth": pending_payload.get("date_of_birth"),
			"date_of_anniversary": pending_payload.get("date_of_anniversary"),
			"status": "Pending Admin Review",
			"mobile_verified": 1,
			"mobile_verified_at": verified_at,
			"admin_approved": 0,
		}
	)
	return customer.insert(ignore_permissions=True)


def _mark_otp_verified(otp_name, verified_at):
	frappe.db.set_value(
		"Mobile OTP",
		otp_name,
		{
			"status": "Verified",
			"verified_at": verified_at,
		},
	)
