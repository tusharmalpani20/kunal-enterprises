# Tally Stock Group Parent Hierarchy Missing from Mobile Product Access

## Issue status

- **Status:** Repaired in the current environment; preventive Frappe-side hardening remains a follow-up task.
- **Recorded on:** 2026-09-02
- **Application:** `kunal_enterprises`
- **Frappe site:** `ke-dev.hopnet.co.in`
- **Tally data-loader application:** `/home/erpmaster/kunal-tally/tally-database-loader`
- **Issue record location:** `/home/erpmaster/kunal-enterprises/issues`
- **Scope constraint:** Tally code, Tally configuration, Tally tables, source PostgreSQL tables, and the Tally-loader code are not to be changed for the proposed permanent solution. The protection must be implemented in Frappe. The mobile application should not need a change for this data-integrity problem. The source PostgreSQL repair described below was a one-time incident response and is not the ongoing solution.

## Short description

Products whose item code began with `21091` existed in Frappe and were active, but they were not returned by the mobile product-search API and could not be opened directly. The affected items belonged to the stock-group branch `MERINO 1MM`.

The item records and their branch existed, but the required root group, `Merino Industries Limited`, was missing from the source PostgreSQL stock-group table at the time of the investigation. Because the backend validates the complete stock-group hierarchy before allowing an item, the products were rejected as `Item is not allowed`.

The missing root was restored in the source PostgreSQL database and the Tally master import was run. The affected products became visible again. This manual restoration is a repair for the current incident, not the long-term protection mechanism.

## Original user-visible symptoms

### Mobile user

- **Sales employee:** `SURAJ`
- **Sales employee ID:** `KE-SE-0004`
- **Customer:** `1221 DESIGN AND ARCHITECTURE-VANASTHALIPURAM`
- **Customer ID:** `KE-CUST-02375`
- **Search term:** `21091`

The mobile application sent the following request parameters:

```text
customer=KE-CUST-02375
sales_employee=KE-SE-0004
search=21091
limit=60
offset=0
```

The response contained no matching products. Direct access to products such as `21091 BR`, `21091 CFR`, and `21091 CMT` returned:

```text
Item is not allowed
```

### Frappe observations

The affected products were present in the general Frappe Item list and were active. The following access records were empty:

- Sales Employee `KE-SE-0004` had no explicit Assigned Customers rows.
- Sales Employee `KE-SE-0004` had no explicit Product Group Access rows.
- Customer `KE-CUST-02375` had no explicit Customer Product Group Access rows.

Empty access tables were not the cause. Under the current permission logic, an empty table provides the default broad access scope. The customer and sales employee were active and approved, and the backend resolved approximately 106 product groups for them.

## Affected products

Examples observed in Frappe included:

- `21091 BR`
- `21091 CFR`
- `21091 CMT`
- `21091 VL`
- `21091 UNI SF`
- `21091 UNI MR+`
- `21091 SF`
- `21091 MR+`
- `21091 ML`
- `21091 LNN`
- `21091 JWL`
- `21091 IMP`
- `21091 HGL`

These products had the root stock group `MERINO 1MM` in their hierarchy-related data.

## How product access works

The mobile application sends the search term, customer, sales employee, limit, and offset to the backend. The backend then filters products and validates access using the stock-group hierarchy.

The relevant validation conceptually checks that:

1. The item is active.
2. The item's stock group exists and is active.
3. The stock-group parent chain is present.
4. The stored root matches the actual hierarchy path.
5. The item's hierarchy intersects the groups allowed for the customer and sales employee.

Therefore, an item can be active and searchable in the general Frappe list but still be rejected by the mobile API if its stock-group hierarchy is broken.

The mobile search request was correct. Changing the mobile search filter or removing backend product-access validation would not fix the underlying problem and would weaken permission enforcement.

## Investigation findings

### Tally loader configuration

The loader export definitions already include the required stock-group relationships. For `mst_stock_group`, the configuration exports:

- `guid`
- `alterid`
- `name`
- `parent` as the parent group name
- `_parent` as the parent group GUID

The item export also includes the corresponding parent information. The configuration itself was not missing the `_parent` field.

The relevant configuration is:

```text
/home/erpmaster/kunal-tally/tally-database-loader/tally-export-config-incremental.yaml
```

### Source PostgreSQL state after repair

The source PostgreSQL `mst_stock_group` table was checked after restoring the missing root:

- Total stock groups: `800`
- Root groups: `80`
- Missing parent names: `0`
- Missing parent GUIDs: `0`
- Parent name/GUID mismatches: `0`
- Duplicate GUIDs: `0`
- Duplicate exact group names: `0`
- Rows with a non-empty parent but empty `_parent`: `0`
- Rows with an empty parent but non-empty `_parent`: `0`

The restored root was:

```text
GUID: aac3341a-ee89-4145-9f7a-3edec7de877b-0000bed1
Name: Merino Industries Limited
Parent: empty
_parent: empty
```

Its `alterid` was null because the row was manually restored rather than received from the loader's normal Tally export. This is a point to remember if the record is inspected again.

