"""Real database tests use disposable fixtures and independent cleanup transactions."""

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from kunal_enterprises.cron import sync_history
from kunal_enterprises.cron.sync_history import cleanup_sync_history
from kunal_enterprises.integrations.reconciliation_settings import VOUCHER_CHECKPOINT_ORDER


class TestSyncHistory(FrappeTestCase):
	def setUp(self):
		self.now = now_datetime()
		self.prefix = "retention-" + uuid4().hex
		self.extra_errors = []
		self.saved_conf = dict(frappe.conf)
		self.clock = patch("kunal_enterprises.cron.sync_history.now_datetime", return_value=self.now)
		self.clock.start()
		frappe.conf.update(tally_sync_history_batch_size=100, tally_sync_history_max_batches=2)
	def tearDown(self):
		frappe.db.rollback()
		for table in ("Tally Sync Error", "Tally Stock Snapshot", "Tally Sync Run", "Tally Item"):
			frappe.db.delete(table, {"name": ("like", self.prefix + "%")})
		if self.extra_errors:
			frappe.db.delete("Tally Sync Error", {"name": ("in", self.extra_errors)})
		frappe.db.commit()
		frappe.conf.clear()
		frappe.conf.update(self.saved_conf)
		self.clock.stop()
	def run_record(self, status="Completed", age=40, sync_type="Stock", **extra):
		name = self.prefix + "-" + uuid4().hex
		when = self.now - timedelta(days=age)
		frappe.db.sql(
			"""INSERT INTO `tabTally Sync Run`
			(name, creation, modified, sync_type, status, started_at, finished_at)
			VALUES (%s,%s,%s,%s,%s,%s,%s)""",
			(name, when, when, sync_type, status, when, when),
		)
		if extra:
			frappe.db.set_value("Tally Sync Run", name, extra, update_modified=False)
		return name
	def error(self, run, resolved=False, age=100, timestamp=True):
		name = self.prefix + "-" + uuid4().hex
		when = self.now - timedelta(days=age)
		frappe.db.sql(
			"""INSERT INTO `tabTally Sync Error`
			(name, sync_run, error_message, detected_at, resolved, resolved_at)
			VALUES (%s,%s,'test error',%s,%s,%s)""",
			(name, run, when, int(resolved), when if resolved and timestamp else None),
		)
		return name
	def cleanup(self, **kwargs):
		frappe.db.commit()
		result = cleanup_sync_history(**kwargs)
		frappe.db.rollback()  # Observe the independent cleanup connection's commits.
		return result
	def test_age_policy_and_running_runs(self):
		old = self.run_record()
		boundary = self.run_record(age=30)
		failed = self.run_record(status="Failed", age=91)
		recent_failure = self.run_record(status="Failed", age=40)
		with_errors = self.run_record(status="Completed With Errors", age=91)
		running = self.run_record(status="Running", age=200)
		self.cleanup()
		for name in (old, failed, with_errors):
			self.assertFalse(frappe.db.exists("Tally Sync Run", name))
		for name in (boundary, recent_failure, running):
			self.assertTrue(frappe.db.exists("Tally Sync Run", name))
	def test_errors_keep_parents_until_resolved_and_expired(self):
		unresolved = self.run_record(age=120)
		self.error(unresolved)
		recent = self.run_record(age=120)
		self.error(recent, resolved=True, age=20)
		unknown_date = self.run_record(age=120)
		self.error(unknown_date, resolved=True, timestamp=False)
		expired = self.run_record(age=120)
		error = self.error(expired, resolved=True)
		running = self.run_record(status="Running", age=120)
		running_error = self.error(running, resolved=True)
		self.cleanup()
		for name in (unresolved, recent, unknown_date, running):
			self.assertTrue(frappe.db.exists("Tally Sync Run", name))
		self.assertTrue(frappe.db.exists("Tally Sync Error", running_error))
		self.assertFalse(frappe.db.exists("Tally Sync Error", error))
		self.assertFalse(frappe.db.exists("Tally Sync Run", expired))
	def test_stock_and_import_checkpoints_survive(self):
		stock = self.run_record(age=120)
		frappe.db.sql(
			"INSERT INTO `tabTally Stock Snapshot` (name, source_sync_run) VALUES (%s,%s)",
			(self.prefix + "-stock", stock),
		)
		master_old = self.run_record(age=120, sync_type="Masters")
		master_latest = self.run_record(age=110, sync_type="Masters")
		voucher = self.run_record(age=120, sync_type="Vouchers", source_table="trn_voucher",
			source_refreshed_at=self.now)
		newer_voucher = self.run_record(age=110, sync_type="Vouchers", source_table="trn_voucher",
			source_refreshed_at=self.now - timedelta(days=1))
		reconciliation = self.run_record(age=100, sync_type="Reconciliation", source_table="trn_voucher")
		self.cleanup()
		for name in (stock, master_latest, voucher, reconciliation):
			self.assertTrue(frappe.db.exists("Tally Sync Run", name))
		for name in (master_old, newer_voucher):
			self.assertFalse(frappe.db.exists("Tally Sync Run", name))
	def test_preview_batch_limits_and_repeat_calls(self):
		frappe.conf.update(tally_sync_history_batch_size=1, tally_sync_history_max_batches=1)
		runs = [self.run_record(age=120) for _ in range(3)]
		errors = [self.error(run, resolved=True) for run in runs]
		self.cleanup(dry_run=True)
		self.assertTrue(all(frappe.db.exists("Tally Sync Error", name) for name in errors))
		result = self.cleanup()
		self.assertEqual(result["errors_deleted"], 1)
		self.assertEqual(result["runs_deleted"], 1)
		self.assertEqual(sum(bool(frappe.db.exists("Tally Sync Run", name)) for name in runs), 2)
		self.cleanup()
		self.cleanup()
		self.assertEqual(self.cleanup()["runs_deleted"], 0)
	def test_disable_and_invalid_settings_do_not_delete(self):
		run = self.run_record()
		frappe.conf.tally_sync_history_cleanup_enabled = False
		self.assertEqual(self.cleanup()["status"], "Disabled")
		self.assertTrue(frappe.db.exists("Tally Sync Run", run))
		frappe.conf.tally_sync_history_cleanup_enabled = True
		frappe.conf.tally_sync_history_success_days = -1
		with self.assertRaises(ValueError):
			self.cleanup()
		self.assertTrue(frappe.db.exists("Tally Sync Run", run))

	def test_recent_completion_missing_dates_and_error_boundary_survive(self):
		recent = self.run_record(age=120, finished_at=self.now)
		missing = self.run_record(age=120, finished_at=None)
		run = self.run_record(age=120)
		error = self.error(run, resolved=True, age=90)
		self.cleanup()
		for name in (recent, missing, run):
			self.assertTrue(frappe.db.exists("Tally Sync Run", name))
		self.assertTrue(frappe.db.exists("Tally Sync Error", error))
	def test_reconciliation_checkpoint_survives_a_newer_voucher(self):
		reconciliation = self.run_record(age=120, sync_type="Reconciliation")
		self.run_record(age=110, sync_type="Vouchers", source_table="trn_voucher")
		self.cleanup()
		self.assertTrue(frappe.db.exists("Tally Sync Run", reconciliation))
	def test_overlap_skips_and_business_rows_are_untouched(self):
		run = self.run_record(age=120)
		item = self.prefix + "-item"
		frappe.db.sql("INSERT INTO `tabTally Item` (name, item_name) VALUES (%s,%s)", (item, "Kept"))
		# A separate lock object holds the same distributed lock as another worker would.
		lock = frappe.cache().lock(frappe.cache().make_key("kunal:tally-sync-history-cleanup"), timeout=60)
		with lock:
			self.assertEqual(self.cleanup()["status"], "Skipped")
			self.assertTrue(frappe.db.exists("Tally Sync Run", run))
		self.cleanup()
		self.assertFalse(frappe.db.exists("Tally Sync Run", run))
		self.assertEqual(frappe.db.get_value("Tally Item", item, "item_name"), "Kept")

	def test_scheduler_entrypoint_commits_cleanup(self):
		run = self.run_record(age=120)
		error = self.error(run, resolved=True)
		frappe.db.commit()
		cleanup_sync_history()
		connection = frappe.db.get_connection()
		try:
			with connection.cursor() as cursor:
				cursor.execute("SELECT name FROM `tabTally Sync Error` WHERE name=%s", (error,))
				self.assertIsNone(cursor.fetchone())
				cursor.execute("SELECT name FROM `tabTally Sync Run` WHERE name=%s", (run,))
				self.assertIsNone(cursor.fetchone())
		finally:
			connection.close()

	def test_failed_batch_rolls_back_deleted_errors(self):
		run = self.run_record(age=120)
		error = self.error(run, resolved=True)
		with patch("kunal_enterprises.cron.sync_history._expired_runs", side_effect=RuntimeError("injected failure")):
			with self.assertRaisesRegex(RuntimeError, "injected failure"):
				self.cleanup()
		self.assertTrue(frappe.db.exists("Tally Sync Error", error))
		self.assertTrue(frappe.db.exists("Tally Sync Run", run))

	def test_caller_writes_are_not_committed(self):
		run = self.run_record(age=120)
		frappe.db.commit()
		item = self.prefix + "-pending-item"
		frappe.db.sql("INSERT INTO `tabTally Item` (name, item_name) VALUES (%s,%s)", (item, "Pending"))
		cleanup_sync_history()
		connection = frappe.db.get_connection()
		try:
			with connection.cursor() as cursor:
				cursor.execute("SELECT name FROM `tabTally Item` WHERE name=%s", (item,))
				self.assertIsNone(cursor.fetchone())
				cursor.execute("SELECT name FROM `tabTally Sync Run` WHERE name=%s", (run,))
				self.assertIsNone(cursor.fetchone())
		finally:
			connection.close()
		self.assertTrue(frappe.db.exists("Tally Item", item))

	def test_stale_caller_view_does_not_delete_a_reopened_error(self):
		run = self.run_record(age=120)
		error = self.error(run, resolved=True)
		frappe.db.commit()
		self.assertEqual(frappe.db.get_value("Tally Sync Error", error, "resolved"), 1)
		connection = frappe.db.get_connection()
		try:
			with connection.cursor() as cursor:
				cursor.execute("UPDATE `tabTally Sync Error` SET resolved=0,resolved_at=NULL WHERE name=%s", (error,))
			connection.commit()
		finally:
			connection.close()
		cleanup_sync_history()
		# Cleanup neither commits nor resets this caller's old read view.
		self.assertEqual(frappe.db.get_value("Tally Sync Error", error, "resolved"), 1)
		frappe.db.rollback()
		self.assertEqual(frappe.db.get_value("Tally Sync Error", error, "resolved"), 0)
		self.assertTrue(frappe.db.exists("Tally Sync Run", run))

	def test_transient_failure_rolls_back_then_retries_a_batch(self):
		run = self.run_record(age=120)
		error = self.error(run, resolved=True)
		original = sync_history._expired_runs
		calls = []
		def transient(*args, **kwargs):
			calls.append(1)
			if len(calls) == 1:
				raise frappe.db.OperationalError(1213, "injected deadlock after error deletion")
			return original(*args, **kwargs)
		with patch.object(sync_history, "_expired_runs", side_effect=transient):
			result = self.cleanup()
		self.assertEqual(result["errors_deleted"], 1)
		self.assertEqual(result["runs_deleted"], 1)
		self.assertFalse(frappe.db.exists("Tally Sync Error", error))

	def test_tied_voucher_refreshes_preserve_the_same_checkpoint_as_imports(self):
		older = self.run_record(age=120, sync_type="Vouchers", source_table="trn_voucher",
			source_refreshed_at=self.now, source_metadata='{"period_from":"2024-01-01"}')
		newer = self.run_record(age=110, sync_type="Vouchers", source_table="trn_voucher",
			source_refreshed_at=self.now, source_metadata='{"period_from":"2025-01-01"}')
		selected = frappe.db.get_value("Tally Sync Run",
			{"sync_type": "Vouchers", "status": "Completed", "source_table": "trn_voucher"},
			"name", order_by=VOUCHER_CHECKPOINT_ORDER)
		self.assertEqual(selected, newer)
		self.cleanup()
		self.assertTrue(frappe.db.exists("Tally Sync Run", newer))
		self.assertFalse(frappe.db.exists("Tally Sync Run", older))


	def test_exhausted_retries_preserve_the_uncommitted_batch(self):
		run = self.run_record(age=120)
		error = self.error(run, resolved=True)
		with patch.object(sync_history, "_expired_runs",
			side_effect=frappe.db.OperationalError(1213, "injected deadlock")) as failed:
			with self.assertRaises(frappe.db.OperationalError):
				self.cleanup()
		self.assertEqual(failed.call_count, 3)
		self.assertTrue(frappe.db.exists("Tally Sync Error", error))
		self.assertTrue(frappe.db.exists("Tally Sync Run", run))

	def test_error_insert_cannot_reference_a_run_deleted_after_link_validation(self):
		from frappe.model.document import Document

		run = self.run_record(age=120)
		frappe.db.commit()
		error = frappe.get_doc({"doctype": "Tally Sync Error", "sync_run": run,
			"error_message": "concurrent reference", "detected_at": self.now})
		validate_links = Document._validate_links
		def cleanup_after_link_validation(document, *args, **kwargs):
			validate_links(document, *args, **kwargs)
			if document is error:
				cleanup_sync_history()
		try:
			with patch.object(Document, "_validate_links", new=cleanup_after_link_validation):
				with self.assertRaises((frappe.LinkValidationError, frappe.QueryDeadlockError)):
					error.insert(ignore_permissions=True)
		finally:
			if error.name:
				self.extra_errors.append(error.name)
		frappe.db.rollback()
		self.assertFalse(frappe.db.exists("Tally Sync Run", run))
		self.assertFalse(frappe.db.exists("Tally Sync Error", {"sync_run": run}))

	def test_resolution_timestamp_transitions(self):
		run = self.run_record(status="Failed")
		error = frappe.get_doc({"doctype": "Tally Sync Error", "sync_run": run,
			"error_message": "test", "detected_at": self.now}).insert(ignore_permissions=True)
		self.extra_errors.append(error.name)
		error.resolved = 1
		error.save(ignore_permissions=True)
		self.assertIsNotNone(error.resolved_at)
		resolved_at = error.resolved_at
		error.resolution_note = "Checked"
		error.resolved_at = self.now - timedelta(days=200)
		error.save(ignore_permissions=True)
		self.assertEqual(error.resolved_at, resolved_at)
		error.resolved = 0
		error.save(ignore_permissions=True)
		self.assertIsNone(error.resolved_at)
