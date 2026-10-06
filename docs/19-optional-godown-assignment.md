# Optional godowns and later assignment

Customers and Sales Employees can place orders with an item and a positive
quantity without selecting a godown. The existing mobile submission endpoint is
unchanged. Mixed assigned/unassigned allocations are supported.

```json
{
  "customer": "CUSTOMER-RECORD",
  "allocations": [{"item": "ITEM-RECORD", "quantity": 5}]
}
```

The Order remains Placed. `godown_assignment_pending` is derived from its
requested quantities and allocations. Every quantity must have a godown before
Processing, including API and direct document saves. Actual Tally fulfillment
remains item-wise; a genuine dispatch can still establish partial/completed
fulfillment. Missing godowns can be filled afterward without changing that
status. Explicitly Cancelled/Partially Closed orders cannot be assigned.

## Role and workspace

The app fixtures publish the Godown Allocator role and Role Profile, add that
role to Owner/Admin profiles, and add Pending Godown Assignment to the Operation
workspace. The assignment queue excludes Cancelled and Partially Closed orders.
Individual user assignments remain site-specific.

Standalone allocators can read orders awaiting godowns and the godown master,
but cannot use generic Order writes or privileged status actions. Branch users
with the allocator role can also read pending orders across branches; their
ordinary assigned-order access remains branch-scoped.

## Assignment API

The portal assignment interface is deferred. Its backend action is ready:

```http
POST /api/method/kunal_enterprises.api.godown_assignment.assign_godowns
```

This uses a Frappe Desk session with Owner, Admin, or Godown Allocator permission,
not a mobile token.

```json
{
  "order": "KE-SO-00001-26-27",
  "assignments": [
    {"allocation": "ORDER-ALLOCATION-ROW-NAME", "godown": "GODOWN-RECORD"}
  ]
}
```

Allocation names come from the Order child rows. The action locks the order,
validates all assignments, fills only blank godowns, and records actor and changes
in Order Status Log. Requested items/quantities and existing selections remain
immutable. Invalid batches roll back completely. Assignments may be partial;
Processing stays blocked until all quantities are assigned. Assignment does not
move the order to Processing automatically. Portal Processing actions also recheck
that selected godowns are still active. Order creation and Processing transitions
roll back if their confirmation or audit writes fail.

## Deployment and mobile verification

Deploy the updated custom app and run `bench --site <site> migrate`, then restart
the backend processes using the site's deployment procedure. Migration applies
the schema/fixtures and backfills existing assignment flags without rewriting
requested quantities or status history. The local `kunal_frappe` migration was
applied during implementation and repeated after the fixture recheck. Legacy
orders with missing or inconsistent allocation rows are flagged as pending; they
require an Owner/Admin repair because this API only fills existing rows.

Mobile now offers Add without godown and displays Godown not assigned in its
summary. Unassigned rows have no fabricated stock evidence and skip godown stock
refresh/warnings. Stock loading or an ordinary stock-service error does not block
adding without a godown. No mobile runtime was started; phone testing remains manual.

Manual checks should cover Customer and Sales Employee orders, mixed selections,
saved draft restoration, and removal of an unassigned row while retaining a
selected-godown row for the same item.
