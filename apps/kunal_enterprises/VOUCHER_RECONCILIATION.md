# Backend-only Tally reconciliation

## Scope and limits

Only the Frappe backend changes. The Tally loader repository, TDL, mobile application and PostgreSQL schema remain unchanged. The backend makes no requests to Tally and uses read-only PostgreSQL connections.

Corrections can be automated only after the existing loader reflects them in PostgreSQL. Missing rows do not establish deletion in Tally. Old inventory left in PostgreSQL cannot be detected as stale merely by reading it again. No number of repeated missing observations becomes automatic deletion evidence.

## Existing source tables

| Table | Use |
| --- | --- |
| `trn_voucher` | GUID, AlterID, voucher number, reference, date, party GUID and type GUID |
| `trn_inventory` | Item/godown GUIDs, signed quantity and tracking number |
| `mst_ledger` | GUID join and customer alias information |
| `config` | Company, export period, header and inventory progress markers |
| `sync_run_ping` | Successful imports, failures and no-change pings |

No `portal_voucher_snapshot`, `portal_voucher_sync_state` or inventory coverage table is required. The module name `voucher_snapshot.py` refers to Frappe's local application of a database observation, not a loader-published snapshot.

The reader uses one repeatable-read transaction so its queries see the same PostgreSQL database view. It rejects wrong-company metadata, invalid periods, missing checkpoints, inventory behind headers, headers above the checkpoint and a failure without a later completed import. A no-change success ping does not clear an earlier failed import. Completed imports are identified by the existing loader's `Import completed successfully.` message.

These are practical checks, not proof of an atomic Tally export. The existing loader can commit its stages separately, diagnostic runs are not unambiguously identified in the available metadata, and inventory rows do not retain per-voucher revision/completeness information. The latest successful loader run and export period are retained in `Tally Sync Run.source_metadata`; stale source data must not be confused with a fresh Tally sync. Period changes are recorded in the import result and metadata. Missing records are always held, including records omitted by an export-period change.

## Acceptance and uncertain data

Company plus GUID identifies the Frappe voucher. Voucher number is a mutable display value and is no longer unique. Customer identity uses its ledger GUID. Only configured delivery-challan type GUIDs contribute fulfillment; invoices and sales orders do not count.

`raw_source_payload` and voucher lines retain the last accepted source observation. `source_observation` holds the latest PostgreSQL observation, including an incomplete one (`null` when the header is missing). `source_pending_references` retains every reference affected by a correction until all related orders can be recalculated. If any related order has uncertain source data or an unmapped legacy contribution, the entire connected group preserves its quantities. This prevents a reference transfer from crediting a new order while the old order still retains that quantity. Multi-step reference corrections retain the whole chain until recovery.

An eligible voucher is held as `Unverified` when its header disappears, its inventory is missing, its type GUID disappears, or its inventory cannot resolve to imported item/godown masters. Existing accepted data is retained. Affected orders preserve all current quantities and move to Manual Review; explicit Cancelled and Partially Closed states remain unchanged. New unverified vouchers contribute nothing. Other orders continue reconciling.

When usable data returns, the hold clears automatically, both the accepted and pending references are reconsidered, and affected orders are recalculated. Missing data never generates `Removed`; that value remains only for compatibility with historical records.

## Scenario behavior

| Change reflected in PostgreSQL | Result |
| --- | --- |
| Customer display name changes, same GUID | Customer identity remains the same |
| Wrong customer GUID | Validation review; correction automatically retries |
| Missing/wrong reference | Unmatched, or validated against the identified order; correction recalculates former/current orders |
| Quantity increases or decreases | Current contribution replaces the prior quantity; no accumulation on repeat imports |
| Additional challan with a new GUID | Counts once alongside other accepted challans |
| Same number on different GUIDs | Separate voucher records |
| Known but unrequested item, inward quantity or over-delivery | Validation review; later correction automatically retries |
| Missing header, empty inventory or unresolved master GUID | Quantities held, source unverified, automatic retry on future imports |
| Completed order receives accepted lower quantities | Reopens according to remaining quantity |
| Completed order's voucher disappears | Preserves quantities and moves to Manual Review |
| Explicitly Cancelled / Partially Closed order | Status preserved; accepted corrections can update quantities; uncertain data preserves quantities |

