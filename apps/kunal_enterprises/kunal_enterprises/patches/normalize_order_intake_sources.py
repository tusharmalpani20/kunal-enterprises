"""Make historical child-level source associations visible to intake context lookup."""
import frappe


def execute():
	if not frappe.db.exists("DocType", "Order Intake Request"):
		return
	last_name = ""
	while True:
		names = frappe.get_all("Order Intake Request", filters={"name": (">", last_name)},
			pluck="name", order_by="name asc", limit_page_length=100)
		if not names:
			return
		for name in names:
			doc = frappe.get_doc("Order Intake Request", name)
			account, sender = doc.whatsapp_account, doc.sender_number
			try:
				doc._validate_sources()
			except frappe.ValidationError:
				# Never guess a source chat or silently drop an invalid reference.
				frappe.throw(f"Review source message references on Order Intake Request {name} before migration")
			# Avoid full document save: historical review/status/item selections
			# are unrelated to this repair and must remain unchanged.
			doc.update_child_table("source_messages")
			values = {}
			if not account and doc.whatsapp_account:
				values["whatsapp_account"] = doc.whatsapp_account
			if not sender and doc.sender_number:
				values["sender_number"] = doc.sender_number
			if values:
				frappe.db.set_value("Order Intake Request", name, values, update_modified=False)
		last_name = names[-1]
