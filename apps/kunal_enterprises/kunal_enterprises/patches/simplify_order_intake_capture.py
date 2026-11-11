"""Consolidate earlier capture evidence onto WhatsApp Message before removing its ledgers."""
from html import escape
import hashlib
import json
import os
from pathlib import Path

import frappe
from frappe.utils import now_datetime

from kunal_enterprises.integrations.order_intake_schema import setup

LEGACY_TYPES = ("Order Intake Message", "Order Intake Conversation")
FIELD_MAP = {
	"processing_status": "intake_status", "attention_reason": "intake_attention",
	"sender": "intake_sender_key", "phone_number_id": "intake_phone_id",
	"received_at": "intake_received_at", "sent_at": "intake_sent_at",
	"content_type": "intake_original_type", "media_id": "intake_media_id",
	"media_mime_type": "intake_media_mime", "media_filename": "intake_media_filename",
	"has_location": "intake_has_location", "latitude": "intake_latitude",
	"longitude": "intake_longitude", "location_name": "intake_location_name",
	"location_address": "intake_location_address", "raw_message": "intake_raw_payload",
}


def _json(value):
	return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def _backup(snapshot):
	"""The private, owner-readable backup also preserves unattached conversation metadata."""
	encoded = _json(snapshot).encode()
	digest = hashlib.sha256(encoded).hexdigest()[:16]
	folder = Path(frappe.get_site_path("private", "backups"))
	folder.mkdir(parents=True, exist_ok=True)
	path = folder / f"order-intake-before-simplification-{digest}.json"
	# Exclusive creation makes reruns safe and never replaces a previous backup.
	try:
		with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
			stream.write(encoded)
	except FileExistsError:
		if path.read_bytes() != encoded:
			raise RuntimeError("Intake migration backup does not match the preserved evidence")
	return str(path)


def _fallback(row):
	"""No controller/hooks: never send, default an unmapped account, or rewrite source data."""
	name = "WA-INTAKE-" + hashlib.sha256(row["name"].encode()).hexdigest()[:32]
	if frappe.db.exists("WhatsApp Message", name):
		return name
	kind = row.get("content_type") or "text"
	allowed = set((frappe.get_meta("WhatsApp Message").get_field("content_type").options or "").splitlines())
	kind = "contact" if kind == "contacts" else kind
	doc = frappe.get_doc(dict(doctype="WhatsApp Message", name=name, type="Incoming",
		whatsapp_account=row.get("whatsapp_account"), **{"from": row.get("sender")},
		profile_name=row.get("profile_name"), message=escape(row.get("text") or ""),
		message_id=row.get("message_id"), reply_to_message_id=row.get("reply_to_message_id"),
		is_reply=int(bool(row.get("reply_to_message_id"))), attach=row.get("attachment"),
		content_type=kind if kind in allowed else "text"))
	doc.flags.intake_migrating = True
	doc.db_insert()
	return doc.name


def _migrate_message(row, conversations):
	source = row.get("source_message")
	if not source or not frappe.db.exists("WhatsApp Message", source):
		source = _fallback(row)
	if frappe.db.get_value("WhatsApp Message", source, "type") != "Incoming":
		raise RuntimeError("Earlier intake evidence points to an outgoing message; migration stopped")
	current = frappe.get_doc("WhatsApp Message", source)
	try:
		evidence = json.loads(current.intake_legacy_evidence or "[]")
	except (ValueError, TypeError):
		evidence = [{"previous_value": current.intake_legacy_evidence}]
	if not isinstance(evidence, list):
		evidence = [evidence]
	entry = {"message": row, "conversation": conversations.get(row.get("conversation"))}
	if not any(isinstance(old, dict) and (old.get("message") or {}).get("name") == row["name"] for old in evidence):
		evidence.append(entry)
	values = {"intake_legacy_evidence": _json(evidence)}
	for old, new in FIELD_MAP.items():
		if row.get(old) is not None and not current.get(new):
			values[new] = row[old]
	if row.get("processing_status") in {"Needs Attention", "Duplicate"} and current.intake_status in {None, "", "New"}:
		values["intake_status"] = row["processing_status"]
	conversation = entry["conversation"] or {}
	for old, new in (("customer", "intake_customer"), ("sales_employee", "intake_sales_employee"),
		("identity_type", "intake_identity_type"), ("identity_status", "intake_identity_status"),
		("identity_candidates", "intake_identity_candidates")):
		if conversation.get(old) and not current.get(new):
			values[new] = conversation[old]
	key = row.get("dedupe_key")
	if key and not current.intake_event_key and not frappe.db.exists("WhatsApp Message", {"intake_event_key": key}):
		values["intake_event_key"] = key
	frappe.db.set_value("WhatsApp Message", source, values, update_modified=False)
	return source


def execute():
	setup()
	if not frappe.db.exists("DocType", "WhatsApp Message"):
		return
	present = [dt for dt in LEGACY_TYPES if frappe.db.exists("DocType", dt)]
	if not present:
		return
	snapshot = {dt: frappe.get_all(dt, fields=["*"], limit_page_length=0) for dt in present}
	files = frappe.get_all("File", filters={"attached_to_doctype": ["in", present]}, fields=["*"], limit_page_length=0)
	snapshot["files"] = files
	_backup(snapshot)
	conversations = {row["name"]: row for row in snapshot.get("Order Intake Conversation", [])}
	destinations = {}
	for row in snapshot.get("Order Intake Message", []):
		source = _migrate_message(row, conversations)
		destinations[("Order Intake Message", row["name"])] = source
		if row.get("conversation"):
			destinations.setdefault(("Order Intake Conversation", row["conversation"]), source)
	for attachment in files:
		target = destinations.get((attachment["attached_to_doctype"], attachment["attached_to_name"]))
		if not target:
			# Leave an orphan attachment intact; its full reference is in the private backup.
			continue
		frappe.db.set_value("File", attachment["name"], {"attached_to_doctype": "WhatsApp Message",
			"attached_to_name": target, "attached_to_field": None}, update_modified=False)
	# Framework DocType removal unregisters these views; the private snapshot and
	# per-message legacy JSON preserve the evidence even after schema cleanup.
	was_migrating = frappe.flags.in_migrate
	try:
		frappe.flags.in_migrate = True
		for doctype in present:
			frappe.delete_doc("DocType", doctype, force=1, ignore_permissions=True)
	finally:
		frappe.flags.in_migrate = was_migrating
	frappe.clear_cache(doctype="WhatsApp Message")
