"""Reviewer-only manual coverage and identity actions; no scheduled processing."""
import frappe
from frappe.utils import cint, get_datetime

from kunal_enterprises.api.quick_orders import _require_reviewer
from kunal_enterprises.integrations.order_intake_capture import capture_saved_message, refresh_sender_identity


def _require_access():
	_require_reviewer()
	if not frappe.has_permission("WhatsApp Message", "read"):
		frappe.throw("Read access to WhatsApp Message is required", frappe.PermissionError)


def _filters(account=None, since=None):
	filters = {"type": "Incoming"}
	if account:
		filters["whatsapp_account"] = account
	if since:
		filters["creation"] = (">=", get_datetime(since))
	return filters


def _count(filters):
	# get_list applies the original WhatsApp Message role and user permissions.
	return cint(frappe.get_list("WhatsApp Message", filters=filters, fields=["count(name) as total"])[0].total)


@frappe.whitelist(methods=["GET"])
def coverage_status(whatsapp_account=None, since=None, limit=20):
	_require_access()
	filters = _filters(whatsapp_account, since)
	missing_filters = {**filters, "intake_received_at": ("is", "not set")}
	incoming, absent = _count(filters), _count(missing_filters)
	missing = frappe.get_list("WhatsApp Message", filters=missing_filters,
		fields=["name", "creation", "from as sender", "profile_name"], order_by="creation, name",
		limit_page_length=min(max(cint(limit), 1), 100))
	return dict(incoming_count=incoming, covered_count=incoming - absent, missing_count=absent,
		attention_count=_count({**filters, "intake_status": "Needs Attention"}),
		pending_count=_count({**filters, "intake_received_at": ("is", "set"), "intake_status": ("in", ["New", "Needs Attention"])}), missing_sources=missing)


@frappe.whitelist(methods=["POST"])
def capture_existing(messages=None, whatsapp_account=None, since=None, limit=50):
	_require_access()
	limit = min(max(cint(limit), 1), 100)
	messages = frappe.parse_json(messages) if isinstance(messages, str) else messages
	if messages is not None:
		if not isinstance(messages, list) or not messages or len(messages) > 100 or any(not isinstance(name, str) for name in messages):
			frappe.throw("Select between one and 100 original WhatsApp messages")
		names = list(dict.fromkeys(messages))
	else:
		if not since:
			frappe.throw("A received-since time is required to capture existing messages")
		names = [row.name for row in coverage_status(whatsapp_account, since, limit)["missing_sources"]]
	captured, errors = [], []
	for index, name in enumerate(names):
		point = f"manual_intake_{index}"
		frappe.db.savepoint(point)
		try:
			doc = frappe.get_doc("WhatsApp Message", name)
			doc.check_permission("read")
			if doc.type != "Incoming" or (whatsapp_account and doc.whatsapp_account != whatsapp_account):
				frappe.throw("Selected message is not incoming in this account")
			receipt = capture_saved_message(doc)
			captured.append(receipt.name)
			frappe.db.release_savepoint(point)
		except frappe.ValidationError:
			frappe.db.rollback(save_point=point)
			raise
		except Exception:
			frappe.db.rollback(save_point=point)
			errors.append(dict(source_message=name, error="Capture failed; the original remains available for repair"))
	return dict(captured=captured, errors=errors, examined=len(names))


@frappe.whitelist(methods=["POST"])
def refresh_sender(message):
	_require_access()
	frappe.get_doc("WhatsApp Message", message).check_permission("read")
	doc = refresh_sender_identity(message)
	return dict(identity_type=doc.intake_identity_type, identity_status=doc.intake_identity_status,
		customer=doc.intake_customer, sales_employee=doc.intake_sales_employee)


@frappe.whitelist(methods=["POST"])
def retry_attachment(message):
	_require_access()
	from kunal_enterprises.integrations.order_intake_media import retry_download
	return retry_download(message)
