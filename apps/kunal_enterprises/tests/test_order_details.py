import unittest

from kunal_enterprises.integrations.order_details import order_candidates


class OrderDetailsTests(unittest.TestCase):
	def test_unknown_is_not_empty(self):
		self.assertTrue(order_candidates(None, None)[1])
		self.assertEqual(order_candidates([], None), ([], ""))

	def test_one_number_and_repeated_entries(self):
		self.assertEqual(order_candidates([
			{"order_number": " KE-SO-00018-26-27 ", "order_date": "2026-09-02"},
			{"order_number": "KE-SO-00018-26-27", "order_date": None},
		], "KE-SO-00018-26-27"), (["KE-SO-00018-26-27"], ""))

	def test_multiple_numbers_retain_all_candidates(self):
		candidates, reason = order_candidates([{"order_number": "A"}, {"order_number": "B"}], None)
		self.assertEqual(candidates, ["A", "B"])
		self.assertTrue(reason)

	def test_bad_contracts_fail(self):
		for details, number in (
			(None, "A"), ([], "A"), ({}, None), ([{}], None),
			([{"order_number": "A"}], "B"),
			([{"order_number": "A", "order_date": "2026-02-30"}], "A"),
			([{"order_number": "A", "order_date": "2026-W01-1"}], "A"),
			([{"order_number": "A\tB", "order_date": None}], "A\tB"),
			([{"order_number": "A"}, {"order_number": "B"}], "A"),
		):
			with self.subTest(details=details, number=number), self.assertRaises(ValueError):
				order_candidates(details, number)
