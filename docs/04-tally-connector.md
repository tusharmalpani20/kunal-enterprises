# Tally Connector Requirements

## Purpose

The Tally connector module brings required Tally data into the application ecosystem and reconciles fulfillment activity back to portal orders.

The proposed connector is:

```text
https://github.com/amol909/tally-database-loader
```

The connector reads from Tally and stores data in PostgreSQL. Frappe should consume only the required, cleaned data from this raw mirror.

## Architecture

The connector architecture should be:

```text
Tally
  -> tally-database-loader
  -> PostgreSQL raw Tally mirror
  -> sync/import service
  -> Frappe DocTypes
```

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

Decision currently recommended:

- Start with Stock Group as the first-level selector.
- Change to Stock Category if real data proves it is cleaner.
- Add Brand Mapping if neither is good enough.

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

Important:

Placing an order does not reserve stock. It only creates an order request.

## Customer/Ledger Sync

Customer mobile accounts and sales employee order placement may need to map to Tally ledgers.

The sync should import only ledgers/customers needed for ordering.

Required mapping:

- Frappe customer/mobile user
- Tally ledger/customer

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

Example:

```text
KE-ORD-2026-000001
```

The exact format should be finalized before implementation.

## Reconciliation Scope

The reconciliation process reads Tally DC and Sales Invoice data and updates Frappe order status.

It should match:

- Portal reference number
- Customer/ledger, if available
- Item
- Godown
- Quantity
- Voucher type
- Voucher date

The reconciliation process should update:

- Fulfilled quantity per order item
- Fulfilled quantity per godown allocation
- Pending quantity
- Order status
- Reconciliation logs

## Matching Rules

Automatic reconciliation should happen only if matching is confident.

Recommended matching process:

1. Find Tally vouchers where reference number equals portal order reference.
2. Validate voucher customer/ledger against portal order customer, if available.
3. Read voucher lines.
4. Match voucher lines to order item and godown allocations.
5. Sum fulfilled quantities.
6. If fulfilled quantity is zero, keep order unchanged or mark review depending on context.
7. If fulfilled quantity is greater than zero but less than requested quantity, mark Partially Processed.
8. If fulfilled quantity equals requested quantity for all lines, mark Completed.
9. If voucher data conflicts with order data, create Manual Review exception.

## Manual Review Conditions

Send reconciliation to manual review when:

- Reference number exists but item does not match.
- Reference number exists but customer/ledger does not match.
- Voucher quantity exceeds requested quantity unexpectedly.
- Voucher has godown mismatch.
- Multiple vouchers use the same reference in an unexpected way.
- Voucher has extra lines that cannot be mapped.
- Required Tally identifiers are missing.

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

- Masters: every few hours or manual trigger
- Stock: every 5-15 minutes during business hours
- Voucher reconciliation: every 5-15 minutes during business hours

This depends on Tally performance, network reliability, and branch expectations.

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
- Can one invoice contain lines from multiple portal orders?
- Will branch users always enter the reference number correctly?
- What is the acceptable stock sync delay for users?
