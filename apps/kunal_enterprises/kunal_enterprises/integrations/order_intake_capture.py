"""Intake metadata on the existing WhatsApp Message; no extra message/chat stores."""
import hashlib
import json
import math
from datetime import datetime, timezone
from kunal_enterprises.integrations.order_intake_contacts import project_contacts, contact_text

import frappe
from frappe.utils import now_datetime, convert_utc_to_system_timezone
from kunal_enterprises.kunal_enterprises.doctype.order_intake_request.order_intake_request import _sender_key


def _json(value):
	return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def event_key(phone_id, message_id):
	return hashlib.sha256(_json([str(phone_id), str(message_id)]).encode()).hexdigest()


def _identity(sender):
	"""Recognise identity, never grant order authorization or choose a sales customer's identity."""
	key = _sender_key(sender)
	if not key.isdigit():
		return dict(identity_type="Unknown", identity_status="Unknown", customer=None, sales_employee=None,
			identity_candidates="[]")
	code = frappe.db.get_single_value("Order Intake Settings", "default_country_calling_code")
	code = str(code or "91").lstrip("+")
	variants = {key}
	if code:
		if len(key) == 10:
			variants.add(code + key)
		elif key.startswith(code) and len(key) == len(code) + 10:
			variants.add(key[len(code):])
	candidates = []
	for doctype, label in (("Customer", "customer_name"), ("Sales Employee", "sales_employee_name")):
		# Exact normalized matches only. SQL parameters contain user values; table/field names are fixed.
		expression = "COALESCE(mobile_number, '')"
		for character in ("+", " ", "-", "(", ")"):
			expression = f"REPLACE({expression}, '{character}', '')"
		placeholders = ",".join(["%s"] * len(variants))
		rows = frappe.db.sql(f"SELECT name, `{label}` AS label, status FROM `tab{doctype}` "
			f"WHERE {expression} IN ({placeholders}) ORDER BY name LIMIT 21", tuple(sorted(variants)), as_dict=True)
		candidates.extend(dict(doctype=doctype, name=row.name, label=row.label, status=row.status) for row in rows)
	result = dict(customer=None, sales_employee=None, identity_candidates=_json(candidates[:40]))
	if len(candidates) == 1:
		match = candidates[0]
		result.update(identity_type=match["doctype"], identity_status=match["status"] or "Unknown")
		result["customer" if match["doctype"] == "Customer" else "sales_employee"] = match["name"]
	else:
		result.update(identity_type="Ambiguous" if candidates else "Unknown",
			identity_status="Ambiguous" if candidates else "Unknown")
	return result



def capture_message_hook(doc, method=None):
	"""Initialise incoming metadata in the same transaction as the original message."""
	if doc.type != "Incoming" or doc.flags.intake_migrating:
		return
	if not doc.meta.has_field("intake_status"):
		return
	if not doc.whatsapp_account:
		doc.set_whatsapp_account()
	if not doc.get("intake_received_at"):
		doc.intake_received_at = doc.creation or now_datetime()
		doc.intake_status = "New"
		doc.intake_sender_key = _sender_key(doc.get("from"))
		doc.intake_phone_id = frappe.db.get_value("WhatsApp Account", doc.whatsapp_account, "phone_id") or ""
		apply_identity(doc)
	if not doc.is_new() and any(doc.has_value_changed(field) for field in ("from", "whatsapp_account")):
		# Context selection uses stored normalized keys. Keep them aligned when
		# a source correction changes its sender or receiving account.
		doc.intake_sender_key = _sender_key(doc.get("from"))
		doc.intake_phone_id = frappe.db.get_value("WhatsApp Account", doc.whatsapp_account, "phone_id") or ""
		doc.intake_event_key = None
		apply_identity(doc)
	if doc.message_id and not doc.get("intake_event_key"):
		key = event_key(doc.get("intake_phone_id") or doc.whatsapp_account, doc.message_id)
		other = frappe.db.get_value("WhatsApp Message", {"intake_event_key": key}, "name")
		if other and other != doc.name:
			doc.intake_status = "Duplicate"
			doc.intake_attention = "Repeated message ID; canonical WhatsApp Message: " + other
		else:
			doc.intake_event_key = key


def apply_identity(doc):
	for field, value in _identity(doc.get("from")).items():
		doc.set("intake_" + field, value)


