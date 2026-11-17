"""Ensure exports are private before Frappe writes their content to disk."""

import frappe
from frappe.core.doctype.file.file import File

from kunal_enterprises.permission_guards.exports import keep_report_file_private


class ExportProtectedFile(File):
	@frappe.whitelist()
	def optimize_file(self):
		# Upstream writes bytes before save permission checks; stop before I/O.
		from kunal_enterprises.permission_guards.sales_portal import is_sales_user
		if is_sales_user():
			frappe.throw("Sales portal attachment access is read-only.", frappe.PermissionError)
		return super().optimize_file()

	def is_downloadable(self):
		# Private-file serving calls this method directly, bypassing DocPerm hooks.
		# Request-linked evidence is readable without opening its sender’s chat.
		from kunal_enterprises.permission_guards.sales_portal import is_sales_user, can_access
		if is_sales_user():
			return can_access(self)
		return super().is_downloadable()

	def before_insert(self):
		self.set_file_name()
		protect = keep_report_file_private(self)
		if protect and (self.file_url or "").startswith("/files/"):
			# Copying an existing public attachment must also protect its blob.
			self.handle_is_private_changed()
		super().before_insert()
