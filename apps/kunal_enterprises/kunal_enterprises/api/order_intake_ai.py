"""Explicit Owner/Admin AI processing; scheduling remains independently controlled."""
import frappe
from kunal_enterprises.api.order_intake_queue import _require_manager
from kunal_enterprises.integrations.order_intake_ai_models import AIProblem
from kunal_enterprises.integrations import order_intake_ai as ai
from kunal_enterprises.integrations import order_intake_queue as preparation
from kunal_enterprises.kunal_enterprises.doctype.order_intake_request.order_intake_request import _sender_key


@frappe.whitelist(methods=["POST"])
def process_sender(whatsapp_account, sender):
	_require_manager()
	frappe.get_doc("WhatsApp Account", whatsapp_account).check_permission("read")
	sender = _sender_key(sender)
	if not sender:
		frappe.throw("Enter a sender number")
	rows = frappe.get_all("WhatsApp Message", filters={"type": "Incoming", "whatsapp_account": whatsapp_account,
		"intake_sender_key": sender, "intake_prepare_state": preparation.READY, "intake_context_ids": ("is", "set")},
		fields=["name", "intake_context_ids"], order_by="intake_prepared_at desc", limit_page_length=1)
	if not rows:
		frappe.throw("Prepare this sender's context first using Prepare Sender Context")
	# Related requests may have been created after preparation. Authorize the
	# actual current snapshot before any provider job is published.
	try:
		snapshot = ai._snapshot(rows[0].name)
	except AIProblem as error:
		frappe.throw(error.note)
	for source in snapshot["messages"]:
		frappe.get_doc("WhatsApp Message", source["name"]).check_permission("read")
	for related in snapshot["open_requests"]:
		doc = frappe.get_doc("Order Intake Request", related["name"])
		doc.check_permission("read")
		doc.check_permission("write")
	for name in snapshot["message_ids"]:
		frappe.get_doc("WhatsApp Message", name).check_permission("write")
	config = frappe.get_single("Order Intake Settings")
	if not config.get_password("api_key", raise_exception=False):
		frappe.throw("Add the AI provider API key in Order Intake Settings first")
	return ai.dispatch(anchor=rows[0].name, force=True)
