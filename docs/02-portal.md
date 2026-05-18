# Portal Requirements

## Purpose

The portal is the internal operating system for the order workflow. It is built as a custom Frappe app and owns users, permissions, approvals, filters, order requests, status, PDF generation, WhatsApp communication logs, and Tally reconciliation state.

The portal should not be a thin viewer over raw Tally tables. It should maintain its own application-level DocTypes and sync only the required Tally-derived data.

ERPNext is not part of the current architecture. All required business entities should be custom Frappe DocTypes.

## Portal User Roles

The internal portal has these user groups:

- Owner
- Admin
- Branch Manager
- Branch Employee

## Role Permissions

### Owner

Owner can see and manage everything:

- All customers
- All sales employees
- All orders
- All branches/godowns
- All filters
- All synced Tally masters
- All reconciliation logs
- WhatsApp logs
- System configuration

### Admin

Admin can also see and manage everything for the initial implementation.

If needed later, owner-only actions can be separated, such as system settings, integration credentials, and destructive admin actions.

### Branch Manager

Branch Manager can see an order if at least one order line is associated with their branch/godown.

Important rule:

If even one item in the order belongs to the manager's branch/godown, the Branch Manager can see the complete order, not just that line.

Branch Manager can:

- View relevant orders
- View branch-visible order history across statuses
- Mark operational state as processing if allowed
- Coordinate fulfillment
- View branch-related reconciliation state
- Possibly see order PDFs

Branch Manager should not manage global filters, global users, integration settings, or unrelated branch orders.

### Branch Employee

Branch Employee can see only orders:

- Associated with their branch/godown
- Currently Placed, Processing, or Manual Review

The branch employee role is intentionally narrower than branch manager.

When a Branch Employee can see an order, they see the complete order, not only their branch lines.

Branch Employee can:

- View relevant Placed and Processing orders
- Move relevant Placed orders to Processing
- Use the portal reference number while creating DC/Sales Invoice in Tally
- Possibly mark internal handling fields if required

Branch Employee should not see completed, cancelled, or partially closed orders unless read-only history is explicitly added later.

For Manual Review, Branch Manager and Branch Employee can view the order and reason if the order is visible to their branch, but cannot resolve or modify it. Only Owner and Admin can resolve Manual Review.

## Branch And Godown Mapping

Branch access is based on godowns.

The system needs a mapping between:

- Portal branch
- Tally godown
- Branch manager users
- Branch employee users

One branch may map to one or more Tally godowns if the business requires it.

Demo data has voucher types for `Sales Seetarambagh` and `Delivery Challan Seetarambagh`, but `mst_godown` does not currently contain a Seetarambagh godown. This must be clarified with the client before final branch mapping.

## Customer Management

Customers can sign up from the mobile app, but they do not automatically get full portal access.

Portal admins can:

- View customer signup requests
- Approve or reject access
- Activate/deactivate a customer
- Map the mobile customer to a Tally customer/ledger
- Enter or maintain the customer client code used for Tally mapping
- Configure visibility filters
- View order history

Customer statuses:

- Pending OTP
- Pending Admin Review
- Active
- Rejected
- Disabled

OTP verification proves phone ownership. Admin approval records the business decision. Customer app access is granted only when the customer also has a client code.

Admin approval and client code validation are separate requirements:

```text
Customer can become Active only when:
mobile_verified = true
admin_approved = true
client_code is present, unique, and exists in imported Tally customer ledgers
```

Admins may approve the business access decision before `client_code` is entered, but effective customer app access remains false until all requirements are satisfied.

Customer detail should show an access checklist/effective access panel:

- Mobile verified
- Admin approved
- Client code present
- Client code unique
- Client code found in imported Tally customer ledgers
- Account not disabled/rejected
- Effective Customer App Access: yes/no
- Missing requirements, if any
- Product Group access summary:
  - No filters configured = All Product Groups
  - Filters configured = selected Product Groups

Sales employee detail should also show an effective access panel:

