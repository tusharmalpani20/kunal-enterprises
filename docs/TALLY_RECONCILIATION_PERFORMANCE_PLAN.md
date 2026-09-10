# Tally–Frappe reconciliation performance and safety plan

**Status:** Audited implementation plan; no code or production behavior has been changed by this document.

**Prepared:** 10 September 2026

## 1. Purpose

Reduce the Frappe Tally import/reconciliation pipeline from the observed roughly
24-minute run time to comfortably below its five-minute schedule for ordinary
no-change or small-change runs, without weakening any of the current correction,
uncertain-source, legacy-data, or atomicity safeguards.

The measured 9 September run spent about 20 minutes reconciling 11,170 vouchers.
The main cost is not PostgreSQL: Frappe loads each voucher as a separate document
and performs a separate latest-log query for each voucher. Almost all vouchers
currently have no usable order number, but every one is reconsidered on every
run.

This plan deliberately preserves a full reconciliation path. Incremental
reconciliation becomes the frequent path only after result parity is proven.

### Audit disposition

This plan was checked against the current voucher snapshot application,
reconciliation engine, scheduler, Order controls, DocTypes, migration patches
and correction tests. The audit identified and incorporated the following
requirements that were missing or underspecified in the first draft:

- configuration and reconciliation-algorithm changes must invalidate incremental
  state and force a full pass;
- reconciliation-log deduplication is keyed by **both** Order and voucher,
  including a null Order, not by voucher alone;
- the Redis lock lease and worker timeout require independent safety headroom and
  must never expire while a valid job is still running;
- work claimed by a run, work created concurrently, and affected Order rows need
  explicit transactional/locking rules;
- an Order created after its voucher, and Customer/master changes outside voucher
  import, require durable invalidation;
- unchanged Unverified/held vouchers must not be document-saved thousands of
  times merely to refresh observation metadata;
- a successful full safety pass must report differences before repairing them,
  or it cannot detect a missed incremental invalidation;
- enabling incremental mode while durable work is corrupt, too old, ambiguous or
  unavailable must fall back to full mode.

## 2. Current behavior and bottleneck

The five-minute scheduler enqueues one sequential long-worker pipeline:

1. Import all Tally masters.
2. Import the complete stock snapshot.
3. Read and apply the voucher mirror snapshot.
4. Reconcile all managed orders and all imported vouchers.

The voucher apply and reconciliation are protected by the same Redis lock and
commit together. This is important: an accepted voucher correction must never be
committed while the related order still has old totals.

The current reconciliation implementation in `cron/reconciliation.py`:

- fetches every Tally Voucher name and calls `frappe.get_doc` once per voucher;
- fetches Orders and Customers separately;
- calls `frappe.db.get_value` for the latest reconciliation log once per voucher;
- may save a voucher and insert a log when its outcome changes;
- scans all vouchers again to assign unmatched/error outcomes and clear pending
  reference history.

This is an N+1 query/document-loading pattern. On the measured live data, 11,169
of 11,170 eligible vouchers had no extracted order details, amplifying that cost.

## 3. Non-negotiable correctness invariants

Every implementation phase must retain these rules:

1. **Identity:** a source voucher is identified by source company plus Tally
   voucher GUID. Voucher number is only a mutable display value.
2. **Allowlist:** only the configured Delivery Challan voucher-type GUIDs can
   contribute fulfillment.
3. **Atomic publication:** voucher source changes, affected order quantities and
   reconciliation outcomes commit together, or all roll back together.
4. **Serialized history:** the existing import lock and stale-transaction check
   remain in place. An older MariaDB transaction must not overwrite a newer
   reconciliation.
5. **Current-state totals:** quantities are rebuilt from accepted voucher state;
   repeated imports never accumulate the same voucher twice.
6. **Reference corrections:** when a voucher moves from one order reference to
   another, both the old and new orders are recalculated.
7. **Connected holds:** `source_pending_references` is a transitive graph. If one
   related voucher/reference is uncertain, the entire connected reference group
   remains frozen until it is safe to rebuild every affected order atomically.
