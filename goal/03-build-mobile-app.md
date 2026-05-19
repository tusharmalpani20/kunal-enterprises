# /goal Prompt: Build Mobile App

Use this as the third independent `/goal` prompt after Goal 2 has at least a stable API contract. Start with UI first, then connect to the Frappe backend and finish the full mobile app.

## Prompt

You are working in `/Users/amol909/development/kunal-enterprise/kunal-enterprises`.

Goal: set up and build the complete Expo / React Native mobile app for the Kunal Enterprise order system. Build the UI first with realistic mocked API data and deterministic test fixtures, then connect the app to the Frappe backend APIs from Goal 2. The finished app must support both Customers and Sales Employees placing quantity-only order requests through Frappe APIs.

The mobile app must never connect directly to Tally or the raw Tally PostgreSQL mirror.

## Source Context To Read First

- `CONTEXT.md`
- `docs/01-overall-problem-statement.md`
- `docs/03-mobile-app.md`
- `docs/02-portal.md`
- `docs/04-tally-connector.md`
- `docs/06-grill-session-log.md`
- all files in `docs/adr/`
- `/Users/amol909/.agents/skills/tdd/SKILL.md`

Use the same business terms as the docs: Product Group, Customer, Customer Business, Client Code, Customer App Access, Sales Employee, Order, Order Quantity, Partial Closure, Fulfillment Signal, Manual Review Reason, Item Access.

## Non-Negotiable Product Decisions

- Build with Expo / React Native.
- Use `react-native-reusables` for components unless the existing app setup proves a better local convention.
- Use the official Frappe JavaScript SDK package from `frappe/frappe-js-sdk`, installed as `frappe-js-sdk`, as the baseline Frappe client.
- UI first, then backend integration.
- The app communicates only with Frappe APIs.
- Customers and Sales Employees use WhatsApp OTP login.
- Customer signup captures name, business/legal name, GSTIN, mobile number, email ID, date of birth, and date of anniversary.
- Customers do not enter or see Client Code.
- Customer ordering access is blocked until backend marks them Active with valid Customer App Access.
- Sales Employees cannot self-register.
- Sales Employees select a Customer before ordering.
- Sales Employee customer search can search by Client Code, customer name, and business/legal name, but Client Code must not be displayed.
- First item selector is Product Group.
- Latest synced stock is advisory.
- Users can order more than latest synced stock and from zero-stock godowns.
- No prices, rates, discounts, tax, or order value are shown anywhere.
- Customer order flow has no note.
- Sales Employee order flow has optional internal note.
- Sales Employee note is never shown to the Customer.
- Confirmed Orders cannot be edited or cancelled in the mobile app.
- Manual Review appears as `Under Review` in the app, with no internal reason shown.
- WhatsApp notifications in v1 are only OTP and Order Placed confirmation/PDF. No push notifications in v1.
- Mobile cart/draft is local only in v1. Backend creates an Order only on final confirmation.
- Internet is required for final order submission.

## TDD Rules For This Goal

Follow `/Users/amol909/.agents/skills/tdd/SKILL.md`.

- Use vertical tracer bullets: one failing UI/API behavior test, minimal implementation, pass, then continue.
- Tests should verify behavior through user-visible screens, navigation, state transitions, API client public methods, and backend contract behavior.
- Do not test private component internals.
- Do not write all tests first.
- During UI-first work, use deterministic fixtures and a public fake API adapter boundary.
- When connecting to Frappe, keep the same public app behavior tests and replace mocked adapters with real API integration tests where practical.
- Mock true external boundaries only: network, device storage, and OTP provider behavior. Do not mock application logic being tested.

## Expected Work

### 1. Project Setup

Set up an Expo app in the repository with:

- TypeScript.
- Navigation suitable for auth, customer flow, sales employee flow, and shared order screens.
- `react-native-reusables` component setup.
- `frappe-js-sdk` as the baseline Frappe backend client.
- A typed Frappe provider/context that exposes `FrappeDB`, `FrappeAuth`, `FrappeCall`, and `FrappeFileUpload`.
- API client layer for Frappe backend, built on top of the Frappe provider instead of ad hoc fetch calls except where a custom endpoint requires it.
- Token/session storage.
- Local cart storage.
- Test tooling for component and behavior tests.
- Environment configuration for backend base URL.

