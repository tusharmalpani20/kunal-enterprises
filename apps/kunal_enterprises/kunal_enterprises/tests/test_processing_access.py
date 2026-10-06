"""Processing is global for coordinators, but confined to one branch for branch users."""

from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from kunal_enterprises.api import branch_orders, order_controls
from kunal_enterprises.api.orders import submit
from kunal_enterprises.tests.test_godown_assignment import TestGodownAssignment as AssignmentHelpers


class TestProcessingAccess(FrappeTestCase):
	_create_product_group = AssignmentHelpers._create_product_group
	_create_item = AssignmentHelpers._create_item
	_create_active_customer = AssignmentHelpers._create_active_customer
	_create_role_user = AssignmentHelpers._create_role_user
	_create_branch_user = AssignmentHelpers._create_branch_user
	setUp = AssignmentHelpers.setUp
	tearDown = AssignmentHelpers.tearDown
	_second_godown = AssignmentHelpers._second_godown

	def _placed_order(self, godowns):
		frappe.set_user("Administrator")
		response = submit(self.customer.name, [
			{"item": self.item.name, "quantity": 1, "godown": godown}
			for godown in godowns
		])
		self.assertTrue(response["success"], response)
		return response["data"]["order"]

	def _branch(self, suffix, godowns):
		frappe.set_user("Administrator")
		branch = frappe.get_doc({"doctype": "Portal Branch",
			"branch_name": self.prefix + suffix, "is_active": 1}).insert()
		for godown in godowns:
			frappe.get_doc({"doctype": "Branch Godown Mapping", "portal_branch": branch.name,
				"godown": godown, "is_active": 1}).insert()
		return branch.name

	def _assert_unchanged(self, order, response, log_count=0):
		self.assertFalse(response["success"], response)
		self.assertEqual(frappe.db.get_value("Order", order, "status"), "Placed")
		self.assertEqual(frappe.db.count("Order Status Log", {"order": order}), log_count)

	def test_global_processing_accepts_all_four_roles_and_records_actual_role(self):
		second = self._second_godown()
		self._branch(" global one", [self.godown.name])
		self._branch(" global two", [second.name])
		for role in ("Owner", "Admin", "Godown Allocator", "Order Coordinator"):
			with self.subTest(role=role):
				order = self._placed_order([self.godown.name, second.name])
				user = self._create_role_user(uuid4().hex + "@example.com", role)
				frappe.set_user(user.name)
				self.assertTrue(order_controls.processing_options(order)["data"]["can_process"])
				response = order_controls.mark_processing(order, role=role)
				self.assertTrue(response["success"], response)
				self.assertEqual(frappe.db.get_value("Order", order, "status"), "Processing")
				log = frappe.get_last_doc("Order Status Log", filters={"order": order})
				self.assertEqual((log.from_status, log.to_status, log.role), ("Placed", "Processing", role))

	def test_global_processing_rejects_branch_roles_and_spoofed_global_role(self):
		for role in ("Branch Manager", "Branch Employee"):
			with self.subTest(role=role):
				order = self._placed_order([self.godown.name])
				user = self._create_role_user(uuid4().hex + "@example.com", role)
				frappe.set_user(user.name)
				self._assert_unchanged(order, order_controls.mark_processing(order))
				self._assert_unchanged(order, order_controls.mark_processing(order, role="Godown Allocator"))

	def test_new_global_roles_still_require_assignment_and_placed_status(self):
		for role in ("Godown Allocator", "Order Coordinator"):
			with self.subTest(role=role):
				order = self._placed_order([None])
				user = self._create_role_user(uuid4().hex + "@example.com", role)
				frappe.set_user(user.name)
				self.assertFalse(order_controls.processing_options(order)["data"]["can_process"])
				response = order_controls.mark_processing(order)
				self._assert_unchanged(order, response)
				self.assertIn("Assign a godown", response["error"]["message"])
				order = self._placed_order([self.godown.name])
				frappe.db.set_value("Order", order, "status", "Cancelled")
				frappe.set_user(user.name)
				self.assertFalse(order_controls.mark_processing(order)["success"])
				self.assertEqual(frappe.db.get_value("Order", order, "status"), "Cancelled")
				self.assertFalse(frappe.db.exists("Order Status Log", {"order": order}))

	def test_new_global_role_processing_audit_failure_restores_status(self):
		order = self._placed_order([self.godown.name])
		user = self._create_role_user(uuid4().hex + "@example.com", "Order Coordinator")
		frappe.set_user(user.name)
		with patch("kunal_enterprises.api.order_controls._transition_order", side_effect=self._fail_after_status_save):
			response = order_controls.mark_processing(order)
		self._assert_unchanged(order, response)

	def _fail_after_status_save(self, order, to_status, role, note):
		order.status = to_status
		order.save(ignore_permissions=True)
		raise RuntimeError("Audit storage failed")

	def test_branch_roles_can_process_all_godowns_in_the_same_permitted_branch(self):
		second = self._second_godown()
		branch = self._branch(" one", [self.godown.name, second.name])
		for role in ("Branch Manager", "Branch Employee"):
			for route in ("explicit", "visible"):
				with self.subTest(role=role, route=route):
					order = self._placed_order([self.godown.name, second.name])
					user = self._create_branch_user(uuid4().hex + "@example.com", role, branch)
					frappe.set_user(user.name)
					self.assertTrue(order_controls.processing_options(order)["data"]["can_process"])
					response = (branch_orders.mark_processing(branch, order, role) if route == "explicit"
						else branch_orders.mark_visible_order_processing(order))
					self.assertTrue(response["success"], response)
					self.assertEqual(frappe.db.get_value("Order", order, "status"), "Processing")
					self.assertEqual(frappe.db.get_value("Order Status Log", {"order": order}, "role"), role)

	def test_branch_routes_reject_split_orders_even_with_both_branch_permissions(self):
		second = self._second_godown()
		first_branch = self._branch(" one", [self.godown.name])
		second_branch = self._branch(" two", [second.name])
		for role in ("Branch Manager", "Branch Employee"):
			for both_permissions in (False, True):
				with self.subTest(role=role, both_permissions=both_permissions):
					order = self._placed_order([self.godown.name, second.name])
					user = self._create_branch_user(uuid4().hex + "@example.com", role, first_branch)
					if both_permissions:
						frappe.get_doc({"doctype": "User Permission", "user": user.name,
							"allow": "Portal Branch", "for_value": second_branch,
							"apply_to_all_doctypes": 1}).insert(ignore_permissions=True)
					frappe.set_user(user.name)
					self.assertFalse(order_controls.processing_options(order)["data"]["can_process"])
					self._assert_unchanged(order, branch_orders.mark_processing(first_branch, order, role))
					self._assert_unchanged(order, branch_orders.mark_visible_order_processing(order))

	def test_branch_processing_rejects_unmapped_or_inactive_mapping_in_entire_order(self):
		second = self._second_godown()
		branch = self._branch(" one", [self.godown.name, second.name])
		order = self._placed_order([self.godown.name, second.name])
		user = self._create_branch_user(uuid4().hex + "@example.com", "Branch Manager", branch)
		mapping = frappe.db.get_value("Branch Godown Mapping", {"portal_branch": branch, "godown": second.name})
		frappe.db.set_value("Branch Godown Mapping", mapping, "is_active", 0)
		frappe.set_user(user.name)
		self._assert_unchanged(order, branch_orders.mark_processing(branch, order, "Branch Manager"))
		self._assert_unchanged(order, branch_orders.mark_visible_order_processing(order))
		frappe.set_user("Administrator")
		frappe.delete_doc("Branch Godown Mapping", mapping)
		frappe.set_user(user.name)
		self._assert_unchanged(order, branch_orders.mark_processing(branch, order, "Branch Manager"))

	def test_branch_processing_rejects_inactive_permitted_branch(self):
		branch = self._branch(" inactive", [self.godown.name])
		order = self._placed_order([self.godown.name])
		user = self._create_branch_user(uuid4().hex + "@example.com", "Branch Employee", branch)
		frappe.db.set_value("Portal Branch", branch, "is_active", 0)
		frappe.set_user(user.name)
		self._assert_unchanged(order, branch_orders.mark_processing(branch, order, "Branch Employee"))
		self._assert_unchanged(order, branch_orders.mark_visible_order_processing(order))

	def test_global_processing_options_exclude_a_deactivated_godown(self):
		order = self._placed_order([self.godown.name])
		user = self._create_role_user(uuid4().hex + "@example.com", "Godown Allocator")
		frappe.db.set_value("Tally Godown", self.godown.name, "is_active", 0)
		frappe.set_user(user.name)
		options = order_controls.processing_options(order)
		self.assertTrue(options["success"], options)
		self.assertFalse(options["data"]["can_process"])
		self._assert_unchanged(order, order_controls.mark_processing(order))


	def test_permission_response_failure_rolls_back_processing_and_audit(self):
		order = self._placed_order([self.godown.name])
		user = self._create_role_user(uuid4().hex + "@example.com", "Godown Allocator")
		frappe.set_user(user.name)
		with patch("kunal_enterprises.api.order_controls.frappe.has_permission", side_effect=RuntimeError("Permission lookup failed")):
			response = order_controls.mark_processing(order)
		self._assert_unchanged(order, response)

	def test_global_role_takes_priority_over_branch_role_for_split_order(self):
		second = self._second_godown()
		first_branch = self._branch(" first", [self.godown.name])
		self._branch(" second", [second.name])
		order = self._placed_order([self.godown.name, second.name])
		user = self._create_branch_user(uuid4().hex + "@example.com", "Branch Employee", first_branch)
		user.append("roles", {"role": "Order Coordinator"})
		user.save(ignore_permissions=True)
		frappe.set_user(user.name)
		self.assertTrue(order_controls.processing_options(order)["data"]["can_process"])
		response = order_controls.mark_processing(order)
		self.assertTrue(response["success"], response)
		self.assertEqual(frappe.db.get_value("Order Status Log", {"order": order}, "role"), "Order Coordinator")
