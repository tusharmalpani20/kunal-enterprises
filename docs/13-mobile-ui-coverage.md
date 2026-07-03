# Mobile UI Coverage

This audit maps Goal 3's required mobile screens and shared states to the current Expo app implementation.

The app uses one `expo-router` entry screen, `apps/mobile/app/index.tsx`, with state-driven workspaces instead of separate route files for each step. This keeps the v1 order flow fast and linear while still covering Customer, Sales Employee, and shared order surfaces.

## Route And Providers

| Requirement | Evidence |
| --- | --- |
| Expo / React Native app | `apps/mobile/app/_layout.tsx` and `apps/mobile/app/index.tsx` define the Expo Router app. |
| TypeScript | App entry and providers use `.tsx` / `.ts`; `npm run typecheck` runs `tsc --noEmit`. |
| Component convention | `docs/14-mobile-component-convention.md` documents why the unavailable `react-native-reusables` runtime package was replaced with local React Native primitive components, shared styles, `@react-native-reusables/cli`, and `lucide-react-native`. |
| Frappe SDK provider | `apps/mobile/src/providers/frappe.tsx` creates `FrappeApp`, exposes `db`, `auth`, `call`, and `file`, sends `Auth-Token: Bearer <accessToken>`, and logs out on invalid-token responses. |
| Auth/session provider | `apps/mobile/src/providers/auth.tsx` stores and exposes the active mobile session. |
| API boundary | `apps/mobile/src/api/mobileApi.mjs` selects the fixture adapter or live Frappe adapter; `apps/mobile/src/api/frappeClient.mjs` maps live calls to backend whitelisted methods. |
| Local cart/session storage | `apps/mobile/src/storage/mobileStorage.mjs` stores mobile sessions and cart rows by viewer/customer context. |

## Customer Screens

| Goal 3 screen | Current implementation |
| --- | --- |
| Login/signup entry | `step === 'auth'`, mode `Customer`, `Workspace title="WhatsApp OTP"` with Login/Signup selector, mobile number, OTP, Send OTP/Start signup, and Verify OTP controls. |
| Customer signup | Signup mode renders Customer name, business/legal name, GSTIN, email ID, date of birth, and date of anniversary fields; `validateCustomerSignupInput(...)` blocks missing required fields, then `requestOtp()` calls `api.startCustomerSignup(buildCustomerSignupPayload(...))` with the entered values. |
| Existing Customer OTP login | `requestOtp()` calls `api.startCustomerOtp(mobileNumber)` when Login is selected, using the shared backend OTP endpoint with `identity_type = Customer`. |
| OTP entry and resend state | `step === 'auth'` renders OTP input, uses `otpResendState` / backend cooldown values, and calls `api.resendOtp(...)` for post-cooldown resend requests only when the same mode, intent, and mobile number requested the prior OTP. |
| Pending approval/access | `step === 'pending'`, `Workspace title="Access Pending"` and `pendingAccessMessage()`. |
| Home/order entry | Customer mode loads allowed Product Groups only after the active Customer session is present, then uses the header/status strip plus Product Group workspace as the order home. |
| Product Group list | `step === 'groups'`, `Workspace title="Product Groups"`. |
| Item list/search | `step === 'items'`, selected Product Group title, search input, and filtered `visibleItems`. |
| Item stock by godown | `step === 'stock'`, selected item title, order quantity input validated by `parseOrderQuantityInput(...)`, and godown stock rows showing latest synced quantity plus sync timestamp. |
| Cart/order summary | `step === 'summary'`, cart rows, quantity edit buttons, remove controls, notes, and Confirm order. |
| Over-stock and zero-stock notes | `buildConfirmationNotes(cart, stockRows)` renders soft notes; over-stock godown rows use warning tone. |
| Order success | `step === 'success'`, `Workspace title="Order Placed"` with backend reference number. |
| Order history | `step === 'history'`, `Workspace title="Order History"`. |
| Order detail/status | `step === 'detail'`, `Workspace title="Order Detail"` with reference, display status, placed-by, and allocation rows. |
| Profile | `step === 'profile'`, Customer mode renders editable email ID, date of birth, and date of anniversary fields plus Save profile. |

## Sales Employee Screens

| Goal 3 screen | Current implementation |
| --- | --- |
| Login | `step === 'auth'`, mode `Sales Employee`, WhatsApp OTP workspace. |
| OTP entry and resend state | Same OTP workspace with Sales Employee send/resend/verify behavior, with resend scoped to the same mobile number and auth mode. |
| Customer selection/search | `step === 'customer'`, active Sales Employee session, `Workspace title="Select Customer"` with search and customer rows that omit Client Code. |
| Home/order entry in selected Customer context | `chooseCustomer()` sets selected Customer, loads effective Product Groups, and moves to `groups`; header subtitle keeps context visible. |
| Product Group list resolved for selected Customer | `api.allowedProductGroups(customer.customer, activeSalesEmployeeIdentity())` in `chooseCustomer()`. |
| Item list/search | Shared `items` workspace after Product Group selection; Sales Employee mode passes the active Sales Employee identity with the selected Customer to the item API. |
| Item stock by godown | Shared `stock` workspace after item selection; Sales Employee mode passes the active Sales Employee identity to stock reads and pre-submit stock refresh, and rows show latest synced quantity plus sync timestamp. |
| Cart/order summary with Customer details | `summary` workspace renders selected Customer details when mode is `Sales Employee`. |
| Optional internal note | `summary` workspace renders `salesNote` input in Sales Employee mode. |
| Order success | Shared `success` workspace displays backend reference; copy states WhatsApp/PDF are queued for the Customer. |
| Sales Employee order history | `showHistory()` requests `api.orderHistory(undefined, activeSalesEmployeeIdentity())` in Sales Employee mode. |
| Order detail/status | Shared `detail` workspace uses Sales Employee identity for detail calls. |
| Read-only profile | `profile` workspace does not render editable fields in Sales Employee mode and shows `editable_fields` as `None` when empty. |

## Shared States

| Goal 3 shared state | Current implementation |
| --- | --- |
| No network | Utility button sets `{ kind: 'no_network' }`; API failures are classified through `requestBanner`. |
| Slow request/loading | `submitOrder()` sets `{ kind: 'loading' }`; `requestBanner` maps loading/slow request state. |
| Expired/invalid session | Frappe provider invalid-token interceptor logs out; domain tests cover invalid stored sessions. |
| Disabled/access removed | Utility button sets `{ kind: 'access_removed' }`; session/bootstrap tests cover disabled/access-removed backend responses. |
| Pending approval | Customer OTP route can move to `pending`; pending workspace is rendered. |
| Backend validation error | `finalizeOrderSubmission` and Frappe client error unwrapping feed recoverable banner states. |
| Stock changed since screen loaded | `prepareStockReviewBeforeSubmit` refreshes stock and returns review state when notes change. |
| Order submission failure | Offline/backend failures return recoverable state and do not show a fake reference. |

## Verification

- `npm test` covers the user-visible behavior for Customer, Sales Employee, cart, profile, history/detail, shared states, source safety, and documentation guards.
- `npm run typecheck` verifies the Expo TypeScript surface.
- `npx expo start --localhost --port 8081` reached Metro startup locally and returned `HTTP/1.1 200 OK` from `http://127.0.0.1:8081`.
