# Overall Problem Statement

## Purpose

The project is a Tally-connected order placement system for customers, sales employees, and internal portal users.

Customers and sales employees place order requests from a mobile app. Internal users review and process those orders through a Frappe-based portal. Tally remains the source of truth for inventory masters, stock, godowns, delivery challans, sales invoices, and fulfillment records.

The portal owns the application workflow: user approvals, access rules, order requests, order references, order status, and communication logs.

## Users

The system has three broad user groups:

- Customers
- Sales employees
- Internal portal users

Customers and sales employees use the mobile app. Internal users use the portal.

## Core Flow

The high-level order flow is:

1. Tally data is synced into a PostgreSQL database using the Tally connector.
2. Required Tally-derived data is imported or synced into Frappe.
3. Customer or sales employee logs in with WhatsApp OTP.
4. User selects allowed item group/category/brand, item, godown stock, and quantity.
5. User confirms the order request.
6. Frappe creates an order with a generated portal reference number.
7. Frappe sends a WhatsApp confirmation with a PDF order summary.
8. Branch users process the order operationally.
9. Branch users create DC and/or Sales Invoice in Tally using the portal reference number.
10. Connector/reconciliation process reads Tally vouchers and updates the portal order status.

## Stack Decision

The agreed stack is:

- Backend and portal: Frappe
- Mobile app: Expo / React Native
- Tally connector: `tally-database-loader` with PostgreSQL
- WhatsApp: Frappe CRM WhatsApp integration / direct WhatsApp Business Platform capabilities through Frappe

Frappe should expose the business APIs used by the mobile app. The mobile app should not directly read the raw Tally connector database.

## Source Of Truth

Tally is the source of truth for:

- Stock items
- Stock groups
- Stock categories
- Godowns
- Units
- Stock balances
- Ledgers/customers, where applicable
- Delivery challans
- Sales invoices
- Voucher-level fulfillment records

Frappe is the source of truth for:

- Portal users
- Customer signup and approval state
- Sales employee accounts
- Role permissions
- Mobile app access
- Visibility filters
- Customer assignments for sales employees
- Order requests
- Portal reference numbers
- Order status shown in the app
- WhatsApp OTP and notification logs
- PDF order summaries
- Reconciliation logs

PostgreSQL connector database is the raw Tally mirror/read replica. It should not become the main application database.

## Data Movement

The data movement should be:

```text
Tally
  -> Tally connector
  -> PostgreSQL raw mirror
  -> controlled sync/import layer
  -> Frappe DocTypes
  -> Portal and mobile APIs
```

For reconciliation:

```text
Tally DC / Sales Invoice
  -> PostgreSQL raw mirror
  -> reconciliation job
  -> Frappe order status update
  -> mobile app order history/status
```

## What To Import Into Frappe

Do not import all raw connector data into Frappe.

Import only the application-facing data that the portal and mobile app require:

- Items
- Stock groups
- Stock categories
- Godowns
- Units of measure
- Customers / ledgers needed for ordering
- Current stock snapshots
- Delivery challans required for reconciliation
- Sales invoices required for reconciliation
- Voucher lines required for matching against order lines

Keep all raw and verbose Tally data in PostgreSQL. Frappe should store cleaned, indexed, app-ready records.

## Visibility Filter Decision

Use inclusive filters.

The rule is:

```text
No filter configured = all visible
Filter configured = only configured values are visible
```

This applies to both customers and sales employees.

Inclusive filters are preferred because they are safer and easier to explain. If a new item group/category is added in Tally, it will not accidentally become visible to a restricted user unless explicitly included.

## Filter Dimensions

Filters may be applied on:

- Stock group
- Stock category
- Item
- Godown/branch, if needed later
- Customer access, for sales employees

The initial implementation should keep the filter model flexible enough to support multiple dimensions, but the first ordering selector should be a single business concept.

## Brand / Group / Category Decision

The mobile flow needs one first-level selector. The options are:

- Brand
- Stock group
- Stock category

Tally does not appear to have a reliable native brand table. Because of this, the first-level selector should initially be mapped to Tally stock group or stock category.

Recommended starting decision:

- Use Tally Stock Group as the first-level selector.
- In the UI, this can be labelled as "Brand" if the business uses groups as brands.
- If actual Tally data shows that Stock Category maps better to brand, switch the selector to Stock Category before implementation.
- If neither group nor category is clean, create a portal-side Brand Mapping DocType that maps one brand to many groups/categories/items.

This must be validated against real Tally master data before final implementation.

## Order Placement Principle

Orders placed in the app are requests, not stock reservations.

Placing an order should not reduce stock in Frappe or Tally. Actual stock movement happens only when the branch creates a DC or Sales Invoice in Tally.

The app should show the latest synced stock. Real-time stock calls to Tally are not required for the initial implementation.

## Order Status Principle

Frappe order status is updated through reconciliation with Tally.

The expected statuses are:

- Draft, if needed before confirmation
- Placed
- Processing
- Partially Processed
- Completed
- Cancelled, if needed
- Manual Review, when automatic matching fails

Automatic status updates should happen only when the Tally voucher can be matched confidently to the portal order reference and item lines. If the match is unclear, the order should go to manual review instead of making a risky update.

## WhatsApp Decision

Use the Frappe WhatsApp integration path where possible, especially since Frappe CRM has built-in WhatsApp capabilities.

WhatsApp will be used for:

- OTP verification
- Order confirmation
- Thank-you message
- PDF order summary attachment
- Potential future order status updates

Before implementation, verify the exact capabilities and constraints of the Frappe WhatsApp integration being used:

- Whether OTP/authentication templates are supported directly
- Whether PDF document messages are supported
- Template approval process
- Webhook support for delivery/read/error statuses
- Retry and failure logging model

## Main Modules

The system can be split into four modules:

- Overall application model
- Portal
- Mobile app
- Tally connector and reconciliation

The detailed docs for these modules are:

- `01-overall-problem-statement.md`
- `02-portal.md`
- `03-mobile-app.md`
- `04-tally-connector.md`

## Key Risks

The biggest risks are:

- Tally group/category structure may not match the desired "brand" experience.
- Stock may be stale because latest synced stock is accepted instead of real-time Tally stock.
- Branch users may create Tally vouchers without the correct portal reference number.
- Tally voucher lines may not match portal order lines cleanly.
- WhatsApp template approval and document message behavior may affect OTP/order confirmation design.
- Frappe role permissions may need custom logic for branch-level order visibility.

## Open Decisions

The following must be finalized after seeing real Tally data:

- Whether first-level item selection uses Stock Group or Stock Category.
- Whether a portal-side Brand Mapping table is needed.
- Exact customer/ledger mapping between mobile users and Tally ledgers.
- Exact branch-to-godown mapping.
- Exact DC/Sales Invoice matching rules.
- Whether branch employees can update order status manually or only through reconciliation.
- Whether cancellation is allowed after order placement.
