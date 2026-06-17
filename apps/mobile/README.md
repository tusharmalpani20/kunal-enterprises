# Kunal Enterprises Mobile

Expo / React Native mobile app for Customers and Sales Employees placing quantity-only order requests through the Frappe backend.

Visual thesis: a quiet field-operations workspace with warm paper surfaces, black utility typography, and a single green action accent for order confidence.

Interaction thesis:

- Screen changes should feel like moving through an order pad: fast, vertical, and task-focused.
- Stock warnings are soft operational notes, never blocking alerts.
- Sales Employee context stays visible so the selected Customer is never ambiguous.

Current scope:

- TypeScript Expo scaffold.
- Frappe provider shell using `frappe-js-sdk`.
- Typed Frappe API client adapter for the implemented backend methods.
- Runtime API selection: live Frappe adapter when `call` is available, fixture adapter while UI-first flows are unauthenticated.
- Mock API adapter for UI-first work.
- AsyncStorage-backed mobile session and local cart storage by Customer or Sales Employee + selected Customer context.
- Customer and Sales Employee WhatsApp OTP flows with resend cooldown state.
- Customer signup without Client Code exposure.
- Customer pending-access state.
- Customer and Sales Employee order flows backed by deterministic fixtures or live Frappe APIs.
- Product Group first selection, item search, godown stock sorted positive-first then zero-stock.
- Quantity-only local cart with merge, edit, allocation removal, and item removal.
- Soft over-stock, zero-stock, and latest-stock-changed confirmation notes.
- Order submission with recoverable pre-submit stock refresh, review gate for newly discovered stock notes, recoverable no-network/backend-failure banner state, success reference display.
- Order history and order detail with Manual Review shown as Under Review.
- Customer profile view/update for email ID, date of birth, and date of anniversary only.
- Sales Employee read-only profile.
- Session persistence, session-derived API identity routing, current-session refresh helpers, and logout/revoke support.

The mobile app never reads Tally or the Tally PostgreSQL mirror. It uses the Frappe API boundary only.

Run:

```sh
cd apps/mobile
bun install
bun run start
```

Run against a local Frappe site:

```sh
cd apps/mobile
EXPO_PUBLIC_FRAPPE_BASE_URL=http://127.0.0.1:8000 bun run start
```

`EXPO_PUBLIC_FRAPPE_BASE_URL` defaults to `http://127.0.0.1:8000` in `src/constants/config.ts`, which works from iOS Simulator against a bench server running on the Mac.
Use `.env.example` as the checked-in starting point for local mobile configuration.

Test:

```sh
cd apps/mobile
bun test
bun run typecheck
```

The local behavior suite is pure Node and does not require Expo dependencies to be installed.
`bun run typecheck` requires `bun install` first because it uses the Expo TypeScript configuration and installed React Native/Frappe SDK types.

Fixture mode:

- Used when the Frappe provider has no live `call` object.
- Provides deterministic Customer and Sales Employee OTP responses.
- Provides fixture Product Groups, items, stock, customers, orders, Sales Employee history across Customers, order detail, profile, current-session, revoke, and profile-update behavior.
- Keeps Client Code searchable for Sales Employee fixtures but never returns it to mobile screens.

Live Frappe mode:

- Used automatically when `FrappeProvider` creates a `frappe-js-sdk` call object from a stored access token.
- Sends the custom mobile auth header as `Auth-Token: Bearer <accessToken>`.
- Maps backend whitelisted methods through `src/api/frappeClient.mjs`.
- Sanitizes Sales Employee allowed-customer responses so Client Code never reaches mobile screen state, even if a backend response includes it.
- Normalizes backend response envelopes and throws backend validation messages for UI banner classification.

Backend method coverage:

- `kunal_enterprises.api.otp.start_customer_signup`
- `kunal_enterprises.api.otp.send_otp`
- `kunal_enterprises.api.otp.resend_otp`
- `kunal_enterprises.api.otp.verify_customer_otp`
- `kunal_enterprises.api.otp.verify_sales_employee_otp`
- `kunal_enterprises.api.token_verification.current_session`
- `kunal_enterprises.api.token_verification.revoke_token`
- `kunal_enterprises.api.customer_access.status`
- `kunal_enterprises.api.sales_employees.allowed_customers`
- `kunal_enterprises.api.product_groups.allowed`
- `kunal_enterprises.api.product_groups.items`
- `kunal_enterprises.api.product_groups.item_stock`
- `kunal_enterprises.api.orders.submit`
- `kunal_enterprises.api.orders.history`
- `kunal_enterprises.api.orders.detail`
- `kunal_enterprises.api.profile.get_profile`
- `kunal_enterprises.api.profile.update_customer_profile`

Verification status:

- `bun test` currently covers mobile auth/access, API adapter behavior, order/cart behavior, Sales Employee customer context and history, profile/history/detail presentation, session storage/bootstrap/logout, local cart persistence, shared request states, fixture/live API selection, source-level React Native style type-safety checks, and a source guard that blocks raw Tally PostgreSQL mirror access from the mobile app.
- `bun run typecheck` passes after dependency install.
- `npx expo start --localhost --port 8081` reached Metro startup locally at `exp://127.0.0.1:8081`; `curl -I http://127.0.0.1:8081` returned `HTTP/1.1 200 OK`.
- Expo SDK 54 dependencies are locked with `bun.lock`; `postcss` is overridden to `8.5.10` to keep the patched transitive version.
