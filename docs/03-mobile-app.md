# Mobile App Requirements

## Purpose

The mobile app is used by customers and sales employees to place order requests. The app is built with Expo / React Native and communicates with the Frappe backend through APIs.

The mobile app should not connect directly to Tally or to the raw PostgreSQL connector database.

## App User Types

The mobile app supports:

- Customer
- Sales Employee

Both use WhatsApp OTP login.

## Customer Signup Flow

Customer signup flow:

1. Customer enters required signup details.
2. Customer enters WhatsApp mobile number.
3. System sends OTP on WhatsApp.
4. Customer verifies OTP.
5. Customer account is created in Frappe in a pending approval state.
6. Admin reviews the customer in the portal.
7. Admin approves or rejects customer access.
8. Approved customer can use the ordering flow.

OTP verification proves the phone number. Admin approval grants business access.

Signup fields:

- Name
- Business name / legal name
- GSTIN number
- Mobile number
- Email ID
- Date of birth
- Date of anniversary

The customer does not enter `client_code` during signup. Internal portal users enter/maintain the client code later for Tally mapping.

The app should not allow customer ordering access until the backend marks the customer as active. A customer can be OTP verified and admin-reviewed but still blocked if the internal `client_code` has not been entered.

## Customer Access States

Recommended customer states:

- Pending OTP
- Pending Admin Review
- Active
- Rejected
- Disabled

The app should show a simple pending access screen if OTP is verified but admin approval is not complete.

If a mobile number already belongs to a rejected customer record, the app should not create a duplicate signup. The backend should return the existing rejected state.

## Sales Employee Login Flow

Sales employees are created from the portal.

Sales employee login flow:

1. Sales employee enters mobile number.
2. System checks that the number belongs to an active sales employee.
3. System sends WhatsApp OTP.
4. Sales employee verifies OTP.
5. App opens sales employee flow.

Sales employees should not self-register.

Mobile number is the login identity for WhatsApp OTP. The same mobile number cannot belong to both a customer and a sales employee.

Sales employee app states:

- Active
- Disabled

Disabled sales employees cannot log in.

## WhatsApp OTP

OTP should be sent through the Frappe WhatsApp integration path where possible.

The app should handle:

- Send OTP
- Resend OTP
- Verify OTP
- Expired OTP
- Incorrect OTP
- Too many attempts
- Account disabled
- Pending approval

OTP implementation details belong to the backend. The app should only call backend APIs.

Auth decisions:

- OTP expiry: 5 minutes.
- OTP resend: allow after 30-60 seconds.
- OTP attempt limits: max 3-5 attempts per 15 minutes.
- Mobile session should not expire normally; user remains logged in unless they log out, are disabled, or access is removed.
- Multi-device login is allowed.
- Mobile auth uses a custom JWT/session flow independent of Frappe Desk login.
- Disabled users or users with removed access must be blocked immediately by backend APIs even if an old token exists.

Customer API access check:

```text
status = Active
mobile_verified = true
admin_approved = true
valid client_code exists
```

Sales employee API access check:

```text
status = Active
mobile_verified = true
```

## Customer App Navigation

Customer app sections:

- Login/signup
- Pending approval screen
- Home/order entry
- Order confirmation
- Order success
- Order history
- Order detail/status
- Profile

## Sales Employee App Navigation

Sales employee app sections:

- Login
- Customer selection
- Home/order entry
- Order confirmation
- Order success
- Order history
- Order detail/status
- Profile

The main difference is that sales employees must select the customer for whom they are placing the order.

## Item Selection Decision

The ordering flow needs one first-level selector.

Current recommended decision:

- Use root Tally Stock Group as the first-level selector.
- Label it as "Product Group".
- Immediate stock group should not be used directly as the first selector because it is too granular.
- Stock category should not be used as the primary selector because many items in the demo data have no category.

Alternative:

- Create portal-side Brand Mapping if neither group nor category is good enough.

## Customer Order Placement Flow

Customer order flow:

1. Customer opens order screen.
2. App loads allowed first-level groups/categories/brands.
3. Customer selects one group/category/brand.
4. App loads allowed items under that selection.
5. Customer selects an item.
6. App shows latest synced stock by godown.
7. Customer selects one or more godowns.
8. Customer enters quantity for each selected godown.
9. Customer adds item to cart/order.
10. Customer may add more items.
11. App shows order summary.
12. Customer confirms order.
13. Backend creates order and reference number.
14. App shows success screen with reference number.
15. Backend sends WhatsApp thank-you message with PDF summary.

## Sales Employee Order Placement Flow

Sales employee order flow:

1. Sales employee logs in.
2. App loads allowed customers.
3. Sales employee selects customer.
4. App loads allowed groups/categories/brands for that employee/customer context.
5. Sales employee selects group/category/brand.
6. App loads allowed items.
7. Sales employee selects item.
8. App shows latest synced stock by godown.
9. Sales employee selects one or more godowns.
10. Sales employee enters quantity for each selected godown.
11. Sales employee adds item to cart/order.
12. Sales employee may add more items.
13. Sales employee may add a note.
14. App shows order summary with customer details.
15. Sales employee confirms order.
16. Backend creates order and reference number.
17. App shows success screen with reference number.
18. Backend sends WhatsApp confirmation and PDF summary to the customer.

The sales employee does not need a WhatsApp order confirmation because the app success screen is their confirmation.

Customer order flow does not include notes. Only sales employee order flow has an optional note field.

Sales employee note is not visible to the customer in the app or PDF.

Sales employee customer search can match:

- Customer name
- Business/legal name
- Client code

Client code may be used as a search key, but should not be displayed as a visible customer field in the mobile app.

Allowed customers:

```text
No customer assignments = all active customers
Customer assignments present = assigned active customers only
```

After the sales employee selects a customer, item visibility must be resolved by the backend as the intersection of employee item access and customer item access.

## Stock Display

The app shows latest synced stock from Frappe.

Real-time calls to Tally are not required initially.

The stock shown by godown should come from Frappe's `Tally Stock Snapshot`, which is populated from a Tally-computed stock-by-godown export. The mobile app should not use transaction-derived calculations from `trn_inventory`.

The stock screen should show:

- Item name
- Unit
- Godown name
- Available quantity from latest sync
- Last synced time, if useful

Show all active godowns for the selected item, including godowns whose latest synced stock is zero. Sort godowns with positive stock first, followed by zero-stock godowns.

If stock sync is stale or failing, do not block ordering. Show the latest available stock and last synced timestamp.

The app must make it clear enough that stock is indicative/latest synced, not a hard reservation.

The app should not show prices, rates, discounts, tax, or order value in v1.

Users are allowed to request quantity greater than the latest synced stock, including from a godown whose latest synced stock is zero. At confirmation, rows where requested quantity exceeds latest synced stock should be highlighted as a soft availability note, not blocked with a hard error.

The app may show latest synced stock during ordering and confirmation. The backend stores the stock value that was shown at order time for each order allocation.

## Cart Behavior

The cart/order draft should support:

- Multiple items
- Multiple godown allocations per item
- Quantity editing
- Removing item
- Removing godown allocation
- Order summary before confirmation

If the same item and same godown are added more than once, the app/backend should merge them into one row by summing quantity. The same item can still appear under different godowns.

The backend should validate all items, godowns, quantities, and access rules again during final order submission. The app should not be trusted as the authority.

## Access Rules In App

The backend should return only allowed data to the app.

The app should not download all items and hide restricted ones locally.

Access rules:

```text
No filter configured = all visible
Filter configured = only configured values visible
```

For customers, filters apply to Product Group visibility.

For sales employees, filters apply to:

- Product Group visibility
- Customer visibility

If both employee and customer Product Group filters are relevant during sales employee ordering, the backend should define the final allowed set as the intersection of applicable filters.

Blank Product Group filters mean unrestricted/all Product Groups for that account.

## Order History

Customer order history shows:

- Orders placed by the customer
- Orders placed by a sales employee on behalf of the customer
- Status
- Reference number
- Date
- Summary quantities
- Detail screen with items/godowns/status

Order detail should show who placed the order:

- You
- Sales employee name

If a sales employee placed the order, the customer can see the sales employee name as the placed-by value, but not the sales employee note.

Sales employee order history shows:

- Orders placed by that sales employee
- Customer name
- Status
- Reference number
- Date
- Detail screen with items/godowns/status

Sales employees do not see all orders for assigned customers; they see only orders they placed.

## Profile

Customer profile should show:

- Name
- Mobile number
- Company/business name, if applicable
- Address, if captured
- Approval/access status
- GSTIN number
- Email ID
- Date of birth
- Date of anniversary

Do not show client code in the customer mobile app.

Customer-editable profile fields:

- Email ID
- Date of birth
- Date of anniversary

Read-only for customer:

- Name
- Business/legal name
- GSTIN number
- Mobile number
- Client code

Sales employee profile should show:

- Name
- Mobile number
- Employee code, if any
- Active status

Sales employee profile is fully read-only in the mobile app. Sales employees cannot edit profile fields.

## Order Status Display

The app should display simple status labels:

- Placed
- Processing
- Partially Processed
- Completed
- Partially Closed
- Cancelled
- Under Review, if backend status is Manual Review

The app does not need to explain reconciliation internals.

The app should not show the internal Manual Review label or Manual Review reason. Customers and sales employees see only `Under Review`.

After confirmation, mobile users cannot edit or cancel an order. Any cancellation or partial closure is handled internally by owner/admin users.

## API Requirements

Likely backend APIs:

- Start customer signup
- Send OTP
- Verify OTP
- Get current user/session
- Get approval status
- List allowed customers, for sales employees
- List allowed groups/categories/brands
- List allowed items
- Get item stock by godown
- Submit order
- Get order history
- Get order detail
- Get profile

## Offline Behavior

Initial implementation requires internet connectivity.

The app should handle:

- No network
- Slow request
- Expired session
- Backend validation error
- Stock changed since screen loaded
- Order submission failure

Offline cart persistence can be considered later, but should not be part of the initial scope unless required.

Cart/draft storage is mobile-local only in v1. The backend creates a Frappe Order only when the user confirms the order.

Final order confirmation/submission requires internet access because the backend must validate access rules and create the Order.

## Notifications

Initial notifications are WhatsApp-based, not app push notifications.

No push notifications are required in v1. WhatsApp is used only for OTP and Order Placed confirmation/PDF; all other status visibility is in-app.

Future push notifications may be added for:

- Order status changes
- Approval completed
- Manual review resolved

WhatsApp notifications in v1 are only for Order Placed. Status changes are visible in the app, not sent through WhatsApp.

## Open Mobile Questions

- What exact fields are required during customer signup?
- Should customer signup require GST number, address, or company name?
- Price/rate/value display is out of scope for v1.
- Should sales employee order confirmation notify customer only, employee only, or both?
- Should users be able to repeat a previous order?
- Should users be able to download/view the PDF from order history?
- Should users be able to cancel a placed order before processing?