- Status: Active/Disabled
- Mobile verified
- Customer assignment summary:
  - No assignments = All active customers
  - Assignments configured = selected customers
- Product Group access summary:
  - No filters configured = All Product Groups
  - Filters configured = selected Product Groups

OTP verification should be stored as fields, not as a long-lived business status:

- `mobile_verified`
- `mobile_verified_at`

Lifecycle rules:

```text
Pending OTP -> Pending Admin Review after successful OTP verification
Pending Admin Review -> Active only if client_code exists and admin approves
Pending Admin Review -> Rejected if admin rejects
Active -> Disabled if access is revoked or client_code is removed
Disabled -> Active only if client_code exists and admin re-enables
```

Customer signup captures:

- Name
- Business name / legal name
- GSTIN number
- Mobile number
- Email ID
- Date of birth
- Date of anniversary

Customers can later edit only email ID, date of birth, and date of anniversary from the mobile app. Name, business/legal name, GSTIN, mobile number, and client code are admin-controlled.

The portal additionally maintains `client_code`. This is entered by internal users and represents the alias/code used to map the app customer to the corresponding Tally customer identity for order completion/reconciliation.

In the connector database, this should map to `mst_ledger.alias` for the relevant Tally customer/debtor ledger.

Customer rules:

- Mobile number must be unique across customers.
- Rejected customers cannot sign up again with the same mobile number; admins must reopen or update the existing record.
- `client_code` can initially be blank.
- Once entered, `client_code` must be unique across customers.
- Once entered, `client_code` must exist in imported Tally customer ledgers, mapped through `mst_ledger.alias`.
- Customer app access cannot be granted unless `client_code` is present.
- If `client_code` is removed, customer app access must be removed automatically.
- Mobile number must also be globally unique across customers and sales employees.

Admins can still see and edit customer signup records in the internal portal even when `client_code` is missing. The block applies to customer-facing app access, not internal admin visibility.

Validation:

```text
client_code blank = allowed, but no Customer App Access
client_code entered but not found in Tally customer ledgers = validation error
client_code entered, unique, and found in Tally = customer can become Active
```

Implementation note:

Prefer enforcing these rules in the custom Frappe DocType controller because this is a custom app. Frappe Server Scripts can also run on document events such as Before Save and support custom validation, but in Frappe v15 they are disabled by default and must be enabled explicitly. Reference: https://docs.frappe.io/framework/user/en/desk/scripting/server-script

## Sales Employee Management

Sales employees do not self-signup.

Portal admins create sales employee accounts directly.

Admins can:

- Create sales employee
- Assign mobile number
- Enable WhatsApp OTP login
- Activate/deactivate account
- Configure item visibility filters
- Configure customer access filters
- View employee order history

Sales employees can place orders for allowed customers only.

Sales employee mobile number must be unique across all mobile login identities, including customers. The same phone number cannot be used for both a customer and a sales employee account.

Sales employee statuses:

- Active
- Disabled

Sales employee fields:

- Name
- Mobile number
- Email ID, optional
- Employee code, optional
- Assigned customers, optional
- Allowed Product Groups, optional
- Mobile verified
- Mobile verified at

Rules:

- Admin creates sales employee accounts.
- Sales employees log in with WhatsApp OTP.
- Disabled sales employees cannot log in.
- Sales employees do not have rejection or client-code lifecycle.
- Sales employees exist only in Frappe and are not mapped to Tally ledgers.
- Sales employee profile/details are admin-managed only. Sales employees cannot edit their own profile fields in the mobile app.

Customer assignment rule:

```text
No customer assignments = sales employee can place orders for all active customers
Customer assignments present = sales employee can place orders only for assigned active customers
```

When a sales employee places an order for a customer, effective item visibility is:

```text
sales employee item access
AND customer item access
```

This prevents sales employees from bypassing customer-specific restrictions.

Sales employee customer assignments are direct child-table rows. There are no sales teams, territories, routes, or reusable assignment groups in v1.

Recommended `Sales Employee Assigned Customer` child table fields:

- Customer link
- Customer name
- Business/legal name
- Client code
- Customer status

