"""Use the installed WhatsApp parser and retain unsupported events in WhatsApp Message."""
import hashlib
import hmac
import json
import re
from copy import deepcopy
from html import escape
from uuid import uuid4

import frappe
from frappe_whatsapp.utils.webhook import webhook as upstream_webhook
from kunal_enterprises.integrations.order_intake_capture import capture_saved_message, event_key, preserve_raw, raw_values
from kunal_enterprises.integrations.order_intake_media import MEDIA_TYPES, queue_download


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def webhook():
	if frappe.request.method == "GET":
		return upstream_webhook()
	request_form = frappe.local.form_dict
	original = verify_signature()
	has_incoming = any((change.get("value") or {}).get("messages") for entry in original.get("entry") or [] for change in entry.get("changes") or [])
	try:
		for entry in original.get("entry") or []:
			for change in entry.get("changes") or []:
				value = change.get("value") or {}
				messages = value.get("messages") or []
				if not messages:
					_status_change(original, entry, change, has_incoming)
					continue
				phone = str((value.get("metadata") or {}).get("phone_number_id") or "")
				account = frappe.db.get_value("WhatsApp Account", {"phone_id": phone}, "name") if phone else None
				if not account:
					# No default-account fallback: fail the request so Meta can retry
					# after the missing account mapping has been corrected.
					frappe.throw("Incoming business phone is not mapped to a WhatsApp Account")
				for message in messages:
					_receive(original, entry, change, message, account, phone)
	finally:
		frappe.local.form_dict = request_form


def verify_signature():
	"""Authenticate the exact body, then parse that body rather than query parameters."""
	raw = frappe.request.get_data(cache=True)
	signature = frappe.request.headers.get("X-Hub-Signature-256", "")
	if not re.fullmatch(r"sha256=[0-9a-fA-F]{64}", signature):
		frappe.throw("A valid Meta webhook signature is required", frappe.PermissionError)
	try:
		payload = json.loads(raw)
		if not isinstance(payload, dict) or not isinstance(payload.get("entry"), list) or not payload["entry"]:
			raise ValueError("Missing entries")
	except (ValueError, TypeError):
		frappe.throw("Invalid webhook JSON", frappe.ValidationError)
	digest = signature.split("=", 1)[1].lower()
	account_checks, mappings = {}, {}
	for entry in payload["entry"]:
		if not isinstance(entry, dict) or not isinstance(entry.get("changes"), list) or not entry["changes"]:
			frappe.throw("Invalid webhook entry", frappe.ValidationError)
		for change in entry["changes"]:
			if not isinstance(change, dict) or not isinstance(change.get("value"), dict):
				frappe.throw("Invalid webhook change", frappe.ValidationError)
			value = change["value"]
			phone = str((value.get("metadata") or {}).get("phone_number_id") or "")
			filters = {"phone_id": phone} if phone else {"business_id": str(entry.get("id") or "")}
			mapping_key = tuple(filters.items())
			if mapping_key not in mappings:
				mappings[mapping_key] = frappe.get_all("WhatsApp Account", filters=filters, fields=["name", "business_id"], limit_page_length=100)
			accounts = mappings[mapping_key]
			if phone and len(accounts) != 1:
				frappe.throw("Incoming business phone must map to one WhatsApp Account", frappe.ValidationError)
			valid = False
			for account in accounts:
				if phone and account.business_id and str(entry.get("id") or "") != str(account.business_id):
					continue
				if account.name not in account_checks:
					secret = frappe.get_doc("WhatsApp Account", account.name).get_password("intake_app_secret", raise_exception=False)
					account_checks[account.name] = bool(secret) and hmac.compare_digest(hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest(), digest)
				valid = account_checks[account.name] or valid
			if not valid:
				frappe.throw("Meta webhook signature could not be verified; check the account App Secret", frappe.PermissionError)
	return frappe._dict(payload)


