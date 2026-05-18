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

## Customer Access States

Recommended customer states:

- Signup Started
- OTP Pending
- OTP Verified
- Pending Admin Approval
- Approved
- Rejected
- Disabled

The app should show a simple pending access screen if OTP is verified but admin approval is not complete.

## Sales Employee Login Flow

Sales employees are created from the portal.

Sales employee login flow:

1. Sales employee enters mobile number.
2. System checks that the number belongs to an active sales employee.
3. System sends WhatsApp OTP.
4. Sales employee verifies OTP.
5. App opens sales employee flow.

Sales employees should not self-register.

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

- Use Tally Stock Group as the first-level selector.
- Label it as "Brand" in the UI only if the business treats stock groups as brands.
- Revisit this after reviewing real Tally master data.

Alternative:

- Use Stock Category if category better represents the buying experience.
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
13. App shows order summary with customer details.
14. Sales employee confirms order.
15. Backend creates order and reference number.
16. App shows success screen with reference number.
17. Backend sends WhatsApp confirmation to the customer, and optionally to the sales employee.

## Stock Display

The app shows latest synced stock from Frappe.

Real-time calls to Tally are not required initially.

The stock screen should show:

- Item name
- Unit
- Godown name
- Available quantity from latest sync
- Last synced time, if useful

The app must make it clear enough that stock is indicative/latest synced, not a hard reservation.

## Cart Behavior

The cart/order draft should support:

- Multiple items
- Multiple godown allocations per item
- Quantity editing
- Removing item
- Removing godown allocation
- Order summary before confirmation

The backend should validate all items, godowns, quantities, and access rules again during final order submission. The app should not be trusted as the authority.

## Access Rules In App

The backend should return only allowed data to the app.

The app should not download all items and hide restricted ones locally.

Access rules:

```text
No filter configured = all visible
Filter configured = only configured values visible
```

For customers, filters apply to item visibility.

For sales employees, filters apply to:

- Item visibility
- Customer visibility

If both employee and customer filters are relevant during sales employee ordering, the backend should define the final allowed set. Recommended behavior is intersection of applicable filters.

## Order History

Customer order history shows:

- Orders placed by the customer
- Status
- Reference number
- Date
- Summary quantities
- Detail screen with items/godowns/status

Sales employee order history shows:

- Orders placed by that sales employee
- Customer name
- Status
- Reference number
- Date
- Detail screen with items/godowns/status

## Profile

Customer profile should show:

- Name
- Mobile number
- Company/business name, if applicable
- Address, if captured
- Approval/access status
- Linked Tally ledger, if exposed

Sales employee profile should show:

- Name
- Mobile number
- Employee code, if any
- Active status

## Order Status Display

The app should display simple status labels:

- Placed
- Processing
- Partially Processed
- Completed
- Cancelled
- Under Review, if backend status is Manual Review

The app does not need to explain reconciliation internals.

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

Initial implementation can require internet connectivity.

The app should handle:

- No network
- Slow request
- Expired session
- Backend validation error
- Stock changed since screen loaded
- Order submission failure

Offline cart persistence can be considered later, but should not be part of the initial scope unless required.

## Notifications

Initial notifications are WhatsApp-based, not app push notifications.

Future push notifications may be added for:

- Order status changes
- Approval completed
- Manual review resolved

## Open Mobile Questions

- What exact fields are required during customer signup?
- Should customer signup require GST number, address, or company name?
- Should the app show prices or only stock and quantity?
- Should sales employee order confirmation notify customer only, employee only, or both?
- Should users be able to repeat a previous order?
- Should users be able to download/view the PDF from order history?
- Should users be able to cancel a placed order before processing?
