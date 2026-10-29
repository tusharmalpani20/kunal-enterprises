"""Bounded retention of diagnostic history, preserving state needed by future syncs."""

from time import monotonic

import frappe
from frappe.utils import add_days, now_datetime

from kunal_enterprises.integrations.reconciliation_settings import VOUCHER_CHECKPOINT_ORDER


CONFIG_PREFIX = "tally_sync_history_"
RETRYABLE_DATABASE_ERRORS = {1020, 1205, 1213}  # Changed read, lock wait timeout, deadlock.


def cleanup_sync_history(dry_run=False):
	"""Daily job with isolated, bounded transactions; never commit the caller's writes.

	Dry runs report only the next bounded batch without deleting anything.
	Resolved errors expire independently; a parent stays until all its errors expire.
	"""
	enabled = str(frappe.conf.get(CONFIG_PREFIX + "cleanup_enabled", True)).lower()
	if enabled not in {"true", "1", "on", "yes", "false", "0", "off", "no"}:
		raise ValueError("tally_sync_history_cleanup_enabled must be a boolean")
	if enabled in {"false", "0", "off", "no"}:
		return {"status": "Disabled", "errors_deleted": 0, "runs_deleted": 0}

	now = now_datetime()
	params = {
		"success_cutoff": add_days(now, -_setting("success_days", 30)),
		"failure_cutoff": add_days(now, -_setting("failure_days", 90)),
		"error_cutoff": add_days(now, -_setting("resolved_error_days", 90)),
		"batch_size": _setting("batch_size", 500, maximum=1000),
	}
	max_batches = _setting("max_batches", 20, maximum=50)
	lock = frappe.cache().lock(frappe.cache().make_key("kunal:tally-sync-history-cleanup"), timeout=600)
	if not lock.acquire(blocking=False):
		return {"status": "Skipped", "reason": "Cleanup is already running"}

	connection = None
	result = {"status": "Preview" if dry_run else "Completed", "errors_deleted": 0, "runs_deleted": 0}
	started = monotonic()
	try:
		connection = frappe.db.get_connection()
		connection.autocommit(False)
		with connection.cursor() as cursor:
			# A request/job may already hold a stale repeatable-read view. Use a fresh
			# connection and READ COMMITTED for checkpoint checks and locking reads.
			cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
			cursor.execute("SET SESSION innodb_lock_wait_timeout = 5")
			for _ in range(max_batches):
				for attempt in range(3):
					try:
						batch = _cleanup_batch(cursor, params, dry_run)
						if not dry_run:
							connection.commit()
						break
					except Exception as error:
						connection.rollback()
						if not error.args or error.args[0] not in RETRYABLE_DATABASE_ERRORS or attempt == 2:
							raise
				if dry_run:
					result.update(batch)
					break
				for key in ("errors_deleted", "runs_deleted"):
					result[key] += batch[key]
				if not any(batch.values()) or monotonic() - started >= 45:
					break
		return result
	finally:
		try:
			if connection is not None:
				connection.close()  # Also ends a read-only preview transaction.
		finally:
			lock.release()


def _cleanup_batch(cursor, params, dry_run):
	params["checkpoints"] = tuple(_checkpoint_runs(cursor)) or ("",)
	errors = _expired_errors(cursor, params, lock_rows=not dry_run)
	errors_deleted = _delete(cursor, "Tally Sync Error", errors) if not dry_run else 0
	runs = _expired_runs(cursor, params, lock_rows=not dry_run)
	if dry_run:
		return {"expired_errors_in_next_batch": len(errors), "empty_runs_in_next_batch": len(runs)}

	# Current locking reads recheck dependencies after candidate row locks have
	# been acquired, including an error committed while we waited for its parent.
	blocked = set()
	if runs:
		for table, field in (("Tally Sync Error", "sync_run"), ("Tally Stock Snapshot", "source_sync_run")):
			cursor.execute(f"SELECT `{field}` FROM `tab{table}` WHERE `{field}` IN %s FOR UPDATE", (tuple(runs),))
			blocked.update(row[0] for row in cursor.fetchall())
	return {
		"errors_deleted": errors_deleted,
		"runs_deleted": _delete(cursor, "Tally Sync Run", [name for name in runs if name not in blocked]),
	}


def _delete(cursor, doctype, names):
	if not names:
		return 0
	cursor.execute(f"DELETE FROM `tab{doctype}` WHERE name IN %s", (tuple(names),))
	return cursor.rowcount


def _setting(name, default, maximum=None):
	key = CONFIG_PREFIX + name
	value = frappe.conf.get(key, default)
	if not str(value).isdigit() or int(value) < 1 or (maximum and int(value) > maximum):
		raise ValueError(f"{key} must be a positive integer" + (f" no greater than {maximum}" if maximum else ""))
	return int(value)


def _checkpoint_runs(cursor):
	"""These readers use run metadata as state, not just as an audit trail."""
	lookups = [
		("sync_type='Masters' AND status='Completed'", "creation desc, name desc"),
		("sync_type='Reconciliation' AND status IN ('Completed','Completed With Errors')", "creation desc, name desc"),
		("sync_type='Vouchers' AND status='Completed' AND source_table='trn_voucher'", VOUCHER_CHECKPOINT_ORDER),
		("sync_type IN ('Vouchers','Reconciliation') AND status IN ('Completed','Completed With Errors') "
			"AND source_table='trn_voucher'", "creation desc, name desc"),
	]
	names = set()
	for condition, order in lookups:
		cursor.execute(f"SELECT name FROM `tabTally Sync Run` WHERE {condition} ORDER BY {order} LIMIT 1")
		row = cursor.fetchone()
		if row:
			names.add(row[0])
	return names


def _expired_errors(cursor, params, lock_rows):
	# The join locks both selected errors and their parents, preserving running runs.
	cursor.execute(
		"""
		SELECT error.name FROM `tabTally Sync Error` error
		LEFT JOIN `tabTally Sync Run` parent ON parent.name = error.sync_run
		WHERE error.resolved = 1 AND error.resolved_at < %(error_cutoff)s
			AND (parent.name IS NULL OR COALESCE(parent.status, '') != 'Running')
		ORDER BY error.resolved_at, error.name
		LIMIT %(batch_size)s
		""" + (" FOR UPDATE" if lock_rows else ""), params,
	)
	return [row[0] for row in cursor.fetchall()]


def _expired_runs(cursor, params, lock_rows):
	cursor.execute(
		"""
		SELECT run.name FROM `tabTally Sync Run` run
		WHERE (
			(run.status = 'Completed' AND run.finished_at < %(success_cutoff)s)
			OR (run.status IN ('Failed', 'Completed With Errors') AND run.finished_at < %(failure_cutoff)s)
		)
			AND run.name NOT IN %(checkpoints)s
			AND NOT EXISTS (SELECT 1 FROM `tabTally Sync Error` error WHERE error.sync_run = run.name)
			AND NOT EXISTS (
				SELECT 1 FROM `tabTally Stock Snapshot` stock WHERE stock.source_sync_run = run.name
			)
		ORDER BY run.finished_at, run.name
		LIMIT %(batch_size)s
		""" + (" FOR UPDATE" if lock_rows else ""), params,
	)
	return [row[0] for row in cursor.fetchall()]
