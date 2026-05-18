# Grill Session Log

This document records the decision-grilling session. Each entry captures the question, recommended answer, confirmed answer, and documentation updates made from that decision.

## 1. First Mobile Selector

**Question**:
What is the canonical first selector in the mobile order flow?

**Recommended answer**:
Use `Product Group` as the customer-facing term, backed technically by root Tally Stock Group.

**Confirmed answer**:
Agreed.

**Decision**:
The first selector in the mobile order flow is `Product Group`.

**Implications**:

- Mobile users see `Product Group`, not `Brand`, `Category`, or raw `Stock Group`.
- Internally, `Product Group` maps to root Tally Stock Group.
- Item filtering happens through the root stock group hierarchy.

**Docs updated**:

- `CONTEXT.md`

## 14. Order Edit, Cancellation, And Partial Closure

**Question**:
Should users be able to edit or cancel an Order after confirmation?

**Recommended answer**:
No mobile edits or cancellations after confirmation. Owner/Admin can cancel if needed.

**Confirmed answer**:
Agreed. Also add an admin option to close an order as partially fulfilled when the remaining quantity will not be supplied.

**Decision**:
Confirmed Orders are locked for customers and sales employees. Owner/Admin can cancel or partially close. Partial closure is used when some quantity was fulfilled and the remaining quantity will not be supplied.

**Implications**:

- Mobile app has no edit/cancel action after confirmation.
- Branch roles cannot cancel or partially close unless explicitly allowed later.
- `Partially Closed` is distinct from `Partially Processed`.
- `Partially Processed` means more fulfillment may still happen.
- `Partially Closed` means fulfillment is intentionally ended short.

**Docs updated**:

- `CONTEXT.md`
- `docs/01-overall-problem-statement.md`
- `docs/02-portal.md`
- `docs/03-mobile-app.md`

## 34. Total Stock Vs Godown-Wise Stock Storage

**Question**:
Should Frappe store total stock or only godown-wise stock snapshots?

**Recommended answer**:
Store both total item closing balance and godown-wise stock snapshots.

**Confirmed answer**:
Agreed.

**Decision**:
Frappe stores total item closing balance and godown-wise stock snapshot.

**Implications**:

- `Tally Item.total_closing_balance` is used for summaries/search/diagnostics.
- `Tally Stock Snapshot` is used for order placement.
- Godown-wise stock must come from Tally-computed snapshot export.

**Docs updated**:

- `docs/02-portal.md`

## 71. Product Group Rename/Removal From Tally

**Question**:
What should happen when a synced Product Group is removed/renamed in Tally?

**Recommended answer**:
Do not delete Frappe records. Rename by stable identity/GUID. Mark missing groups inactive.

**Confirmed answer**:
Agreed.

**Decision**:
Product Groups are updated or marked inactive, not hard-deleted.

**Implications**:

- Tally rename updates Frappe display name when stable identity matches.
- Missing Tally groups become inactive.
- Existing Orders keep snapshot names from order time.
- Permission rows pointing to inactive Product Groups show warnings.

**Docs updated**:

- `docs/02-portal.md`
- `docs/04-tally-connector.md`

## 78. Master Sync Performance Boundary

**Question**:
When noting master sync performance risk, is the concern Tally or Frappe consuming PostgreSQL?

**Clarification**:
The performance concern is the Tally-to-PostgreSQL extraction leg. Frappe consumes the PostgreSQL mirror after the connector writes it, which should be cheaper.

**Decision**:
Keep 5-minute master sync as target. If the connector uses true incremental/delta sync with correct AlterID tracking, this should be acceptable; the stress concern mainly applies to full extraction every 5 minutes.

**Implications**:

- Frappe should not query Tally directly for master sync.
- Frappe consumes PostgreSQL mirror data, so Frappe-side consumption is not the main stress point.
- If heavy, optimize connector incremental extraction rather than changing Frappe consumption first.

**Docs updated**:

- `docs/04-tally-connector.md`

## 80. Frappe Data Consumption Model

**Question**:
Should Frappe read directly from the PostgreSQL mirror or import/sync PostgreSQL data into Frappe DocTypes?

**Recommended answer**:
Import/sync required data into Frappe DocTypes.

**Confirmed answer**:
Sync required data into Frappe.

**Decision**:
Frappe imports/syncs required PostgreSQL mirror data into Frappe DocTypes.

**Implications**:

- Mobile app reads only Frappe APIs.
- Portal business logic uses Frappe DocTypes.
- PostgreSQL remains the raw Tally mirror/integration source.
- Frappe can store computed root Product Group, active flags, access metadata, and stock snapshots.

**Docs updated**:

- `docs/01-overall-problem-statement.md`
- `docs/04-tally-connector.md`

## 81. Pricing ADR

**Question**:
Should we add ADR for "no pricing in Frappe/mobile"?

**Recommended answer**:
Yes.

**Confirmed answer**:
Agreed.

**Decision**:
Create ADR for keeping pricing out of Frappe and mobile v1.

**Implications**:

- Future contributors have an explicit architectural record for quantity-only Orders.
- Pricing scope creep is easier to reject unless the ADR is revisited.

**Docs updated**:

- `docs/adr/0006-keep-pricing-out-of-frappe-and-mobile-v1.md`

## 82. Advisory Stock ADR

**Question**:
Should we add ADR for "stock is advisory, not a hard ordering cap"?

**Recommended answer**:
Yes.

**Confirmed answer**:
Agreed.

**Decision**:
Create ADR for treating stock as advisory during order placement.

**Implications**:

- Future developers know over-stock ordering is intentional.
- Validation should not reintroduce a hard `quantity <= stock` rule.

**Docs updated**:

- `docs/adr/0007-treat-stock-as-advisory-during-order-placement.md`

## 83. Client Code Access ADR

**Question**:
Should we add ADR for customer/client_code access rule?

**Recommended answer**:
Yes.

**Confirmed answer**:
Agreed.

**Decision**:
Create ADR requiring valid client code mapping for Customer App Access.

**Implications**:

- Client code access rule is recorded as architecture, not just validation detail.
- Future changes to onboarding must intentionally revisit this decision.

**Docs updated**:

- `docs/adr/0008-require-client-code-mapping-for-customer-app-access.md`

## 84. Mobile Authentication

**Question**:
What are the Frappe/mobile auth decisions?

**Recommended answer**:
Use WhatsApp OTP with custom mobile sessions, enforce access on every API call, and keep mobile auth separate from Frappe Desk auth.

**Confirmed answer**:
OTP expires in 5 minutes. OTP resend/attempt limits are required. Users should never be logged out normally; sessions end only on logout, disabled account, or access removal. Multi-device login is allowed. Disabled/access-removed users are blocked. Customer and sales employee API checks are required. Mobile auth should use a custom independent JWT/session flow.

**Decision**:
Mobile app uses custom WhatsApp OTP + JWT/session auth, independent of Frappe Desk login.

**Implications**:

