"""Coordinators can inspect genuine converted intake Orders, without broader writes."""
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from kunal_enterprises.permission_query_conditions import orders
from kunal_enterprises.tests import test_foundation as foundation


class TestIntakeOrderPermissions(FrappeTestCase):
	def setUp(self):
		frappe.set_user('Administrator')
		self.user=foundation.TestOrderSubmission._create_role_user(self,'intake-order-'+uuid4().hex+'@example.com','Order Coordinator').name

	def tearDown(self):
		frappe.set_user('Administrator');frappe.db.rollback()

	def test_linked_intake_order_read_requires_both_sides_of_conversion(self):
		request=frappe.get_doc(dict(doctype='Order Intake Request',sender_name='Permission fixture')).insert()
		order=frappe.get_doc(dict(doctype='Order',name='intake-permission-'+uuid4().hex,status='Placed',order_intake_request=request.name))
		order.db_insert()
		frappe.db.set_value('Order Intake Request',request.name,dict(status='Converted to Order',order=order.name))
		frappe.set_user(self.user)
		self.assertTrue(orders.has_permission(order,permission_type='read'))
		self.assertFalse(orders.has_permission(order,permission_type='write'))
		self.assertFalse(orders.has_permission(order,permission_type='delete'))
		self.assertIn(order.name,frappe.get_list('Order',pluck='name'))
		frappe.set_user('Administrator')
		frappe.db.set_value('Order Intake Request',request.name,'order','different-order')
		frappe.set_user(self.user)
		self.assertFalse(orders.has_permission(order,permission_type='read'))
		self.assertNotIn(order.name,frappe.get_list('Order',pluck='name'))

	def test_unrelated_orders_are_not_exposed_by_coordinator_intake_access(self):
		order=frappe.get_doc(dict(doctype='Order',name='unrelated-'+uuid4().hex,status='Placed'))
		order.db_insert();frappe.set_user(self.user)
		self.assertFalse(orders.has_permission(order,permission_type='read'))
		self.assertNotIn(order.name,frappe.get_list('Order',pluck='name'))
