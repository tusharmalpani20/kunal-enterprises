import hashlib

from frappe.model.document import Document


class TallyVoucher(Document):
	def autoname(self):
		if self.tally_guid and self.source_company:
			key = f"{self.source_company}:{self.tally_guid}"
			self.name = "TV-" + hashlib.sha256(key.encode()).hexdigest()[:32]
		elif self.voucher_number:
			self.name = self.voucher_number
