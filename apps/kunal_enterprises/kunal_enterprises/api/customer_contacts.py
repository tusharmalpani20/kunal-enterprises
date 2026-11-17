"""Reviewer-authorized linking of an actual WhatsApp sender to a Customer."""
import frappe

from kunal_enterprises.api.quick_orders import _require_reviewer
from kunal_enterprises.integrations.customer_contacts import lock_customer_numbers, normalize_phone


@frappe.whitelist(methods=["POST"])
def link_sender(request, customer, contact_name, designation="", expected_modified=None):
	_require_reviewer()
	if any(not isinstance(value, str) or not value or len(value) > 140 for value in (request, customer)):
		frappe.throw("Select a valid intake request and Customer.")
	if not isinstance(contact_name, str) or (designation is not None and not isinstance(designation, str)):
		frappe.throw("Enter the person's name and designation as text.")
	doc = frappe.get_doc("Order Intake Request", request, for_update=True)
	doc.check_permission("read")
	doc.check_permission("write")
	if str(doc.modified) != str(expected_modified):
		frappe.throw("The request changed. Reload it before linking the sender.", frappe.TimestampMismatchError)
	if doc.source != "WhatsApp" or doc.order or doc.status in {"Resolved", "Dismissed", "Converted to Order"}:
		frappe.throw("Link senders from an open WhatsApp intake request.")
	phone = normalize_phone(doc.sender_number, international=True)
	if not phone:
		frappe.throw("This request has no sender phone number to link.")
	contact_name, designation = str(contact_name or "").strip(), str(designation or "").strip()
	if not contact_name or len(contact_name) > 140 or len(designation) > 140:
		frappe.throw("Enter a person name and a designation of at most 140 characters each.")
	if doc.customer and doc.customer != customer:
		frappe.throw("This request already has a different Customer. Correct and save the request first.")
	if not doc.source_messages:
		frappe.throw("Link an incoming WhatsApp message before registering its sender.")
	for row in doc.source_messages:
		message = frappe.get_doc("WhatsApp Message", row.message)
		message.check_permission("read")
		if (message.type != "Incoming" or message.whatsapp_account != doc.whatsapp_account
			or normalize_phone(message.get("from"), international=True) != phone):
			frappe.throw("The linked messages must belong to this WhatsApp account and sender.")
	lock_customer_numbers()
	from kunal_enterprises.integrations.order_intake_capture import _identity
	identity = _identity(doc.sender_number)
	candidates = frappe.parse_json(identity.get("identity_candidates") or "[]")
	if any(row.get("doctype") == "Sales Employee" for row in candidates):
		frappe.throw("This sender is registered as a Sales Employee. Its identity cannot be changed here.")
	if any(row.get("doctype") == "Customer" and row.get("name") != customer for row in candidates):
		frappe.throw("This sender is already linked to another Customer. Review that Customer's contact details.")
	target = frappe.get_doc("Customer", customer, for_update=True)
	known = [target.mobile_number, *(row.mobile_number for row in target.get("contacts") or [])]
	if not any(normalize_phone(number) == phone for number in known if number):
		target.append("contacts", {"contact_name": contact_name, "mobile_number": "+" + phone, "designation": designation})
		# Reviewers have a narrow contact-linking action, not arbitrary Customer
		# edit access. Only the sender derived from verified sources is appended.
		target.save(ignore_permissions=True)
	if not doc.customer:
		doc.customer = customer
		doc.save()
	from kunal_enterprises.integrations.order_intake_capture import refresh_sender_identity
	for row in doc.source_messages:
		refresh_sender_identity(row.message)
	return {"customer": customer, "mobile_number": "+" + phone}
