# /goal Prompt: Build Frappe Portal And Backend API

Use this as the second independent `/goal` prompt after Goal 1 is complete.

## Prompt

You are working in `/Users/amol909/development/kunal-enterprise/kunal-enterprises`.

Goal: build the complete custom Frappe portal app and backend API for the Kunal Enterprise Tally-connected order system. The portal owns customer approval, sales employee management, Product Group access, branch/godown visibility, order creation, status workflow, WhatsApp/PDF logs, Tally master sync into Frappe DocTypes, and fulfillment reconciliation state. The mobile app must consume Frappe APIs only; it must never read the raw Tally PostgreSQL mirror.

This goal assumes Goal 1 already created and ran the Frappe bench, PostgreSQL site, custom app, and `frappe_whatsapp` install.

## Source Context To Read First

- `CONTEXT.md`
- `docs/01-overall-problem-statement.md`
- `docs/02-portal.md`
- `docs/04-tally-connector.md`
- `docs/05-tally-db-discovery.md`
- `docs/06-grill-session-log.md`
- `docs/07-frappe-app-patterns-from-sf-dpms.md`
- all files in `docs/adr/`
- `/Users/amol909/.agents/skills/tdd/SKILL.md`

Treat the ADRs as binding unless implementation proves an ADR cannot be satisfied. If that happens, stop and document the conflict before changing direction.

## Non-Negotiable Domain Decisions

- Use a custom Frappe app, not ERPNext.
- Tally is the source of truth for inventory masters, stock, godowns, ledgers, delivery challans, sales invoices, and fulfillment records.
- Frappe is the source of truth for portal users, mobile access, Customer and Sales Employee records, Product Group permissions, Orders, reference numbers, status, WhatsApp logs, PDFs, and reconciliation logs.
- Raw Tally PostgreSQL data is an integration mirror only. Portal and mobile business logic read Frappe DocTypes and APIs.
- Product Group is the customer-facing first selector and is backed by root Tally Stock Group.
- Customer App Access requires mobile verification, admin approval, and a valid unique Client Code mapped to imported Tally customer ledger alias.
- Mobile auth is custom WhatsApp OTP plus JWT/session, independent of Frappe Desk auth.
- Orders are quantity-only requests. Do not store or show price, rate, discount, tax, or monetary value.
- Latest synced stock is advisory. Users can order more than latest synced stock and from zero-stock godowns.
- Frappe must store stock shown at order time and stock snapshot timestamp on order allocations.
- Customer-facing WhatsApp in v1 is only OTP and Order Placed confirmation/PDF.
- No mobile push notifications in v1.
- Confirmed orders are immutable for mobile users. Owner/Admin can cancel or partially close; branch roles cannot.
- Fulfillment reconciliation is item-wise, not godown-wise.
- Sales Invoice is the primary fulfillment signal when present. Delivery Challan is provisional when no Sales Invoice exists.
- Duplicated DC/Sales movement must not be counted twice.
- Manual Review always needs a reason code/message and is resolved only by Owner/Admin.

## TDD Rules For This Goal

Follow `/Users/amol909/.agents/skills/tdd/SKILL.md`.

- Use vertical tracer bullets: one failing behavior test, minimal implementation, passing test, then the next behavior.
- Tests must describe behavior through public interfaces: DocType saves, whitelisted APIs, permission-visible lists, scheduled job entrypoints, and reconciliation job results.
- Do not bulk-write all tests first.
- Do not test private helpers or implementation shape unless there is no public behavior surface.
- Mock only true external systems such as WhatsApp provider calls and raw Tally mirror access. Keep Frappe DocType and API behavior real in tests.
- After each green slice, refactor only while tests are passing.

## Expected Work

### 1. App Structure And Fixtures

Build app structure using the patterns in `docs/07-frappe-app-patterns-from-sf-dpms.md`:

- `hooks.py` as registry only.
- `api/` modules grouped by business feature.
- `api/utils.py` for response envelopes and request/header helpers.
- `api/otp.py` for OTP send/resend/verify.
- `api/token_verification.py` for mobile JWT/session verification, refresh, and revoke.
- `cron/` for sync and reconciliation jobs.
- `doc_events/` for lifecycle hooks when needed.
- `permission_query_conditions/` for row-level visibility.
- `fixtures/` for roles, permissions, workflows, workspaces, and seed setup.

Create role fixtures:

- Owner
- Admin
- Branch Manager
- Branch Employee

### 2. Core DocTypes

Create custom DocTypes required by the docs. Use exact project vocabulary.

Customer and access:

- Customer
- Customer Business, if separate from Customer fields
- Mobile Login Identity or equivalent identity model
- Mobile OTP
- Mobile Auth Token
- Sales Employee
- Sales Employee Assigned Customer child table
- Customer Product Group Access child table
- Sales Employee Product Group Access child table