### Frappe state after repair

After the source row was restored and the master import was run:

- The affected `21091` products passed the hierarchy/access validation.
- Invalid item paths checked: `0`.
- Stored-root mismatches checked: `0`.
- The affected products became available to the expected customer/sales-employee access path.

## Probable root cause

The loader's incremental master synchronization treats any stock-group GUID missing from the latest Tally response as deleted. Its process is effectively:

1. Export the current Tally stock groups into a temporary difference table.
2. Find existing PostgreSQL groups whose GUID is not present in that response.
3. Delete those existing rows.
4. Load the returned rows.

If a Tally response is incomplete, truncated, interrupted, or otherwise omits an existing parent group, the loader cannot distinguish that omission from a genuine deletion. It can therefore delete a valid parent group such as `Merino Industries Limited` while leaving children such as `MERINO 1MM` and its items behind. A slow response by itself is not evidence of this problem; the important condition is an incomplete or inconsistent returned dataset.

The loader's normal master-table operations are not published as one atomic, validated snapshot. Consequently, a partial response or a failure during the update can leave the source PostgreSQL mirror in an incomplete state.

Once the source hierarchy was incomplete, the Frappe sync/backend could receive child data without a valid root. The previous Frappe-side fallback behavior could then treat an immediate group as the item's root, which does not represent the real Tally hierarchy and can cause the allowed product-group intersection to fail.

The exact historical event that removed the root cannot be proven from the current repository alone because the deployed loader configuration, original Tally response, and historical loader logs for that event were not available. The deletion-on-omission behavior is, however, sufficient to explain the observed state.

### Confidence and remaining unknowns

The missing-parent condition and the loader behavior were confirmed. The exact reason the parent was absent from the loader's response remains unconfirmed. Possible explanations include a partial Tally export, an interrupted loader operation, or another source-data/synchronization inconsistency. The incident record must not state that Tally itself deleted the group unless the Tally audit history or loader logs prove that event.

The loader repository did not contain the deployed runtime configuration or the historical response payload for the incident. Therefore, the exact company context, loader mode, and first sync that removed the parent cannot be reconstructed from this issue note alone.

## What this issue is not

This incident was not caused by:

- The mobile application failing to send the `21091` search term.
- The customer being inactive.
- The sales employee being inactive.
- Missing customer or sales-employee access rows.
- The products being absent from Frappe.
- A need to grant unrestricted product access.
- A need to remove the backend `item_is_allowed` validation.

## Frappe-only solution

Because the Tally loader cannot be changed, Frappe must fail safely when it sees incomplete source data.

### 1. Validate before writing

Before changing Frappe stock groups or items, the sync should validate the complete incoming hierarchy:

- Every non-root group has a parent name and parent GUID.
- Every parent GUID exists in the incoming or retained hierarchy.
- The parent name maps to the same parent GUID.
- There are no duplicate GUIDs.
- There are no cycles.
- Every item points to a valid group.
- Every item's stored root agrees with the resolved hierarchy.

### 2. Preserve the last-known-good hierarchy

If a known existing parent group is absent from the source data, Frappe should not delete, deactivate, rename, or re-root the existing Frappe records merely because of that one sync response.

The sync should mark the run as failed or requiring review and retain the previous valid records.

### 3. Protect known critical root groups

Frappe may maintain a local protected-group registry or equivalent configuration containing the exact GUID and name of important root groups such as `Merino Industries Limited`. This registry is a safety net; it must not be the only validation mechanism. All previously valid groups and their source GUIDs need to be retained, because the same problem can affect any branch, not only Merino.

If such a group is absent from the source response but already exists in Frappe, the sync should retain it. If the group is absent from both systems, it should be created only from an approved, verified mapping—not guessed from an item's immediate group. Source GUID must be the identity key; group names alone are not safe because names can change or be duplicated across companies.

### 4. Do not import incomplete new branches as valid

When a new Tally item arrives without its required parent hierarchy, Frappe should leave the item pending or exclude it from the mobile-access dataset until the hierarchy can be resolved. It must not assign an arbitrary root.

### 5. Make the sync failure safe

The group, hierarchy, and item updates should be performed atomically within Frappe, or through a staging/preflight phase followed by a controlled commit. If validation fails, existing valid data must remain unchanged. The implementation must also avoid committing individual records before the preflight has completed; otherwise, a later failure can still leave Frappe partially updated.

Dependent stock, voucher, and reconciliation processing should be skipped when the required master-data preflight fails. Otherwise, downstream processes could interpret missing master data as zero or invalid data.

### 6. Keep mobile validation strict

The mobile API should continue enforcing product access. Once Frappe retains a valid hierarchy, no mobile code change should be required.

## Limits of a Frappe-only solution

Frappe cannot prevent the Tally loader from deleting or incompletely updating a row in the source PostgreSQL database. It also cannot prove, from one missing row alone, whether the row was genuinely deleted in Tally or was omitted from an incomplete export.

The Frappe-only protection can prevent that bad source state from being propagated into Frappe and the mobile application. It cannot make a genuinely new group or item available if the loader never provides its source record. Such records must remain pending until the source data becomes available or an explicitly approved Frappe-side mapping is provided.

