import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from kunal_enterprises.patches import use_voucher_order_numbers as cutover


class OrderCutoverTests(unittest.TestCase):
	def test_replay_does_not_hold_an_authoritative_empty_order(self):
		row = SimpleNamespace(name="voucher", reference_number="OLD", order_number=None,
			source_pending_references="[]", source_status="Active",
			raw_source_payload=json.dumps({"order_details": [], "order_number": None}))
		db = SimpleNamespace(set_value=Mock())
		with patch.object(cutover, "frappe", SimpleNamespace(get_all=lambda *a, **k: [row], db=db)):
			cutover.execute()
			cutover.execute()
		db.set_value.assert_not_called()

	def test_legacy_hold_is_repeatable_and_never_copies_reference_to_order(self):
		row = SimpleNamespace(name="voucher", reference_number="OLD", order_number=None,
			source_pending_references='["OTHER"]', source_status="Active", raw_source_payload="{}")
		def save(doctype, name, values, **kwargs):
			self.assertNotIn("order_number", values)
			self.assertNotIn("reconciled", values)
			self.assertEqual(json.loads(values["source_pending_references"]), ["OLD", "OTHER"])
			for key, value in values.items():
				setattr(row, key, value)
		db = SimpleNamespace(set_value=Mock(side_effect=save))
		with patch.object(cutover, "frappe", SimpleNamespace(get_all=lambda *a, **k: [row], db=db)):
			cutover.execute()
			cutover.execute()
		self.assertEqual(row.source_status, "Unverified")
		self.assertEqual(db.set_value.call_count, 2)

	def test_incomplete_or_invalid_payload_is_not_treated_as_cut_over(self):
		for payload in [None, "not-json", "[]", '{}', '{"order_details":null,"order_number":null}',
			'{"order_details":[],"order_number":"wrong"}']:
			self.assertFalse(cutover._already_observed_orders(payload))
