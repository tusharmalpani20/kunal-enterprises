"""Private confirmed-selection evidence, visible but never editable by reviewers."""
import frappe
from frappe.model.document import Document


class OrderIntakeMatchEvidence(Document):
	def validate(self):
		frappe.throw("Confirmed match evidence is managed by confirmed intake processing", frappe.PermissionError)

	def on_trash(self):
		frappe.throw("Confirmed match evidence is retained as an audit trail", frappe.PermissionError)