8. **Uncertain source:** missing headers, missing inventory, missing type GUIDs,
   and unresolved item/godown mappings preserve previously accepted quantities
   and put affected orders into Manual Review. Absence is not treated as deletion.
9. **Legacy protection:** fulfilled legacy vouchers without verified Tally
   identity prevent destructive recalculation of their related orders.
10. **Order status:** explicit Cancelled and Partially Closed statuses survive
    reconciliation. Other managed statuses continue to follow the current
    fulfillment evaluator.
11. **Derived mappings:** a newly available or corrected item, godown, ledger, or
    customer GUID mapping must cause the affected voucher/order to be reconsidered
    even when the raw PostgreSQL voucher JSON is unchanged.
12. **Late order creation:** creating an Order after its matching voucher was
    already imported must still reconcile that order.
13. **Idempotency and audit:** unchanged outcomes must not create duplicate
    reconciliation logs or needless Version records.
14. **Recovery:** a full reconciliation remains available to repair any missed
    invalidation and to validate the incremental path.
15. **Configuration/version invalidation:** changes to the source company,
    fulfillment allowlist, reconciliation schema, or evaluation algorithm cannot
    reuse an older incremental watermark or scope. An incompatible company
    change still aborts and requires the existing explicit migration; it is not
    made safe merely by selecting full scope.
16. **Concurrency:** a web request changing an affected Order while a run is in
    progress must not be silently overwritten or have its invalidation deleted.
17. **Audit identity:** latest-log comparison is scoped to the exact `(order,
    voucher)` pair. The same voucher can legitimately have audit history against
    different Orders after a reference correction.
18. **Source validation:** the current repeatable-read PostgreSQL observation,
    mirror completeness checks, checkpoint/history validation and older-snapshot
    rejection remain ahead of any apply/reconciliation optimization. AlterID
    alone is not a safe change detector because same-revision inventory
    corrections are supported.

## 4. Target architecture

Use one reconciliation engine with two scopes, rather than two independent
implementations:

- **Full scope:** all managed orders, all relevant references, and all vouchers.
- **Incremental scope:** an explicitly collected set of changed vouchers and
  affected references, expanded to the complete connected reference group.

Both scopes must call the same evaluation and write functions. Only scope
selection and bulk data loading should differ. This prevents behavior drift.

Define an explicit `RECONCILIATION_ALGORITHM_VERSION`. Persist it together with a
fingerprint of correctness-affecting configuration (at minimum source company
and the sorted fulfillment type GUID allowlist) on every successful run. Missing
or changed version/fingerprint forces full scope. A deployment that changes
evaluation, reference-graph, hold, or mapping semantics must bump the version.
The existing wrong-company check runs first: if configured company conflicts
with stored history, abort and require explicit migration rather than attempting
either reconciliation mode.

### 4.1 Change-set collection during voucher import

While applying a PostgreSQL voucher snapshot, collect a transaction-local change
set containing:

- voucher document names whose accepted data, observation, eligibility, source
  status, error, party mapping, order number, or mapped lines changed;
- the voucher's previous order number;
- its new order number and all order candidates from `order_details`;
- all existing `source_pending_references`;
- vouchers that newly become missing/unverified or recover from that state;
- orders newly marked as Tally-managed.

An unchanged raw payload is not automatically unchanged. The existing derived
ledger and line mappings must still be calculated and compared before a voucher
is excluded from the change set.

Pass this change set directly to reconciliation inside the current lock and
transaction. Do not commit an intermediate queue between snapshot application
and the related reconciliation.

### 4.2 Persistent invalidation for changes outside voucher import

Source import is not the only trigger. Add a small persistent reconciliation
work-item mechanism for changes such as:

- a new Order whose portal reference may match an existing voucher;
- changes to an Order's customer or requested items;
- changes to a Customer's Tally GUID/client-code relationship;
- changes or renames in relevant Tally item, godown, or customer-ledger masters;
- an external/manual Tally Voucher or voucher-line change, unless those writes
  are prohibited and enforced because these documents are source-managed;
- an operator requesting a Manual Review recheck.