- Internal portal users continue using Frappe authentication.
- Customers and sales employees authenticate through mobile OTP APIs.
- Mobile sessions do not have normal expiry.
- Backend APIs must check current account/access state on every request.
- Multi-device login is allowed.

**Docs updated**:

- `docs/01-overall-problem-statement.md`
- `docs/02-portal.md`
- `docs/03-mobile-app.md`
- `docs/adr/0009-use-custom-jwt-mobile-auth.md`

## 85. PostgreSQL For Frappe

**Question**:
Should Frappe use PostgreSQL?

**Confirmed answer**:
Yes. Use PostgreSQL with Frappe.

**Decision**:
Frappe will use PostgreSQL as its application database.

**Implications**:

- Frappe PostgreSQL is the application database.
- Tally connector PostgreSQL is the raw Tally mirror.
- These should remain separate logical stores even though both use PostgreSQL.

**Docs updated**:

- `docs/01-overall-problem-statement.md`
- `docs/04-tally-connector.md`
- `docs/adr/0010-use-postgresql-for-frappe.md`

## 79. Push Notifications

**Question**:
Should mobile app have push notifications, or only WhatsApp/in-app status?

**Recommended answer**:
No push notifications in v1.

**Confirmed answer**:
Agreed.

**Decision**:
No mobile push notifications in v1.

**Implications**:

- WhatsApp is used only for OTP and Order Placed confirmation/PDF.
- Status updates are viewed in the app.
- Push can be added later if required.

**Docs updated**:

- `docs/03-mobile-app.md`

## 72. Stale Or Failed Tally Stock Sync

**Question**:
What should happen if Tally sync is stale or failing?

**Recommended answer**:
Allow order placement. Show last synced timestamp and record it on the order.

**Confirmed answer**:
Agreed.

**Decision**:
Stale or failed stock sync does not block ordering.

**Implications**:

- Mobile app shows latest available stock and last synced timestamp.
- Order stores stock shown at order time and stock snapshot sync timestamp.
- Admin portal exposes sync health/failure status.

**Docs updated**:

- `docs/02-portal.md`
- `docs/03-mobile-app.md`
- `docs/04-tally-connector.md`

## 73. Stock Sync And Voucher Reconciliation Independence

**Question**:
Should voucher reconciliation run even if stock sync fails?

**Recommended answer**:
Yes. Stock sync and voucher reconciliation should be independent.

**Confirmed answer**:
Agreed.

**Decision**:
Stock snapshot sync and voucher reconciliation are independent jobs.

**Implications**:

- Stock sync failure does not block voucher reconciliation.
- Voucher sync/reconciliation failure does not block stock updates.
- Portal sync health should show each job separately.

**Docs updated**:

- `docs/04-tally-connector.md`

## 77. Manual Sync Controls

**Question**:
Should the portal have a manual "Sync Now" button?

**Recommended answer**:
Yes, for Owner/Admin only, with separate actions for masters, stock, and reconciliation.

**Confirmed answer**:
Agreed.

**Decision**:
Owner/Admin can manually trigger master sync, stock sync, and reconciliation.

**Implications**:

- Portal needs sync control UI.
- Branch/customer roles do not get sync controls.
- Useful for onboarding and debugging Tally updates.

**Docs updated**:

- `docs/02-portal.md`
- `docs/04-tally-connector.md`

## 76. Master Data Sync Frequency

**Question**:
How often should Tally master data sync run?

**Recommended answer**:
Every 30 minutes plus manual Sync Now.

**Confirmed answer**:
Every 5 minutes, assuming it is not too heavy.

**Decision**:
Master data sync target cadence is every 5 minutes.

**Implications**:

- Items, Product Groups, godowns, categories, and customer ledgers update frequently.
- Client code validation against Tally ledger alias updates quickly.
- Must validate connector/Tally performance; if full sync is heavy, revisit incremental/delta approach.

**Docs updated**:

- `docs/04-tally-connector.md`

## 75. Voucher Reconciliation Frequency

**Question**:
What should be the voucher reconciliation frequency?

**Recommended answer**:
Every 5 minutes.

**Confirmed answer**:
Agreed.

**Decision**:
Voucher reconciliation runs every 5 minutes.

**Implications**:

- Order status updates should appear soon after Tally DC/Sales Invoice sync.
- Reconciliation cadence aligns with stock snapshot cadence.

**Docs updated**:

- `docs/04-tally-connector.md`

## 74. Stock Snapshot Sync Frequency

**Question**:
What should be the stock snapshot sync frequency?

**Recommended answer**:
Every 5 minutes, configurable.

**Confirmed answer**:
Every 5 minutes.

**Decision**:
Stock snapshot sync runs every 5 minutes.

**Implications**:

- Mobile stock is latest synced stock, refreshed on a 5-minute cadence.
- Orders store the snapshot timestamp used.
- Tally availability and connector health matter for freshness.

**Docs updated**:

- `docs/04-tally-connector.md`

## 67. Order Notes

**Question**:
Should Owner/Admin be able to edit customer/order notes after placement?

**Recommended answer**:
Keep customer-submitted note immutable and allow internal notes.

**Confirmed answer**:
There are no customer notes. Sales employees can add notes when placing orders for customers.

**Decision**:
Customer order flow has no notes. Sales employee order flow has an optional note.

**Implications**:

- Order stores optional sales employee note only when source is Sales Employee.
- Customer app does not show a note field during order placement.
- No post-placement note editing requirement is in scope yet.

**Docs updated**:

- `docs/02-portal.md`
- `docs/03-mobile-app.md`

## 69. Customer Visibility Of Sales Employee Placed-By

**Question**:
Should customers see who placed an order on their behalf if a sales employee placed it?

**Recommended answer**:
Yes, show sales employee name, but not sales note.

**Confirmed answer**:
Agreed.

**Decision**:
Customer order detail can show sales employee name as the placed-by value.

**Implications**:

- Customer can identify who placed the order.
- Sales employee note remains hidden.

**Docs updated**:

- `docs/03-mobile-app.md`

## 70. PDF Placed-By Field

**Question**:
Should the PDF show "Placed by Sales Employee Name"?

**Recommended answer**:
Yes. Include placed-by, but not sales note, stock, price, or client code.

**Confirmed answer**:
Agreed.

**Decision**:
PDF includes placed-by value.

**Implications**:

- Customer PDF shows whether the order was placed by customer or sales employee.
- PDF excludes sales note, stock, pricing, and client code.

**Docs updated**:

- `docs/02-portal.md`

## 68. Sales Employee Note Visibility

**Question**:
Should the sales employee note be visible to the customer in app/PDF?

**Recommended answer**:
No.

**Confirmed answer**:
It should not be visible.

**Decision**:
Sales employee note is internal only.

**Implications**:

- Customer app does not show sales employee note.
- Customer PDF does not include sales employee note.
- Portal/internal users can see the note.

**Docs updated**:

- `docs/02-portal.md`
- `docs/03-mobile-app.md`

## 66. Editing Order Lines After Placement

