"""Backfill fetched customer and sales employee details on existing Orders."""

import frappe


ORDER_DETAIL_FIELDS = ("customer_name", "customer_code", "sales_employee_name")


def execute():
	if not all(frappe.db.has_column("Order", fieldname) for fieldname in ORDER_DETAIL_FIELDS):
		return

	frappe.db.sql(
		"""
		UPDATE `tabOrder` AS order_record
		LEFT JOIN `tabCustomer` AS customer
			ON customer.name = order_record.customer
		LEFT JOIN `tabSales Employee` AS sales_employee
			ON sales_employee.name = order_record.sales_employee
		SET order_record.customer_name = customer.customer_name,
			order_record.customer_code = customer.client_code,
			order_record.sales_employee_name = sales_employee.sales_employee_name
		"""
	)
