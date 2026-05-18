# Tally PostgreSQL Discovery

## Scope

This note records findings from the demo PostgreSQL database created by the Tally database loader.

The goal was to inspect:

- Available tables
- Stock groups
- Stock categories
- Stock items
- Godowns
- Stock-related tables
- `trn_voucher`
- Practical impact on the portal/mobile/connector architecture

Credentials are intentionally not recorded in this document.

## Connector Documentation Reviewed

The following connector docs were reviewed:

- `docs/cli-plan.md`
- `docs/cli.md`
- `docs/commandline-options.md`
- `docs/faq.md`
- `docs/google-bigquery.md`
- `docs/incremental-sync.md`
- `docs/postgres-local-tally-service.md`
- `docs/release-history.md`
- `database-structure.sql`

Relevant points from the docs:

- The utility can load Tally data into PostgreSQL.
- It supports full sync and incremental sync.
- Incremental sync requires the incremental schema from the beginning.
- For continuous/background sync, frequency can be configured in minutes.
- Tally company should be explicitly configured to avoid syncing the wrong active company.
- The schema has separate master tables like `mst_stock_item`, `mst_stock_group`, `mst_stock_category`, `mst_godown`, and transaction tables like `trn_voucher`, `trn_inventory`, and `trn_batch`.

## Database Status

The demo database is reachable and uses the public schema.

Observed connector config:

| Config | Value |
| --- | --- |
| Company Name | `KUNAL ENTERPRISES - (from 1-Apr-24)` |
| Period From | `2026-01-01` |
| Period To | `2026-05-11` |
| Update Timestamp | `12/5/2026, 7:56:25 pm` |

Important implication:

The current demo sync is for a limited period, not necessarily the full financial year or all history. Any stock calculation from transaction movement must be treated carefully.

## Tables Present

The database has 33 base tables:

- `config`
- `mst_attendance_type`
- `mst_cost_category`
- `mst_cost_centre`
- `mst_employee`
- `mst_godown`
- `mst_group`
- `mst_gst_effective_rate`
- `mst_ledger`
- `mst_opening_batch_allocation`
- `mst_opening_bill_allocation`
- `mst_payhead`
- `mst_stock_category`
- `mst_stock_group`
- `mst_stock_item`
- `mst_stockitem_standard_cost`
- `mst_stockitem_standard_price`
- `mst_uom`
- `mst_vouchertype`
- `trn_accounting`
- `trn_attendance`
- `trn_bank`
- `trn_batch`
- `trn_bill`
- `trn_closingstock_ledger`
- `trn_cost_category_centre`
- `trn_cost_centre`
- `trn_cost_inventory_category_centre`
- `trn_employee`
- `trn_inventory`
- `trn_inventory_additional_cost`
- `trn_payhead`
- `trn_voucher`

## Important Row Counts

| Table | Rows |
| --- | ---: |
| `mst_godown` | 3 |
| `mst_ledger` | 12,578 |
| `mst_stock_category` | 189 |
| `mst_stock_group` | 775 |
| `mst_stock_item` | 10,879 |
| `trn_batch` | 65,058 |
| `trn_closingstock_ledger` | 0 |
| `trn_inventory` | 65,021 |
| `trn_voucher` | 47,151 |

## Customer Ledger And Client Code

`mst_ledger` appears to contain Tally customer/debtor ledgers as well as other ledger types.

Important fields:

- `name`
- `parent`
- `alias`
- `mobile`
- `gstn`

Demo observations:

- Ledger aliases include client-code-like values such as `KE1001`, `KE2594`, and `CS1633`.
- Many customer-like ledgers roll up through groups whose `primary_group` is `Sundary Debtors`.
- `mst_ledger.alias` is the likely Tally-side field for app `client_code`.

Decision:

```text
Customer.client_code = mst_ledger.alias
```

Use `client_code` only for automatic customer identity matching. Party name, GSTIN, legal name, and mobile number are useful for display/debugging but should not be automatic match keys.

## Godowns

There are 3 godowns:

| Godown | Parent | Notes |
| --- | --- | --- |
| `Goshamahal` | `Primary` | Has address |
| `Kukatpally` | `Primary` | Has address |
| `Main Location` | `Primary` | No address |

Portal branches should map to these godowns.

Likely branch mapping:

- Branch: Goshamahal -> Godown: Goshamahal
- Branch: Kukatpally -> Godown: Kukatpally
- Main Location needs business clarification