def _parse(original, entry, change, message=None):
	piece = deepcopy(change)
	if message is not None:
		piece["value"]["messages"] = [message]
		sender = str(message.get("from") or message.get("from_user_id") or "")
		piece["value"]["contacts"] = [c for c in piece["value"].get("contacts", [])
			if sender in {str(c.get("wa_id") or ""), str(c.get("user_id") or "")}]
	frappe.local.form_dict = frappe._dict(object=original.get("object"), entry=[{**entry, "changes": [piece]}])
	return upstream_webhook()


def _existing(account, message_id, key):
	if not message_id:
		return frappe.db.get_value("WhatsApp Message", {"intake_event_key": key}, "name", for_update=True)
	return frappe.db.get_value("WhatsApp Message", {"type": "Incoming", "whatsapp_account": account,
		"message_id": message_id}, "name", order_by="creation asc", for_update=True)


def _receive(original, entry, change, message, account, phone):
	value = change.get("value") or {}
	message_id = message.get("id")
	# Missing IDs still have an idempotent raw-payload identity, scoped to this phone.
	key = event_key(phone, message_id or frappe.as_json(message))
	name = _existing(account, message_id, key)
	warning = None
	if not name:
		point = "wa_parse_" + uuid4().hex[:12]
		frappe.db.savepoint(point)
		try:
			if message.get("type") not in MEDIA_TYPES:
				_parse(original, entry, change, message)
			name = _existing(account, message_id, key)
		except Exception as error:
			frappe.db.rollback(save_point=point)
			# A concurrent delivery may have won the unique event-key insert.
			name = _existing(account, message_id, key)
			if not name:
				warning = "WhatsApp parser could not save this message (" + type(error).__name__ + "); review original payload"
			frappe.local.message_log = []
		finally:
			frappe.db.release_savepoint(point)
		if not name:
			if message.get("type") not in MEDIA_TYPES:
				warning = warning or "WhatsApp parser did not save this message; review original payload"
			sender, profile, text, _ = raw_values(message, value.get("contacts") or [])
			kind = message.get("type")
			allowed = frappe.get_meta("WhatsApp Message").get_field("content_type").options.splitlines()
			kind = "contact" if kind == "contacts" else kind
			doc = frappe.get_doc({"doctype": "WhatsApp Message", "type": "Incoming", "whatsapp_account": account,
				"from": sender, "profile_name": profile, "message": escape(text), "message_id": message_id,
				"content_type": kind if kind in allowed else "text", "intake_event_key": key,
				"reply_to_message_id": (message.get("context") or {}).get("id")})
			# Internal inserts may initialise protected intake metadata.
			doc.flags.intake_service_write = True
			# Unique key is enforced even for unsupported/missing-ID messages.
			point = "wa_fallback_" + uuid4().hex[:12]
			frappe.db.savepoint(point)
			try:
				doc.insert(ignore_permissions=True)
				name = doc.name
			except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
				frappe.db.rollback(save_point=point)
				name = _existing(account, message_id, key)
				if not name:
					raise
				frappe.local.message_log = []
			finally:
				frappe.db.release_savepoint(point)
	# Failed storage here propagates; an uncaptured event must not receive success.
	doc = frappe.get_doc("WhatsApp Message", name)
	if not doc.intake_received_at:
		capture_saved_message(doc)
	preserve_raw(doc, message, value, entry.get("id"), warning)
	if message.get("type") in MEDIA_TYPES:
		queue_download(name)


def _status_change(original, entry, change, has_incoming):
	point = "wa_status_" + uuid4().hex[:12]
	frappe.db.savepoint(point)
	try:
		_parse(original, entry, change)
	except Exception:
		frappe.db.rollback(save_point=point)
		if not has_incoming:
			raise
		# Preserve status evidence without rolling back unrelated incoming orders.
		frappe.get_doc({"doctype": "WhatsApp Notification Log", "template": "Webhook status needs review",
			"meta_data": frappe.as_json(change)}).insert(ignore_permissions=True)
		frappe.local.message_log = []
	finally:
		frappe.db.release_savepoint(point)