Order hooks must cover insert and meaningful updates (customer, requested item,
requested quantity and any other evaluator input), using the before-save document
to enqueue both old and new affected references where applicable. Customer
identity changes must enqueue all managed Orders for that Customer. Relevant
ledger mapping changes must cover both vouchers carrying the party GUID and
Customers using the changed client code. Deletion/rename must either be rejected
by existing link rules or invalidate the pre-change references; it must not be an
unhandled path.

Each work item should have a deterministic key and contain a voucher and/or
reference, source company, reason, creation/last-seen time, a monotonically
increasing generation, and retry information. Hash normalized key components for
the document key instead of assuming a Tally/portal reference is a safe document
name. A unique deterministic key and atomic upsert must make duplicate
invalidations coalesce rather than grow the queue. Limit queue write/read
permissions to the integration and appropriate administrators.

Work is acknowledged only in the same transaction that successfully reconciles
its complete scope. A rollback must leave it available for retry. A durable
singleton/full marker follows the same acknowledgement rule.

Hooks must ignore reconciliation's own internal writes, otherwise saving an
Order would continuously re-enqueue itself. Use an explicit Frappe flag/context
guard for internal reconciliation writes.

The existing Manual Review resolution endpoint is synchronous: it runs a recheck
and then returns the resulting Order status. Preserve that contract by running a
scoped reconciliation for the requested Order while holding the normal lock;
merely enqueueing future work would make the API response misleading. The
Owner/Admin full-reconciliation endpoint must remain explicitly full scope.

For the first safe version, any master/customer change whose precise impact
cannot be established should enqueue a **full reconciliation required** marker.
It is better to run a slower safe pass occasionally than to guess an incomplete
scope. More precise invalidation can be added after production evidence.

Master import currently processes all master rows on every pipeline run, so
`records_processed` cannot be treated as evidence that all Orders are dirty.
Compare correctness-relevant stored values with incoming values and emit an
invalidation only for a semantic change. Otherwise a naive master hook would
force a full reconciliation every five minutes and eliminate the intended gain.

Site configuration does not pass through DocType hooks. At reconciliation start,
compare the persisted configuration/algorithm fingerprint described above. A
mismatch or missing prior fingerprint must prevent incremental scope and force a
full pass when the configuration is otherwise valid. An invalid allowlist or
company conflict must stop safely, never run against guessed settings.

### 4.3 Work claiming and concurrent writes

The persistent queue is an invalidation journal, not the source of business
truth. Use the following transaction rules:

1. Acquire the existing site-specific reconciliation Redis lock and ensure a
   fresh MariaDB transaction/history view.
2. Select a bounded, versioned set of work items for this run. Retain each
   `(name, generation)` (or an equivalent immutable claim token); never later
   delete the whole queue by filter.
3. Union claimed work with the transaction-local voucher-import change set.
4. Expand the complete connected scope.
5. Lock affected Order rows before reading evaluator inputs and writing totals.
   Use deterministic Order ordering to reduce deadlock risk.
6. Reconcile and conditionally acknowledge only the exact work-item generations
   claimed, in the same transaction as the resulting Order/voucher changes. An
   atomic upsert that increments a generation after selection makes the old
   acknowledgement fail and leaves the newer invalidation queued.
7. Work inserted after the claim remains queued for the next run. A rollback
   retains all claimed work.

If an affected Order cannot be locked or its `modified` value changes outside the
expected reconciliation write path, abort/retry instead of overwriting it. A web
transaction that completes after work selection must leave a durable work item;
the current run must not clear it accidentally. Exact names alone are not enough
when a deterministic queue row can be updated after selection; generation-aware
acknowledgement is required. Concurrency tests must exercise both commit
orderings and same-key re-enqueueing.

### 4.4 Connected-scope expansion

Incremental reconciliation cannot process only the directly changed voucher.
Construct a lightweight graph using bulk-loaded voucher headers:

- each voucher connects its current `order_number` to every value in
  `source_pending_references`;
- begin with all references and vouchers in the change set/work items;
- repeatedly include every voucher touching an included reference and every
  reference touched by those vouchers until the set stops growing;