## Stock Groups

`mst_stock_group` columns:

- `guid`
- `name`
- `parent`

There are 775 stock groups.

In `mst_stock_item`:

- 10,841 of 10,879 items have a stock group in `parent`.
- 642 distinct groups are actually used by items.

Top-level stock group hierarchy is useful. There are 74 root stock groups.

Top root groups by item count include:

| Root Group | Items |
| --- | ---: |
| `Merino Industries Limited` | 2,504 |
| `OUTLAM (4823)` | 1,605 |
| `CENTURY PLB (4410)` | 835 |
| `MARIA DECOR` | 598 |
| `KE STOCK` | 524 |
| `GREEN VENEER` | 516 |
| `PRAVEEDDH (3921,4411 & 4412) (PRAVEDH)` | 419 |
| `EURO` | 374 |
| `GREENPANEL` | 319 |
| `PLYWOOD (4412)` | 313 |

## Stock Categories

`mst_stock_category` columns:

- `guid`
- `name`
- `parent`

There are 189 stock categories.

In `mst_stock_item`:

- 6,246 of 10,879 items have a category.
- 4,633 items have no category.
- 148 distinct categories are used by items.

Top categories by item count include:

| Category | Items |
| --- | ---: |
| blank/unmapped | 4,633 |
| `Greenlam Veneer` | 493 |
| `MERINO 1 MM - TXT` | 418 |
| `Century  PLB` | 392 |
| `PRAVEEDH` | 379 |
| `MARIA DECOR` | 372 |
| `CENTURY MDF` | 286 |
| `MERINO FLEX 6` | 265 |
| `PVC LAM (1.00 MM)` | 226 |
| `MERINO 1 MM - SF` | 207 |

## Item Master

`mst_stock_item` columns include:

- `guid`
- `name`
- `parent`
- `category`
- `alias`
- `description`
- `notes`
- `part_number`
- `uom`
- `alternate_uom`
- `conversion`
- `opening_balance`
- `opening_rate`
- `opening_value`
- `closing_balance`
- `closing_rate`
- `closing_value`
- GST fields

Important observations:

- Item `parent` is the immediate stock group.
- Item `category` is optional and missing for many items.
- Item-level `closing_balance` exists.
- Item-level `closing_balance` is not broken down by godown in `mst_stock_item`.

## First Selector Recommendation

Based on actual data, the first selector in the app should not be raw category.

Reason:

- Category is missing for 4,633 items.
- Category coverage is only around 57% of items.
- Using category directly would hide or awkwardly group too many items.

Better recommendation:

Use **root stock group** as the first selector.

Reason:

- Stock group coverage is almost complete.
- Immediate stock group is too granular with 642 used groups.
- Root stock group gives a manageable business-level selector with 74 roots.
- Root group names look closer to brand/family/business divisions.

Recommended app terminology:

```text
UI label: Product Group
Technical source: root of mst_stock_group hierarchy
```

Then the item list can be filtered by all child groups under that root.

## Frappe Import Shape

The project will use a custom Frappe app, not ERPNext.

The Tally group hierarchy should be imported into custom Frappe DocTypes.

Recommended `Tally Stock Group` fields:

- Tally GUID
- Group name
- Parent stock group
- Root stock group
- Is root
- Depth
- Full path
- Last synced timestamp
- Is active

Recommended `Tally Item` fields:

- Tally GUID
- Item name
- Immediate stock group
- Root stock group
- Stock category
- UOM
- Total closing balance
- Last synced timestamp
- Is active

The root stock group should be precomputed during sync/import so mobile APIs can filter efficiently.

## Stock And Godown Availability

There is no obvious ready-made current stock-by-godown table in the database.

Relevant tables:

- `mst_stock_item` has item-level `closing_balance`.
- `mst_opening_batch_allocation` has opening balance by item/godown.
- `trn_inventory` has transaction lines by item/godown.
- `trn_batch` has batch/allocation lines by item/godown.
- `trn_closingstock_ledger` exists but has 0 rows.

Important finding:

Calculating current godown stock from `mst_opening_batch_allocation + trn_inventory` did not consistently match `mst_stock_item.closing_balance`.

This may be because:

- The sync period is limited to `2026-01-01` through `2026-05-11`.
- Tally sign conventions and voucher types need careful handling.
- Physical stock, transfers, sales, purchases, DCs, sales invoices, and returns may need type-specific treatment.
- The loader may not include a direct stock summary by godown collection.

