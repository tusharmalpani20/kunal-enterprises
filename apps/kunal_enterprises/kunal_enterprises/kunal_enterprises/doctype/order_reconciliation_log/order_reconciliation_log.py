import frappe
from frappe import _
from frappe.model.document import Document


class OrderReconciliationLog(Document):
	def validate(self):
		if self.status != "Manual Review":
			return
		if not self.reason_code:
			frappe.throw(_("Manual Review reason code is required"), frappe.ValidationError)
		if not self.message:
			frappe.throw(_("Manual Review reason message is required"), frappe.ValidationError)