- add legacy reconciled vouchers for included references;
- mark the full connected set blocked if any included voucher is Unverified or
  any included reference has an unidentified legacy contribution.

Only after this expansion should full voucher documents/lines and Orders be
loaded. This preserves multi-hop reference-transfer and frozen-quantity behavior
without loading all 11,170 complete documents.

Header-only scanning of the current 11,170 records is acceptable initially if it
is one or a few bulk queries. The main goal is to eliminate thousands of
individual document and log queries. If header scanning later becomes material,
the graph can be represented in indexed work/reference tables.

If a claimed work item has malformed references, the configuration/algorithm
fingerprint is unknown, the queue table is unavailable, the queue is older than
its safety threshold, or scope expansion exceeds a configured proportion of all
vouchers, switch the entire run to full scope and record the reason. Do not
silently drop malformed work and do not mix an uncertain partial scope with
committed writes.

This fallback applies to invalidation metadata, which can be bypassed because a
full pass derives scope from business records. Malformed business state such as
unparseable `source_pending_references` cannot be bypassed safely: abort the
transaction, record the offending voucher and require explicit repair.

### 4.5 Bulk reads and writes

Refactor data access so query count grows with the number of affected batches,
not the total number of vouchers:

1. Bulk-load voucher headers with only required fields.
2. Bulk-load child lines for scoped voucher parents in bounded chunks.
3. Bulk-load scoped Orders and Order Items.
4. Bulk-load Customers and fallback Tally Customer Ledgers needed by those
   Orders.
5. Bulk-load the latest Order Reconciliation Log outcome for every scoped
   **`(order, voucher)` pair**, including pairs whose Order is null, in one
   indexed query (or bounded batch queries). A voucher can have logs against old
   and new Orders after a reference transfer; partitioning only by voucher would
   suppress valid history or create duplicates.
6. Save only documents whose business fields changed. Do not update
   `reconciliation_last_attempt` through a document save when the outcome is
   otherwise unchanged; record run-level attempt time instead.
7. Insert only genuinely new audit outcomes. Preserve human-readable history.

The latest-log ordering must be deterministic and match existing semantics:
`created_at DESC, creation DESC`, with document name as a final tie-break if
timestamps can collide. Compare status, reason code and message for the exact
pair before inserting.

Optimize snapshot application as well as reconciliation. In particular,
`_hold` currently saves an Unverified voucher on every observation even when the
hold status, observation, reason, accepted data and reference set are unchanged.
Preserve required per-snapshot freshness metadata, but update it without a full
document validation/version cycle (prefer a measured bounded bulk update), and
do not emit a change-set entry unless reconciliation-relevant semantics changed.
Do not remove `source_snapshot_id`, `source_refreshed_at` or
`source_observation`; they are operational evidence.

Use Frappe query APIs where they provide bounded bulk access. Any direct SQL must
use parameters, work on both supported database behavior for this deployment,
and be covered by integration tests.

### 4.6 Database indexes

Do not add indexes speculatively. First capture `EXPLAIN` output and inspect
existing MariaDB indexes after migration. Likely candidates are:

- Tally Voucher: `(source_company, order_number)`;
- Tally Voucher: fields used to select pending/unverified work, if the final
  query needs them;
- Order Reconciliation Log: a composite index beginning with `(voucher, order)`
  and supporting deterministic newest-row selection by `created_at`/creation;
- Order: `tally_reconciliation_managed` only if full-scope selection is shown to
  scan a materially large table;
- work-item deterministic key/reference indexes.

The existing unique Order portal reference and unique `(source_company,
tally_guid)` voucher identity must be retained. Verify that Frappe's child-table
parent index is already sufficient before adding another line-table index.

### 4.7 Scheduling, leases and safety reconciliation

After rollout:

- keep the five-minute import schedule, using incremental reconciliation after
  voucher application;
- run a full reconciliation once nightly during the quietest period;
- keep the Owner/Admin manual full-reconciliation action;
- use the same serialization lock for incremental and full modes;
- keep scheduler/job deduplication so runs cannot overlap;
- give the nightly job a distinct job ID and an explicit retry/alert path if it
  cannot acquire the lock;
