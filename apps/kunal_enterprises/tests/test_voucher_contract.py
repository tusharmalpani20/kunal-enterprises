import unittest

from kunal_enterprises.integrations.voucher_contract import validate_snapshot, validate_sync_metadata


class ContractTests(unittest.TestCase):
	def setUp(self):
		self.config = {
			"Company Name": "Company",
			"Period From": "2024-04-01",
			"Period To": "2027-03-31",
			"Last AlterID Transaction": "20",
			"Last Voucher Inventory AlterID": "20",
		}
		self.latest = {"id": 12, "status": "success"}
		self.completed = {"id": 10, "finished_at": "2026-09-05"}
		self.state = dict(
			source_kind="postgres_mirror",
			read_complete=True,
			source_company="Company",
			snapshot_id="observation",
			completed_at="2026-09-05",
			voucher_count=1,
		)
		self.row = dict(guid="g", alterid=1, source_company="Company", lines=[], order_details=[], order_number=None)

	def test_existing_success_and_markers_are_sufficient_for_read(self):
		self.assertEqual(validate_sync_metadata(self.config, self.latest, self.completed, 9, "Company"), 20)

	def test_no_change_ping_does_not_clear_failed_import(self):
		with self.assertRaises(ValueError):
			validate_sync_metadata(self.config, self.latest, self.completed, 11, "Company")

	def test_missing_history_lagging_inventory_wrong_company_or_bad_period_reject(self):
		for changes in [
			{"Last Voucher Inventory AlterID": "19"},
			{"Company Name": "Other"},
			{"Period From": "2028-01-01"},
			{"Last Voucher Inventory AlterID": None},
		]:
			with self.assertRaises(ValueError):
				validate_sync_metadata(self.config | changes, self.latest, self.completed, 0, "Company")
		with self.assertRaises(ValueError):
			validate_sync_metadata(self.config, self.latest, None, 0, "Company")

	def test_empty_inventory_is_observed_not_proof_of_zero_or_deletion(self):
		validate_snapshot(self.state, [self.row], "Company", {"type"})

	def test_bad_read_or_duplicate_identity_rejected(self):
		with self.assertRaises(ValueError):
			validate_snapshot(self.state | {"read_complete": False}, [self.row], "Company", {"type"})
		with self.assertRaises(ValueError):
			validate_snapshot(self.state | {"voucher_count": 2}, [self.row, self.row], "Company", {"type"})

	def test_cancellation_cannot_be_claimed_from_existing_schema(self):
		with self.assertRaises(ValueError):
			validate_snapshot(self.state, [self.row | {"inactive": True}], "Company", {"type"})