**Question**:
Should Owner/Admin be able to edit an Order's line items after it is placed?

**Recommended answer**:
No. Keep placed order lines immutable.

**Confirmed answer**:
Agreed.

**Decision**:
Placed Order line items cannot be edited by any role.

**Implications**:

- The WhatsApp/PDF order summary remains consistent with stored order data.
- Wrong orders should be cancelled and recreated.
- Partial closure handles short fulfillment, not line correction.

**Docs updated**:

- `docs/02-portal.md`

## 65. Branch Manager Cancellation And Partial Closure Permissions

**Question**:
Should Branch Manager be able to cancel or partially close orders?

**Recommended answer**:
No. Only Owner/Admin should cancel or partially close.

**Confirmed answer**:
Agreed.

**Decision**:
Only Owner/Admin can cancel or partially close orders.

**Implications**:

- Branch Manager/Employee can view and move Placed to Processing where allowed.
- Customer-impacting closure actions remain centralized.

**Docs updated**:

- `docs/02-portal.md`

## 63. Owner/Admin Order Visibility

**Question**:
Should Owner/Admin see all orders regardless of status/branch?

**Recommended answer**:
Yes.

**Confirmed answer**:
Agreed.

**Decision**:
Owner and Admin see all orders across all statuses and branches.

**Implications**:

- Owner/Admin are not constrained by branch/godown visibility.
- Owner/Admin can resolve Manual Review globally.

**Docs updated**:

- Existing portal role documentation already covers this.

## 64. Branch Manager Historical Visibility

**Question**:
Should Branch Manager see Completed/Cancelled/Partially Closed history?

**Recommended answer**:
Yes. Branch Manager should see branch-visible orders across statuses.

**Confirmed answer**:
Agreed.

**Decision**:
Branch Manager sees branch-visible order history across all statuses.

**Implications**:

- Branch Manager can review completed/cancelled/partially closed branch-visible orders.
- Branch Employee remains limited to Placed, Processing, and Manual Review unless history is added later.

**Docs updated**:

- `docs/02-portal.md`

## 62. Branch Employee Manual Review Reason Visibility

**Question**:
Should Branch Employee be able to view Manual Review reason?

**Recommended answer**:
Yes, read-only.

**Confirmed answer**:
Agreed.

**Decision**:
Branch Employee can view Manual Review reason read-only for branch-visible orders.

**Implications**:

- Branch employees understand why an order is blocked.
- Branch employees still cannot resolve or edit Manual Review orders.

**Docs updated**:

- `docs/02-portal.md`

## 52. Customer Profile Editability

**Question**:
Should customers see their own profile fields as editable or read-only?

**Recommended answer**:
Allow customers to edit email, date of birth, and date of anniversary only.

**Confirmed answer**:
Agreed.

**Decision**:
Customers can edit only email ID, date of birth, and date of anniversary.

**Implications**:

- Name, business/legal name, GSTIN, mobile number, and client code are admin-controlled.
- Mobile app profile needs read-only and editable field separation.

**Docs updated**:

- `docs/02-portal.md`
- `docs/03-mobile-app.md`

## 61. Branch Visibility For Manual Review

**Question**:
Should Branch Manager/Employee see Manual Review orders?

**Recommended answer**:
Branch Manager can see Manual Review; Branch Employee should not.

**Confirmed answer**:
Show Manual Review orders to both branch roles if branch-visible, but they cannot take action. Owner/Admin resolve.

**Decision**:
Branch Manager and Branch Employee can view branch-visible Manual Review orders read-only.

**Implications**:

- Branch roles can understand why an order is stuck.
- Branch roles cannot resolve Manual Review.
- Owner/Admin remain the only resolution roles.

**Docs updated**:

- `docs/02-portal.md`

## 59. Manual Review Mobile Label

**Question**:
Should customers/sales employees see Manual Review as "Manual Review" in the app?

**Recommended answer**:
No. Show `Under Review` in the app and keep `Manual Review` internal.

**Confirmed answer**:
Do not show Manual Review in the app.

**Decision**:
Mobile app shows `Under Review`; internal portal uses `Manual Review`.

**Implications**:

- Internal reconciliation language stays in portal.
- Customer/sales app uses a simpler status label.

**Docs updated**:

- `docs/03-mobile-app.md`

## 60. Manual Review Reason Visibility

**Question**:
Should the mobile app show Manual Review reason / Under Review reason to customers or sales employees?

**Recommended answer**:
No. Show reasons only to internal portal users.

**Confirmed answer**:
No.

**Decision**:
Mobile users do not see Manual Review reasons.

**Implications**:

- Customers and sales employees see only `Under Review`.
- Internal portal users see reason details.
- Manual Review reason can include Tally/reconciliation details without exposing them customer-facing.

**Docs updated**:

- `docs/02-portal.md`
- `docs/03-mobile-app.md`

## 56. Customer Order History Scope

**Question**:
For customer's own order history, should they see orders placed by sales employees on their behalf?

**Recommended answer**:
Yes. Customer history shows all Orders where `order.customer` is the current customer.

**Confirmed answer**:
Agreed.

**Decision**:
Customers see both self-placed orders and sales-employee-placed orders for them.

**Implications**:

- Order history is customer-centric, not source-centric.
- Order detail should show whether it was placed by the customer or a sales employee.

**Docs updated**:

- `docs/03-mobile-app.md`

## 57. Sales Employee Order History Scope

**Question**:
For sales employee order history, should they see only orders they placed, or all orders for assigned customers?

**Recommended answer**:
Only orders they placed.

**Confirmed answer**:
Only orders placed by them.

**Decision**:
Sales employee order history shows only Orders where `order.sales_employee` is the current employee.

**Implications**:

- Assigned customer access does not grant visibility into all customer order history.
- Sales employee history remains source-centric.

**Docs updated**:

- `docs/03-mobile-app.md`

## 55. Client Code In Sales Employee Customer Search

**Question**:
Should sales employees see customer client_code when selecting a customer?

**Recommended answer**:
No, do not show client_code to sales employees.

**Confirmed answer**:
Sales employees can search by client_code, customer name, and business/legal name, but client_code should not be displayed as a visible field except as a search key/select matching mechanism.

**Decision**:
Client code is searchable in sales employee customer selection but not visibly displayed.

**Implications**:

- Customer selector backend search includes client_code.
- Search results display customer name and business/legal name.
- Client code remains hidden as a field in the mobile app.

**Docs updated**:

- `docs/02-portal.md`
- `docs/03-mobile-app.md`

## 54. Client Code Visibility

**Question**:
Should client_code be visible to the customer in the mobile profile?

**Recommended answer**:
No. Client code is an internal Tally mapping/admin field.

**Confirmed answer**:
Agreed. Internal client code should not be shown customer-facing anywhere in the system.

**Decision**:
Client code is hidden from customer-facing surfaces.

**Implications**:

- Customer mobile profile does not show client code.
- Customer PDF does not show client code.
- Internal portal still stores and manages client code for admin/Tally mapping.

**Docs updated**:

- `docs/02-portal.md`
- `docs/03-mobile-app.md`

## 53. Sales Employee Profile Editability

**Question**:
Can sales employees edit their own profile fields?

**Recommended answer**:
Make sales employee profile read-only in the mobile app.

**Confirmed answer**:
Sales employees can edit nothing.

**Decision**:
Sales employee profile is fully read-only in the mobile app.

**Implications**:

- Admins manage all sales employee fields in portal.
- Mobile app profile screen is view-only for sales employees.

**Docs updated**:

- `docs/02-portal.md`
- `docs/03-mobile-app.md`

## 51. Product Group Permission Child Table Fields

**Question**:
For Product Group permission child tables, should we also store display fields?

**Recommended answer**:
Yes. Store link plus display name. Skip item count.

**Confirmed answer**:
Agreed. No item count needed.

**Decision**:
Product Group permission child rows store Product Group link and Product Group name only.

**Implications**:

- Admins can read selected Product Groups clearly.
- No unnecessary summary fields in v1.
- Same structure applies to customer and sales employee Product Group access tables.

**Docs updated**:

- `docs/02-portal.md`

## 49. Sales Employee Customer Assignment Model

**Question**:
Should sales employee customer assignments also be direct assignment only?

**Recommended answer**:
Yes. Use direct child rows, blank means all active customers.

**Confirmed answer**:
Agreed.

**Decision**:
Sales employee customer assignments are direct child-table rows.

**Implications**:

- No sales teams, territories, routes, or customer groups in v1.
- Blank assigned customer table means all active customers.
- Configured rows restrict the sales employee to selected customers.

**Docs updated**:

- `docs/02-portal.md`

## 50. Assignment UI And Stored Display Fields

**Question**:
Should assignments use MultiSelect or a table, and should rows store only links or display fields too?

**Recommended answer**:
Use child tables. Store the link as canonical data and use fetched/display fields for readability.

**Confirmed answer**:
Use a table. Store link and visible names, including customer name and legal/business name.

**Decision**:
Assignment and Product Group permission UIs should use child tables. Sales employee customer assignment rows should include customer link, customer name, business/legal name, client code, and status.

**Implications**:

- Admins can see readable customer details directly in assignment rows.
- Link remains the canonical relationship.
- Display fields improve selection/review without opening every customer record.

**Docs updated**:

- `docs/02-portal.md`

## 48. Product Group Permission Assignment Model

**Question**:
Should Product Group permissions be assigned directly to each customer/sales employee, or through reusable permission profiles?

**Recommended answer**:
Direct assignment only for v1.

**Confirmed answer**:
Direct assignment. Access is given per customer and per sales person.

**Decision**:
Product Group access is directly assigned on each customer and sales employee.

**Implications**:

- No reusable permission profiles in v1.
- Customer has its own allowed Product Group child table.
- Sales employee has its own allowed Product Group child table.
- Blank child table means all Product Groups.

**Docs updated**:

- `docs/02-portal.md`

## 47. Permission Summary In Access Panels

**Question**:
Should Product Group permissions also be shown in the customer/sales employee access panel?

**Recommended answer**:
Yes. Show effective Product Group and customer assignment access in human-readable form.

**Confirmed answer**:
Agreed.

**Decision**:
Customer and sales employee detail screens must show effective permission summaries.

**Implications**:

- Customer detail shows Product Group access summary.
- Sales employee detail shows Product Group access and customer assignment summary.
- Blank filters must be displayed as "All", not as empty/missing.

**Docs updated**:

- `docs/02-portal.md`

## 46. Approval Before Client Code And Effective Access Display

**Question**:
Should admins be able to approve a customer before entering client_code, leaving them non-active until code is added?

**Recommended answer**:
Yes. Keep approval separate from Tally mapping.

**Confirmed answer**:
Accepted, but the customer detail screen must clearly show effective access, granted permissions, and missing requirements.

**Decision**:
Admins can approve before client_code exists, but Customer App Access remains false until all requirements are met. Portal must show an effective access checklist.

**Implications**:

- Status does not alone explain access.
- Customer detail needs an access panel/checklist.
- Missing client_code or invalid mapping should be visible to admins.
- Effective access is computed from mobile verification, admin approval, valid client code, and not disabled/rejected.

**Docs updated**:

- `docs/02-portal.md`
- `docs/04-tally-connector.md`

## 43. Cart/Draft Persistence

**Question**:
Should carts/drafts be saved on the backend or only local in the mobile app?

**Recommended answer**:
Keep cart local in app for v1. Create Frappe Order only on final confirmation.

**Confirmed answer**:
Cart/draft should be only on the mobile phone.

**Decision**:
V1 cart/draft persistence is mobile-local only.

**Implications**:

- No backend draft Order status in v1.
- No reference number until final confirmation.
- Abandoned carts do not appear in Frappe.
- App can persist cart locally if needed.

**Docs updated**:

- `docs/02-portal.md`
- `docs/03-mobile-app.md`

## 44. Internet Requirement

**Question**:
Should the mobile app require internet for all ordering, or support offline order creation?

**Recommended answer**:
Internet required for v1.

**Confirmed answer**:
Internet is required.

**Decision**:
Mobile ordering requires internet in v1.

**Implications**:

- Local cart can exist on device.
- Final confirmation requires backend connectivity.
- No offline order submission in v1.

**Docs updated**:

- `docs/03-mobile-app.md`

## 45. Admin Approval Vs Client Code

**Question**:
Should customer signup require admin approval after OTP, or should client_code entry itself be approval?

**Recommended answer**:
Keep explicit admin approval separate from client_code.

**Confirmed answer**:
Agreed.

**Decision**:
Customer activation requires both admin approval and valid client_code.

**Implications**:

- `client_code` is data mapping.
- `admin_approved` is business permission.
- A valid client code alone does not activate the customer.
- Approval alone does not activate the customer if client code is missing/invalid.

**Docs updated**:

- `docs/02-portal.md`

## 42. Reference Number Date Source

**Question**:
Which date decides the `YY-MM` in the reference number?

**Recommended answer**:
Use server-side order confirmation/submission timestamp.

**Confirmed answer**:
Agreed.

**Decision**:
Reference number is assigned at confirmed submission, and `YY-MM` comes from server confirmation timestamp.

**Implications**:

- Draft/cart creation does not consume a reference.
- Reference generation must happen server-side.
- Confirmation timestamp determines monthly sequence bucket.

**Docs updated**:

- `docs/02-portal.md`
- `docs/04-tally-connector.md`

## 41. Order Reference Sequence Reset

**Question**:
Should the sequence reset every month?

**Recommended answer**:
Yes.

**Confirmed answer**:
Agreed.

**Decision**:
Order reference sequence resets monthly.

**Implications**:

- `KE-26-05-0001` and `KE-26-06-0001` can both exist because month differs.
- Sequence generation must be atomic per year/month.
- Reference uniqueness is across the full formatted reference.

**Docs updated**:

- `docs/02-portal.md`
- `docs/04-tally-connector.md`