- do not reduce the current timeout until measured p95/p99 timings show safe
  headroom;
- treat the worker job timeout and Redis lock lease as separate settings. The
  lock must use a safely renewable lease or exceed the maximum permitted job
  duration plus cleanup margin. It must never expire while a valid job can still
  commit;
- keep the MariaDB import lock and Redis reconciliation lock acquisition order
  consistent across scheduled, nightly and manual entry points.

The current worker timeout is 1,500 seconds and the reconciliation Redis lock
lease is 1,800 seconds, while the measured full pipeline took about 24 minutes
and reconciliation alone took about 20 minutes. The job has almost no timeout
headroom, and the locked section also needs an explicit safety margin. Before
relying on a nightly full pass, give both the job and lock measured headroom; the
lock lease must remain longer than the job's hard timeout plus termination and
transaction-cleanup margin, not merely longer than the expected average.

The nightly pass is not permission to ignore invalidation bugs. Any parity
difference is an incident to diagnose; the full pass is a recovery and detection
safety net.

Before the nightly full pass writes repairs, calculate and record a concise
business-state diff against current stored state. Otherwise a full pass could
repair a missed incremental invalidation without revealing that incremental
selection was wrong. Alert on any unexplained correction.

## 5. Implementation phases

### Phase 0 — Baseline and observability

1. Add structured phase timings to Tally Sync Run metadata: header load, graph
   expansion, voucher-line load, order/customer load, evaluation, voucher writes,
   order writes, log reads/writes, snapshot hold writes, and commit.
2. Record reconciliation mode, candidate/scoped voucher counts, scoped reference
   and order counts, changed document counts, log insert counts, error counts and
   whether a full-fallback marker caused the run.
3. Capture database query counts in test/staging instrumentation.
4. Record at least several no-change and small-change baseline runs separately
   from the unusually heavy first allowlist run.
5. Record worker timeout, Redis lock lease, lock wait/contention and whether a
   run approached either deadline.

**Exit gate:** reliable phase timings and counts exist without changing outcomes.

### Phase 1 — Optimize the full path without changing scope

1. Extract scope selection, data loading, evaluation and persistence into clear
   internal functions.
2. Replace per-voucher `get_doc` calls with bulk header/line loading.
3. Replace per-voucher latest-log lookups with one/batched indexed lookup.
4. Avoid writes when state, reason, message, linked order and relevant totals are
   unchanged.
5. Avoid full document saves for semantically unchanged held vouchers while
   retaining snapshot freshness evidence.
6. Add only indexes justified by `EXPLAIN` and measured query time.

This phase still reconciles everything. It is the lowest-risk performance gain
and creates the shared engine needed by the later incremental scope.

**Exit gate:** full-mode results and audit behavior are identical to the current
implementation across the existing test suite and a sanitized production-like
snapshot; query growth is batched rather than one query per voucher.

### Phase 2 — Introduce incremental scope behind a disabled feature flag

1. Make voucher snapshot application return/retain its precise change set.
2. Implement persistent work items for non-import invalidations.
3. Implement transitive connected-scope expansion.
4. Call the shared reconciliation engine with that scope.
5. Add a site setting such as `tally_incremental_reconciliation_enabled`,
   defaulting to false. Absence or false must retain full mode.
6. If scope collection/parsing is inconsistent, fail closed to full mode and
   record the reason; never proceed with a suspected partial scope.
7. Add and persist the reconciliation algorithm/configuration fingerprint. Its
   first run and every change force full scope.
8. Claim/delete work by exact identity under the transaction rules in section
   4.3, and lock affected Orders in deterministic order.

**Exit gate:** comprehensive tests prove that incremental and full modes produce
the same final Orders, voucher outcomes and audit changes.

### Phase 3 — Shadow comparison

On a staging clone with production-like data:

1. Generate the intended incremental scope and outcome plan.
2. Generate the full-scope outcome plan from the same database state without
   duplicating writes.
3. Compare affected Order statuses/quantities, voucher states/reasons, pending
   reference releases and logs that would be emitted.