Tally-derived masters:

- Tally Stock Group
- Tally Item
- Tally Stock Category
- Tally Godown
- Portal Branch
- Branch Godown Mapping
- Tally Unit
- Tally Customer Ledger
- Tally Stock Snapshot
- Tally Voucher
- Tally Voucher Line
- Tally Sync Run
- Tally Sync Error

Orders and workflow:

- Order
- Order Item
- Order Godown Allocation
- Order Status Log
- Order PDF
- Order WhatsApp Notification
- Order Reconciliation Log
- Manual Review reason/resolution fields, either on reconciliation log or a dedicated child table

### 3. Customer Lifecycle And Access

Implement:

- Customer statuses: Pending OTP, Pending Admin Review, Active, Rejected, Disabled.
- `mobile_verified` and `mobile_verified_at` as fields, not a long-lived business status replacement.
- Signup fields: name, business/legal name, GSTIN, mobile number, email ID, date of birth, date of anniversary.
- Admin-maintained `client_code`.
- Global mobile number uniqueness across Customers and Sales Employees.
- Rejected customers cannot sign up again with the same mobile number.
- `client_code` can be blank initially.
- Entered `client_code` must be unique among Customers and exist in imported Tally Customer Ledger alias.
- Customer App Access is true only when mobile verified, admin approved, valid Client Code exists, and account is not disabled/rejected.
- Removing `client_code` from an Active Customer disables access immediately.
- Access checklist fields/API for admin detail screen.

### 4. Sales Employee Lifecycle And Access

Implement:

- Sales Employee statuses: Active, Disabled.
- Admin-created only, no self-registration.
- Mobile number globally unique across Customers and Sales Employees.
- WhatsApp OTP login for active sales employees.
- Customer assignment child rows; blank means all active customers.
- Product Group access child rows; blank means all Product Groups.
- Sales employee order item visibility is the intersection of sales employee Product Group access and selected Customer Product Group access.
- Sales employees are Frappe-only and are not mapped to Tally ledgers.

### 5. Tally Master Sync Into Frappe

Implement import/sync services from the raw Tally mirror into Frappe DocTypes:

- Stock groups with hierarchy, root stock group, depth, full path, active flag.
- Items with immediate stock group, root stock group, stock category, UOM, total closing balance, active flag.
- Stock categories.
- Godowns.
- Units.
- Customer ledgers with alias used as Client Code.
- Stock snapshots by item and godown from the preferred Tally-computed stock snapshot table/export.
- Voucher headers and voucher lines needed for DC/Sales Invoice reconciliation.

Owner/Admin manual actions:

- Sync Masters Now
- Sync Stock Now
- Run Reconciliation Now

Scheduled target cadence:

- Masters every 5 minutes, assuming connector incremental sync is acceptable.
- Stock snapshot every 5 minutes.
- Voucher reconciliation every 5 minutes.

### 6. Portal Permissions

Implement row-level visibility:

- Owner/Admin see and manage everything.
- Branch Manager sees full orders across all statuses when at least one order allocation is linked to their branch/godown.
- Branch Employee sees full relevant orders only when status is Placed, Processing, or Manual Review.
- Branch Employee can move relevant Placed orders to Processing.
- Branch Manager and Branch Employee can view Manual Review reason for visible orders but cannot resolve it.
- Only Owner/Admin can cancel, partially close, or resolve Manual Review.

### 7. Mobile Backend APIs

Build whitelisted APIs with consistent response envelopes and HTTP status codes:

- Start customer signup
- Send OTP
- Resend OTP
- Verify OTP
- Current session/user
- Approval/access status
- Sales employee allowed customer list/search
- Allowed Product Groups
- Allowed items by Product Group
- Item stock by godown
- Submit order
- Order history
- Order detail
- Profile get/update where allowed
- Logout/revoke token

API rules:

- Protected APIs verify custom JWT and current access state on every request.
- Customer APIs reject stale tokens immediately when account is disabled or Client Code access is removed.
- Sales employee APIs reject stale tokens immediately when employee is disabled.
- Backend returns only allowed Product Groups/items/customers. Do not return all and rely on mobile filtering.
- Sales employee customer search can match Client Code, customer name, and business/legal name, but Client Code must not be displayed in mobile API result fields.
- Customer profile update allows only email ID, date of birth, and date of anniversary.
- Sales employee profile is read-only.

### 8. Order Creation

Implement final order submission only; no backend cart/draft in v1.

Rules:

