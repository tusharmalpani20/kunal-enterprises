# Delivery Audit

This audit captures the current handoff evidence for the Kunal Enterprises Frappe backend and Expo mobile app built from the `/goal` prompts. `docs/17-goal-completion-matrix.md` maps the goal requirements to current evidence and release follow-up items.

## Backend Deliverables

| Requirement | Evidence |
| --- | --- |
| Complete portal/backend implementation | Custom Frappe app source lives at `apps/kunal_enterprises` and is symlinked into the local bench. It includes API modules, cron jobs, DocTypes, document lifecycle validation, Order permission query hooks, permission-visible branch order APIs, order control APIs, PDF/WhatsApp log records, Tally sync entrypoints, voucher reconciliation, and mobile token verification. |
| Local Frappe runtime | `docs/08-local-frappe-foundation.md` records the bench path, site config, installed apps, run command, and a 2026-05-19 local `curl -I http://127.0.0.1:8000` verification returning `HTTP/1.1 200 OK`. |
| Passing test suite | Latest backend verification ran with `bench --site kunal.localhost run-tests --app kunal_enterprises` and passed `Ran 86 tests` / `OK`. |
| API documentation | `docs/10-backend-api.md` documents response envelopes, status codes, guest-whitelisted mobile token endpoints, auth headers, health, OTP/session, Customer App Access, Sales Employee customers, Product Groups, stock, orders, profile, branch orders, order controls, sync APIs, scheduler entry points, and reconciliation behavior. Backend tests also verify the response utilities set `frappe.local.response["http_status_code"]` to match the returned envelope. |
| Fixture and migration documentation | `docs/08-local-frappe-foundation.md` documents the bench/site paths, explicit bench executable, app mirror, PostgreSQL site, migration command, and verified install checks. Role fixtures live in `apps/kunal_enterprises/kunal_enterprises/fixtures/role.json`; DocTypes are migration artifacts under `apps/kunal_enterprises/kunal_enterprises/kunal_enterprises/doctype`. `docs/09-foundation-tdd-log.md` records the cycles where fixtures, DocTypes, migrations, and required DocType install evidence were added. |
| Scheduler and manual job documentation | `docs/10-backend-api.md` documents Owner/Admin manual sync APIs for masters, stock, vouchers, and reconciliation. It also lists the five-minute scheduler jobs: master sync, stock sync, voucher sync, and reconciliation. |

## Mobile Deliverables

| Requirement | Evidence |
| --- | --- |
| Runnable Expo mobile app | Expo app source is in `apps/mobile` with `expo-router`, TypeScript, `frappe-js-sdk`, session storage, fixture/live API adapter selection, Customer and Sales Employee flows, local cart, order submission, history/detail, profile, and shared recoverable states. |
| UI screen coverage | `docs/13-mobile-ui-coverage.md` maps Goal 3's required Customer screens, Sales Employee screens, and shared states to the current Expo implementation in `apps/mobile/app/index.tsx` and supporting providers/domain modules. |
| Mobile component convention | `docs/14-mobile-component-convention.md` documents the `react-native-reusables` runtime package exception, installed `@react-native-reusables/cli`, and the local React Native primitive/lucide component convention used by the app. |
| Expo launch instructions | `apps/mobile/README.md` documents `npm install`, `npm run start`, and the local Frappe launch command using `EXPO_PUBLIC_FRAPPE_BASE_URL=http://127.0.0.1:8000`. |
| Mobile test results | Latest mobile verification ran with `npm test` in `apps/mobile` and passed `103` tests. |
| Backend environment configuration | `apps/mobile/.env.example` provides `EXPO_PUBLIC_FRAPPE_BASE_URL=http://127.0.0.1:8000`; `apps/mobile/README.md` documents the variable, its default in `src/constants/config.ts`, live Frappe mode, and the `Auth-Token: Bearer <accessToken>` header sent by the Frappe SDK adapter. |
| remaining operational setup assumptions | The mobile app assumes a reachable Frappe backend, installed backend DocTypes, active scheduler or manual sync runs, configured WhatsApp provider credentials, and Customer App Access administered in Frappe before Customer ordering is enabled. |

## Implemented Behavior Summary

- Customer signup captures and validates name, business/legal name, GSTIN, mobile number, email ID, date of birth, and date of anniversary without exposing Client Code.
- Customer App Access requires mobile verification, admin approval, active account state, and a unique Client Code mapped to an imported Tally Customer Ledger alias.
- Sales Employees are admin-created, OTP-authenticated, Customer-scoped, and Product Group scoped.
- Product Group, item, and godown stock APIs return only allowed data, including Sales Employee plus selected Customer effective access; latest stock is advisory, shows sync timestamp, and can be exceeded.
- Orders are quantity-only, validate positive order quantity before cart insertion, are immutable after placement for mobile users, and receive `KE-YY-MM-####` references.
- Owner/Admin order controls can cancel, partially close, and resolve Manual Review; branch roles have narrower processing visibility/actions.
- Order placement creates PDF and WhatsApp notification log records for the Customer-only confirmation.
- Tally masters, stock snapshots, vouchers, and reconciliation run through manual APIs and scheduled entrypoints.
- Reconciliation matches by portal reference, validates Customer Client Code, applies fulfillment item-wise, prefers Sales Invoice over mirrored Delivery Challan, and sends ambiguous or invalid cases to Manual Review.
- The mobile app supports Customer signup OTP, existing Customer OTP login, Sales Employee OTP login, backend OTP resend after cooldown scoped to the same auth identity, protected API loading only after an active mode-specific session, SDK handle cleanup on logout/session removal, pending/disabled/access-removed states, local cart, soft stock warnings, submit review after stock refresh, order success, history/detail, and profile behavior.

