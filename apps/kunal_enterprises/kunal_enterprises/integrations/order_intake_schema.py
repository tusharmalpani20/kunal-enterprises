"""Install intake tracking on the existing WhatsApp Message, without editing its app."""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def custom_fields():
	# Append after the final original field so collapsing intake cannot hide message content.
	fields = [dict(fieldname="intake_details", label="Intake Details", fieldtype="Section Break",
		collapsible=1, depends_on='eval:doc.type == "Incoming"', insert_after="reference_name")]
	definitions = [
		("intake_status", "Intake Status", "Select", "New\nNeeds Attention\nDuplicate"),
		("intake_attention", "Needs Attention", "Small Text", None),
		("intake_customer", "Recognized Customer", "Link", "Customer"),
		("intake_sales_employee", "Recognized Salesperson", "Link", "Sales Employee"),
		("intake_identity_type", "Sender Match", "Data", None),
		("intake_identity_status", "Sender Master Status", "Data", None),
		("intake_received_at", "Received At", "Datetime", None),
		("intake_sent_at", "WhatsApp Timestamp", "Datetime", None),
		("intake_sender_key", "Normalized Sender", "Small Text", None),
		("intake_phone_id", "Receiving Business Phone ID", "Small Text", None),
		("intake_original_type", "Original Message Type", "Small Text", None),
		("intake_media_id", "WhatsApp Media ID", "Small Text", None),
		("intake_media_mime", "Media MIME Type", "Small Text", None),
		("intake_media_filename", "Original Filename", "Small Text", None),
		("intake_has_location", "Coordinates Supplied", "Check", None),
		("intake_latitude", "Latitude", "Float", None),
		("intake_longitude", "Longitude", "Float", None),
		("intake_location_name", "Location Name", "Small Text", None),
		("intake_location_address", "Location Address", "Small Text", None),
		("intake_identity_candidates", "Possible Sender Matches", "Code", "JSON"),
		("intake_raw_payload", "Original Incoming Payload", "Code", "JSON"),
		("intake_legacy_evidence", "Preserved Earlier Intake Evidence", "Code", "JSON"),
		("intake_event_key", "Intake Event Key", "Data", None),
		("intake_manual_context", "Manually Recovered Context", "Check", None),
		("intake_media_state", "Attachment Download", "Select", "Pending\nQueued\nDownloaded\nFailed"),
		("intake_media_note", "Attachment Download Note", "Small Text", None),
		("intake_media_job_token", "Attachment Job Token", "Data", None),
		("intake_media_queued_at", "Attachment Queued At", "Datetime", None),
		("intake_media_attempts", "Attachment Attempts", "Int", None),
		("intake_prepare_state", "Context Preparation", "Select", "Pending\nQueued\nContext Ready\nRetry\nNeeds Attention"),
		("intake_prepare_note", "Preparation Note", "Small Text", None),
		("intake_prepared_at", "Context Prepared At", "Datetime", None),
		("intake_context_anchor", "Context Details On Message", "Link", "WhatsApp Message"),
		("intake_context_ids", "Prepared Context References", "Code", "JSON"),
		("intake_attempts", "Preparation Attempts", "Int", None),
		("intake_batch_size", "Claimed Message Count", "Int", None),
		("intake_retry_at", "Next Preparation Retry", "Datetime", None),
		("intake_lease_until", "Preparation Lease Until", "Datetime", None),
		("intake_job_token", "Preparation Job Token", "Data", None),
		("intake_context_digest", "Context Digest", "Data", None),
		("intake_ai_state", "AI Processing", "Select", "Pending\nQueued\nRetry\nDrafted\nUnresolved\nNeeds Attention"),
		("intake_ai_note", "AI Processing Note", "Small Text", None),
		("intake_ai_token", "AI Job Token", "Data", None),
		("intake_ai_digest", "AI Input Digest", "Data", None),
		("intake_ai_prepared_digest", "AI Prepared Context Version", "Data", None),
		("intake_ai_attempts", "AI Attempts", "Int", None),
		("intake_ai_retry_at", "Next AI Retry", "Datetime", None),
		("intake_ai_lease_until", "AI Lease Until", "Datetime", None),
		("intake_ai_result", "AI Draft References", "Code", "JSON"),
		("intake_ai_coverage", "AI Message Coverage", "Code", "JSON"),
	]
	for name, label, kind, options in definitions:
		field = dict(fieldname=name, label=label, fieldtype=kind, read_only=1, no_copy=1,
			insert_after=fields[-1]["fieldname"])
		if options:
			field["options"] = options
		if name == "intake_status":
			field.update(default="New", in_standard_filter=1)
		if name == "intake_media_state":
			field["default"] = "Pending"
		if name == "intake_ai_state":
			field.update(default="Pending", in_standard_filter=1)
		if name == "intake_prepare_state":
			field.update(default="Pending", in_standard_filter=1)
		if name in {"intake_job_token", "intake_context_digest", "intake_media_job_token", "intake_ai_token", "intake_ai_digest", "intake_ai_prepared_digest"}:
			field["hidden"] = 1
		if name == "intake_event_key":
			field.update(unique=1, hidden=1)
		if kind == "Float":
			field["precision"] = "8"
		fields.append(field)
	return {"WhatsApp Message": fields, "WhatsApp Account": [dict(
		fieldname="intake_app_secret", label="Meta App Secret", fieldtype="Password", permlevel=1,
		insert_after="app_id", no_copy=1, description="Meta application secret used to verify incoming webhook signatures. Enter the secret from Meta App Settings; this is different from the access token and verification token.")]}


