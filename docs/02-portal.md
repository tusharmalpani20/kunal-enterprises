# Portal Requirements

## Purpose

The portal is the internal operating system for the order workflow. It is built on Frappe and owns users, permissions, approvals, filters, order requests, status, PDF generation, WhatsApp communication logs, and Tally reconciliation state.

The portal should not be a thin viewer over raw Tally tables. It should maintain its own application-level DocTypes and sync only the required Tally-derived data.

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
- Mark operational state as processing if allowed
- Coordinate fulfillment
- View branch-related reconciliation state
- Possibly see order PDFs

Branch Manager should not manage global filters, global users, integration settings, or unrelated branch orders.

### Branch Employee

Branch Employee can see only orders:

- Associated with their branch/godown
- Currently in processing

The branch employee role is intentionally narrower than branch manager.

Branch Employee can:

- View relevant processing orders
- Use the portal reference number while creating DC/Sales Invoice in Tally
- Possibly mark internal handling fields if required

Branch Employee should not see all placed orders by default unless they are moved to processing.

## Branch And Godown Mapping

Branch access is based on godowns.

The system needs a mapping between:

- Portal branch
- Tally godown
- Branch manager users
- Branch employee users

One branch may map to one or more Tally godowns if the business requires it.

## Customer Management

Customers can sign up from the mobile app, but they do not automatically get full portal access.

Portal admins can:

- View customer signup requests
- Approve or reject access
- Activate/deactivate a customer
- Map the mobile customer to a Tally customer/ledger
- Configure visibility filters
- View order history

Customer approval states may include:

- Pending Verification
- OTP Verified
- Pending Admin Approval
- Approved
- Rejected
- Disabled

OTP verification proves phone ownership. Admin approval controls business access.

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

## Access Filters

Use inclusive filters across customers and sales employees.

Rule:

```text
No filter configured = all visible
Filter configured = only configured values are visible
```

Possible filter dimensions:

- Stock Group
- Stock Category
- Item
- Godown/Branch
- Customer, for sales employees

The filter system should support combining filters.

Example:

```text
Allowed Groups: Group A, Group B
Allowed Categories: none
Allowed Items: none

Result: user sees items in Group A or Group B.
```

If both group and item filters are configured, the exact combination rule must be finalized. Recommended default:

```text
Visible item = item matches all configured filter dimensions.
```

This means if group and category filters are both set, the item must belong to an allowed group and an allowed category.

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
- Last synced timestamp
- Is active
- Raw source reference, if needed for debugging

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
- Notes, if needed
- PDF attachment
- Tally reconciliation status

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

This structure is important because branch visibility depends on godown/branch.

## Order Statuses

Recommended status model:

- Placed
- Processing
- Partially Processed
- Completed
- Cancelled
- Manual Review

Draft can exist internally if the mobile app needs cart persistence, but a confirmed order should start at Placed.

### Placed

Order has been confirmed by customer or sales employee.

### Processing

Internal users have started operational processing.

The requirement says there is no need to track the exact start time. However, the system may still store the current status for visibility and permissions.

### Partially Processed

Some order quantities have been found in matching Tally DC/Sales Invoice records, but not all requested quantities are fulfilled.

### Completed

All requested quantities have been matched against Tally DC/Sales Invoice records.

### Manual Review

Automatic reconciliation failed or found ambiguous data.

Examples:

- Reference number matches but item lines do not match.
- Voucher contains extra items.
- Quantities exceed requested quantity.
- Same reference number is used in multiple unexpected vouchers.
- Tally item name changed and no stable item key is available.

## Tally Reference Number

Every portal order must generate a unique reference number.

Branch users must enter this reference number into Tally when creating:

- Delivery Challan
- Sales Invoice

The reconciliation process depends on this value.

Reference number requirements:

- Unique
- Human-readable
- Short enough for Tally entry
- Contains enough structure for support/debugging
- Never reused

Example format:

```text
KE-ORD-2026-000001
```

The final format can be decided later.

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

## WhatsApp Integration

The portal should use Frappe WhatsApp integration capabilities where possible.

Use cases:

- OTP verification
- Order confirmation message
- Thank-you message
- PDF order summary attachment
- Optional status update notifications

The portal should store WhatsApp logs:

- Recipient phone number
- Template/message type
- Related document
- Provider message ID
- Status
- Error response
- Sent timestamp
- Delivered/read timestamp, if available

## PDF Order Summary

After order confirmation, generate a basic PDF summary.

The PDF should include:

- Portal reference number
- Customer name
- Sales employee name, if applicable
- Order date
- Item list
- Godown allocations
- Requested quantities
- Unit
- Notes, if any

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
- Should there be price visibility or only stock/order quantity?
