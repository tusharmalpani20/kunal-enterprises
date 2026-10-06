"""Optional godowns and the controlled assignment/Processing boundary."""

from uuid import uuid4
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from kunal_enterprises.api.orders import submit
from kunal_enterprises.api.godown_assignment import assign_godowns
from kunal_enterprises.api import godown_assignment
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

	def _second_godown(self):
		return frappe.get_doc({"doctype": "Tally Godown", "godown_name": self.prefix + " second", "is_active": 1}).insert()

	def test_split_unassigned_quantity_preserves_selected_rows_and_item_total(self):
		order = self._order(mixed=True)
		second = self._second_godown()
		selected = order.godown_allocations[1].as_dict()
		response = assign_godowns(order.name, [{"allocation": order.godown_allocations[0].name,
			"splits": [{"godown": self.godown.name, "quantity": 1}, {"godown": second.name, "quantity": 2}]}])
		self.assertTrue(response["success"], response)
		order.reload()
		self.assertEqual(order.total_quantity, 5)
		self.assertEqual(order.items[0].requested_quantity, 5)
		self.assertEqual(order.status, "Placed")
		self.assertFalse(order.godown_assignment_pending)
		self.assertEqual([(row.godown, row.requested_quantity) for row in order.godown_allocations],
			[(self.godown.name, 1), (second.name, 2), (self.godown.name, 2)])
		self.assertEqual(order.godown_allocations[-1].name, selected.name)
		self.assertEqual(order.godown_allocations[-1].requested_quantity, selected.requested_quantity)
		self.assertEqual(order.godown_allocations[-1].stock_shown_at_order_time, selected.stock_shown_at_order_time)
		log = frappe.get_last_doc("Order Status Log", filters={"order": order.name})
		self.assertIn(second.name, log.note)

	def test_split_requires_exact_finite_positive_sum_and_unique_active_godowns(self):
		order = self._order()
		second = self._second_godown()
		for splits in (
			[], [{"godown": self.godown.name, "quantity": 2}],
			[{"godown": self.godown.name, "quantity": 0}, {"godown": second.name, "quantity": 3}],
			[{"godown": self.godown.name, "quantity": -1}, {"godown": second.name, "quantity": 4}],
			[{"godown": self.godown.name, "quantity": float("nan")}],
			[{"godown": self.godown.name, "quantity": float("inf")}],
			[{"godown": self.godown.name, "quantity": 1}, {"godown": self.godown.name, "quantity": 2}],
			[{"godown": "Does not exist", "quantity": 3}],
		):
			with self.subTest(splits=splits):
				response = assign_godowns(order.name, [{"allocation": order.godown_allocations[0].name, "splits": splits}])
				self.assertFalse(response["success"])
				self.assertEqual(response["http_status_code"], 400)
				order.reload()
				self.assertEqual(len(order.godown_allocations), 1)
				self.assertFalse(order.godown_allocations[0].godown)

	def test_split_does_not_distribute_historical_fulfillment(self):
		order = self._order()
		second = self._second_godown()
		order.status = "Partially Processed"
		order.items[0].fulfilled_quantity = 1
		order.godown_allocations[0].fulfilled_quantity = 1
		order.save(ignore_permissions=True)
		response = assign_godowns(order.name, [{"allocation": order.godown_allocations[0].name,
			"splits": [{"godown": self.godown.name, "quantity": 1}, {"godown": second.name, "quantity": 2}]}])
		self.assertFalse(response["success"])
		self.assertIn("fulfilled", response["error"]["message"])
		self.assertTrue(self._assign(order)["success"])
		order.reload()
		self.assertEqual(order.godown_allocations[0].fulfilled_quantity, 1)
		self.assertEqual(order.godown_allocations[0].pending_quantity, 2)
		self.assertEqual(order.items[0].fulfilled_quantity, 1)

	def test_assignment_options_exposes_scoped_latest_stock_without_stock_permissions(self):
		order = self._order()
		second = self._second_godown()
		for name, quantity, company, synced_at in (
			("old", 7, self.prefix, "2026-09-01 10:00:00"),
			("latest", -2, self.prefix, "2026-09-02 10:00:00"),
			("other-company", 99, "Other Company", "2026-09-03 10:00:00"),
		):
			frappe.get_doc({"doctype": "Tally Stock Snapshot", "item": self.item.name,
				"godown": self.godown.name, "quantity": quantity, "source_company": company,
				"synced_at": synced_at}).insert(set_name=self.prefix + " " + name)
		allocator = self._create_role_user(uuid4().hex + "@example.com", "Godown Allocator")
		frappe.set_user(allocator.name)
		self.assertFalse(frappe.has_permission("Tally Stock Snapshot", "read"))
		previous_company = frappe.conf.get("tally_source_company")
		try:
			frappe.conf.tally_source_company = self.prefix
			response = godown_assignment.assignment_options(order.name)
		finally:
			frappe.conf.tally_source_company = previous_company
		self.assertTrue(response["success"], response)
		allocation = response["data"]["allocations"][0]
		self.assertEqual(allocation["name"], order.godown_allocations[0].name)
		self.assertEqual(allocation["quantity"], 3)
		self.assertEqual(allocation["stock"][self.godown.name], -2)
		self.assertIsNone(allocation["stock"][second.name])

	def test_branch_employee_cannot_read_assignment_options(self):
		order = self._order()
		user = self._create_role_user(uuid4().hex + "@example.com", "Branch Employee")
		frappe.set_user(user.name)
		response = godown_assignment.assignment_options(order.name)
		self.assertFalse(response["success"])

	def test_decimal_split_quantities_conserve_requested_quantity(self):
		second = self._second_godown()
		response = submit(self.customer.name, [{"item": self.item.name, "quantity": 0.3}])
		self.assertTrue(response["success"], response)
		order = frappe.get_doc("Order", response["data"]["order"])
		response = assign_godowns(order.name, [{"allocation": order.godown_allocations[0].name,
			"splits": [{"godown": self.godown.name, "quantity": 0.1}, {"godown": second.name, "quantity": 0.2}]}])
		self.assertTrue(response["success"], response)
		order.reload()
		self.assertEqual(order.total_quantity, 0.3)
		self.assertFalse(order.godown_assignment_pending)

	def test_split_rejects_precision_that_would_round_the_stored_total(self):
		order = self._order()
		second = self._second_godown()
		response = assign_godowns(order.name, [{"allocation": order.godown_allocations[0].name,
			"splits": [{"godown": self.godown.name, "quantity": 1.0000000005},
				{"godown": second.name, "quantity": 1.9999999995}]}])
		self.assertFalse(response["success"])
		self.assertEqual(response["http_status_code"], 400)
		self.assertIn("nine decimal", response["error"]["message"])
		order.reload()
		self.assertEqual(len(order.godown_allocations), 1)
		self.assertEqual(order.godown_allocations[0].requested_quantity, 3)
		self.assertFalse(order.godown_allocations[0].godown)

	def test_nine_decimal_split_quantities_remain_exact_after_storage(self):
		order = self._order()
		second = self._second_godown()
		response = assign_godowns(order.name, [{"allocation": order.godown_allocations[0].name,
			"splits": [{"godown": self.godown.name, "quantity": 1.000000001},
				{"godown": second.name, "quantity": 1.999999999}]}])
		self.assertTrue(response["success"], response)
		stored_total = frappe.db.sql("select sum(requested_quantity) from `tabOrder Godown Allocation` where parent=%s", order.name)[0][0]
		self.assertEqual(stored_total, 3)

	def test_split_audit_failure_rolls_back_all_child_rows(self):
		order = self._order()
		second = self._second_godown()
		original_get_doc = frappe.get_doc

		def fail_status_log(*args, **kwargs):
			if args and isinstance(args[0], dict) and args[0].get("doctype") == "Order Status Log":
				raise RuntimeError("Audit storage failed")
			return original_get_doc(*args, **kwargs)

		with patch.object(frappe, "get_doc", side_effect=fail_status_log):
			response = assign_godowns(order.name, [{"allocation": order.godown_allocations[0].name,
				"splits": [{"godown": self.godown.name, "quantity": 1}, {"godown": second.name, "quantity": 2}]}])
		self.assertFalse(response["success"])
		order.reload()
		self.assertEqual(len(order.godown_allocations), 1)
		self.assertFalse(order.godown_allocations[0].godown)
		self.assertEqual(order.godown_allocations[0].requested_quantity, 3)
		self.assertEqual(frappe.db.count("Order Godown Allocation", {"parent": order.name}), 1)
		self.assertFalse(frappe.db.exists("Order Status Log", {"order": order.name}))

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
		self.assertIn(assigned.name, visible)
		self.assertTrue(pending.has_permission("read"))
		self.assertFalse(pending.has_permission("write"))
		self.assertTrue(assigned.has_permission("read"))
		self.assertFalse(assigned.has_permission("write"))

	def test_placed_assignments_can_be_replaced_with_exact_item_distribution(self):
		order = self._order(mixed=True)
		second = self._second_godown()
		response = godown_assignment.replace_assignments(order.name, [{"item": self.item.name,
			"splits": [{"godown": second.name, "quantity": 4}, {"godown": self.godown.name, "quantity": 1}]}])
		self.assertTrue(response["success"], response)
		order.reload()
		self.assertEqual(order.status, "Placed")
		self.assertEqual(order.items[0].requested_quantity, 5)
		self.assertEqual([(row.godown, row.requested_quantity) for row in order.godown_allocations], [(second.name, 4), (self.godown.name, 1)])
		self.assertFalse(order.godown_assignment_pending)
		log = frappe.get_last_doc("Order Status Log", filters={"order": order.name})
		self.assertIn("Before:", log.note)
		self.assertIn("After:", log.note)

	def test_edit_options_group_all_placed_rows_by_item_with_current_quantities(self):
		order = self._order(mixed=True)
		response = godown_assignment.assignment_options(order.name, edit=1)
		self.assertTrue(response["success"], response)
		self.assertTrue(response["data"]["editing"])
		self.assertEqual(len(response["data"]["allocations"]), 1)
		row = response["data"]["allocations"][0]
		self.assertEqual(row["item"], self.item.name)
		self.assertEqual(row["quantity"], 5)
		self.assertEqual(row["current_allocations"], {self.godown.name: 2})

	def test_edit_options_aggregate_decimal_duplicates_without_binary_rounding(self):
		response = submit(self.customer.name, [
			{"item": self.item.name, "quantity": 0.1},
			{"item": self.item.name, "quantity": 0.2, "godown": self.godown.name},
		])
		self.assertTrue(response["success"], response)
		order = frappe.get_doc("Order", response["data"]["order"])
		self.assertTrue(self._assign(order)["success"])
		response = godown_assignment.assignment_options(order.name, edit=1)
		self.assertTrue(response["success"], response)
		row = response["data"]["allocations"][0]
		self.assertEqual(row["current_allocations"], {self.godown.name: 0.3})
		response = godown_assignment.replace_assignments(order.name, [{"item": row["item"],
			"splits": [{"godown": self.godown.name, "quantity": row["current_allocations"][self.godown.name]}]}])
		self.assertTrue(response["success"], response)

	def test_reassignment_retains_matching_godown_identity_and_stock_evidence(self):
		order = self._order(mixed=True)
		second = self._second_godown()
		selected = order.godown_allocations[1]
		frappe.db.set_value("Order Godown Allocation", selected.name, {
			"stock_shown_at_order_time": 7, "stock_snapshot_at": "2026-09-01 10:00:00"})
		response = godown_assignment.replace_assignments(order.name, [{"item": self.item.name,
			"splits": [{"godown": self.godown.name, "quantity": 1}, {"godown": second.name, "quantity": 4}]}])
		self.assertTrue(response["success"], response)
		order.reload()
		retained, added = order.godown_allocations
		self.assertEqual(retained.name, selected.name)
		self.assertEqual(retained.stock_shown_at_order_time, 7)
		self.assertEqual(str(retained.stock_snapshot_at), "2026-09-01 10:00:00")
		self.assertEqual(added.stock_shown_at_order_time, 0)
		self.assertIsNone(added.stock_snapshot_at)

	def test_reassignment_is_locked_after_processing_and_on_historical_fulfillment(self):
		order = self._order()
		self.assertTrue(self._assign(order)["success"])
		self.assertTrue(mark_processing(order.name)["success"])
		response = godown_assignment.replace_assignments(order.name, [{"item": self.item.name,
			"splits": [{"godown": self.godown.name, "quantity": 3}]}])
		self.assertFalse(response["success"])
		self.assertFalse(godown_assignment.assignment_options(order.name, edit=1)["success"])
		order.reload()
		order.flags.in_godown_reassignment = True
		order.godown_allocations[0].requested_quantity = 2
		with self.assertRaises(frappe.ValidationError):
			order.save(ignore_permissions=True)
		order = self._order()
		order.godown_allocations[0].fulfilled_quantity = 1
		order.save(ignore_permissions=True)
		response = godown_assignment.replace_assignments(order.name, [{"item": self.item.name,
			"splits": [{"godown": self.godown.name, "quantity": 3}]}])
		self.assertFalse(response["success"])
		self.assertIn("fulfilled", response["error"]["message"])

	def test_reassignment_requires_authorized_role_and_each_item_exactly_once(self):
		order = self._order()
		user = self._create_role_user(uuid4().hex + "@example.com", "Branch Employee")
		frappe.set_user(user.name)
		assignments = [{"item": self.item.name, "splits": [{"godown": self.godown.name, "quantity": 3}]}]
		self.assertFalse(godown_assignment.replace_assignments(order.name, assignments)["success"])
		order.flags.in_godown_reassignment = True
		order.godown_allocations[0].godown = self.godown.name
		with self.assertRaises(frappe.ValidationError):
			order.save(ignore_permissions=True)
		frappe.set_user("Administrator")
		for payload in ([], assignments + assignments,
			[{"item": self.item.name, "splits": [{"godown": self.godown.name, "quantity": 2}]}],
			[{"item": self.item.name, "splits": [{"godown": self.godown.name, "quantity": 1.0000000005}, {"godown": self._second_godown().name, "quantity": 1.9999999995}]}]):
			response = godown_assignment.replace_assignments(order.name, payload)
			self.assertFalse(response["success"])
			self.assertEqual(response["http_status_code"], 400)
		order.reload()
		self.assertFalse(order.godown_allocations[0].godown)

	def test_reassignment_audit_failure_restores_previous_distribution(self):
		order = self._order(mixed=True)
		second = self._second_godown()
		before = [(row.name, row.godown, row.requested_quantity) for row in order.godown_allocations]
		original_get_doc = frappe.get_doc

		def fail_status_log(*args, **kwargs):
			if args and isinstance(args[0], dict) and args[0].get("doctype") == "Order Status Log":
				raise RuntimeError("Audit storage failed")
			return original_get_doc(*args, **kwargs)

		with patch.object(frappe, "get_doc", side_effect=fail_status_log):
			response = godown_assignment.replace_assignments(order.name, [{"item": self.item.name,
				"splits": [{"godown": second.name, "quantity": 5}]}])
		self.assertFalse(response["success"])
		order.reload()
		self.assertEqual([(row.name, row.godown, row.requested_quantity) for row in order.godown_allocations], before)

	def test_reassignment_cannot_omit_another_requested_item(self):
		other = self._create_item(self.prefix + " other", self.item.root_stock_group)
		response = submit(self.customer.name, [
			{"item": self.item.name, "quantity": 3, "godown": self.godown.name},
			{"item": other.name, "quantity": 2, "godown": self.godown.name},
		])
		self.assertTrue(response["success"], response)
		order = frappe.get_doc("Order", response["data"]["order"])
		before = [(row.name, row.item, row.godown, row.requested_quantity) for row in order.godown_allocations]
		response = godown_assignment.replace_assignments(order.name, [{"item": self.item.name,
			"splits": [{"godown": self.godown.name, "quantity": 3}]}])
		self.assertFalse(response["success"])
		order.reload()
		self.assertEqual([(row.name, row.item, row.godown, row.requested_quantity) for row in order.godown_allocations], before)

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