- Generate reference number on confirmed submission using `KE-YY-MM-####`, based on server-side confirmation timestamp.
- Sequence resets monthly and must be atomic.
- Customer order flow has no note.
- Sales employee order flow may include an internal sales employee note.
- Sales employee note is not visible to customer APIs or PDFs.
- Duplicate item+godown rows are merged by summing quantity.
- Positive quantity is required.
- Quantity can exceed latest synced stock.
- Zero-stock godown quantities are allowed.
- Backend revalidates item, godown, Product Group access, selected customer access, and account state.
- Store stock shown at order time and stock snapshot timestamp on allocation.
- Confirmed order starts as Placed.
- Order lines are immutable after placement.
- Order does not reserve or reduce stock.

### 9. PDF And WhatsApp Logs

Implement:

- Order Placed confirmation PDF.
- PDF includes requested item/godown/quantity and placed-by value.
- PDF excludes price, rate, tax, value, stock availability, sales employee note, and Client Code.
- WhatsApp confirmation/PDF is sent only to the Customer, including sales employee placed orders.
- Sales employee gets in-app success only.
- WhatsApp notification logs capture request, provider response, retry/failure status, and attachment reference.

### 10. Reconciliation

Implement reconciliation from synced Tally vouchers:

- Match by portal reference number from `trn_voucher.reference_number`.
- Validate customer using Customer `client_code` mapped to Tally ledger alias.
- Match item lines and quantities.
- Sum fulfilled quantities across multiple vouchers for one Order.
- Prefer Sales Invoice over Delivery Challan when both represent the same movement.
- Use tracking number and voucher/item/godown/customer/quantity context to avoid double-counting mirrored DC/Sales movement.
- Completion is item-wise, not godown-wise.
- If fulfilled quantity is greater than requested, move to Manual Review.
- If voucher contains extra unmatched item lines, move to Manual Review.
- If reference matches but customer mismatches, move to Manual Review.
- If duplicate detection is ambiguous, move to Manual Review.
- Partially fulfilled orders become Partially Processed.
- Fully fulfilled orders become Completed.
- Partial Closure is Owner/Admin action when remaining quantity will not be supplied.

## Required Outcomes

The goal is complete only when:

- All required DocTypes exist with migrations/fixtures.
- Role fixtures and permission rules are installed.
- Customer, Sales Employee, Product Group access, Tally sync, Order, PDF/WhatsApp log, and Reconciliation flows work through public APIs or Desk-visible behavior.
- Mobile backend APIs are documented with request/response examples.
- All API responses use consistent success/error envelopes and HTTP status codes.
- Scheduled jobs and manual sync actions are registered and testable.
- Tests exist and pass for each major behavior cluster.

## Acceptance Tests

Write tests incrementally and run them through Frappe/bench. The suite must cover at least:

- Customer signup creates a pending record and duplicate rejected mobile cannot create a second Customer.
- OTP verification moves a Customer to Pending Admin Review without granting Customer App Access.
- Admin approval alone does not grant Customer App Access when Client Code is missing.
- Valid unique Client Code from imported Tally Customer Ledger enables activation.
- Removing Client Code disables an Active Customer's app access.
- Mobile number cannot be reused between Customer and Sales Employee.
- Sales Employee login is blocked when disabled.
- Blank Product Group filters mean all visible.
- Restricted Product Group filters return only configured Product Groups.
- Sales employee Product Group visibility intersects with selected Customer visibility.
- Blank customer assignments let a sales employee see all active customers.
- Configured customer assignments restrict the allowed customer list.
- Customer order submission creates a Placed Order with `KE-YY-MM-####` reference.
- Sales employee order submission creates a Customer order, stores internal note, and hides that note from customer APIs/PDF.
- Duplicate item+godown allocations are merged.
- Quantity greater than stock and zero-stock godown orders are accepted.
- Backend rejects unauthorized item/godown/customer/order submissions.
- Branch Manager sees complete branch-visible orders across statuses.
- Branch Employee sees complete branch-visible Placed, Processing, and Manual Review orders only.
- Branch Employee can move a visible Placed order to Processing.
- Branch roles cannot cancel, partially close, or resolve Manual Review.
- Owner/Admin can resolve Manual Review with a note.
- PDF excludes price, stock, Client Code, and sales employee note.
- WhatsApp Order Placed notification logs are written for Customer recipient only.
- Reconciliation marks Partially Processed when fulfillment is partial.
- Reconciliation marks Completed when fulfilled quantity equals requested quantity for all items.
- Reconciliation does not double-count mirrored DC/Sales movement.
- Customer mismatch, extra item, over-fulfillment, and ambiguous duplicate movement produce Manual Review with reasons.

## Deliverable

Leave the repo with:

- Complete custom Frappe portal/backend implementation.
- Passing test suite.
- API documentation.
- Fixture/migration documentation.
- Scheduler/manual job documentation.
- A final summary of implemented behavior, commands run, tests run, and any unresolved operational questions such as Tally reference field proof, Main Location mapping, Seetarambagh mapping, and exact customer ledger filter.

