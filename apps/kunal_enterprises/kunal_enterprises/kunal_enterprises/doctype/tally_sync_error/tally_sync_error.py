import frappe
from frappe.model.document import Document
from frappe.utils import cint, now_datetime


class TallySyncError(Document):
	def validate(self):
		# Serialize new/edited error references with retention's parent-row deletion.
		if self.sync_run and not frappe.db.sql(
			"SELECT name FROM `tabTally Sync Run` WHERE name=%s FOR UPDATE", (self.sync_run,)
		):
			raise frappe.LinkValidationError("The sync run was removed; reload before saving this error")
		previous = self.get_doc_before_save()
		if not cint(self.resolved):
			self.resolved_at = None
		elif previous and cint(previous.resolved) and previous.resolved_at:
			self.resolved_at = previous.resolved_at
		else:
			self.resolved_at = now_datetime()