A wrong reference that happens to identify another compatible order for the same customer may be indistinguishable from a correct reference. The backend does not guess references from names, dates or amounts.

Manual review's recheck action cannot force an incorrect order into Processing. It recalculates current accepted Frappe data; the scheduled/manual PostgreSQL import is what obtains newer source corrections. Source updates and order recalculation commit together under a site-specific lock. A history check using a separate read connection also rejects an older Frappe transaction view before applying changes; retry such an import or reconciliation in a fresh transaction. The check does not commit or discard the caller's pending writes. Repeated unchanged source observations avoid rewriting voucher lines and duplicate version history, but updated local master mappings are still applied. Read observations are ordered by their start time so a slow earlier read cannot overwrite a later observation. Order reconciliation still considers all managed orders to catch customer/master changes and pending reviews.

## Legacy migration

Run the normal Frappe migration. It retains document names, removes voucher-number uniqueness, adds company/GUID uniqueness and adds observation fields. Legacy vouchers are adopted only when number, reference, challan classification and customer GUID agree unambiguously on both the source and legacy sides. An incomplete but unambiguous adoption establishes identity while preserving legacy lines and quantities. Previously reconciled legacy vouchers with no verified identity preserve their order quantities and report `LEGACY_IDENTITY_REQUIRED`.

## Configuration and read-only preview

Retain the existing `tally_postgres_*` connection settings. Add the exact source company and reviewed challan type GUIDs to Frappe site configuration:

```json
{
  "tally_source_company": "EXACT TALLY COMPANY NAME",
  "tally_fulfillment_voucher_type_guids": ["REVIEWED-CHALLAN-TYPE-GUID"]
}
```

Find candidate types using a read-only PostgreSQL query; review before configuring:

```sql
SELECT voucher_type, _voucher_type, count(*)
FROM trn_voucher
GROUP BY voucher_type, _voucher_type
ORDER BY voucher_type;
```

After deploying the backend and migrating the site, run the non-mutating preview:

```sh
bench --site <site> execute kunal_enterprises.integrations.tally_postgres.diagnose_vouchers
```

It reports source metadata, approved-type counts, eligible vouchers without inventory, missing imported GUIDs and a bounded sample. It does not change orders or validate deletions in Tally.

### Live fulfillment allowlist recorded 9 September 2026

The `ke-dev.hopnet.co.in` site was configured with the three reviewed branch
Delivery Challan voucher-type GUIDs below. These values come from
`trn_voucher._voucher_type`; they are voucher-type identities shared by all
vouchers of that type. They are not voucher GUIDs, stock-item GUIDs or
inventory-line identities.

| Tally voucher type | Approved type GUID |
| --- | --- |
| Delivery Challan Goshamahal | `aac3341a-ee89-4145-9f7a-3edec7de877b-00000028` |
| Delivery Challan Kukatpally | `aac3341a-ee89-4145-9f7a-3edec7de877b-0000f4f7` |
| Delivery Challan Seetarambagh | `aac3341a-ee89-4145-9f7a-3edec7de877b-000165f2` |

The allowlist applies to every normal Frappe voucher import and reconciliation,
not only to manually backfilled vouchers. Its purpose is to fail closed: Sales
Invoices, Sales Orders, inward vouchers, stock transfers and other inventory
voucher types must not contribute fulfillment merely because they contain
inventory lines.

The read-only preview immediately after activation observed 12,917 voucher
headers and classified 11,170 Delivery Challans as eligible. Of those, 4,679
had no mirrored inventory and 11,169 still had `order_details` unavailable and
no resolved `order_number`. Only the agreed Kukatpally target voucher had the
new order fields populated at that point. Enabling a type does not make missing
order or inventory data trustworthy; the importer retains those conditions as
source errors and they require loader publication/backfill or evidence-based
review.

The first scheduled run after activation began at 23:30:38 IST and completed
successfully at 23:54:42 IST, taking about 24 minutes. Masters processed 17,727
records in about 54 seconds with no errors. Stock processed 9,331 of 9,362 rows
in about 43 seconds and recorded 31 mapping errors. Voucher publication accepted
11,170 eligible vouchers, and the agreed Kukatpally voucher was matched to
`KE-SO-00018-26-27`; that Order became Completed.

