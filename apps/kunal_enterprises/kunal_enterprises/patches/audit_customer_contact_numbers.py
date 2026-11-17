"""Refuse ambiguous legacy ownership without changing existing login numbers."""
import frappe

from kunal_enterprises.integrations.customer_contacts import configured_country_code, normalize_phone


def execute():
	seen = {}
	code = configured_country_code()
	rows = frappe.get_all("Customer", fields=["name", "mobile_number"])
	rows += [frappe._dict(name=row.parent, mobile_number=row.mobile_number)
		for row in frappe.get_all("Customer Contact", filters={"parenttype": "Customer", "parentfield": "contacts"},
			fields=["parent", "mobile_number"])]
	for row in rows:
		if not row.mobile_number:
			continue
		try:
			key = normalize_phone(row.mobile_number, code)
		except frappe.ValidationError as error:
			raise frappe.ValidationError(f"Invalid phone on Customer {row.name}. Correct that record before migrating; no phone numbers were changed.") from error
		if key in seen:
			frappe.throw(f"Duplicate customer phone +{key}: {seen[key]} and {row.name}. Correct the existing records before migrating; no phone numbers were reassigned.")
		seen[key] = row.name
