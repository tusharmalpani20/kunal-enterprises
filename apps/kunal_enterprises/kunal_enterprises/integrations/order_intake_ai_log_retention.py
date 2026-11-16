"""Bounded payload expiry retains numeric AI usage and estimated-spend history."""
import frappe
import math
from time import monotonic
from frappe.utils import add_to_date, now_datetime, cint

from kunal_enterprises.integrations.order_intake_ai_logging import Writer, RUN, CALL, PAYLOAD_FIELDS


def cleanup(max_runs=100, max_batches=20, time_budget_seconds=30):
	"""Expire payloads in short batches without committing any caller writes.

	The time budget is checked between batches; queries already in progress
	finish their current bounded batch. Numeric call/run history is retained.
	"""
	now = now_datetime()
	days = cint(frappe.db.get_single_value("Order Intake Settings", "log_payload_retention_days") or 30)
	cutoff = add_to_date(now, days=-days, as_datetime=True)
	stale = add_to_date(now, days=-1, as_datetime=True)
	writer = Writer(not frappe.flags.in_test)
	batch_size = min(max(cint(max_runs), 1), 100)
	batch_limit = min(max(cint(max_batches), 1), 50)
	seconds = float(time_budget_seconds)
	if not math.isfinite(seconds) or seconds < 0:
		raise ValueError("The cleanup time budget must be finite and non-negative")
	seconds = min(seconds, 60)
	started = monotonic()
	result = dict(payloads_purged=0, interrupted=0, batches=0, time_budget_reached=False)
	for _ in range(batch_limit):
		if monotonic() - started >= seconds:
			result["time_budget_reached"] = True
			break
		batch = _cleanup_batch(writer, now, stale, cutoff, batch_size)
		result["batches"] += 1
		for field in ("payloads_purged", "interrupted"):
			result[field] += batch[field]
		if batch["payloads_purged"] < batch_size and batch["interrupted"] < batch_size:
			break
	result["backlog_remaining"] = _has_backlog(writer, stale, cutoff)
	return result


def _cleanup_batch(writer, now, stale, cutoff, batch_size):
	with writer.transaction() as cursor:
		cursor.execute(f"""SELECT name FROM `tab{RUN}` WHERE status IN ('Running','Awaiting Commit')
			AND started_at < %s ORDER BY started_at LIMIT %s FOR UPDATE""", (stale, batch_size))
		interrupted = [row[0] for row in cursor.fetchall()]
		for name in interrupted:
			writer.update(cursor, RUN, name, dict(status="Interrupted", finished_at=now,
				error_note="The worker did not finalize this run; publication and unknown usage require review.", created_request_count=0, updated_request_count=0))
			cursor.execute(f"UPDATE `tab{CALL}` SET state='Interrupted',finished_at=%s WHERE parent=%s AND state='Running'", (now, name))
		cursor.execute(f"""SELECT name FROM `tab{RUN}` WHERE status NOT IN ('Running','Awaiting Commit')
			AND started_at < %s AND payloads_purged_at IS NULL ORDER BY started_at LIMIT %s FOR UPDATE""", (cutoff, batch_size))
		names = [row[0] for row in cursor.fetchall()]
		for name in names:
			cursor.execute(f"UPDATE `tab{CALL}` SET {','.join('`' + field + '`=NULL' for field in PAYLOAD_FIELDS)} WHERE parent=%s", (name,))
			writer.update(cursor, RUN, name, dict(input_snapshot=None, stages_json=None, result_json=None, sender=None, payloads_purged_at=now))
	return dict(payloads_purged=len(names), interrupted=len(interrupted))


def _has_backlog(writer, stale, cutoff):
	# Existence checks expose a bounded run/time cap without counting a large
	# historical ledger or silently claiming the retention queue is drained.
	with writer.transaction() as cursor:
		cursor.execute(f"""SELECT name FROM `tab{RUN}` WHERE status IN ('Running','Awaiting Commit')
			AND started_at < %s LIMIT 1""", (stale,))
		if cursor.fetchall():
			return True
		cursor.execute(f"""SELECT name FROM `tab{RUN}` WHERE status NOT IN ('Running','Awaiting Commit')
			AND started_at < %s AND payloads_purged_at IS NULL LIMIT 1""", (cutoff,))
		return bool(cursor.fetchall())
