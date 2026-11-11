"""Owner/Admin controls for inspecting and manually preparing one sender's context."""
import frappe
from frappe.utils import now_datetime
from kunal_enterprises.integrations import order_intake_queue as queue
from kunal_enterprises.kunal_enterprises.doctype.order_intake_request.order_intake_request import _sender_key


def _require_manager():
	if frappe.session.user != "Administrator" and not {"Owner", "Admin"}.intersection(frappe.get_roles()):
		frappe.throw("Owner or Admin is required for context preparation", frappe.PermissionError)
	for doctype in ("Order Intake Settings", "WhatsApp Message"):
		if not frappe.has_permission(doctype, "read"):
			frappe.throw("Read access is required for context preparation", frappe.PermissionError)


def _check_context_access(context):
	for name in context["message_ids"] + context["reply_message_ids"] + context["manual_review_message_ids"]:
		frappe.get_doc("WhatsApp Message", name).check_permission("read")
	for request in context["open_requests"]:
		frappe.get_doc("Order Intake Request", request["name"]).check_permission("read")


@frappe.whitelist(methods=["GET"])
def preview(whatsapp_account, sender):
	_require_manager()
	if not whatsapp_account or not _sender_key(sender):
		frappe.throw("Select a receiving account and sender number")
	frappe.get_doc("WhatsApp Account", whatsapp_account).check_permission("read")
	rows = queue._chat_rows(whatsapp_account, _sender_key(sender), now_datetime(), queue.settings())
	if len(rows) > queue.MAX_MESSAGES:
		return dict(state="Needs Attention", sender=_sender_key(sender), whatsapp_account=whatsapp_account, note="This chat exceeds the automatic message limit; review the full sender history.")
	if not rows:
		return dict(state="Empty", sender=_sender_key(sender), whatsapp_account=whatsapp_account, note="No prepared incoming messages are inside the context window.")
	docs = [frappe.get_doc("WhatsApp Message", row.name) for row in rows if row.intake_prepare_state != queue.TERMINAL]
	if not docs:
		return dict(state="Needs Attention", sender=_sender_key(sender), whatsapp_account=whatsapp_account, note="These messages are retained for manual review; there is no new input to prepare.")
	context = queue.build_context(docs)
	_check_context_access(context)
	return dict(state="Preview", sender=_sender_key(sender), whatsapp_account=whatsapp_account, context=context, note="Preview only; no records, jobs, AI calls or orders were created.")


@frappe.whitelist(methods=["POST"])
def prepare_now(whatsapp_account, sender):
	_require_manager()
	result = preview(whatsapp_account, sender)
	if result["state"] != "Preview":
		return result
	# A manual run changes only the current previewed chat, not historical
	# expiry/recovery state. Claim-time checks also cover arrivals after preview.
	result = queue.dispatch_pending(force=True, account=whatsapp_account, sender=_sender_key(sender), inline=True,
		maintain=False, check_permissions=True)
	return {**result, "sender": _sender_key(sender), "whatsapp_account": whatsapp_account}


@frappe.whitelist(methods=["POST"])
def retry_selected(whatsapp_account, sender, messages):
	"""Recover only an explicitly selected bounded set, including older manual evidence."""
	_require_manager()
	sender = _sender_key(sender)
	if not whatsapp_account or not sender:
		frappe.throw("Select a receiving account and sender number")
	frappe.get_doc("WhatsApp Account", whatsapp_account).check_permission("read")
	messages = frappe.parse_json(messages) if isinstance(messages, str) else messages
	if not isinstance(messages, list) or not messages or len(messages) > queue.MAX_MESSAGES or any(not isinstance(name, str) or not name.strip() for name in messages):
		frappe.throw("Select between one and 100 WhatsApp messages to retry")
	if len(set(messages)) != len(messages):
		frappe.throw("Select each WhatsApp message only once")
	result = queue.recover_selected(whatsapp_account, sender, messages)
	if result.get("context"):
		_check_context_access(result["context"])
	return {**result, "sender": sender, "whatsapp_account": whatsapp_account}