## Commands Verified

Backend:

```sh
./scripts/verify-local.sh

/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost migrate
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Mobile:

```sh
cd apps/mobile
npm install
npm test
npm run typecheck
npx expo start --localhost --port 8081
```

## Tests Run

- Backend: `bench --site kunal.localhost run-tests --app kunal_enterprises`, latest verified result on 2026-05-19 `Ran 86 tests` / `OK`.
- Mobile: `npm test`, latest known result `103` passed.
- Mobile typecheck: `npm run typecheck`, latest known result `tsc --noEmit` passed.
- Mobile startup: `npx expo start --localhost --port 8081`, latest known result reached Metro `Metro waiting on exp://127.0.0.1:8081` and returned `HTTP/1.1 200 OK` from `http://127.0.0.1:8081`.
- Mobile dependency audit: `npm audit --omit=dev`, latest known result `found 0 vulnerabilities` after overriding `postcss` to `8.5.10` under Expo SDK 53.

## Acceptance Coverage

| Goal prompt | Coverage evidence |
| --- | --- |
| `01-install-frappe-and-run.md` | `TestFoundation.test_smoke_reports_postgres_and_required_apps` proves app import, PostgreSQL database reachability, custom app install, `frappe_whatsapp` install, and installed app visibility. `test_required_portal_roles_are_installed` and `test_required_goal_doctypes_are_installed` verify install-visible fixtures and migrations. `docs/08-local-frappe-foundation.md` documents bench path, site name, app name, commands, installed apps, and the reverified local `HTTP/1.1 200 OK` server response. |
| `02-build-frappe-portal-and-backend-api.md` | Backend tests cover Customer signup/OTP/access, Client Code validation/removal, global mobile uniqueness, Sales Employee lifecycle, Product Group and customer visibility intersections, quantity-only order creation, monthly reference generation, duplicate allocation merge, advisory stock behavior, immutable placed lines, PDF/WhatsApp field exclusions, branch role visibility/actions, branch APIs checked against current session role and `Portal Branch` `User Permission` instead of claimed request parameters, mobile token APIs registered as guest-whitelisted Frappe methods so custom `Auth-Token` verification can run without Desk login, Desk Order permission query hooks using Portal Branch `User Permission`, Owner/Admin manual review controls, Owner/Admin sync actions checked against the current session role instead of a claimed request parameter, Tally master/stock/voucher sync, scheduler registration, and reconciliation outcomes including partial, completed, double-count avoidance, customer mismatch, extra item, over-fulfillment, and ambiguous duplicate Manual Review reason codes. |
| `03-build-mobile-app.md` | Mobile tests cover signup payloads without Client Code, Customer signup form fields without fixture defaults, Customer signup required-field validation, existing Customer OTP login through the shared OTP endpoint, backend OTP resend after cooldown scoped to the same auth identity, protected API gating until the active mode has a valid session, OTP/access routing, session persistence/refresh/revoke, Frappe SDK handle cleanup without access token, app-start stored-session validation through the Frappe SDK, disabled/access-removed states, Sales Employee customer selection/search without displaying Client Code, Product Group/item/stock filtering through the selected Customer plus Sales Employee API context, godown stock ordering and sync timestamp display, local cart persistence and duplicate merge, invalid order quantity validation before cart insertion, over-stock/zero-stock and refreshed-stock notes, customer and sales employee submit payloads, offline/validation failures, history/detail/profile safety, Manual Review displayed as Under Review, no pricing copy, and a source guard that blocks raw Tally mirror access from mobile code. |

## Release Follow-Up

`docs/12-operational-readiness-checklist.md` defines optional operations evidence and the system action to take after each confirmation. `docs/15-tally-pilot-evidence-template.md` provides the controlled-pilot capture form and SQL checks for collecting Tally/WhatsApp evidence. `docs/16-production-pilot-signoff.md` provides an optional production pilot sign-off template for the verified Frappe backend and mobile app.

Per current scope, Tally/WhatsApp operational proof and production pilot sign-off are not blockers for the build goal. They remain useful release/operations follow-up items.

- Tally reference field proof: demo data showed only sparse Delivery Challan `reference_number` population. The client still needs to prove which Tally field operators will enter the portal Order reference into for every related Delivery Challan and Sales Invoice.
- Main Location mapping: `Main Location` exists in Tally godown data, but its branch meaning is not confirmed. It must be mapped to a Portal Branch or explicitly excluded by operations.
- Seetarambagh mapping: demo vouchers include `Sales Seetarambagh` and `Delivery Challan Seetarambagh`, while the discovered godown list did not clearly expose a Seetarambagh godown. The client must confirm whether this is a branch, voucher naming convention, missing godown, or mapping to another godown.
- exact customer ledger filter: customer ledgers appear to roll up under `Sundary Debtors` in discovery, but the exact production filter for importable Customer aliases/Client Codes must be confirmed against the client Tally company.
- godown-wise stock snapshot validation: stock by godown must be validated against Tally-computed Stock Summary/Godown Summary output before production use.
- WhatsApp provider credentials: live OTP and Order Placed confirmation/PDF dispatch requires configured provider credentials and one controlled send test.
- Production pilot sign-off: run the verified backend and mobile app with representative real users/data and capture acceptance for Customer signup/login, Sales Employee login, Customer selection, Product Group/item/stock visibility, cart/order submission, order history/detail, and profile flows.