The link is the canonical relationship. Name/business/client-code/status fields are stored or fetched for admin readability.

## Access Filters

Use inclusive filters across customers and sales employees.

Rule:

```text
No filter configured = all visible
Filter configured = only configured values are visible
```

Initial filter dimensions:

- Product Group, backed by root Tally Stock Group
- Customer assignment, for sales employees

Stock Category, specific Item, and Godown/Branch filters are not part of the current scope.

Product Group permissions are assigned directly on each customer and each sales employee. There are no reusable permission profiles/groups in v1.

Use child tables for Product Group permission assignment rather than MultiSelect fields.

Recommended Product Group permission child table fields:

- Product Group link
- Product Group name

No item count or additional summary fields are needed in v1.

If a selected Product Group becomes inactive because it was removed from Tally sync, keep the permission row but show an inactive warning to admins.

Example:

```text
Allowed Product Groups: Group A, Group B

Result: user sees items under Product Group A or Product Group B.
```

For Product Group filters:

```text
No Product Group filter = all Product Groups visible
Product Group filter present = only selected Product Groups visible
```

For sales employee orders, filters are evaluated in the selected customer context. The final allowed item list is the intersection of sales employee filters and customer filters.

Blank filters are treated as unrestricted:

```text
employee blank + customer restricted = customer restricted
employee restricted + customer blank = employee restricted
employee blank + customer blank = all Product Groups
employee restricted + customer restricted = intersection
```

## Tally-Derived Master Data In Frappe

Frappe should store app-ready copies of required Tally data:

- Tally Item
- Tally Stock Group
- Tally Stock Category
- Tally Godown
- Tally Unit
- Tally Customer/Ledger
- Tally Stock Snapshot
- Tally Voucher Header, only for relevant DC/Sales Invoice records
- Tally Voucher Line, only for relevant reconciliation records

These DocTypes should include the Tally identifiers needed to re-sync without duplicates.

Recommended fields:

- Tally GUID or stable key, if available
- Tally master name
- Parent group/category, if applicable
- Root stock group, for item filtering
- Hierarchy depth, for stock groups
- Full path, for stock groups
- Last synced timestamp
- Is active
- Raw source reference, if needed for debugging

### Tally Stock Group

`Tally Stock Group` should preserve the hierarchy from Tally.

Fields:

- Tally GUID
- Group name
- Parent stock group
- Root stock group
- Is root
- Depth
- Full path
- Last synced timestamp
- Is active

A group with no parent is a root group. Root stock group is the first-level selector used by the mobile app.

### Tally Item

`Tally Item` should keep both immediate and root group references.

Fields:

- Tally GUID
- Item name
- Immediate stock group
- Root stock group
- Stock category
- UOM
- Total closing balance from Tally
- Last synced timestamp
- Is active

The mobile app should filter by `root_stock_group`, not by raw immediate group.

Total closing balance is stored for search/list summaries and diagnostics. Order placement should use godown-wise `Tally Stock Snapshot`.

### Tally Stock Snapshot

`Tally Stock Snapshot` should store the latest Tally-computed stock by item and godown.

Fields:

- Item
- Godown
- Quantity
- UOM
- As on date
- Source company
- Synced at
- Source sync run

This should come from a proper stock-by-godown export from Tally, not from naive voucher summation.

Godown-wise stock snapshot is the source used by order placement.

## Order DocTypes

Recommended DocTypes:

- Order
- Order Item
- Order Godown Allocation
- Order Status Log
- Order PDF
- Order WhatsApp Notification
- Order Reconciliation Log

### Order

The Order document should include:

- Portal reference number
- Order source: Customer or Sales Employee
- Customer
- Sales employee, if applicable
- Current status
- Order date/time
- Confirmation date/time
- Total item count
- Total quantity
- Sales employee note, if order was placed by a sales employee
- PDF attachment
- Tally reconciliation status

The Order should not store prices, rates, discounts, tax, or monetary value.

### Order Item

Each Order Item should include:

