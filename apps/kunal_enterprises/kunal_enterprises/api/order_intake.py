"""Minimal reviewer-only master lookups for the Step 1 intake form."""
import frappe
import json
from frappe.utils import cint

from kunal_enterprises.api.quick_orders import _require_reviewer
from kunal_enterprises.kunal_enterprises.doctype.order_intake_request.order_intake_request import _sender_key


@frappe.whitelist(methods=["POST"])
def review_update(request, proposal_index, expected_modified):
	"""Acknowledge a suggestion without applying it or deleting its history."""
	_require_reviewer()
	doc = frappe.get_doc("Order Intake Request", request, for_update=True)
	doc.check_permission("read")
	doc.check_permission("write")
	if str(doc.modified) != str(expected_modified):
		frappe.throw("The request changed. Reload it before reviewing this update.", frappe.TimestampMismatchError)
	if isinstance(proposal_index, bool) or not str(proposal_index).isdigit():
		frappe.throw("Select a valid message update")
	index = int(proposal_index)
	updates = frappe.parse_json(doc.proposed_updates or "[]")
	if not isinstance(updates, list) or index >= len(updates) or not isinstance(updates[index], dict):
		frappe.throw("This message update is unavailable. Reload the request.")
	if not updates[index].get("reviewed_at"):
		updates[index].update(reviewed_at=str(frappe.utils.now_datetime()), reviewed_by=frappe.session.user)
		doc.proposed_updates = json.dumps(updates, ensure_ascii=False)
		previous = frappe.flags.intake_ai_write
		try:
			frappe.flags.intake_ai_write = True
			doc.save()
		finally:
			frappe.flags.intake_ai_write = previous
	return dict(state="Reviewed", pending=sum(not row.get("reviewed_at") for row in updates))


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def intake_link_query(doctype, txt, searchfield, start, page_len, filters):
	_require_reviewer()
	columns = {
		"Customer": ["name", "customer_name", "business_legal_name", "client_code"],
		"Sales Employee": ["name", "sales_employee_name", "employee_code"],
		"WhatsApp Account": ["name"],
		"Tally Item": ["name", "item_name"],
		"Tally Godown": ["name", "godown_name"],
		"WhatsApp Message": ["name", "profile_name", "from", "creation"],
	}
	if doctype not in columns:
		frappe.throw("Unsupported intake lookup", frappe.PermissionError)
	fields = columns[doctype]
	query_filters = {}
	if doctype == "WhatsApp Message":
		query_filters["type"] = "Incoming"
		filters = frappe.parse_json(filters) or {}
		if filters.get("whatsapp_account"):
			query_filters["whatsapp_account"] = str(filters["whatsapp_account"])
		if filters.get("from"):
			raw_sender = str(filters["from"]).strip()
			sender = _sender_key(raw_sender)
			# WhatsApp normally stores digits; reviewers may enter + and spacing.
			# Preserve opaque sender IDs and never guess a missing country code.
			query_filters["from"] = (
				("in", sorted({raw_sender, sender, "+" + sender})) if sender.isdigit() else raw_sender
			)
	search_fields = [field for field in fields if field != "creation"]
	# get_all is intentional: reviewers need these minimal identity fields without
	# granting them upstream account credentials or unrestricted message bodies.
	rows = frappe.get_all(doctype, filters=query_filters,
		or_filters=[[field, "like", f"%{str(txt or '')[:140]}%"] for field in search_fields],
		fields=fields, order_by="modified desc, name asc", limit_start=max(cint(start), 0),
		limit_page_length=min(max(cint(page_len), 1), 40))
	return [[row.get(field) for field in fields] for row in rows]