4. Persist only concise mismatch diagnostics; do not place raw source payloads or
   credentials in logs.

Run representative cases: no change, one voucher correction, new voucher,
missing/recovered header, missing/recovered lines, reference transfer, customer
mapping correction, master correction, new matching Order and legacy hold.

Also run two-connection cases where an Order edit/work item commits immediately
before and immediately after work selection. Verify that neither ordering loses
the edit or its next-run invalidation.

**Exit gate:** zero unexplained parity differences across repeated staging runs
and no lost work in the concurrency cases.

### Phase 4 — Controlled production rollout

1. Back up the site and deploy with the feature flag off.
2. Migrate and verify indexes/work-item schema.
3. Confirm full mode is faster and functionally unchanged.
4. Increase/renew the job and lock leases based on baseline worst-case timings;
   verify experimentally that the lock cannot expire before the worker timeout.
5. Enable incremental mode for the scheduled import while retaining the nightly
   full pass.
6. Closely monitor the first runs and compare the next nightly full pass. A full
   pass should normally make zero business-data corrections.
7. If a mismatch, growing queue, repeated fallback, lock timeout, or unexplained
   Manual Review transition occurs, disable the feature flag immediately and
   return to full mode.

### Phase 5 — Stabilize and tune

After an agreed observation period with zero unexplained differences:

1. Set alerts for runtime, queue age/depth, nightly parity corrections, job
   failures and lock contention.
2. Tune batch sizes from measurements.
3. Consider more precise master/customer invalidation only if fallback full runs
   are frequent.
4. Retain nightly/manual full reconciliation permanently unless a separate
   reviewed decision removes it.

## 6. Required test matrix

Run existing reconciliation, voucher correction, fulfillment, order cutover,
PostgreSQL reader and scheduler tests in both applicable modes. Add explicit
regressions for:

- unchanged snapshot creates no duplicate log or Version and performs no Order
  write;
- a new eligible voucher updates its matching Order;
- quantity increase/decrease replaces, rather than accumulates, contribution;
- voucher renumbering retains company/GUID identity;
- reference transfer recalculates old and new Orders;
- multi-hop pending-reference chains expand transitively and release together;
- an Unverified voucher freezes every connected Order;
- missing header/inventory/master mapping preserves quantities and later
  recovery recalculates correctly;
- wrong customer GUID and its correction;
- duplicate tracking movement and over-delivery review behavior;
- same voucher number with different GUIDs;
- ignored non-allowlisted voucher type;
- Cancelled and Partially Closed status preservation;
- legacy unidentified contribution protection;
- a matching Order created after the voucher already exists;
- Customer GUID/client-code change invalidation;
- unchanged raw voucher with corrected ledger/item/godown mapping;
- manual Manual Review recheck affects only the complete connected scope;
- failed reconciliation rolls back source changes and retains queued work;
- stale transaction is rejected without committing/discarding caller writes;
- incremental/full lock contention and scheduler deduplication;
- nightly full reconciliation repairs a deliberately injected missed work item
  and reports the parity correction;
- query-count test showing no per-voucher latest-log query regression;
- one voucher logging outcomes for two different Orders does not suppress either
  pair's latest semantic outcome;
- null-Order log outcomes deduplicate correctly;
- allowlist, source-company and algorithm-version changes force full mode;
- malformed/old/unavailable work state falls back to full mode;
- work enqueued after a run's claim watermark is not deleted;
- same-key work re-enqueued with a newer generation is not acknowledged as the
  older claimed generation;
- simultaneous Order edit and reconciliation does not overwrite the edit or lose
  its invalidation;
- unchanged Unverified vouchers retain fresh snapshot metadata without Version,
  validation or reconciliation churn;
- same-AlterID inventory corrections remain detectable and applicable;
- invalid/older/incomplete PostgreSQL observations still fail before apply;
- incompatible source-company configuration still requires explicit migration;
- the worker timeout cannot outlive the reconciliation lock lease.