- Parent order
- Item
- Item name at time of ordering
- Stock group/category snapshot
- Unit
- Requested quantity
- Fulfilled quantity
- Pending quantity
- Status

### Order Godown Allocation

Each item may be ordered from one or more godowns.

The allocation should include:

- Parent order
- Parent order item
- Godown
- Branch
- Stock shown at order time
- Requested quantity
- Fulfilled quantity
- Pending quantity

Duplicate item+godown allocations should be merged by summing quantity. The same item may have multiple allocations only when the godown differs.

`Stock shown at order time` records the latest synced stock visible when the order was placed. It is for internal audit/diagnostics and should not be printed on the customer PDF.

Also store the stock snapshot sync timestamp used at order time.

This structure is important because branch visibility depends on godown/branch.

Godown allocation is used for order intent and branch visibility. Fulfillment completion is reconciled item-wise, because operations may fulfill from a different godown than the customer originally selected.

Requested quantity can exceed latest synced stock, including for godowns whose latest synced stock is zero. This should be stored as submitted; the mobile app highlights the row at confirmation, but the backend does not reject it solely for exceeding synced stock.

## Order Statuses

Recommended status model:

- Placed
- Processing
- Partially Processed
- Completed
- Partially Closed
- Cancelled
- Manual Review

Draft can exist internally if the mobile app needs cart persistence, but a confirmed order should start at Placed.

These are the v1 order statuses.

For v1, drafts/carts are not stored in Frappe. Frappe creates an Order only at final mobile confirmation.

### Placed

Order has been confirmed by customer or sales employee.

### Processing

Internal users have started operational processing.

The requirement says there is no need to track the exact start time. However, the system may still store the current status for visibility and permissions.

Allowed roles can move an order from Placed to Processing:

- Owner
- Admin
- Branch Manager
- Branch Employee

Branch Manager and Branch Employee can do this only when the order has at least one godown allocation linked to their branch.

### Partially Processed

Some order quantities have been found in matching Tally DC/Sales Invoice records, but not all requested quantities are fulfilled.

### Completed

All requested quantities have been matched against Tally DC/Sales Invoice records.

### Partially Closed

Some requested quantity was fulfilled, but the remaining quantity will not be supplied.

Example:

```text
Requested: 100
Fulfilled: 80
Remaining: 20
Customer bought remaining quantity elsewhere
Admin closes order as Partially Closed
```

This is an admin action, not an automatic reconciliation status.

### Manual Review

Automatic reconciliation failed or found ambiguous data.

Every Manual Review status must include a visible reason for internal users.

Examples:

- Reference number matches but item lines do not match.
- Voucher contains extra items.
- Quantities exceed requested quantity.
- Same reference number is used in multiple unexpected vouchers.
- Tally item name changed and no stable item key is available.

Recommended Manual Review fields:

- Reason code
- Reason message
- Related Tally voucher
- Related Tally voucher line, if applicable
- Detected at
- Resolved by
- Resolved at
- Resolution note

Only Owner and Admin can resolve Manual Review.

Resolution options:

- Accept as Completed
- Accept as Partially Processed
- Mark Partially Closed
- Cancel Order
- Return to Processing

Resolution requires a note.

Branch Manager and Branch Employee may view the Manual Review reason when the order is visible to their branch, but they cannot resolve Manual Review.

Mobile users do not see Manual Review reasons. They see only the customer-facing status label `Under Review`.

## Tally Reference Number

Every portal order must generate a unique reference number.

Branch users must enter this reference number into Tally when creating:

- Delivery Challan
- Sales Invoice

The reconciliation process depends on this value.

The portal order reference should be entered into Tally's Reference Number field. The connector reads this as `trn_voucher.reference_number`.

The same portal order reference must be entered on every related Delivery Challan and Sales Invoice.

Reference number requirements:

- Unique
- Human-readable
- Short enough for Tally entry
- Contains enough structure for support/debugging
- Never reused

Chosen format:

```text
KE-YY-MM-####
```

Example:

```text
KE-26-05-0001
```