## Stock Display Implication

The mobile app requires stock by godown for a selected item.

Current connector tables are enough to show:

- Overall item closing balance from `mst_stock_item.closing_balance`
- Transaction lines by godown from `trn_inventory` / `trn_batch`

But they may not be enough to safely show current stock by godown without additional work.

Recommended options:

1. Extend connector/export config to pull Tally stock summary by item and godown.
2. Add a custom Tally XML request from our connector layer to fetch stock by item/godown.
3. Build a calculation engine from opening allocations and transactions only after validating formulas against Tally reports.

Recommended starting approach:

Enhance `tally-database-loader` to export a Tally-computed stock-by-godown snapshot and raise the change as a generic upstream pull request. Do not depend on inferred godown stock calculations until validated against Tally.

The snapshot should be imported into Frappe as `Tally Stock Snapshot`.

Recommended fields:

- Item
- Godown
- Quantity
- UOM
- As on date
- Source company
- Synced at
- Source sync run

## Duplicate Movement Risk

The demo data confirms a major duplication risk when calculating stock from `trn_inventory`.

Many inventory lines appear once in Delivery Challan vouchers and again in Sales vouchers. These rows often have:

- Same `tracking_number`
- Same item
- Same godown
- Same quantity
- Same or related voucher number
- Same party

Example pattern:

```text
Delivery Challan Goshamahal | G/18308/25-26 | item X | -qty | tracking G/18308/25-26
Sales Goshamahal            | G/18308/25-26 | item X | -qty | tracking G/18308/25-26
```

This means a naive stock query that sums all non-order `trn_inventory` rows can double-count the same physical movement.

Observed duplicate indicators:

| Metric | Value |
| --- | ---: |
| `trn_inventory` lines | 65,021 |
| Lines with `tracking_number` | 53,343 |
| Distinct tracking numbers | 14,515 |
| Sales/DC duplicate item-godown-quantity keys | 26,598 |

Sales and Delivery Challan movements are almost mirrored:

| Voucher Type | Lines With Tracking Number | Quantity |
| --- | ---: | ---: |
| `Delivery Challan Goshamahal` | 9,131 | -154,253.1600 |
| `Sales Goshamahal` | 9,131 | -154,253.1600 |
| `Delivery Challan Kukatpally` | 12,395 | -154,962.0000 |
| `Sales Kukatpally` | 12,396 | -154,962.0000 |
| `Delivery Challan Kukatpally 1` | 626 | -7,426.0000 |
| `Sales Kukatpally 1` | 626 | -7,426.0000 |
| `Delivery Challan Seetarambagh` | 4,518 | -45,193.0000 |
| `Sales Seetarambagh` | 4,518 | -45,193.0000 |

This validates the warning that GRN/GDN plus purchase/sales workflows can duplicate inventory movement in the extracted tables.

## Stock Query Validation

A proposed stock query was tested:

```sql
opening batch allocation
+ trn_inventory movement where is_order_voucher = 0
```

This query is structurally reasonable, but in the demo DB it does not consistently match `mst_stock_item.closing_balance`.

The issue improves if either Sales or Delivery Challan rows are excluded, which confirms duplicate counting:

| Calculation | Total Absolute Difference vs `mst_stock_item.closing_balance` |
| --- | ---: |
| Opening + all non-order movement | 552,435.2700 |
| Opening + movement excluding Sales vouchers | 277,502.1100 |
| Opening + movement excluding Delivery Challan vouchers | 274,405.1100 |

Even after excluding one side, the calculated stock still does not fully match item closing balances. So duplicate handling is necessary but not sufficient.

Recommended rule for any transaction-derived stock calculation:

1. Do not count both Delivery Challan and Sales rows for the same tracked movement.
2. Prefer one fulfillment document type for stock movement calculation.
3. Use `tracking_number` to detect linked/duplicated movement.
4. Validate against Tally's stock summary before exposing to users.

For our product, a proper Tally stock summary by item/godown is still preferred over deriving stock from all transaction rows.

## Voucher Tables

`trn_voucher` columns include:

- `guid`
- `date`
- `voucher_type`
- `voucher_number`
- `reference_number`
- `reference_date`
- `narration`
- `party_name`
- `place_of_supply`
- `is_invoice`
- `is_accounting_voucher`
- `is_inventory_voucher`
- `is_order_voucher`

`trn_inventory` columns include:

