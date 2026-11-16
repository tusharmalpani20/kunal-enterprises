"""Restricted provider and bounded processing configuration."""
import re
import math

import frappe
from frappe.model.document import Document


class OrderIntakeSettings(Document):
	def validate(self):
		if frappe.session.user != "Administrator" and not {"Owner", "Admin"}.intersection(frappe.get_roles()):
			frappe.throw("Owner or Admin is required to change Order Intake Settings", frappe.PermissionError)
		self.company_name = (self.get("company_name") or "").strip()
		aliases = list(dict.fromkeys(line.strip() for line in (self.get("company_aliases") or "").splitlines() if line.strip()))
		if len(self.company_name) > 140 or len(aliases) > 20 or any(len(alias) > 140 for alias in aliases):
			frappe.throw("Company names must be at most 140 characters, with at most 20 alternative names")
		self.company_aliases = "\n".join(aliases)
		code = (self.default_country_calling_code or "+91").strip() or "+91"
		if code and not re.fullmatch(r"\+?[1-9][0-9]{0,2}", code):
			frappe.throw("Country calling code must contain one to three digits, optionally prefixed by +")
		self.default_country_calling_code = "+" + code.lstrip("+")
		if self.log_payload_retention_days is None:
			self.log_payload_retention_days = 30
		if not 1 <= self.log_payload_retention_days <= 3650:
			frappe.throw("Log payload retention must be between 1 and 3650 days")
		seen_prices = set()
		for row in self.pricing or []:
			row.model = (row.model or "").strip()
			row.service_tier = (row.service_tier or "default").strip()
			if not row.model or len(row.model) > 140 or re.search(r"\s", row.model):
				frappe.throw("Pricing model identifiers must be non-empty and contain no whitespace")
			if not row.max_context_tokens or not 1 <= row.max_context_tokens <= 2_147_483_647:
				frappe.throw("Pricing context limits must be positive integers")
			key = (row.provider, row.model, row.service_tier, row.max_context_tokens)
			if key in seen_prices:
				frappe.throw("Pricing rows must be unique by provider, model, tier and context limit")
			seen_prices.add(key)
			for rate in ("input_per_million", "cached_input_per_million", "output_per_million", "cache_write_per_million"):
				if not math.isfinite(row.get(rate) or 0) or (row.get(rate) or 0) < 0:
					frappe.throw("AI pricing rates must be finite and non-negative")
		if self.processing_enabled and not self.get_password("api_key", raise_exception=False):
			frappe.throw("Add the AI provider API key before enabling processing")
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
