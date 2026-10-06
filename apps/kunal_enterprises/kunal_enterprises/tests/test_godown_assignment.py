"""Optional godowns and the controlled assignment/Processing boundary."""

from uuid import uuid4
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from kunal_enterprises.api.orders import submit
from kunal_enterprises.api.godown_assignment import assign_godowns
from kunal_enterprises.api.order_controls import mark_processing
from kunal_enterprises.api.branch_orders import mark_processing as branch_processing
from kunal_enterprises.api.token_verification import issue_token
from kunal_enterprises.tests import test_foundation as helpers


class TestGodownAssignment(FrappeTestCase):
	_create_product_group = helpers.TestOrderSubmission._create_product_group
	_create_item = helpers.TestOrderSubmission._create_item
	_create_active_customer = helpers.TestOrderSubmission._create_active_customer
	_create_role_user = helpers.TestOrderSubmission._create_role_user
	_create_branch_user = helpers.TestOrderSubmission._create_branch_user

	def setUp(self):
		frappe.set_user("Administrator")
		self.prefix = "Assignment " + uuid4().hex[:10]
		group = self._create_product_group(self.prefix)
		self.item = self._create_item(self.prefix, group.name)
		self.customer = self._create_active_customer(
			str(int(uuid4().hex[:12], 16)), self.prefix,
		)
		self.godown = frappe.get_doc({
			"doctype": "Tally Godown", "godown_name": self.prefix, "is_active": 1,
		}).insert()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_order_can_be_placed_without_a_godown(self):
		response = submit(self.customer.name, [{"item": self.item.name, "quantity": 3}])
		self.assertTrue(response["success"], response)
		order = frappe.get_doc("Order", response["data"]["order"])
		self.assertEqual(order.status, "Placed")
		self.assertEqual(order.total_quantity, 3)
		self.assertTrue(order.godown_assignment_pending)
		self.assertFalse(order.godown_allocations[0].godown)

	def test_mixed_order_preserves_customer_selected_godown(self):
		response = submit(self.customer.name, [
			{"item": self.item.name, "quantity": 3},
			{"item": self.item.name, "quantity": 2, "godown": self.godown.name},
		])
		self.assertTrue(response["success"], response)
		order = frappe.get_doc("Order", response["data"]["order"])
		self.assertTrue(order.godown_assignment_pending)
		self.assertEqual(order.total_quantity, 5)
		self.assertEqual(len(order.godown_allocations), 2)
		self.assertEqual(order.godown_allocations[1].godown, self.godown.name)

	def _order(self, mixed=False):
		allocations = [{"item": self.item.name, "quantity": 3}]
		if mixed:
			allocations.append({"item": self.item.name, "quantity": 2, "godown": self.godown.name})
		response = submit(self.customer.name, allocations)
		self.assertTrue(response["success"], response)
		return frappe.get_doc("Order", response["data"]["order"])

	def _assign(self, order):
		return assign_godowns(order.name, [
			{"allocation": row.name, "godown": self.godown.name}
			for row in order.godown_allocations if not row.godown
		])

	def test_missing_godown_blocks_api_and_direct_processing(self):
		order = self._order()
		response = mark_processing(order.name)
		self.assertFalse(response["success"])
		self.assertIn("Assign a godown", response["error"]["message"])
		self.assertEqual(frappe.db.get_value("Order", order.name, "status"), "Placed")
		order.status = "Processing"
		with self.assertRaisesRegex(frappe.ValidationError, "Assign a godown"):
			order.save(ignore_permissions=True)

	def test_allocator_fills_only_missing_godowns_then_owner_can_process(self):
		order = self._order(mixed=True)
		allocator = self._create_role_user(uuid4().hex + "@example.com", "Godown Allocator")
		frappe.set_user(allocator.name)
		response = self._assign(order)
		self.assertTrue(response["success"], response)
		self.assertFalse(response["data"]["godown_assignment_pending"])
		frappe.set_user("Administrator")
		order.reload()
		self.assertEqual(order.total_quantity, 5)
		self.assertEqual([row.requested_quantity for row in order.godown_allocations], [3, 2])
		self.assertEqual(order.status, "Placed")
		log = frappe.get_last_doc("Order Status Log", filters={"order": order.name})
		self.assertEqual(log.role, "Godown Allocator")
		self.assertIn(allocator.name, log.note)
		self.assertTrue(mark_processing(order.name)["success"])

	def test_selected_godown_and_quantity_cannot_be_changed(self):
		order = self._order(mixed=True)
		selected = order.godown_allocations[1]
		response = assign_godowns(order.name, [{"allocation": selected.name, "godown": self.godown.name}])
		self.assertFalse(response["success"])
		self.assertIn("Previously selected", response["error"]["message"])
		order.godown_allocations[0].godown = self.godown.name
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be edited"):
			order.save(ignore_permissions=True)
		order.reload()
		order.flags.in_godown_assignment = True
		order.items[0].requested_quantity += 1
		with self.assertRaisesRegex(frappe.ValidationError, "item lines cannot be edited"):
			order.save(ignore_permissions=True)

	def test_branch_employee_cannot_assign_even_with_client_flag(self):
		order = self._order()
		user = self._create_role_user(uuid4().hex + "@example.com", "Branch Employee")
		frappe.set_user(user.name)
		response = self._assign(order)
		self.assertFalse(response["success"])
		self.assertFalse(frappe.db.get_value("Order Godown Allocation", order.godown_allocations[0].name, "godown"))
		order.flags.in_godown_assignment = True
		order.godown_allocations[0].godown = self.godown.name
		with self.assertRaises(frappe.ValidationError):
			order.save(ignore_permissions=True)

	def test_assignment_is_atomic_when_one_godown_is_invalid(self):
		other = self._create_item(self.prefix + " other", self.item.root_stock_group)
		response = submit(self.customer.name, [
			{"item": self.item.name, "quantity": 3}, {"item": other.name, "quantity": 2},
		])
		self.assertTrue(response["success"], response)
		order = frappe.get_doc("Order", response["data"]["order"])
		response = assign_godowns(order.name, [
			{"allocation": order.godown_allocations[0].name, "godown": self.godown.name},
			{"allocation": order.godown_allocations[1].name, "godown": "Does not exist"},
		])
		self.assertFalse(response["success"])
		order.reload()
		self.assertTrue(all(not row.godown for row in order.godown_allocations))
		self.assertFalse(frappe.db.exists("Order Status Log", {"order": order.name}))

	def test_branch_processing_blocked_for_partially_assigned_order(self):
		order = self._order(mixed=True)
		branch = frappe.get_doc({"doctype": "Portal Branch", "branch_name": self.prefix, "is_active": 1}).insert()
		frappe.get_doc({"doctype": "Branch Godown Mapping", "portal_branch": branch.name,
			"godown": self.godown.name, "is_active": 1}).insert()
		user = self._create_branch_user(uuid4().hex + "@example.com", "Branch Employee", branch.name)
		frappe.set_user(user.name)
		response = branch_processing(branch.name, order.name, "Branch Employee")
		self.assertFalse(response["success"])
		self.assertIn("Assign a godown", response["error"]["message"])

	def test_sales_employee_can_place_without_godown_with_matching_token(self):
		employee = frappe.get_doc({"doctype": "Sales Employee", "sales_employee_name": self.prefix,
			"employee_code": self.prefix, "mobile_number": str(int(uuid4().hex[:12], 16)),
			"status": "Active"}).insert()
		token = issue_token("Sales Employee", employee.name)
		response = submit(self.customer.name, [{"item": self.item.name, "quantity": 4}],
			sales_employee=employee.name, headers={"Auth-Token": "Bearer " + token["access_token"]})
		self.assertTrue(response["success"], response)
		self.assertTrue(response["data"]["godown_assignment_pending"])

	def test_unassigned_duplicates_merge_and_pdf_has_readable_label(self):
		response = submit(self.customer.name, [
			{"item": self.item.name, "quantity": 1, "godown": ""},
			{"item": self.item.name, "quantity": 2},
		])
		self.assertTrue(response["success"], response)
		order = frappe.get_doc("Order", response["data"]["order"])
		self.assertEqual(len(order.godown_allocations), 1)
		self.assertEqual(order.godown_allocations[0].requested_quantity, 3)
		pdf = frappe.get_last_doc("Order PDF", filters={"order": order.name})
		self.assertIn("Godown: Not assigned", pdf.summary_text)

	def test_allocator_has_real_list_and_document_read_but_cannot_write(self):
		pending = self._order()
		assigned_response = submit(self.customer.name, [
			{"item": self.item.name, "quantity": 1, "godown": self.godown.name},
		])
		self.assertTrue(assigned_response["success"], assigned_response)
		assigned = frappe.get_doc("Order", assigned_response["data"]["order"])
		allocator = self._create_role_user(uuid4().hex + "@example.com", "Godown Allocator")
		frappe.set_user(allocator.name)
		visible = frappe.get_list("Order", filters={"customer": self.customer.name}, pluck="name")
		self.assertIn(pending.name, visible)
		self.assertNotIn(assigned.name, visible)
		self.assertTrue(pending.has_permission("read"))
		self.assertFalse(pending.has_permission("write"))
		self.assertFalse(assigned.has_permission("read"))

	def test_inactive_godown_rejected_at_placement_and_assignment(self):
		order = self._order()
		frappe.db.set_value("Tally Godown", self.godown.name, "is_active", 0)
		self.assertFalse(self._assign(order)["success"])
		response = submit(self.customer.name, [
			{"item": self.item.name, "quantity": 1, "godown": self.godown.name},
		])
		self.assertFalse(response["success"])

	def test_assignment_from_another_order_cannot_be_used(self):
		first = self._order()
		second = self._order()
		response = assign_godowns(first.name, [
			{"allocation": second.godown_allocations[0].name, "godown": self.godown.name},
		])
		self.assertFalse(response["success"])
		first.reload()
		self.assertFalse(first.godown_allocations[0].godown)

	def test_real_dispatch_status_does_not_prevent_filling_missing_godown(self):
		order = self._order()
		order.status = "Partially Processed"
		order.items[0].fulfilled_quantity = 1
		order.save(ignore_permissions=True)
		response = self._assign(order)
		self.assertTrue(response["success"], response)
		order.reload()
		self.assertEqual(order.status, "Partially Processed")
		self.assertEqual(order.items[0].fulfilled_quantity, 1)
		self.assertFalse(order.godown_assignment_pending)

	def test_final_assignment_invalidates_incremental_reconciliation(self):
		order = self._order()
		previous_flag = frappe.conf.get("tally_incremental_reconciliation_enabled")
		previous_company = frappe.conf.get("tally_source_company")
		try:
			frappe.conf.tally_incremental_reconciliation_enabled = True
			frappe.conf.tally_source_company = self.prefix
			response = self._assign(order)
			self.assertTrue(response["success"], response)
			self.assertTrue(frappe.db.exists("Tally Reconciliation Work Item", {
				"source_company": self.prefix, "reference_number": order.portal_reference_number,
			}))
		finally:
			frappe.conf.tally_incremental_reconciliation_enabled = previous_flag
			frappe.conf.tally_source_company = previous_company

	def test_confirmation_failure_does_not_leave_a_created_order(self):
		before = frappe.db.count("Order", {"customer": self.customer.name})
		with patch("kunal_enterprises.api.orders.get_pdf", side_effect=RuntimeError("PDF renderer failed")):
			response = submit(self.customer.name, [{"item": self.item.name, "quantity": 3}])
		self.assertFalse(response["success"])
		self.assertEqual(frappe.db.count("Order", {"customer": self.customer.name}), before)
		self.assertFalse(frappe.db.exists("Order PDF", {"customer": self.customer.name}))

	def test_deactivated_selected_godown_cannot_enter_processing(self):
		response = submit(self.customer.name, [
			{"item": self.item.name, "quantity": 2, "godown": self.godown.name},
		])
		self.assertTrue(response["success"], response)
		frappe.db.set_value("Tally Godown", self.godown.name, "is_active", 0)
		response = mark_processing(response["data"]["order"])
		self.assertFalse(response["success"])
		self.assertIn("active godown", response["error"]["message"])

	def test_malformed_allocations_and_assignment_ids_are_validation_errors(self):
		for allocations in ("bad", [{}], [{"item": self.item.name, "godown": [], "quantity": 1}]):
			response = submit(self.customer.name, allocations)
			self.assertFalse(response["success"])
			self.assertEqual(response["http_status_code"], 400)
		order = self._order()
		for assignments in ("[invalid", [{"allocation": {}, "godown": self.godown.name}]):
			response = assign_godowns(order.name, assignments)
			self.assertFalse(response["success"])
			self.assertEqual(response["http_status_code"], 400)

	def test_processing_audit_failure_rolls_back_status_change(self):
		response = submit(self.customer.name, [
			{"item": self.item.name, "quantity": 2, "godown": self.godown.name},
		])
		self.assertTrue(response["success"], response)
		order = frappe.get_doc("Order", response["data"]["order"])
		original_get_doc = frappe.get_doc

		def fail_status_log(*args, **kwargs):
			if args and isinstance(args[0], dict) and args[0].get("doctype") == "Order Status Log":
				raise RuntimeError("Audit storage failed")
			return original_get_doc(*args, **kwargs)

		with patch.object(frappe, "get_doc", side_effect=fail_status_log):
			response = mark_processing(order.name)
		self.assertFalse(response["success"])
		self.assertEqual(frappe.db.get_value("Order", order.name, "status"), "Placed")

	def test_branch_processing_audit_failure_rolls_back_status_change(self):
		response = submit(self.customer.name, [
			{"item": self.item.name, "quantity": 2, "godown": self.godown.name},
		])
		self.assertTrue(response["success"], response)
		order_name = response["data"]["order"]
		branch = frappe.get_doc({"doctype": "Portal Branch", "branch_name": self.prefix, "is_active": 1}).insert()
		frappe.get_doc({"doctype": "Branch Godown Mapping", "portal_branch": branch.name,
			"godown": self.godown.name, "is_active": 1}).insert()
		user = self._create_branch_user(uuid4().hex + "@example.com", "Branch Employee", branch.name)
		frappe.set_user(user.name)
		with patch("kunal_enterprises.api.branch_orders._create_status_log", side_effect=RuntimeError("Audit storage failed")):
			response = branch_processing(branch.name, order_name, "Branch Employee")
		self.assertFalse(response["success"])
		self.assertEqual(frappe.db.get_value("Order", order_name, "status"), "Placed")