Meaning:

- `KE` = Kunal Enterprise
- `YY` = year code
- `MM` = month
- `####` = monthly sequence

The sequence resets every month.

The reference is assigned only when the Order is confirmed. `YY-MM` comes from the server-side confirmation timestamp, not from draft creation time.

## Reconciliation Behavior

The portal should automatically update order status only when matching is confident.

Matching inputs:

- Portal reference number
- Tally voucher type
- Tally voucher date
- Tally customer/ledger
- Tally item
- Tally godown
- Quantity

If all required data matches, update fulfilled quantities and status.

If matching fails, do not guess. Put the order into Manual Review or create a reconciliation exception for admin handling.

Mobile users cannot edit or cancel an order after confirmation. Owner/admin users can cancel an order or mark it Partially Closed if the remaining quantity will not be supplied.

Branch Manager and Branch Employee cannot cancel or partially close orders.

Order line items cannot be edited after placement, even by Owner/Admin. If the order is wrong, cancel it and create a new order, or use partial closure after fulfillment where appropriate.

Customers do not submit order notes. Sales employees may add a note while placing an order for a customer.

Sales employee note is internal only. It should not be visible to the customer in the mobile app or PDF.

## WhatsApp Integration

The portal should use Frappe WhatsApp integration capabilities where possible.

Use cases:

- OTP verification
- Order confirmation message
- Thank-you message
- PDF order summary attachment

Do not send WhatsApp status update notifications in v1.

Order confirmation WhatsApp rule:

- For customer-placed orders, send the thank-you/order summary PDF to the customer.
- For sales-employee-placed orders, send the thank-you/order summary PDF to the customer for whom the order was placed.
- Do not send a separate WhatsApp order confirmation to the sales employee; the sales employee gets confirmation inside the app.
- WhatsApp order notification is sent only when the Order is placed.

The portal should store WhatsApp logs:

- Recipient phone number
- Template/message type
- Related document
- Provider message ID
- Status
- Error response
- Sent timestamp
- Delivered/read timestamp, if available

Mobile authentication is separate from Frappe Desk login. Customers and sales employees use WhatsApp OTP and custom JWT/session tokens. Internal portal users use normal Frappe authentication.

Mobile sessions remain valid until logout, account disablement, or access removal. Backend APIs must enforce current account/access state on every request.

## PDF Order Summary

After order confirmation, generate a basic PDF summary.

The PDF should include:

- Portal reference number
- Customer name
- Sales employee name, if applicable
- Placed by value: Customer or Sales Employee Name
- Order date
- Item list
- Godown allocations
- Requested quantities
- Unit

The PDF should not include price/rate/value in v1.

The PDF should not include stock availability or stock shown at order time. Stock is shown in the app during ordering and stored internally on the order allocation.

The PDF should not include internal client code.

The PDF should not include sales employee note.

Sales employees may search customers by client code in the mobile customer selector, but client code should not be displayed as a visible field in the sales employee mobile app.

The PDF is attached to the order and sent over WhatsApp.

## Admin Screens

Initial portal screens:

- Dashboard
- Customer approvals
- Customer list
- Sales employee list
- Orders list
- Order detail
- Branch/godown mapping
- Visibility filters
- Tally sync status
- Reconciliation exceptions
- WhatsApp logs

Owner/Admin Tally sync controls:

- Sync Masters Now
- Sync Stock Now
- Run Reconciliation Now

## Reports

Useful reports:

- Orders by status
- Orders by customer
- Orders by sales employee
- Orders by branch/godown
- Pending fulfillment
- Partially processed orders
- Manual review queue
- WhatsApp failures
- Sync failures

## Open Portal Questions

- Should branch managers be allowed to manually move orders to Processing?
- Should branch employees be allowed to update any portal field, or only view details?
- Should owners/admins be able to override reconciliation results?
- Should customer rejection require a reason?
- Should users be notified when access is approved/rejected?
- Should order cancellation be supported before processing?
- Price visibility is out of scope for v1; only stock/order quantity is shown.