## 35. Ordering More Than Latest Synced Stock

**Question**:
Should users be allowed to order more than the latest synced stock?

**Recommended answer**:
Block quantities greater than latest synced stock.

**Confirmed answer**:
Do not block. Let users order any quantity. At confirmation, highlight rows where requested quantity exceeds latest synced stock as a soft note, not a hard warning.

**Decision**:
Ordering more than latest synced stock is allowed.

**Implications**:

- Stock is advisory, not a hard cap.
- Backend validates quantity is positive, but not `<= stock`.
- Confirmation UI should highlight over-stock rows in a polished, non-alarming way.
- Branch/operations can decide how to fulfill or partially fulfill.

**Docs updated**:

- `docs/02-portal.md`
- `docs/03-mobile-app.md`

## 40. Order Reference Number Format

**Question**:
What should the Order reference number format be?

**Recommended answer**:
Use a short format such as `KE-260001`.

**Confirmed answer**:
Use year and month: `KE-YY-MM-####`.

**Decision**:
Order reference format is `KE-YY-MM-####`.

**Example**:

```text
KE-26-05-0001
```

**Implications**:

- Reference is short enough for manual Tally entry.
- Month is visible in the reference.
- Sequence can reset monthly.
- The same reference is entered in Tally Reference Number for all related DC/Sales Invoice vouchers.

**Docs updated**:

- `docs/02-portal.md`
- `docs/04-tally-connector.md`

## 38. Godown Stock Display

**Question**:
Should the app show all godowns even when stock is zero, or only godowns with stock?

**Recommended answer**:
Show all active godowns, sorted with positive stock first.

**Confirmed answer**:
Agreed.

**Decision**:
The app shows all active godowns for the selected item, including zero-stock godowns.

**Implications**:

- Users can request quantity from any active godown.
- Positive-stock godowns appear before zero-stock godowns.
- Zero-stock godowns are not hidden.

**Docs updated**:

- `docs/03-mobile-app.md`

## 39. Duplicate Item/Godown Rows In Cart

**Question**:
Should customers/sales employees be allowed to add the same item multiple times in one Order?

**Recommended answer**:
Allow same item across different godowns, but merge duplicate item+godown rows.

**Confirmed answer**:
Agreed.

**Decision**:
Duplicate item+godown rows are merged by summing quantity.

**Implications**:

- Same item can be ordered from multiple godowns.
- Same item+same godown appears once in cart/order.
- Both app and backend should normalize duplicates.

**Docs updated**:

- `docs/02-portal.md`
- `docs/03-mobile-app.md`

## 37. Stock In PDF And Order Audit

**Question**:
Should the order confirmation PDF include latest synced stock shown at order time?

**Recommended answer**:
Do not include stock in the customer PDF. Store stock shown at order time internally.

**Confirmed answer**:
Agreed. Stock should not be present in the PDF, only in the app. Frappe should record stock at the time the order was placed in the order items/allocation section.

**Decision**:
Customer PDF excludes stock. Frappe stores stock shown at order time.

**Implications**:

- App can display latest synced stock during ordering.
- Order allocation stores `stock_shown_at_order_time`.
- PDF contains requested item/godown/quantity only, not stock availability.
- Internal users can audit what stock was shown when the order was placed.

**Docs updated**:

- `docs/02-portal.md`
- `docs/03-mobile-app.md`

## 36. Ordering From Zero-Stock Godown

**Question**:
Should users be allowed to enter quantity for a godown where latest synced stock is zero?

**Recommended answer**:
Yes, consistent with stock being advisory.

**Confirmed answer**:
Agreed.

**Decision**:
Users can request quantity from a zero-stock godown.

**Implications**:

- Latest synced stock does not restrict ordering.
- Zero-stock rows with requested quantity should receive the same soft availability highlight at confirmation.
- Backend should still require positive quantity.

**Docs updated**:

- `docs/02-portal.md`
- `docs/03-mobile-app.md`

## 15. Moving Orders To Processing

**Question**:
Who can mark an Order as Processing?

**Recommended answer**:
Owner, Admin, Branch Manager, and Branch Employee can move Placed orders to Processing. Branch roles can do this only for orders linked to their branch/godown.

**Confirmed answer**:
Agreed.

**Decision**:
Branch employees can mark relevant branch orders as Processing.

**Implications**:

- Processing status is operational, not a timestamped workflow audit requirement.
- Branch role permissions must check order godown allocations.
- Branch employees still only see processing/relevant orders as previously defined.

**Docs updated**:

- `docs/02-portal.md`

## 21. Fulfillment Matching Granularity

**Question**:
Should fulfillment quantity match at item level only, or item + godown allocation level?

**Recommended answer**:
Match by item + godown because customers select godowns and branch visibility depends on godown.

**Confirmed answer**:
Match item-wise only. Customers may select one godown, but operations may reroute fulfillment from another godown.

**Decision**:
Fulfillment reconciliation is item-wise, not godown-wise.

**Implications**:

- Godown allocation remains important for ordering intent and branch visibility.
- Completion status is based on total fulfilled quantity per item.
- Tally godown on voucher lines is stored for diagnostics but does not block completion.
- Operations can fulfill from any godown without forcing Manual Review.

**Docs updated**:

- `CONTEXT.md`
- `docs/02-portal.md`
- `docs/04-tally-connector.md`

## 24. Manual Review Resolution

**Question**:
Who can resolve Manual Review, and what can they do?

**Recommended answer**:
Only Owner and Admin can resolve Manual Review. Branch roles can view reasons but not resolve.

**Confirmed answer**:
Agreed.

**Decision**:
Manual Review resolution is restricted to Owner and Admin.

**Implications**:

- Resolution actions are Accept as Completed, Accept as Partially Processed, Mark Partially Closed, Cancel Order, and Return to Processing.
- Resolution requires a note.
- Branch Manager/Employee can view reasons for visible orders but cannot resolve them.

**Docs updated**:

- `docs/02-portal.md`
- `docs/04-tally-connector.md`

## 33. Pricing Scope

**Question**:
Should prices/rates be shown in the mobile app?

**Recommended answer**:
No. Keep v1 quantity-only.

**Confirmed answer**:
No pricing-related thing will be stored in Frappe or shown to the customer.

**Decision**:
Pricing, rates, discounts, tax, and monetary value are out of scope for Frappe/mobile v1.

**Implications**:

- Orders store quantities only.
- Mobile app shows stock and requested quantity only.
- PDF order summary excludes price/rate/value.
- Tally remains the only place where invoice value/pricing is handled.

**Docs updated**:

- `CONTEXT.md`
- `docs/01-overall-problem-statement.md`
- `docs/02-portal.md`
- `docs/03-mobile-app.md`

## 32. Sales Employee Tally Mapping

**Question**:
Should sales employees be mapped to Tally ledgers or only exist in Frappe?

**Recommended answer**:
Sales employees exist only in Frappe.

**Confirmed answer**:
Agreed.