def capture_saved_message(doc):
	if doc.type != "Incoming":
		frappe.throw("Only incoming messages can be prepared for intake")
	capture_message_hook(doc)
	values = {field: doc.get(field) for field in (
		"intake_received_at", "intake_status", "intake_sender_key", "intake_phone_id", "intake_event_key",
		"intake_attention", "intake_customer", "intake_sales_employee", "intake_identity_type",
		"intake_identity_status", "intake_identity_candidates")}
	frappe.db.set_value("WhatsApp Message", doc.name, values, update_modified=False)
	return doc


def refresh_sender_identity(name):
	doc = frappe.get_doc("WhatsApp Message", name)
	if doc.type != "Incoming":
		frappe.throw("Only incoming messages have a sender to match")
	apply_identity(doc)
	frappe.db.set_value("WhatsApp Message", name, {"intake_" + key: value for key, value in _identity(doc.get("from")).items()}, update_modified=False)
	return doc


def raw_values(message, contacts):
	sender = str(message.get("from") or message.get("from_user_id") or "")
	profile = next((c.get("profile", {}).get("name", "") for c in contacts
		if sender in {str(c.get("wa_id") or ""), str(c.get("user_id") or "")}), "")
	kind = message.get("type") or "unknown"
	body = message.get(kind) or {}
	text = (body.get("body") if kind == "text" else body.get("caption")) if isinstance(body, dict) else None
	if kind == "contacts":
		text = contact_text(project_contacts(body)[0])
	if text is None:
		text = _json(body)
	values = {"intake_original_type": kind}
	if str(message.get("timestamp") or "").isdigit():
		try:
			values["intake_sent_at"] = convert_utc_to_system_timezone(datetime.fromtimestamp(int(message["timestamp"]), timezone.utc).replace(tzinfo=None)).replace(tzinfo=None)
		except (ValueError, OverflowError, OSError):
			pass  # Exact original timestamp remains in the payload.
	if kind in {"image", "audio", "video", "document", "sticker"} and isinstance(body, dict):
		values.update(intake_media_id=body.get("id"), intake_media_mime=body.get("mime_type"), intake_media_filename=body.get("filename"))
	if kind == "location" and isinstance(body, dict):
		values.update(intake_location_name=body.get("name"), intake_location_address=body.get("address"))
		lat, lon = body.get("latitude"), body.get("longitude")
		if isinstance(lat, (float, int)) and isinstance(lon, (float, int)) and math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
			values.update(intake_has_location=1, intake_latitude=lat, intake_longitude=lon)
	return sender, profile, text or "", values


def preserve_raw(doc, message, value, entry_id, warning=None):
	"""Keep provider evidence on the message itself, including conflicting repeated IDs."""
	# A worker may finish between webhook lookup and enrichment. Inspect the
	# current locked row so late evidence cannot leave its context marked ready.
	doc = frappe.get_doc("WhatsApp Message", doc.name, for_update=True)
	raw = _json({"entry_id": entry_id, "metadata": value.get("metadata"), "contacts": value.get("contacts") or [], "message": message})
	_, _, _, values = raw_values(message, value.get("contacts") or [])
	previous = frappe.parse_json(doc.intake_raw_payload) if doc.intake_raw_payload else None
	# Earlier ledgers stored the message object alone. Enrich that compatible
	# payload with its envelope instead of flagging an unchanged redelivery.
	compatible_legacy = previous == message
	evidence_changed = doc.intake_raw_payload != raw
	if doc.intake_raw_payload and doc.intake_raw_payload != raw and not compatible_legacy:
		evidence = frappe.parse_json(doc.intake_legacy_evidence or "[]")
		if not isinstance(evidence, list):
			evidence = [evidence]
		evidence_changed = raw not in evidence
		if evidence_changed:
			evidence.append(raw)
		values = {"intake_legacy_evidence": _json(evidence)}
		warning = "Conflicting payload for the same message ID; retained in additional evidence"
	else:
		values["intake_raw_payload"] = raw
	if doc.get("intake_prepare_state") == "Context Ready" and evidence_changed:
		# Raw evidence is written directly, so normal document-change hooks do
		# not run. Changed/late evidence must be reconsidered by the next batch.
		values.update(intake_prepare_state="Pending", intake_prepare_note="New incoming evidence awaits context preparation.")
	if warning:
		values.update(intake_status="Needs Attention", intake_attention=warning)
	frappe.db.set_value("WhatsApp Message", doc.name, values, update_modified=False)
	return doc.name
