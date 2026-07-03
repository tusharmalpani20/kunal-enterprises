# Tally Connector Requirements

## Purpose

The Tally connector module brings required Tally data into the application ecosystem and reconciles fulfillment activity back to portal orders.

The proposed connector is:

```text
https://github.com/amol909/tally-database-loader
```

The connector reads from Tally and stores data in PostgreSQL. Frappe should consume only the required, cleaned data from this raw mirror.

Current decision: prefer enhancing this connector for stock-by-godown snapshots and raising a pull request to the official repository, instead of maintaining a separate custom connector service.

## Architecture

The connector architecture should be:

```text
Tally
  -> tally-database-loader
  -> PostgreSQL raw Tally mirror
  -> sync/import service
  -> Frappe DocTypes
```

Frappe itself should also run on PostgreSQL, but the Frappe application database is separate from the connector's raw PostgreSQL mirror.

Reconciliation path:

```text
Tally DC / Sales Invoice
  -> PostgreSQL raw mirror
  -> reconciliation service/job
  -> Frappe Order / Order Item / Order Allocation updates
```

## Principle

Do not make the mobile app or portal business logic depend directly on raw connector tables.

The raw PostgreSQL database is an integration source, not the application model.

Frappe should contain the business-level records required by the portal and mobile app.

## Required Tally Data

The initial required Tally data is:

- Stock items
- Stock groups
- Stock categories
- Godowns
- Units of measure
- Customers/ledgers needed for ordering
- Current stock by item and godown
- Delivery challans
- Sales invoices
- Voucher lines for reconciliation

Data not needed by the app should remain only in the raw PostgreSQL mirror unless a future requirement needs it.

## Sync Into Frappe

Sync only required application data into Frappe.

Frappe should import/sync required PostgreSQL mirror data into Frappe DocTypes. The mobile app and portal business logic should not query the raw PostgreSQL mirror directly.

Recommended synced DocTypes:

- Tally Item
- Tally Stock Group
- Tally Stock Category
- Tally Godown
- Tally Unit
- Tally Customer Ledger
- Tally Stock Snapshot
- Tally Voucher
- Tally Voucher Line
- Tally Sync Run
- Tally Sync Error

Owner/Admin portal should provide manual sync actions:

- Sync Masters Now
- Sync Stock Now
- Run Reconciliation Now

These are for onboarding, testing, and operational troubleshooting.

## Item Master Sync

Each item record should preserve:

- Tally stable identifier, if available
- Tally item name
- Stock group
- Stock category
- Unit
- Active/inactive state
- Last synced timestamp

If Tally does not expose a reliable stable identifier, item name may be used initially, but this creates rename risk. We should inspect actual connector output before finalizing identity rules.

## Group And Category Sync

Stock groups and stock categories are important because one of them will likely become the app's first-level selector.

Before implementation, inspect real Tally data and answer:

- Are brands represented as stock groups?
- Are brands represented as stock categories?
- Are groups hierarchical?
- Are categories consistently maintained?
- Are item names dependent on group/category context?

Decision after demo data review:

- Use root Stock Group as the first-level selector.
- Keep immediate Stock Group for hierarchy and item classification.
- Keep Stock Category as secondary metadata because many items do not have a category.
- Add Brand Mapping later only if the business wants a cleaner commercial layer.

Sync behavior:

- If a Tally stock group is renamed but has the same stable identity/GUID, update the Frappe Product Group display name.
- If a Tally stock group disappears from sync, mark the corresponding Product Group inactive rather than deleting it.
- Existing Orders retain snapshot names from order time.
- Access child rows pointing to inactive Product Groups should show an inactive warning in the portal.

## Godown Sync

Godowns are required for:

- Showing stock by location
- Allowing users to choose from which godown they want to request quantity
- Mapping orders to branches
- Controlling branch manager/employee visibility

Frappe must maintain a mapping:

- Tally Godown
- Portal Branch

One branch may map to one or more godowns.

## Stock Sync

Latest synced stock is acceptable.

The system does not need real-time Tally stock calls for the initial implementation.

Stock should be available by:

- Item
- Godown
- Quantity
- Unit
- Last synced timestamp

Store both:

- Total item closing balance from `mst_stock_item.closing_balance`
- Godown-wise quantity from the stock snapshot export

Order placement uses godown-wise stock. Total item closing balance is for summaries and diagnostics.

Important:

Placing an order does not reserve stock. It only creates an order request.

Godown-wise stock should come from a Tally-computed stock snapshot, not from naive summation of voucher movement rows.

The existing connector tables provide:

- `mst_stock_item.closing_balance`, which is total item closing balance.
- `mst_opening_batch_allocation`, which has opening balance by item/godown.
- `trn_inventory`, which has transaction movement lines by item/godown.
- `trn_batch`, which has batch allocation lines by item/godown.

Demo data shows that Sales and Delivery Challan rows can duplicate the same physical movement. Therefore, godown-wise stock should not be calculated by naively summing `trn_inventory`.

Preferred implementation:

