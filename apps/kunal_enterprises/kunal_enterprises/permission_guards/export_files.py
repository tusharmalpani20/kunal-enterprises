"""Ensure exports are private before Frappe writes their content to disk."""

from frappe.core.doctype.file.file import File

from kunal_enterprises.permission_guards.exports import keep_report_file_private


class ExportProtectedFile(File):
	def before_insert(self):
		self.set_file_name()
		protect = keep_report_file_private(self)
		if protect and (self.file_url or "").startswith("/files/"):
			# Copying an existing public attachment must also protect its blob.
			self.handle_is_private_changed()
		super().before_insert()
