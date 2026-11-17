import frappe
from frappe.model.document import Document


class CustomerContact(Document):
	def validate(self):
		# Parent saves validate the complete phone set before writing child rows.
		frappe.throw("Edit contacts through the Customer form or WhatsApp intake.", frappe.PermissionError)

	def on_trash(self):
		frappe.throw("Remove contacts through the Customer form.", frappe.PermissionError)