- Add a Tally-computed stock-by-godown snapshot export to `tally-database-loader`.
- Store it in a new PostgreSQL table.
- Import that table into Frappe's `Tally Stock Snapshot` DocType.
- Raise the connector change as a generic upstream pull request.

Possible PostgreSQL table:

```sql
create table rpt_stock_godown_balance (
    item varchar(1024),
    godown varchar(1024),
    batch_name varchar(1024),
    quantity decimal(17,4),
    rate decimal(17,4),
    value decimal(17,2),
    uom varchar(32),
    as_on_date date
);
```

The connector export may emit one row per batch. Frappe imports this table grouped by `item` and `godown`, summing `quantity`, so batch-level detail does not leak into the mobile ordering flow.

The source should be TallyPrime's computed Stock Summary / Godown Summary data exposed through XML/TDL, not a transaction reconstruction.

Official TallyPrime docs confirm:

- TallyPrime supports XML/HTTP integration and can export data/reports through XML requests.
- Stock Summary is a real-time stock-in-hand report.
- Godown/Location Summary shows stock details by godown/location.

Relevant docs:

- https://help.tallysolutions.com/integration-with-tallyprime/
- https://help.tallysolutions.com/tally-prime/inventory-reports/track-your-inventory-stock-summary-tally/
- https://help.tallysolutions.com/godown-summary-tally/

If `tally-database-loader` runs every 5 minutes, the new stock snapshot table can also refresh every 5 minutes. This gives the application latest synced stock, not second-by-second live stock. It is still based on Tally's live computed data at sync time.

## Customer/Ledger Sync

Customer mobile accounts and sales employee order placement may need to map to Tally ledgers.

The sync should import only ledgers/customers needed for ordering.

Sales employees are not synced from or mapped to Tally. They exist only in Frappe.

Required mapping:

- Frappe customer/mobile user
- Tally ledger/customer

Customer reconciliation key:

```text
Customer.client_code = mst_ledger.alias
```

Use only `client_code` for automatic customer identity matching. Tally party name, legal name, GSTIN, and mobile number may be shown for diagnostics, but should not be used as automatic match keys.

Based on demo data, customer ledgers appear in `mst_ledger`, with debtor groups rolling up to `Sundary Debtors`. The exact debtor/customer ledger filter should be confirmed against client Tally data.

Customer activation depends on this mapping:

```text
client_code blank = allowed while pending/reviewing
client_code entered but not found in imported Tally customer ledgers = invalid
client_code entered and found in imported Tally customer ledgers = eligible for activation
```

Open question:

- Should customer signup create a new Tally ledger later, or must admin map the signup to an existing Tally ledger?

Initial recommendation:

- Admin maps approved customers to existing Tally ledgers.
- Tally ledger creation from portal can be considered later only if required.

## Order Reference Number

Frappe generates the portal order reference number.

Branch users must enter this reference number in Tally when creating:

- Delivery Challan
- Sales Invoice

The reference number is the main matching key for reconciliation.

Use Tally's Reference Number field for the portal order reference. The connector exports this as `trn_voucher.reference_number`.

The same portal order reference should be entered in every related DC and Sales Invoice.

One portal Order can be fulfilled by multiple Tally vouchers. Reconciliation should sum deduplicated fulfilled item quantities across all matching DC/Sales Invoice vouchers for the same reference.

One Tally voucher should belong to one portal Order reference. Do not mix items from multiple portal Orders into a single Tally voucher because `reference_number` is voucher-level in the current connector data.

Chosen format:

```text
KE-YY-MM-####
```

Example:

```text
KE-26-05-0001
```

The sequence resets every month.

`YY-MM` is based on the server-side Order confirmation timestamp.

## Reconciliation Scope

The reconciliation process reads Tally DC and Sales Invoice data and updates Frappe order status.

Fulfillment source rule:

```text
Use Sales Invoice as the primary/confirmed fulfillment signal when present.
Use Delivery Challan as a provisional fulfillment signal when Sales Invoice is not yet present.
Never count both DC and Sales Invoice for the same tracked item/godown movement.
```

Because demo data shows mirrored DC and Sales rows, reconciliation must de-duplicate using available identifiers such as `tracking_number`, voucher number, item, godown, customer, quantity, and portal reference number.

It should match:

- Portal reference number
- Customer `client_code` against Tally ledger alias
- Item
- Quantity
- Voucher type
- Voucher date

Godown is useful for diagnostics and branch context, but fulfillment completion is matched item-wise rather than godown-wise. Operations may fulfill from a different godown than the order allocation.

For fulfillment reconciliation, `tracking_number` can help detect linked Delivery Challan/Sales records, but the primary matching key for our portal order should still be the portal reference number once the client enters it into the correct Tally field.

The reconciliation process should update:

- Fulfilled quantity per order item
- Fulfilled quantity per godown allocation
- Pending quantity
- Order status
- Reconciliation logs

Sales Invoice and Delivery Challan line items are available through `trn_inventory`, linked to `trn_voucher` by `guid`. This allows quantity-level reconciliation:

```text
Order Item requested quantity
  vs
deduplicated fulfilled quantity from Tally voucher lines
```

