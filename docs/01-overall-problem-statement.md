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
4. User selects allowed Product Group, item, godown stock, and quantity.
5. User confirms the order request.
6. Frappe creates an order with a generated portal reference number.
7. Frappe sends a WhatsApp confirmation with a PDF order summary.
8. Branch users process the order operationally.
9. Branch users create DC and/or Sales Invoice in Tally using the portal reference number.
10. Connector/reconciliation process reads Tally vouchers and updates the portal order status.

## Stack Decision

The agreed stack is:

- Backend and portal: Frappe custom app
- Frappe database: PostgreSQL
  - "frappe": "15.103.3",	"frappe_whatsapp": "1.0.12",
  - install guide for frappe https://docs.frappe.io/framework/user/en/installation#macos
- Mobile app: Expo / React Native 
  - ~ react-native-reusables for components
- Tally connector: `tally-database-loader` with PostgreSQL 
  - ~ repo : https://github.com/amol909/tally-database-loader
- WhatsApp: Frappe CRM WhatsApp integration / direct WhatsApp Business Platform capabilities through Frappe

Frappe should expose the business APIs used by the mobile app. The mobile app should not directly read the raw Tally connector database.

ERPNext is not part of the current plan. Inventory, ordering, access control, and Tally sync records will be modelled as custom Frappe DocTypes based on this project's requirements.

Mobile authentication is a custom WhatsApp OTP + JWT/session flow independent of Frappe Desk login. Internal portal users continue using Frappe authentication.

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

Frappe should also use PostgreSQL as its application database. The Frappe PostgreSQL database and the Tally connector PostgreSQL mirror should remain separate logical stores.

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
- Current stock by item and godown, through a proper Tally stock snapshot export
- Delivery challans required for reconciliation
- Sales invoices required for reconciliation
- Voucher lines required for matching against order lines

Keep all raw and verbose Tally data in PostgreSQL. Frappe should store cleaned, indexed, app-ready records.

Frappe imports/syncs required PostgreSQL mirror data into DocTypes. The mobile app and portal business rules read from Frappe, not directly from raw PostgreSQL tables.

## Visibility Filter Decision

Use inclusive filters.

The rule is:

```text
No filter configured = all visible
Filter configured = only configured values are visible
```

This applies to both customers and sales employees.

Inclusive filters are preferred because they are safer and easier to explain. If a new Product Group is added from Tally, it will not accidentally become visible to a restricted user unless explicitly included.

## Filter Dimensions

Initial filters apply on:

- Product Group, backed by root Tally Stock Group
- Customer assignment, for sales employees

Stock category, specific item, and godown/branch filters are out of current scope unless added later.

For sales employee orders, effective Product Group access is:

```text
sales employee Product Group access
AND customer Product Group access
```

Blank Product Group access means unrestricted/all Product Groups for that side of the intersection.

## Brand / Group / Category Decision

The mobile flow needs one first-level selector. The options are:

- Brand
- Stock group
- Stock category

Tally does not appear to have a reliable native brand table. Because of this, the first-level selector should initially be mapped to Tally stock group or stock category.

Decision after inspecting demo Tally data:

- Use root Tally Stock Group as the first-level selector.
- In the UI, label this as "Product Group".
- Immediate stock group is too granular for the first selector.
- Stock category is not suitable as the primary selector because many items do not have a category.
- If later the business wants a cleaner commercial brand layer, create a portal-side Brand Mapping DocType that maps one brand to many root groups/groups/categories/items.

A root stock group is a stock group row whose parent is blank. The item stores its immediate stock group, and the application derives the root group by walking up the stock group parent hierarchy.

## Order Placement Principle

Orders placed in the app are requests, not stock reservations.

Placing an order should not reduce stock in Frappe or Tally. Actual stock movement happens only when the branch creates a DC or Sales Invoice in Tally.

The app should show the latest synced stock. Real-time stock calls to Tally are not required for the initial implementation.

For godown-wise stock, the system should not rely on reconstructing stock from voucher transactions because Delivery Challan and Sales voucher rows can duplicate the same physical movement. The preferred approach is to enhance `tally-database-loader` to export a Tally-computed stock snapshot by item and godown.

Pricing, rates, discounts, tax, and order value are out of scope for Frappe and the mobile app in v1. Orders are quantity-only requests.

## Order Status Principle

Frappe order status is updated through reconciliation with Tally.

The expected statuses are:

- Placed
- Processing
- Partially Processed
- Completed
- Partially Closed
- Cancelled
- Manual Review, when automatic matching fails

Automatic status updates should happen only when the Tally voucher can be matched confidently to the portal order reference and item lines. If the match is unclear, the order should go to manual review instead of making a risky update.

Confirmed orders are locked for mobile users. Customers and sales employees cannot edit or cancel after confirmation. Owner/admin users can cancel or partially close an order when operationally required.

## WhatsApp Decision

Use the Frappe WhatsApp integration path where possible, especially since Frappe CRM has built-in WhatsApp capabilities.

WhatsApp will be used for:

- OTP verification
- Order confirmation
- Thank-you message
- PDF order summary attachment

WhatsApp status updates are out of scope for v1. Order Placed is the only order lifecycle event sent over WhatsApp.

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
- Godown-wise stock may be wrong if derived naively from voucher transactions because Sales and Delivery Challan rows can duplicate the same movement.
- Branch users may create Tally vouchers without the correct portal reference number.
- Tally voucher lines may not match portal order lines cleanly.
- WhatsApp template approval and document message behavior may affect OTP/order confirmation design.
- Frappe role permissions may need custom logic for branch-level order visibility.

## Open Decisions

The following must still be finalized or validated:

- Whether a portal-side Brand Mapping table is needed later.
- Exact branch-to-godown mapping.
- Whether Seetarambagh is a missing godown, a branch, a voucher naming convention, or mapped to another godown.
- Exact debtor/customer ledger filter for importing Tally customer aliases from `mst_ledger`.
- Proof test that Tally Reference Number syncs into `trn_voucher.reference_number`.
- Exact stock-by-godown export implementation in `tally-database-loader`.
- Connector performance with 5-minute incremental master, stock, and voucher sync.