A full run is not a small incremental lookup inside Frappe:
`import_all` sequentially reads and applies all configured masters, the complete
published stock snapshot, all 12,917 voucher headers and their lines, and then
reconciles managed orders. Frappe validation, DocType saves, child-row mapping
and reconciliation can therefore take materially longer than the PostgreSQL
read itself. Scheduler enqueue success only means the long-worker job was
accepted; completion must be established from the final job result and
`Tally Sync Run` records.

The measured bottleneck was reconciliation: it ran from 23:34:11 to 23:54:19,
about 20 minutes, and finished `Completed With Errors` for 11,169 of 11,170
eligible vouchers because their order details had not been extracted. The
current implementation loads all Tally Voucher documents individually, then
per voucher looks up the latest reconciliation log and may save the voucher and
insert a new log. This N+1 document/query pattern, amplified by the initial
11,169 changed error outcomes, explains the high worker CPU and most of the
wall-clock time. It was active work rather than a stuck worker or a slow
PostgreSQL mirror read. Subsequent runs still scan all vouchers and perform the
per-voucher log lookup even when unchanged, though they avoid some saves and log
inserts. Optimize reconciliation batching and avoid reconsidering unchanged,
unmatchable vouchers before shortening the scheduler interval or treating this
duration as a worker failure.

### Incremental reconciliation implementation

The performance implementation is guarded by the default-off site setting
`tally_incremental_reconciliation_enabled`. When disabled or absent, the existing
full reconciliation remains active. After migration and staging parity checks,
enabling it activates the bulk engine, transaction-local voucher change sets and
durable generation-aware invalidation for relevant Order, Customer, voucher and
master changes. A configuration or reconciliation-algorithm fingerprint change
forces the next enabled run to full scope.

The first enabled run is therefore full. Ordinary later runs process only the
complete connected reference group affected by changes. The system retains the
same uncertain-source and legacy holds, and it falls back to full scope when
invalidation metadata is unavailable, stale or too large. A nightly full safety
job runs at 02:17 only while incremental mode is enabled, with a 02:47 retry that
skips when a full pass already completed that day. Owner/Admin manual full
reconciliation remains available.

Do not enable the setting until the site has been migrated and the staging
full-versus-incremental parity gate in
`docs/TALLY_RECONCILIATION_PERFORMANCE_PLAN.md` has passed. The implementation
records mode, fallback reason, scope counts, write counts and phase timings in
the Reconciliation Tally Sync Run's `source_metadata`.

## Rollout

1. Back up the Frappe site and pause its import schedule during migration.
2. Deploy only this backend, configure the company/type GUIDs, run `bench --site <site> migrate` and restart workers.
3. Run the read-only preview. Review source age, missing inventory and ambiguous legacy identities.
4. Run a controlled `kunal_enterprises.integrations.tally_postgres.import_all` import and inspect quantities, Manual Review reasons and sync logs.
5. Resume the existing Frappe schedule. No loader rebuild, TDL installation, additional Tally scan or PostgreSQL write is needed.

## Verification

Tests cover pure quantity calculations, sync metadata checks, corrections and holds against Frappe, and the reader against disposable PostgreSQL schemas containing only the original loader tables. PostgreSQL tests require `KUNAL_TEST_PG_DSN` pointing to a disposable database. Frappe tests must use a disposable site because the actual import commits transactions.

A read-only check on 5 September 2026 successfully read the current database: 12,917 headers, 11,170 challans, and 4,679 challans without inventory. The latest reported completed loader import was run 650 on 3 September 2026 at 16:35:59 IST. The missing inventory is an existing source limitation, not evidence of deleted Tally vouchers.

Production migration and activation have not been performed by this implementation.

Audit validation: 19 unit tests, 24 Frappe correction/hold tests and 7 PostgreSQL reader/integration tests passed. Added regressions cover incomplete legacy adoption, ambiguous legacy candidates, frozen reference transfers (including multi-step transfers and legacy holds), corrected master mappings, equivalent decimal tracking quantities, read ordering, and a two-connection stale-transaction regression. The earlier broader foundation suite passed 152 of 155 tests; the remaining three failures are the previously confirmed Mobile OTP permission expectation and two master-unit name assertions. Python lint and compilation passed. Migration was tested only on disposable Frappe sites.