- `guid`
- `item`
- `quantity`
- `rate`
- `amount`
- `additional_amount`
- `discount_amount`
- `godown`
- `tracking_number`
- `order_number`
- `order_duedate`

The `guid` links voucher header to inventory lines.

Sales Invoice line items are available in `trn_inventory` joined to `trn_voucher` by `guid`. This includes item, quantity, godown, and tracking number. Therefore, line-level and quantity-level order reconciliation is possible if the portal reference number and customer/item matching rules are reliable.

## Voucher Data

Top operational voucher types:

| Voucher Type | Rows |
| --- | ---: |
| `Sales Kukatpally` | 6,905 |
| `Delivery Challan Kukatpally` | 6,905 |
| `Receipt` | 5,651 |
| `Sales Goshamahal` | 4,470 |
| `Delivery Challan Goshamahal` | 4,470 |
| `Sales Seetarambagh` | 2,862 |
| `Delivery Challan Seetarambagh` | 2,862 |
| `Purchase Goshamahal` | 1,833 |
| `Purchase Order Goshamahal` | 1,587 |

Sales and DC vouchers have matching counts by branch:

- `Sales Kukatpally`: 6,905
- `Delivery Challan Kukatpally`: 6,905
- `Sales Goshamahal`: 4,470
- `Delivery Challan Goshamahal`: 4,470
- `Sales Seetarambagh`: 2,862
- `Delivery Challan Seetarambagh`: 2,862

## Reference Number Finding

Reference number availability is currently weak for our planned reconciliation flow.

Observed:

- Main sales vouchers checked: 14,539 total, 0 with `reference_number`.
- Delivery challans checked: 14,539 total, only 2 with `reference_number`.

This means the current Tally data is not consistently using `trn_voucher.reference_number` for sales/DC records.

For our system, branch users must reliably enter the portal reference number into the correct Tally field that maps to `trn_voucher.reference_number`, or reconciliation will fail.

Before implementation, we must test a new Tally DC/Sales Invoice entry with a known reference number and confirm it appears in `trn_voucher.reference_number` after sync.

## Order Number Finding

`trn_inventory.order_number` is populated in some records.

Observed:

- `trn_inventory` total lines: 65,021
- Lines with `order_number`: 3,574
- Lines with `tracking_number`: 53,343

The sampled `order_number` values were primarily from `Purchase Order Goshamahal`, not customer sales order fulfillment.

This is not enough to replace the planned portal reference number strategy.

## Reconciliation Implication

The planned reconciliation approach is still valid, but it depends on Tally entry discipline.

Required operational rule:

Branch users must put the portal order reference number into the Tally field that syncs to `trn_voucher.reference_number`.

Reconciliation should match:

- `trn_voucher.reference_number`
- `trn_voucher.party_name`
- `trn_inventory.item`
- `trn_inventory.quantity`

Godown from Tally lines should be stored for diagnostics, but fulfillment completion should be item-wise because operations may reroute fulfillment from another godown.

Fulfillment status should use both Delivery Challan and Sales Invoice with de-duplication:

- Sales Invoice is the primary/confirmed fulfillment signal when present.
- Delivery Challan is provisional when no Sales Invoice is present yet.
- The same tracked DC/Sales movement must be counted only once.

Because sales/DC reference numbers are currently mostly empty, this must be verified with a controlled Tally test before building final automation.

## Updated Architecture Decisions

Based on demo data:

1. Use root stock group as the app's first-level selector.
2. Keep category as a secondary/filtering attribute, not the primary selector.
3. Import `mst_stock_group` hierarchy into Frappe.
4. Store root group on synced item records for fast filtering.
5. Import godowns and map them to portal branches.
6. Do not rely only on current connector tables for godown-wise stock until validated.
7. Add or fetch a proper Tally stock summary by item/godown.
8. Test `reference_number` sync from new Tally DC/Sales Invoice entries before final reconciliation design.

## Open Follow-Up Checks

- Confirm which Tally screen/field writes to `trn_voucher.reference_number`.
- Confirm whether sales invoice or delivery challan should be the primary fulfillment signal.
- Confirm whether one portal order can create multiple DCs/invoices.
- Confirm whether one Tally DC/invoice can contain multiple portal references.
- Validate stock by godown against a live Tally stock summary report.
- Decide how to handle `Main Location`.
- Decide whether `Sales Seetarambagh` and `Delivery Challan Seetarambagh` represent a third branch even though `mst_godown` only has Goshamahal, Kukatpally, and Main Location.