**Decision**:
Sales employees are Frappe-only records and are not mapped to Tally.

**Implications**:

- Tally voucher party/customer remains the Customer.
- Order source can still store Sales Employee in Frappe.
- Reconciliation validates Customer `client_code`, not sales employee identity.

**Docs updated**:

- `docs/02-portal.md`
- `docs/04-tally-connector.md`

## 27. Multiple Tally Vouchers Per Order

**Question**:
Can one Order be fulfilled by multiple DCs/Sales Invoices?

**Recommended answer**:
Yes. Sum deduplicated item quantities across all matching Tally vouchers for the same portal reference.

**Confirmed answer**:
Agreed.

**Decision**:
One Order can be fulfilled by multiple Tally vouchers.

**Implications**:

- Partial fulfillment can accumulate over time.
- Multiple invoices/DCs with the same reference are valid.
- Reconciliation must sum fulfilled quantity across all matching vouchers after de-duplication.

**Docs updated**:

- `docs/04-tally-connector.md`

## 30. Customer Match Key For Reconciliation

**Question**:
Which customer field should reconciliation use to validate Tally customer identity?

**Recommended answer**:
Use `client_code` as the primary match key, mapped to Tally ledger alias.

**Confirmed answer**:
Use only `client_code`. In the Tally-connected PostgreSQL database, `mst_ledger.alias` appears to be the likely field for this mapping if `mst_ledger` is the client/customer table.

**Decision**:
Automatic customer identity matching uses only `client_code`, mapped to `mst_ledger.alias`.

**Implications**:

- Do not auto-match customers by legal name, party name, GSTIN, mobile number, or email.
- Import relevant customer/debtor ledgers from `mst_ledger`.
- Confirm the exact customer ledger filter, likely debtor ledgers under `Sundary Debtors`.
- Show non-key fields only for diagnostics and manual review context.

**Docs updated**:

- `CONTEXT.md`
- `docs/02-portal.md`
- `docs/04-tally-connector.md`
- `docs/05-tally-db-discovery.md`

## 31. Client Code Must Exist In Tally

**Question**:
Should the portal allow creating a Customer if `client_code` does not exist in `mst_ledger.alias`?

**Recommended answer**:
Allow customer/signup creation without client code. When client code is entered, validate that it exists in imported Tally customer ledgers and is unique among app customers.

**Confirmed answer**:
Agreed.

**Decision**:
`client_code` can be blank initially, but once entered it must be unique and must exist in imported Tally customer ledgers.

**Implications**:

- Blank `client_code` blocks Customer App Access but does not block admin visibility.
- Invalid `client_code` cannot be saved/activated.
- Customer can become Active only when `client_code` is present, unique, and found in Tally customer ledgers.

**Docs updated**:

- `docs/02-portal.md`
- `docs/04-tally-connector.md`

## 29. Reference Match But Customer Mismatch

**Question**:
What should happen if a Tally voucher has the correct reference number but wrong customer/client code?

**Recommended answer**:
Move to Manual Review.

**Confirmed answer**:
Agreed.

**Decision**:
Reference match plus customer/client-code mismatch moves the Order to Manual Review.

**Implications**:

- Reference number alone is not enough when customer identity conflicts.
- Admin must decide whether the Tally voucher or portal customer mapping is wrong.
- Manual Review reason should show both portal customer and Tally voucher customer.

**Docs updated**:

- `docs/04-tally-connector.md`

## 28. Multiple Orders In One Tally Voucher

**Question**:
Can one Tally voucher contain items from multiple portal Orders?

**Recommended answer**:
No. One Tally voucher should belong to one portal Order reference.

**Confirmed answer**:
Agreed.

**Decision**:
Do not mix multiple portal Orders into one Tally voucher.

**Implications**:

- `reference_number` is voucher-level, so line-level order splitting is unsafe.
- If two portal Orders need invoices, create separate Tally vouchers or process them separately.
- A voucher with mismatched/extra order lines may go to Manual Review.

**Docs updated**:

- `docs/04-tally-connector.md`

## 25. Tally Reference Field

**Question**:
What exact field in Tally must carry our Order reference?

**Recommended answer**:
Use Tally Reference Number and verify it syncs into `trn_voucher.reference_number`.

**Confirmed answer**:
Use Reference Number for now. If the client asks for a different field later, revisit.

**Decision**:
Portal Order reference is entered in Tally's Reference Number field and read from `trn_voucher.reference_number`.

**Implications**:

- Do not use `voucher_number` because that is Tally's own document number.
- Do not use `tracking_number` because it is line/movement related.
- Do not use `order_number` for this unless future Tally testing proves it is better.
- A proof test should still confirm the value appears in `trn_voucher.reference_number`.

**Docs updated**:

- `docs/02-portal.md`
- `docs/04-tally-connector.md`

## 26. Reference Number On DC And Sales Invoice

**Question**:
Should the same portal Order reference be entered in both DC and Sales Invoice?

**Recommended answer**:
Yes. Use the same reference on every related fulfillment document.

**Confirmed answer**:
Agreed.

**Decision**:
The same portal Order reference must be entered on every related Delivery Challan and Sales Invoice.

**Implications**:

- Reconciliation can see DC first and invoice later.
- Multiple DCs/invoices can still map to one Order.
- Missing reference on any related voucher can cause incomplete reconciliation.

**Docs updated**:

- `docs/02-portal.md`
- `docs/04-tally-connector.md`
- `docs/05-tally-db-discovery.md`

## 22. Over-Fulfillment

**Question**:
If Tally fulfills more quantity than requested, what should happen?

**Recommended answer**:
Move to Manual Review.

**Confirmed answer**:
Agreed.

**Decision**:
Over-fulfillment moves the order to Manual Review.

**Implications**:

- Do not silently cap fulfilled quantity.
- Do not mark Completed automatically when fulfilled quantity exceeds requested quantity.
- Admin must review whether the reference, item, or quantity is wrong.

**Docs updated**:

- `docs/04-tally-connector.md`

## 23. Extra Tally Items And Manual Review Reasons

**Question**:
If Tally has an extra item that was not in the Order, what should happen?

**Recommended answer**:
Move to Manual Review.

**Confirmed answer**:
Agreed. Also show users why the order moved to Manual Review.

**Decision**:
Extra unmatched Tally items move the order to Manual Review. Manual Review must always include a visible reason.

**Implications**:

- Extra voucher lines are not silently ignored.
- Manual Review is not just a status; it requires reason details.
- Portal users should see a reason code/message and related voucher context.

**Docs updated**:

- `CONTEXT.md`
- `docs/02-portal.md`
- `docs/04-tally-connector.md`

## 18. Fulfillment Source Of Truth

**Question**:
What is the fulfillment source of truth: Delivery Challan, Sales Invoice, or both?

**Recommended answer**:
Use both with de-duplication. Sales Invoice is the primary/confirmed signal when present; Delivery Challan is provisional when invoice is not yet present. Never count both for the same tracked movement.

**Confirmed answer**:
Agreed.

