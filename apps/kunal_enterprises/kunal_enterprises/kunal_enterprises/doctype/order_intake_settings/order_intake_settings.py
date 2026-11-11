"""Configuration only. Step 1 deliberately cannot activate any processing jobs."""
import re

import frappe
from frappe.model.document import Document


class OrderIntakeSettings(Document):
	def validate(self):
		if frappe.session.user != "Administrator" and not {"Owner", "Admin"}.intersection(frappe.get_roles()):
			frappe.throw("Owner or Admin is required to change Order Intake Settings", frappe.PermissionError)
		code = (self.default_country_calling_code or "+91").strip() or "+91"
		if code and not re.fullmatch(r"\+?[1-9][0-9]{0,2}", code):
			frappe.throw("Country calling code must contain one to three digits, optionally prefixed by +")
		self.default_country_calling_code = "+" + code.lstrip("+")
		if self.processing_enabled:
			frappe.throw("Processing cannot be enabled until the scheduling and AI implementation is complete")
		bounds = {
			"interval_minutes": (1, 1440), "lookback_minutes": (1, 10080), "pdf_page_limit": (1, 1000),
			"request_timeout_seconds": (5, 600), "transport_retries": (0, 5), "output_retries": (0, 5),
			"max_requests_per_job": (1, 100), "max_input_tokens": (100, 500000), "max_output_tokens": (100, 128000),
		}
		for field, (minimum, maximum) in bounds.items():
			value = self.get(field)
			if value is None or not minimum <= value <= maximum:
				frappe.throw(f"{self.meta.get_label(field)} must be between {minimum} and {maximum}")
		for field in ("grouping_model", "extraction_model"):
			value = (self.get(field) or "").strip()
			if not value or len(value) > 140 or re.search(r"\s", value):
				frappe.throw("Model identifiers must be non-empty and contain no whitespace")
			if self.provider == "OpenRouter" and "/" not in value:
				frappe.throw("OpenRouter model identifiers need the provider prefix, for example openai/gpt-6-luna")
			self.set(field, value)
		delays = (self.deferred_retry_minutes or "").split(",")
		if not 1 <= len(delays) <= 5 or any(not re.fullmatch(r"\s*[0-9]+\s*", delay) for delay in delays):
			frappe.throw("Deferred retry delays must contain one to five comma-separated minute values")
		values = [int(delay) for delay in delays]
		if any(not 1 <= value <= 1440 for value in values) or values != sorted(set(values)):
			frappe.throw("Deferred retry delays must be increasing unique values between 1 and 1440 minutes")
		self.deferred_retry_minutes = ",".join(str(value) for value in values)
