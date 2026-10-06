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

Standalone allocators can read Placed orders, orders awaiting godowns, and the godown master,
but cannot use generic Order writes or privileged status actions. Branch users
with the allocator role can also read Placed and pending orders across branches; their
ordinary assigned-order access remains branch-scoped.

## Assignment API

The Order form provides **Assign Godowns** for Owner, Admin, and Godown Allocator
users while godowns are missing, and **Edit Godown Assignments** after they are
saved while the order remains Placed. For Placed orders, the modal groups all
allocations by item and pre-fills the saved quantities; for historical orders,
it lists only missing allocations. It
shows fixed item names/quantities, and groups **Available** and **Allocate**
under each active godown. Allocators can split a row across godowns; its allocated
quantities must exactly total Order Qty and use at most nine decimal places
(the database quantity precision). Missing snapshots display —; stock
remains informational, consistent with the existing soft stock checks.
After saving a Placed order, the form reloads so assignments can be edited again.
Allocators completing missing assignments on other statuses return to the list. Clicking outside,
pressing Escape, or closing the modal with unsaved quantities offers **Discard
Changes** or **Continue Editing**. Continue preserves entered quantities; discard
closes without saving. Closing is blocked while a save is in progress.

The modal uses this backend action:

```http
POST /api/method/kunal_enterprises.api.godown_assignment.assign_godowns
```

This uses a Frappe Desk session with Owner, Admin, or Godown Allocator permission,
not a mobile token.

```json
{
  "order": "KE-SO-00001-26-27",
  "assignments": [
    {"allocation": "ORDER-ALLOCATION-ROW-NAME", "splits": [
      {"godown": "GODOWN-A", "quantity": 2},
      {"godown": "GODOWN-B", "quantity": 3}
    ]}
  ]
}
```

The fill-only API below uses allocation names from the Order child rows. The action locks the order,
validates all assignments, assigns or splits only unassigned allocations, and records actor and changes
in Order Status Log. Requested items/quantities and existing selections remain
immutable. The older `{allocation, godown}` full-row payload remains supported.
Invalid batches roll back completely. Rows with dispatched quantities cannot be
split across godowns; their dispatch history is preserved by single-godown assignment. Assignments may be partial;
Processing stays blocked until all quantities are assigned. Assignment does not
move the order to Processing automatically. Portal Processing actions also recheck
that selected godowns are still active. Order creation and Processing transitions
roll back if their confirmation or audit writes fail.

The modal loads its data through
`GET /api/method/kunal_enterprises.api.godown_assignment.assignment_options`
with the same role guard. This returns only the selected order’s unassigned
allocations, active godowns, and latest synced stock for those items, filtered by
the configured source company when present.

To edit the distribution while Placed, load `assignment_options` with `edit=1`.
The response has `editing=true` and item-grouped rows with `current_allocations`.
Save every requested item through:

```http
POST /api/method/kunal_enterprises.api.godown_assignment.replace_assignments
```

```json
{
  "order": "KE-SO-00011-26-27",
  "assignments": [{"item": "ITEM-RECORD", "splits": [
    {"godown": "GODOWN-A", "quantity": 2},
    {"godown": "GODOWN-B", "quantity": 3}
  ]}]
}
```

This replaces the godown distribution, preserving each item's original total and
order status. It requires Placed status with no fulfillment history, and records
before/after distributions in the audit log. Editing is blocked once Processing
begins. The fill-only endpoint retains its historical missing-godown behavior.

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

The assignment table shows live allocated and remaining quantities beside each item.
A complete distribution turns green; excess quantities or invalid entries turn red.
Item names and order quantities remain fixed during horizontal scrolling.
