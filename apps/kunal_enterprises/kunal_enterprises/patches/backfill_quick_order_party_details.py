"""Populate read-only party details without modifying request status or audit history."""

import frappe


PARTY_DETAIL_FIELDS = (
	"customer_name", "customer_business_name", "customer_code", "customer_mobile_number",
	"customer_gstin", "sales_employee_name", "sales_employee_code", "sales_employee_mobile_number",
)


def execute():
	if not all(frappe.db.has_column("Quick Order Request", field) for field in PARTY_DETAIL_FIELDS):
		return

	# Match the fetched fields for new requests; don't save documents or touch modified timestamps.
	frappe.db.sql("""
		UPDATE `tabQuick Order Request` AS request
		LEFT JOIN `tabCustomer` AS customer ON customer.name = request.customer
		LEFT JOIN `tabSales Employee` AS employee ON employee.name = request.sales_employee
		SET request.customer_name = customer.customer_name,
			request.customer_business_name = customer.business_legal_name,
			request.customer_code = customer.client_code,
			request.customer_mobile_number = customer.mobile_number,
			request.customer_gstin = customer.gstin,
			request.sales_employee_name = employee.sales_employee_name,
			request.sales_employee_code = employee.employee_code,
			request.sales_employee_mobile_number = employee.mobile_number
	""")