For parity testing, compare business state rather than volatile timestamps and
generated document names. Compare at minimum Order status and item fulfillment,
voucher reconciliation state/reason/reconciled flag, pending references, and the
semantic latest reconciliation-log outcome.

## 7. Performance and rollout acceptance criteria

Correctness is the hard gate; a fast mismatched run is a failure.

- Zero unexplained full-versus-incremental business-state differences in staging
  and during the production observation period.
- Ordinary no-change and small-change pipelines finish before the next five-minute
  schedule, with a preferred p95 target of three minutes or less for the complete
  pipeline on current data.
- Reconciliation query count is bounded by bulk batches and affected Orders, not
  approximately one or more queries per all 11,170 vouchers.
- Nightly full reconciliation has substantial headroom below its worker timeout;
  target no more than 50% of the configured timeout at p95 before lowering any
  timeout.
- Work queue oldest age remains below ten minutes during normal operation and
  returns to zero after successful runs.
- An unchanged nightly full run changes zero Order totals/statuses and emits no
  duplicate outcome logs.
- Existing audit history, Manual Review reasons and source metadata remain
  available.
- Every successful run records reconciliation algorithm/configuration
  fingerprint, mode, scope counts and any full-fallback reason.
- Any nightly full-pass business correction is measured before write and raises
  an operational alert unless it is an explicitly understood migration/change.

The earlier estimate of one to three minutes is a target for ordinary runs, not a
guarantee. Phase 0/1 measurements determine the final service threshold.

## 8. Rollback plan

Rollback must not require reverting source data or deleting work:

1. Set `tally_incremental_reconciliation_enabled` to false.
2. Allow the active transaction/job to finish or fail; do not kill it mid-commit.
3. Run the full reconciliation through the existing Owner/Admin action or a
   controlled bench command.
4. Verify affected Order totals/statuses and the latest Tally Sync Run.
5. Preserve work items and mismatch diagnostics for root-cause analysis. Full
   mode may ignore the queue but must not destructively clear it until success is
   confirmed.

Schema additions should be backward-compatible so application rollback can use
the original full path. Do not make the incremental queue the only record of
accepted voucher state.

If a rollback follows a parity mismatch, capture the pre-repair diff first, then
run full reconciliation. Do not destroy the evidence by repairing silently.

## 9. Expected code areas

The implementation is expected to touch:

- `kunal_enterprises/cron/reconciliation.py` — shared engine, scopes, bulk data
  loading, exact `(order, voucher)` bulk log comparison, concurrency controls,
  algorithm/configuration fingerprint and metrics;
- `kunal_enterprises/integrations/voucher_snapshot.py` — precise change-set
  collection, unchanged-hold write reduction and atomic scoped invocation;
- `kunal_enterprises/integrations/tally_postgres.py` — mode selection, scheduler
  result metadata and nightly full enqueue function;
- `kunal_enterprises/hooks.py` — nightly schedule and targeted invalidation hooks;
- relevant Order/Customer/master controller hooks — persistent invalidation with
  an internal-write recursion guard;
- a new reconciliation work-item DocType or equivalent durable mechanism;
- migration patches for only the measured indexes that are required;
- `kunal_enterprises/tests/test_voucher_corrections.py`,
  `kunal_enterprises/tests/test_foundation.py` and focused new performance/scope
  tests;
- `VOUCHER_RECONCILIATION.md` — final operational behavior and runbook after the
  implementation is proven.

Exact schema and function names may change during implementation, but the safety
invariants, staged rollout, parity gates, full fallback and rollback behavior in
this plan are required.

## 10. Recommended implementation order

Proceed in this order:

1. Instrument and baseline.
2. Correct lock/job timeout headroom and bulk-optimize full reconciliation and
   unchanged hold handling.
3. Prove unchanged full-mode behavior.
4. Add durable invalidation and connected-scope selection behind a disabled flag.
5. Add incremental/full parity tests.
6. Shadow-test against production-like data.
7. Deploy flag-off, verify, then enable scheduled incremental mode.
8. Keep nightly/manual full reconciliation and monitor parity.

This order provides useful speed improvements before introducing incremental
scope and gives a clean, one-setting rollback at every production stage.
