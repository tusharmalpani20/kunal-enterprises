# Copyright (c) 2026, Kunal Enterprises and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from kunal_enterprises.patches.backfill_order_party_details import (
	execute as backfill_order_party_details,
)


class TestOrder(FrappeTestCase):
	def test_order_fetch_fields_are_populated_and_can_backfill_existing_orders(self):
		customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": "Order Fetch Customer",
				"business_legal_name": "Order Fetch Customer Business",
				"mobile_number": "9000000991",
				"mobile_verified": 1,
				"admin_approved": 1,
				"status": "Active",
				"client_code": "ORDER-FETCH-CUSTOMER-001",
			}
		).insert()
		sales_employee = frappe.get_doc(
			{
				"doctype": "Sales Employee",
				"sales_employee_name": "Order Fetch Sales Employee",
				"mobile_number": "9000000992",
				"status": "Active",
			}
		).insert()
		stock_group = frappe.get_doc(
			{
				"doctype": "Tally Stock Group",
				"group_name": "Order Fetch Group",
				"tally_guid": "ORDER-FETCH-GROUP-GUID",
				"is_root": 1,
				"depth": 0,
				"full_path": "Order Fetch Group",
				"is_active": 1,
			}
		).insert()
		item = frappe.get_doc(
			{
				"doctype": "Tally Item",
				"item_name": "Order Fetch Item",
				"tally_guid": "ORDER-FETCH-ITEM-GUID",
				"root_stock_group": stock_group.name,
				"uom": "PCS",
				"is_active": 1,
			}
		).insert()

		order = frappe.get_doc(
			{
				"doctype": "Order",
				"portal_reference_number": "ORDER-FETCH-001",
				"order_source": "Sales Employee",
				"customer": customer.name,
				"sales_employee": sales_employee.name,
				"status": "Placed",
				"confirmation_datetime": "2026-09-02 12:00:00",
				"items": [
					{
						"item": item.name,
						"item_name_at_order": "Order Fetch Item",
						"unit": "PCS",
						"requested_quantity": 1,
						"pending_quantity": 1,
					}
				],
			}
		).insert(ignore_permissions=True)

		self.assertEqual(order.customer_name, customer.customer_name)
		self.assertEqual(order.customer_code, customer.client_code)
		self.assertEqual(order.sales_employee_name, sales_employee.sales_employee_name)

		frappe.db.set_value(
			"Order",
			order.name,
			{"customer_name": None, "customer_code": None, "sales_employee_name": None},
			update_modified=False,
		)
		backfill_order_party_details()
		order.reload()

		self.assertEqual(order.customer_name, customer.customer_name)
		self.assertEqual(order.customer_code, customer.client_code)
		self.assertEqual(order.sales_employee_name, sales_employee.sales_employee_name)
