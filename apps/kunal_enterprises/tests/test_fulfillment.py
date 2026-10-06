import unittest
from copy import deepcopy

from kunal_enterprises.cron.fulfillment import evaluate_order


class FulfillmentTests(unittest.TestCase):
	def setUp(self):
		self.order = dict(reference="R1", customer_guid="C1", status="Placed", items={"A": 10})
		self.v = dict(
			guid="V1",
			reference="R1",
			party_guid="C1",
			eligible=True,
			source_status="Active",
			lines=[dict(item="A", quantity=-4, tracking_number="T1")],
		)

	def result(self, *vouchers):
		return evaluate_order(self.order, list(vouchers))

	def test_quantity_correction_replaces_prior_contribution(self):
		self.assertEqual(self.result(self.v)["fulfilled"]["A"], 4)
		self.v["lines"][0]["quantity"] = -6
		self.assertEqual(self.result(self.v)["fulfilled"]["A"], 6)
		self.assertEqual(self.result(self.v), self.result(self.v))

	def test_customer_correction_clears_review(self):
		self.v["party_guid"] = "WRONG"
		self.assertEqual(self.result(self.v)["status"], "Manual Review")
		self.v["party_guid"] = "C1"
		self.assertEqual(self.result(self.v)["status"], "Partially Processed")

	def test_reference_correction_removes_old_order_contribution(self):
		self.v["reference"] = "R2"
		self.assertEqual(self.result(self.v)["fulfilled"]["A"], 0)
		self.order["reference"] = "R2"
		self.assertEqual(self.result(self.v)["fulfilled"]["A"], 4)

	def test_removed_voucher_reopens_completed_order(self):
		self.order["status"] = "Completed"
		self.v["source_status"] = "Removed"
		self.assertEqual(self.result(self.v)["status"], "Processing")
		self.assertEqual(self.result(self.v)["fulfilled"]["A"], 0)

	def test_new_voucher_adds_and_overdelivery_requires_review(self):
		second = deepcopy(self.v)
		second["guid"] = "V2"
		second["lines"][0]["tracking_number"] = "T2"
		second["lines"][0]["quantity"] = -6
		self.assertEqual(self.result(self.v, second)["status"], "Completed")
		second["lines"][0]["quantity"] = -7
		self.assertEqual(self.result(self.v, second)["status"], "Manual Review")

	def test_invoice_does_not_duplicate_challan(self):
		invoice = deepcopy(self.v)
		invoice["guid"] = "I1"
		invoice["eligible"] = False
		self.assertEqual(self.result(self.v, invoice)["fulfilled"]["A"], 4)

	def test_manual_closures_are_preserved(self):
		for status in ["Cancelled", "Partially Closed"]:
			self.order["status"] = status
			self.assertEqual(self.result(self.v)["status"], status)

	def test_unknown_item_and_inward_quantity_require_review(self):
		self.v["lines"][0]["item"] = "B"
		self.assertEqual(self.result(self.v)["status"], "Manual Review")
		self.v["lines"][0]["item"] = "A"
		self.v["lines"][0]["quantity"] = 4
		self.assertEqual(self.result(self.v)["status"], "Manual Review")

	def test_incomplete_lines_never_count_as_zero_delivery(self):
		self.v["source_error"] = "Missing inventory lines"
		self.assertEqual(self.result(self.v)["status"], "Manual Review")

	def test_duplicate_guids_are_rejected(self):
		with self.assertRaises(ValueError):
			self.result(self.v, self.v)

	def test_duplicate_tracking_is_reviewed_not_silently_dropped(self):
		second = deepcopy(self.v)
		second["guid"] = "V2"
		self.assertEqual(self.result(self.v, second)["status"], "Manual Review")

	def test_missing_customer_identity_never_matches(self):
		self.order["customer_guid"] = None
		self.v["party_guid"] = None
		self.assertEqual(self.result(self.v)["status"], "Manual Review")

	def test_review_recovery_without_dispatch_waits_for_godown_assignment(self):
		self.order.update(status="Manual Review", godown_assignment_pending=True)
		self.assertEqual(self.result()["status"], "Placed")
		self.order["godown_assignment_pending"] = False
		self.assertEqual(self.result()["status"], "Processing")


if __name__ == "__main__":
	unittest.main()


class TrackingPrecisionTests(unittest.TestCase):
	def test_equivalent_decimal_quantities_do_not_hide_duplicate_tracking(self):
		order = dict(reference="R", customer_guid="C", status="Placed", items={"A": 10})
		v = dict(reference="R", party_guid="C", eligible=True, source_status="Active")
		result = evaluate_order(
			order,
			[
				v | dict(guid="one", lines=[dict(item="A", quantity="-4.0", tracking_number="T")]),
				v | dict(guid="two", lines=[dict(item="A", quantity="-4.0000", tracking_number="T")]),
			],
		)
		self.assertEqual(result["status"], "Manual Review")
		self.assertEqual(result["fulfilled"]["A"], 0)