def setup():
	"""Reapplied on install/migrate so a second server gets the same extension."""
	if frappe.db.exists("DocType", "Order Intake Match Evidence"):
		frappe.db.add_index("Order Intake Match Evidence", ["kind", "normalized_key", "whatsapp_account", "sender"], "order_intake_learned_scope")
		frappe.db.add_index("Order Intake Match Evidence", ["whatsapp_account", "sender", "active", "creation"], "order_intake_recent_learning")
	if frappe.db.exists("DocType", "Order Intake AI Run"):
		frappe.db.add_index("Order Intake AI Run", ["payloads_purged_at", "started_at"], "order_intake_log_expiry")
		frappe.db.add_index("Order Intake AI Run", ["status", "started_at"], "order_intake_log_recovery")
	if not frappe.db.exists("DocType", "WhatsApp Message"):
		return
	create_custom_fields(custom_fields(), update=True)
	# Account-scoped incoming history uses stable creation/name pagination.
	frappe.db.add_index("WhatsApp Message", ["type", "whatsapp_account", "creation", "name"], "whatsapp_inbox_history")
	frappe.db.add_index("WhatsApp Message", ["intake_ai_state", "intake_ai_retry_at"], "order_intake_ai_dispatch")
	frappe.db.add_index("WhatsApp Message", ["type", "intake_prepare_state", "intake_received_at"], "order_intake_dispatch")
	frappe.db.add_index("WhatsApp Message", ["whatsapp_account", "intake_prepare_state"], "order_intake_account_jobs")
	from kunal_enterprises.permission_guards.whatsapp import setup as setup_permissions
	setup_permissions()
	if frappe.db.exists("DocType", "Order Intake Settings"):
		if frappe.db.get_single_value("Order Intake Settings", "preparation_enabled") is None:
			frappe.db.set_single_value("Order Intake Settings", "preparation_enabled", 0)
		code = frappe.db.get_single_value("Order Intake Settings", "default_country_calling_code")
		normalized = "+" + (str(code or "").strip().lstrip("+") or "91")
		if normalized != code:
			frappe.db.set_single_value("Order Intake Settings", "default_country_calling_code", normalized)