**Decision**:
Order fulfillment status is reconciled from both DC and Sales Invoice, with Sales Invoice preferred and duplicate DC/Sales movement counted once.

**Implications**:

- Reconciliation must handle mirrored DC/Sales rows.
- `tracking_number` and line attributes help detect duplicated fulfillment.
- DC can move status to Partially Processed/Completed provisionally.
- Sales Invoice later confirms/replaces the provisional signal.
- Ambiguous duplicate matching goes to Manual Review.

**Docs updated**:

- `CONTEXT.md`
- `docs/04-tally-connector.md`
- `docs/05-tally-db-discovery.md`

## 19. Sales Invoice Line Items And Quantity Reconciliation

**Question**:
Will we get line items for Sales Invoices, and can we track partial execution until the full order quantity is fulfilled?

**Recommended answer**:
Yes, if Tally voucher reference matching is reliable. Sales/DC line items are available through `trn_inventory` linked to `trn_voucher.guid`.

**Confirmed answer**:
Accepted as the basis for partial/completed status handling.

**Decision**:
Use Tally voucher line items for quantity-level reconciliation.

**Implications**:

- Fulfilled quantity is tracked per order item/allocation.
- Partially fulfilled orders become `Partially Processed`.
- Orders become `Completed` when fulfilled quantity reaches requested quantity for all lines.
- DC/Sales duplication still needs de-duplication before summing quantities.

**Docs updated**:

- `docs/04-tally-connector.md`
- `docs/05-tally-db-discovery.md`

## 20. Order Statuses

**Question**:
What exact statuses should an Order have in v1?

**Recommended answer**:
Use `Placed`, `Processing`, `Partially Processed`, `Completed`, `Partially Closed`, `Cancelled`, and `Manual Review`.

**Confirmed answer**:
Agreed. These statuses are perfect for v1.

**Decision**:
V1 order statuses are `Placed`, `Processing`, `Partially Processed`, `Completed`, `Partially Closed`, `Cancelled`, and `Manual Review`.

**Implications**:

- Status model is fixed for v1.
- `Partially Processed` means more fulfillment may still happen.
- `Partially Closed` means remaining quantity will not be fulfilled.
- `Manual Review` is for reconciliation ambiguity.

**Docs updated**:

- `docs/02-portal.md`

## 17. Branch Employee Status Visibility

**Question**:
Should Branch Employee see Placed orders, or only Processing orders?

**Recommended answer**:
Branch Employee must see relevant Placed and Processing orders so they can move Placed orders to Processing.

**Confirmed answer**:
Agreed.

**Decision**:
Branch Employee can see full relevant orders in Placed and Processing statuses.

**Implications**:

- Branch Employee can mark relevant Placed orders as Processing.
- Branch Employee does not see Completed, Cancelled, or Partially Closed orders unless read-only history is added later.
- Visibility still depends on at least one godown allocation belonging to their branch.

**Docs updated**:

- `docs/02-portal.md`

## 16. Branch Visibility Scope

**Question**:
For branch visibility, should branch users see the full order or only their branch lines?

**Recommended answer**:
Show the full order once the order qualifies for branch visibility.

**Confirmed answer**:
Show the full order to both Branch Manager and Branch Employee.

**Decision**:
Branch Manager and Branch Employee see the complete order when the order is visible to them.

**Implications**:

- Branch Manager sees the full order if any allocation belongs to their branch.
- Branch Employee sees the full order if any allocation belongs to their branch and the order is Processing.
- UI/API permissions filter order visibility, not individual order lines.

**Docs updated**:

- `docs/02-portal.md`
- `docs/01-overall-problem-statement.md`
- `docs/03-mobile-app.md`
- `docs/05-tally-db-discovery.md`

## 2. Customer Meaning And Tally Mapping

**Question**:
What is the canonical meaning of `Customer`, and how does it relate to Tally customer records?

**Recommended answer**:
Separate app `Customer` from `Tally Customer Ledger`, and require a mapping before ordering.

**Confirmed answer**:
`Customer` means the person placing the order. In Tally, customers are maintained with their business names. During signup, the app must capture name, business/legal name, GSTIN, mobile number, email ID, date of birth, and date of anniversary. The portal additionally stores a client code, entered internally, which is the alias/code used in Tally and later helps map order completion.

**Decision**:
`Customer` is the app/order-facing person/contact. `Client Code` is the portal-maintained alias/code used to map that customer to the corresponding Tally customer identity. Customer app access is blocked unless client code is present.

**Implications**:

- Signup captures customer and business details.
- Customer does not self-enter the client code.
- Portal users maintain the client code.
- Reconciliation and order completion logic can use the client code/Tally alias where needed.
- Mobile number must be unique.
- Client code can initially be blank, but once entered it must be unique.
- Customer app access cannot be granted without client code.
- Removing client code removes customer app access.
- Enforce this in the Frappe custom app controller; Server Script Before Save can also do this, but server scripts may need enabling in Frappe v15.

**Docs updated**:

- `CONTEXT.md`
- `docs/02-portal.md`
- `docs/03-mobile-app.md`

## 13. Order Meaning

**Question**:
What is the exact meaning of an Order?

**Recommended answer**:
Use `Order Request` as the domain term and `Order` in the UI.

**Confirmed answer**:
Use `Order` everywhere because it is simpler for Frappe terms and UI.

**Decision**:
The canonical term is `Order`.

**Implications**:

- An Order is still only a request.
- An Order does not reduce or reserve stock.
- An Order is not a Tally Sales Order or invoice.
- Fulfillment status comes later through Tally DC/Sales Invoice reconciliation.

**Docs updated**:

- `CONTEXT.md`

## 10. Client Code Removal From Active Customer

**Question**:
If `client_code` is removed from an Active Customer, what status should the customer move to?

**Recommended answer**:
Move to `Disabled`.

**Confirmed answer**:
Agreed.

**Decision**:
Removing `client_code` from an Active Customer moves the customer to `Disabled`.

**Implications**:

- This is treated as an access-breaking admin action, not a new pending review.
- Customer app access is revoked immediately.
- Reactivation requires restoring `client_code` and admin re-enabling the customer.

**Docs updated**:

- `docs/02-portal.md`

## 11. Rejected Customer Re-Signup

**Question**:
Can a Rejected Customer sign up again with the same mobile number?

**Recommended answer**:
No. Admin must reopen or update the rejected record.

**Confirmed answer**:
Agreed.

**Decision**:
Rejected customers cannot create duplicate signups with the same mobile number.

**Implications**:

- Mobile number uniqueness remains simple and global.
- Rejected state is preserved for audit.
- Backend signup API should return existing rejected state instead of creating a new customer.
- Admins can manually reopen/update the rejected record if needed.

**Docs updated**:

- `docs/02-portal.md`
- `docs/03-mobile-app.md`

## 12. Sales Employee Lifecycle

**Question**:
What is the sales employee lifecycle?

**Recommended answer**:
Use `Active` and `Disabled` only. Sales employees are created by admins and log in with WhatsApp OTP.