If fulfilled quantity is less than requested quantity, status remains Partially Processed. When fulfilled quantity reaches requested quantity for all order lines, status becomes Completed.

## Matching Rules

Automatic reconciliation should happen only if matching is confident.

Recommended matching process:

1. Find Tally vouchers where reference number equals portal order reference.
2. Validate voucher customer/ledger against portal order customer, if available.
3. Read DC and Sales Invoice voucher lines.
4. De-duplicate linked DC/Sales Invoice movement so the same physical fulfillment is counted once.
5. Match voucher lines to order items.
6. Sum fulfilled quantities across all matching vouchers for the same portal reference.
7. If fulfilled quantity is zero, keep order unchanged or mark review depending on context.
8. If fulfilled quantity is greater than zero but less than requested quantity, mark Partially Processed.
9. If fulfilled quantity equals requested quantity for all lines, mark Completed.
10. If voucher data conflicts with order data, create Manual Review exception.

## Manual Review Conditions

Send reconciliation to manual review when:

- Reference number exists but item does not match.
- Reference number exists but customer/ledger does not match.
- Voucher quantity exceeds requested quantity unexpectedly.
- Multiple vouchers use the same reference in an unexpected way.
- DC and Sales Invoice lines appear duplicated but cannot be confidently linked.
- Voucher has extra lines that cannot be mapped.
- Required Tally identifiers are missing.

If fulfilled quantity for an item exceeds the requested quantity, the order should move to Manual Review rather than silently capping or accepting the excess.

If a Tally voucher contains an extra item that does not exist on the Order, the order should move to Manual Review.

If the reference number matches but the Tally customer/client code does not match the Order customer, the order should move to Manual Review.

Every Manual Review transition must store a reason code and human-readable reason message so portal users can understand why automation stopped.

Manual Review resolution is owner/admin only and requires a resolution note.

Manual review should expose enough detail for an admin to decide what happened.

## Partial Fulfillment

Partial fulfillment is allowed.

Example:

```text
Order requested:
- Item A, Godown 1, 100 pcs

Tally processed:
- Item A, Godown 1, 40 pcs

Portal status:
- Partially Processed
- Fulfilled quantity: 40
- Pending quantity: 60
```

When remaining quantity is later processed in Tally using the same reference number, the portal can move the order to Completed.

## Sync Frequency

Initial acceptable behavior:

- Master data sync can run periodically.
- Stock sync can run frequently enough for business comfort.
- Voucher reconciliation can run periodically.

Exact frequency needs operational input.

Possible starting point:

- Masters: every 5 minutes
- Stock: every 5 minutes
- Voucher reconciliation: every 5 minutes

This depends on the Tally-to-PostgreSQL extraction performance, network reliability, and connector mode. If the connector runs true incremental/delta sync with correct AlterID tracking, the 5-minute master cadence should be much lighter. The stress concern applies mainly to full master extraction every 5 minutes. Frappe consumes the PostgreSQL mirror after the connector writes it, which should be much cheaper than asking Tally directly.

## Error Handling

The connector/sync layer should log:

- Sync start and end time
- Sync type
- Records inserted/updated
- Records skipped
- Errors
- Last successful sync timestamp

Frappe portal should expose:

- Latest stock sync time
- Latest voucher sync time
- Sync failures
- Reconciliation failures

Stale or failed stock sync should not block order placement. The app should show the latest available sync timestamp, and the order should record which stock snapshot timestamp was used.

Stock snapshot sync and voucher reconciliation should run independently. Failure in one should not stop the other.

## Operational Requirements

The connector likely runs in or near the Tally environment.

Expected requirements:

- Windows machine with Tally available
- Tally XML/ODBC/server access as required by connector
- Node.js runtime for connector
- PostgreSQL database
- Network access from Frappe sync job to PostgreSQL or an intermediate API

The exact deployment model must be decided:

- Same machine as Tally
- Branch/server machine
- Cloud-hosted PostgreSQL receiving data from local connector
- VPN/private network

## Security Considerations

The raw PostgreSQL mirror may contain sensitive business data.

Security requirements:

- Restrict PostgreSQL network access
- Use separate database credentials for sync
- Do not expose raw connector DB to mobile app
- Store integration credentials securely
- Log access to reconciliation/admin screens where needed

## Open Connector Questions

- Which exact connector tables contain item, group, category, godown, stock, voucher, and voucher line data?
- Does the connector expose stable Tally GUIDs for masters and vouchers?
- Which Tally field should store the portal reference number?
- Are DC and Sales Invoice both required for fulfillment status, or should one have priority?
- How should returns/cancellations/credit notes affect order status?
- Can multiple invoices be created against one portal order?
- Can one invoice contain lines from multiple portal orders? Current decision: no.
- Will branch users always enter the reference number correctly?
- What is the acceptable stock sync delay for users?
- What exact TDL/XML collection should be added to `tally-database-loader` for stock-by-godown snapshot?
- Should the stock snapshot be generated for all items/godowns every sync, or filtered by active/visible items?
- Should stock snapshot sync be full replace each time or upsert by item/godown/as-on-date?
