"""Server-managed restricted AI diagnostics."""
import frappe
from frappe.model.document import Document


class OrderIntakeAICall(Document):
	def validate(self):
		frappe.throw("AI run logs are managed by the system", frappe.PermissionError)

	def on_trash(self):
		frappe.throw("AI run logs are managed by the system", frappe.PermissionError)
