# Tally sync history retention

A daily long-queue job removes expired diagnostic rows from **Tally Sync Error** and
**Tally Sync Run**. It does not delete items, stock, customers, vouchers, orders, or
reconciliation audit records. It does not connect to Tally or start imports.

## Default policy

- Completed runs: 30 days after `finished_at`.
- Failed / Completed With Errors runs: 90 days after `finished_at`.
- Resolved errors: 90 days after `resolved_at`.
- Unresolved errors and their parent runs remain. A parent also remains while any
  error is recently resolved or has no resolution timestamp.
- Running runs, terminal runs without a finish date, stock-source runs, and the
  latest master/voucher/reconciliation checkpoints remain regardless of age.

Marking an error resolved records the resolution time. Reopening clears that time;
resolving again starts a new retention window. Older resolved rows without a
resolution time are retained; saving them records a new time rather than assuming
that they are already safe to delete.

Cleanup deletes errors before empty parent runs, locks selected rows, and commits
small batches on a separate database connection. It neither commits nor resets
the caller's transaction. READ COMMITTED isolation avoids stale snapshots during
concurrent sync, and lock/deadlock failures roll back the current batch and retry
up to three times. Other failures roll back that batch and propagate; previously
completed batches remain committed. It uses a distributed lock to avoid overlapping cleanup jobs. The
default limit is 20 batches of up to 500 errors and 500 runs each; it stops between
batches after 45 seconds. Further eligible history is left for the next daily run.
No table rebuild or automatic database-file compaction is performed.

## Settings

Optional per-site keys in `site_config.json`:

```json
{
  "tally_sync_history_cleanup_enabled": true,
  "tally_sync_history_success_days": 30,
  "tally_sync_history_failure_days": 90,
  "tally_sync_history_resolved_error_days": 90,
  "tally_sync_history_batch_size": 500,
  "tally_sync_history_max_batches": 20
}
```

Retention periods must be positive integers. Batch size is capped at 1,000 and
batch count at 50. Invalid settings abort cleanup before it deletes anything.

From the target bench, register the scheduler hook and indexes with:

```bash
bench --site <site> migrate
```

Migration only adds indexes and registers the job; it does not run cleanup. Adding
indexes to a large existing history table can take time; plan the production
migration accordingly. Regular execution requires the site's scheduler and a long
queue worker. The restored offline site's scheduler remains disabled.

Preview the next bounded batch without changing data:

```bash
bench --site <site> execute kunal_enterprises.cron.sync_history.cleanup_sync_history --kwargs '{"dry_run": 1}'
```

The preview reports expired errors and already-empty runs in the next batch, not
total backlog counts. A real pass may additionally remove parents made empty by
its error deletions. To perform a manual pass after reviewing the preview:

```bash
bench --site <site> execute kunal_enterprises.cron.sync_history.cleanup_sync_history
```

Invoke manual cleanup in a fresh command, without a caller holding locks on the
history being cleaned. Manual cleanup is independent of import/scheduler enablement. It never enables
Tally sync. Keep a backup before the first cleanup of production history.

## Limits

Unresolved errors are intentionally retained. The existing unresolved backlog needs
investigation/resolution; this policy neither deduplicates recurring errors nor
marks them resolved automatically. Deletion makes InnoDB space reusable but does
not necessarily shrink existing database files on disk.

## Verification

Run real-database retention tests on a disposable Frappe site with the app installed:

```bash
bench --site <test-site> run-tests --module kunal_enterprises.tests.test_sync_history --skip-test-records --skip-before-tests
```