**Confirmed answer**:
Agreed.

**Decision**:
Sales employee statuses are `Active` and `Disabled`.

**Implications**:

- Sales employees do not self-register.
- Sales employees do not have rejection or client-code lifecycle.
- Disabled sales employees cannot log in.
- Mobile number remains globally unique across Customers and Sales Employees.

**Docs updated**:

- `CONTEXT.md`
- `docs/02-portal.md`
- `docs/03-mobile-app.md`

## 7. Initial Filter Scope

**Question**:
What is the item access filter behavior when multiple dimensions are configured?

**Recommended answer**:
Define combination rules for Product Group, category, item, and godown filters.

**Confirmed answer**:
Current scope only needs Product Group/root stock group filters for both customers and sales employees, plus customer assignment list for sales employees.

**Decision**:
Initial access filters are limited to Product Group and sales employee customer assignments.

**Implications**:

- Do not design category, specific item, or godown filters yet.
- Customer item access means Product Group access.
- Sales employee item access means Product Group access.
- For sales employee orders, effective Product Group access is the intersection of employee Product Group access and customer Product Group access.

**Docs updated**:

- `CONTEXT.md`
- `docs/01-overall-problem-statement.md`
- `docs/02-portal.md`
- `docs/03-mobile-app.md`

## 9. Customer Account Lifecycle

**Question**:
What is the exact customer account lifecycle?

**Recommended answer**:
Use a clean lifecycle with `Pending OTP`, `Pending Admin Review`, `Active`, `Rejected`, and `Disabled`. Store OTP verification as fields instead of a separate long-lived business status.

**Confirmed answer**:
Agreed.

**Decision**:
Customer statuses are `Pending OTP`, `Pending Admin Review`, `Active`, `Rejected`, and `Disabled`.

**Implications**:

- OTP verification is represented by `mobile_verified` and `mobile_verified_at`.
- After OTP verification, the customer enters `Pending Admin Review`.
- Customer becomes `Active` only when admin approves and `client_code` exists.
- Rejected and Disabled are separate states.

**Docs updated**:

- `CONTEXT.md`
- `docs/02-portal.md`
- `docs/03-mobile-app.md`

## 8. Product Group Filter Semantics

**Question**:
Should Product Group filters be inclusive with blank meaning all?

**Recommended answer**:
Yes. Blank means unrestricted/all Product Groups. Configured rows mean only those Product Groups. For sales employee orders, combine employee and customer Product Group access by intersection, treating blank as unrestricted.

**Confirmed answer**:
Agreed.

**Decision**:
Product Group filters are inclusive. Blank means all. Sales employee ordering uses intersection of sales employee and customer Product Group access.

**Implications**:

- No Product Group filter rows means all Product Groups are visible.
- Customer restrictions are respected during sales employee ordering.
- Sales employee restrictions are respected even when selected customer is unrestricted.
- Backend must compute effective Product Group access in customer context.

**Docs updated**:

- `CONTEXT.md`
- `docs/01-overall-problem-statement.md`
- `docs/02-portal.md`
- `docs/03-mobile-app.md`

## 5. WhatsApp Order Confirmation Recipients

**Question**:
Who receives WhatsApp order confirmation for customer orders and sales employee orders?

**Recommended answer**:
Customer always receives the official WhatsApp order confirmation and PDF. Sales employee receives a simple acknowledgement.

**Confirmed answer**:
Customer receives the WhatsApp order confirmation and PDF. Sales employee does not need WhatsApp confirmation because the app itself shows confirmation.

**Decision**:
Send WhatsApp order confirmation/PDF only to the customer, including when the order is placed by a sales employee.

**Implications**:

- Customer is the official recipient of order summary PDFs.
- Sales employee order submission confirmation is in-app only.
- WhatsApp notification logs should primarily track customer-facing order messages.

**Docs updated**:

- `docs/02-portal.md`
- `docs/03-mobile-app.md`

Additional confirmation:

- Customer always receives WhatsApp order confirmation/PDF even when a sales employee places the order.
- Sales employee receives in-app confirmation only.

## 58. WhatsApp Status Updates

**Question**:
Should WhatsApp status updates be sent when an Order becomes Partially Processed, Completed, Partially Closed, Cancelled, or Manual Review?

**Recommended answer**:
No. Send WhatsApp only for Order Placed in v1.

**Confirmed answer**:
Send only for Order Placed.

**Decision**:
V1 WhatsApp notifications are limited to OTP and Order Placed confirmation/PDF.

**Implications**:

- Status changes are visible in app only.
- Manual Review does not trigger customer WhatsApp.
- Completed/Cancelled/Partially Closed do not trigger WhatsApp in v1.

**Docs updated**:

- `docs/02-portal.md`
- `docs/03-mobile-app.md`

## 6. Sales Employee Customer And Item Access

**Question**:
What is the sales employee's customer access rule, and how does item visibility work when ordering for a customer?

**Recommended answer**:
Use inclusive customer assignments. If no assignments exist, all active customers are allowed. If assignments exist, only assigned active customers are allowed. Effective item access is the intersection of sales employee item access and customer item access.

**Confirmed answer**:
Agreed.

**Decision**:
Sales employee customer access is inclusive. For sales employee orders, item visibility is the intersection of employee and selected customer access.

**Implications**:

- Sales employees can be unrestricted by leaving customer assignments blank.
- Customer assignments restrict sales employees only when configured.
- Sales employees cannot bypass customer-specific item restrictions.
- Backend APIs must resolve item visibility after customer selection.

**Docs updated**:

- `CONTEXT.md`
- `docs/02-portal.md`
- `docs/03-mobile-app.md`

## 4. Customer App Access Vs Internal Admin Visibility

**Question**:
What exactly does "portal access" mean for a Customer?

**Recommended answer**:
Admins can always see and edit customer signup records. The access block applies to customer-facing mobile ordering access.

**Confirmed answer**:
Agreed.

**Decision**:
Admins can see/edit customer records even when `client_code` is missing. Customers cannot use mobile ordering until they are approved and have `client_code`.

**Implications**:

- Missing `client_code` does not hide the customer from admins.
- Missing `client_code` blocks customer app access.
- Removing `client_code` removes customer app access.
- The canonical term is `Customer App Access`, not portal access.

**Docs updated**:

- `CONTEXT.md`
- `docs/02-portal.md`
- `docs/03-mobile-app.md`

## 3. Mobile Number Uniqueness

**Question**:
Should customer mobile number uniqueness be global across both Customers and Sales Employees?

**Recommended answer**:
Yes. A mobile number should identify exactly one mobile login principal.

**Confirmed answer**:
Agreed.

**Decision**:
Mobile number must be globally unique across customers and sales employees.

**Implications**:

- WhatsApp OTP login can resolve a mobile number to one account.
- The same number cannot exist in both Customer and Sales Employee records.
- Validation must check across both account types.

**Docs updated**:

- `CONTEXT.md`
- `docs/02-portal.md`
- `docs/03-mobile-app.md`