### Baseline Frappe Provider

Use this provider shape as the starting point for the mobile app's Frappe integration. Adjust paths, error presentation, and auth context names to match the actual app structure, but preserve the SDK usage, typed context, `Auth-Token` bearer header, and invalid-token logout behavior.

```tsx
import { useRouter } from 'expo-router';
import { FrappeApp, FrappeAuth, FrappeCall, FrappeDB, FrappeFileUpload } from 'frappe-js-sdk';
import React, { createContext, useContext, useEffect, useState } from 'react';
import { AuthContext } from './auth';
import { APP_CONFIG } from '../constants/config';

interface FrappeContextType {
  db: FrappeDB | null;
  auth: FrappeAuth | null;
  call: FrappeCall | null;
  file: FrappeFileUpload | null;
}

const FrappeContext = createContext<FrappeContextType>({
  db: null,
  auth: null,
  call: null,
  file: null,
});

const FrappeProvider = ({ children }: { children: React.ReactNode }) => {
  const { accessToken, logout } = useContext(AuthContext);
  const router = useRouter();
  const [db, setDb] = useState<FrappeDB | null>(null);
  const [call, setCall] = useState<FrappeCall | null>(null);
  const [auth, setAuth] = useState<FrappeAuth | null>(null);
  const [file, setFile] = useState<FrappeFileUpload | null>(null);

  useEffect(() => {
    if (!accessToken) {
      return;
    }

    const frappe = new FrappeApp(
      APP_CONFIG.BASE_URL,
      {
        useToken: false,
        type: 'Bearer',
      },
      undefined,
      {
        'Auth-Token': `Bearer ${accessToken}`,
      }
    );

    frappe.axios.interceptors.response.use(
      (response) => response,
      (error) => {
        const message =
          error.response?.data?.message?.message ||
          error.response?.data?.message ||
          error.message ||
          'An error occurred';

        if (
          message === 'Invalid or inactive token' ||
          message === 'App Update Required' ||
          message === 'Error verifying token'
        ) {
          logout().then(() => {
            router.replace('/login');
          });
        }

        return Promise.reject(error);
      }
    );

    setDb(frappe.db());
    setCall(frappe.call());
    setAuth(frappe.auth());
    setFile(frappe.file());
  }, [accessToken, logout, router]);

  return (
    <FrappeContext.Provider value={{ db, auth, call, file }}>
      {children}
    </FrappeContext.Provider>
  );
};

export const useFrappe = (): FrappeContextType => {
  return useContext(FrappeContext);
};

export { FrappeContext, FrappeProvider };
```

### 2. UI-First Mocked App

Build the complete UI using mocked API fixtures before wiring live Frappe calls.

Customer screens:

- Login/signup entry.
- Customer signup.
- OTP entry and resend state.
- Pending approval/access screen.
- Home/order entry.
- Product Group list.
- Item list/search.
- Item stock by godown.
- Cart/order summary.
- Over-stock and zero-stock soft availability notes at confirmation.
- Order success with reference number.
- Order history.
- Order detail/status.
- Profile with editable email ID, date of birth, and date of anniversary only.

Sales Employee screens:

- Login.
- OTP entry and resend state.
- Customer selection/search.
- Home/order entry in selected Customer context.
- Product Group list resolved for selected Customer.
- Item list/search.
- Item stock by godown.
- Cart/order summary with Customer details.
- Optional internal note.
- Order success with reference number.
- Sales employee order history showing only orders placed by that employee.
- Order detail/status.
- Read-only profile.

Shared states:

- No network.
- Slow request/loading.
- Expired/invalid session.
- Disabled/access removed.
- Pending approval.
- Backend validation error.
- Stock changed since screen loaded.
- Order submission failure.

### 3. Auth And Session

Implement:

- Send OTP.
- Resend OTP after backend-defined cooldown.
- Verify OTP.
- Persist JWT/session.
- Stay logged in until logout, backend disables/removes access, or token is rejected.
- Multi-device assumptions are backend-owned; app should not block them.
- Logout/revoke token.
- Current session refresh on app start.

### 4. Customer Flow

Implement:

- Signup with required fields.
- OTP verification.
- Pending access state when OTP is verified but admin approval or Client Code access is incomplete.
- Customer ordering only when backend says Active/access allowed.
- Product Group, item, godown stock, cart, confirmation, submit order.
- Order history includes self-placed and sales-employee-placed orders for the Customer.
- Order detail shows placed-by as `You` or Sales Employee name.
- Customer profile hides Client Code.
- Customer profile updates only editable fields.

### 5. Sales Employee Flow

Implement:

- Login by mobile number and OTP.
- Block disabled state based on backend response.
- Customer search and selection.
- Search can match Client Code, but Client Code is not displayed.
- Product Group and items are loaded after Customer selection and reflect backend-computed effective access.
- Order placement on behalf of selected Customer.
- Optional internal note.
- Success screen only; no WhatsApp confirmation expected for Sales Employee.
- Order history shows only orders placed by that Sales Employee.
- Sales Employee profile is read-only.

### 6. Ordering And Cart

Implement:

- Multiple items.
- Multiple godown allocations per item.
- Quantity editing.
- Remove item.
- Remove godown allocation.
- Merge duplicate item+godown rows by summing quantity.
- Show all active godowns for selected item, positive-stock first, then zero-stock.
- Allow quantity greater than latest synced stock.
- Allow quantity from zero-stock godown.
- Highlight over-stock rows as a soft availability note at confirmation.
- Do not show prices or monetary totals.
- Final submit requires internet and backend validation.
- Confirmed orders cannot be edited or cancelled.

### 7. Frappe API Integration

Wire the app to Goal 2 APIs:

- Start customer signup.
- Send/resend/verify OTP.
- Current user/session.
- Approval/access status.
- Allowed customers for Sales Employee.
- Allowed Product Groups.
- Allowed items.
- Item stock by godown.
- Submit order.
- Order history.
- Order detail.
- Profile get/update.
- Logout/revoke token.

The app should treat backend validation as authoritative and show clear user-facing errors without exposing internal stack traces or Manual Review reasons.

## Required Outcomes

The goal is complete only when:

- Expo app is created and runnable locally.
- UI-first mocked app covers the full Customer and Sales Employee experience.
- Frappe API integration is complete behind a clean API client boundary.
- Auth, session persistence, local cart, order submission, history, detail, and profile flows work.
- The app never displays Client Code customer-facing.
- The app never displays pricing/rate/tax/value.
- Manual Review is shown as Under Review only.
- Disabled/access-removed states are enforced from backend responses.
- Tests cover the major user-visible behavior.

## Acceptance Tests

Write tests incrementally and run them. The suite must cover at least:

- Customer signup validates required fields and submits the expected payload without Client Code.
- OTP verify for a pending Customer routes to pending approval/access screen.
- Active Customer session routes to order home.
- Disabled/access-removed Customer is blocked after backend session check.
- Sales Employee cannot access ordering before selecting a Customer.
- Sales Employee customer search displays name/business name and hides Client Code while still supporting Client Code search matches.
- Product Group list renders backend-allowed Product Groups only.
- Item list renders backend-allowed items only.
- Godown stock list shows positive stock first and zero stock after.
- Cart merges duplicate item+godown rows.
- Cart allows quantity greater than latest synced stock.
- Cart allows quantity from zero-stock godown.
- Confirmation screen shows soft availability note for over-stock rows.
- Customer order submit sends no note.
- Sales Employee order submit sends internal note when entered.
- Order success shows backend reference number.
- Customer history includes both self-placed and sales-employee-placed orders.
- Sales Employee history includes only orders placed by that Sales Employee.
- Customer order detail shows placed-by but not Sales Employee note.
- Manual Review backend status displays as Under Review and hides reason.
- Customer profile hides Client Code and permits only email/date of birth/date of anniversary edits.
- Sales Employee profile is read-only.
- No price/rate/tax/value text appears in order entry, cart, confirmation, history, or detail screens.
- Offline/no-network final submission shows recoverable error and does not create a fake confirmed order.

## Deliverable

Leave the repo with:

- Runnable Expo mobile app.
- Mock fixture mode for UI development.
- Frappe-connected mode for real backend use.
- Passing tests.
- App run/test documentation.
- API environment documentation.
- Final summary with commands run, local app URL or Expo launch instructions, tests run, and any API contract gaps found while integrating.