Frappe should read the source data consistently where possible, record the source sync marker before and after the read, and retry or reject the import if the source changes during the read. This reduces race conditions, but it cannot create a cross-database transaction between source PostgreSQL and Frappe. The last-known-good Frappe hierarchy is therefore the final safety boundary.

## Required Frappe design details

The implementation should include the following, regardless of whether it uses existing Frappe records or a new local state table:

- A durable source-GUID-to-Frappe-record mapping.
- A last successful master-sync marker and status.
- Counts or another diagnostic summary for the incoming groups and items.
- A list of missing expected parent GUIDs when validation fails.
- A distinction between a complete accepted import and a rejected/partial import.
- No deletion or deactivation based solely on absence from one source response.
- Explicit logging of the source sync identifier, affected GUIDs, and affected item count.
- A retry path that does not require creating duplicate Frappe groups.

The existing Frappe documents can serve as the retained hierarchy only if their source GUIDs and parent relationships are preserved reliably. If those values are not durable in the existing DocTypes, a small Frappe-side mapping/state table is required.

## Expected behavior if the issue happens again

If the loader again omits `Merino Industries Limited` or another existing parent:

1. Frappe detects the missing parent during preflight.
2. The sync is marked failed or incomplete.
3. Existing Frappe groups and items remain unchanged.
4. Existing mobile product visibility is preserved.
5. New items depending on the missing branch remain pending.
6. The sync log records the missing group name, GUID, affected children, and source sync identifier.
7. The source data and loader logs can then be reviewed without causing further damage.

Until the Frappe preflight protection is deployed, a repeated master import should not be run blindly after a missing-parent alert. First capture the source and Frappe state described in the investigation checklist, then decide whether the import is safe to retry. The one-time source repair can otherwise be overwritten by a later incomplete loader response.

## Recommended investigation checklist

When this issue is reported again, capture the following before manually editing data:

### From the mobile request

- Customer ID
- Sales employee ID
- Search term
- Exact endpoint and response
- One or more item codes that were rejected

### From Frappe

For the affected item, inspect:

- Item name and item code
- Active status
- Stored stock group
- Stored root stock group
- Immediate stock group
- Source Tally GUID, if stored

For each group in the path, inspect:

- Frappe document name
- Displayed group name
- Parent group
- Source GUID
- Active status

### From source PostgreSQL

Inspect `mst_stock_group` for:

- The affected group name
- Its parent name
- Its `_parent` GUID
- The expected root GUID
- Whether the expected root row exists
- Duplicate or conflicting names/GUIDs

Also record the loader sync time and status. Do not expose or copy database credentials into the issue record.

If the issue is being investigated before the Frappe guard is deployed, record the following additional evidence:

- The source `Last AlterID Master` value before and after the import.
- The Frappe sync/run identifier and status.
- The timestamp of the last known-good Frappe master import.
- Whether the missing group was present in the previous accepted Frappe hierarchy.
- Whether the source row disappeared before the Frappe import or during a loader run.
- The number of groups/items returned by the source at the time of the incident.

Do not manually re-root affected items or grant broad mobile access as an incident workaround. Those actions can hide the hierarchy defect and create incorrect access.

## Files likely involved in the Frappe implementation

The Frappe-only hardening should be reviewed primarily in:

- `apps/kunal_enterprises/kunal_enterprises/integrations/tally_postgres.py`
- `apps/kunal_enterprises/kunal_enterprises/cron/tally_sync.py`
- Relevant Frappe sync and product-access tests

The product-access validation in `api/product_groups.py` should remain strict. The fix belongs in the synchronization and hierarchy-integrity handling, not in bypassing access checks.

## Acceptance criteria for the future fix

The Frappe-only fix should not be considered complete until these cases are tested:

1. A normal complete import updates new and changed groups/items.
2. A response omitting an existing root group leaves the previous Frappe hierarchy and mobile visibility unchanged.
3. A response omitting an intermediate parent is rejected without partial Frappe writes.
4. A new item with a missing parent is held pending and is not assigned an invented root.
5. A real source rename preserves identity through the source GUID.
6. Duplicate or conflicting source names do not cause records to be merged incorrectly.
7. A failure after staging but before commit leaves the previous accepted data unchanged.
8. Dependent stock/voucher processing does not run after a failed master-data preflight.
9. A retry after the source becomes complete succeeds without duplicate groups or items.
10. Existing mobile product-access restrictions still reject genuinely unauthorized items.

## Final conclusion

The Tally loader may continue to produce an incomplete PostgreSQL mirror because it is outside the permitted change scope. Frappe must therefore treat source data as potentially incomplete, validate it before applying updates, and preserve its last valid hierarchy whenever a parent group disappears unexpectedly.

This approach does not modify Tally or the loader, does not require a mobile search change, and prevents a temporary source omission from making existing products disappear from the mobile application.

## Change record

This document records the investigation and proposed Frappe-only mitigation. No Tally-loader code, mobile code, or additional customer/item data was changed while creating this note.
