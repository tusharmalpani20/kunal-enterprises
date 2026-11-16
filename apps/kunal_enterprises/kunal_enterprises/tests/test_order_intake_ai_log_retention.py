"""Retention keeps up with daily traffic while preserving metrics and live calls."""
from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from kunal_enterprises.integrations import order_intake_ai_log_retention as retention
from kunal_enterprises.integrations.order_intake_ai_logging import RUN, CALL


class TestAILogRetentionBatches(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.previous_in_test = frappe.flags.in_test
		frappe.flags.in_test = True
		frappe.db.set_single_value("Order Intake Settings", "log_payload_retention_days", 30)

	def tearDown(self):
		frappe.db.rollback()
		frappe.flags.in_test = self.previous_in_test

	def logs(self, count, active=False):
		stamp = now_datetime() if active else datetime(2000, 1, 1)
		names = ["retention-audit-" + uuid4().hex for _ in range(count)]
		frappe.db.bulk_insert(RUN, ["name", "status", "started_at", "finished_at", "input_snapshot", "input_tokens", "wire_attempts", "estimated_cost_usd"],
			[(name, "Running" if active else "Drafted", stamp, None if active else stamp, '{"input":"synthetic"}', 100, 1, .001) for name in names])
		frappe.db.bulk_insert(CALL, ["name", "parent", "parenttype", "parentfield", "idx", "state", "request_json", "response_json", "input_tokens"],
			[(uuid4().hex, name, RUN, "calls", 1, "Running" if active else "Responded", '{"input":"synthetic"}', '{"output":"synthetic"}', 100) for name in names])
		return names

	def purged(self, names):
		return frappe.db.count(RUN, {"name": ("in", names), "payloads_purged_at": ("is", "set")})

	def test_default_job_purges_more_than_one_hundred_expired_runs(self):
		names = self.logs(101)
		active = self.logs(1, active=True)[0]
		result = retention.cleanup()
		self.assertEqual(self.purged(names), 101)
		self.assertFalse(result["backlog_remaining"])
		self.assertEqual(frappe.db.get_value(RUN, active, "status"), "Running")
		self.assertEqual(frappe.db.get_value(RUN, names[0], "input_tokens"), 100)
		self.assertAlmostEqual(frappe.db.get_value(RUN, names[0], "estimated_cost_usd"), .001)
		self.assertFalse(frappe.db.get_value(CALL, {"parent": names[0]}, "request_json"))

	def test_batch_limit_reports_backlog_without_deleting_numeric_history(self):
		names = self.logs(5)
		result = retention.cleanup(max_runs=2, max_batches=1)
		self.assertEqual(self.purged(names), 2)
		self.assertEqual(result["batches"], 1)
		self.assertTrue(result["backlog_remaining"])
		self.assertEqual(frappe.db.count(RUN, {"name": ("in", names)}), 5)

	def test_time_budget_stops_between_batches_and_reports_remaining_work(self):
		names = self.logs(3)
		clock = iter((0, 0, 2))
		with patch.object(retention, "monotonic", side_effect=lambda: next(clock, 2)):
			result = retention.cleanup(max_runs=1, max_batches=20, time_budget_seconds=1)
		self.assertEqual(self.purged(names), 1)
		self.assertTrue(result["time_budget_reached"])
		self.assertTrue(result["backlog_remaining"])
