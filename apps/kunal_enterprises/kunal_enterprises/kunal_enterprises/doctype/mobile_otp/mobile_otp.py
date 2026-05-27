import re

import frappe
from frappe import _
from frappe.model.document import Document


class MobileOTP(Document):
	def validate(self):
		otp_code = (self.otp_code or "").strip()
		if not re.fullmatch(r"\d{4}", otp_code):
			frappe.throw(_("OTP Code must be a 4 digit number"))
		self.otp_code = otp_code
