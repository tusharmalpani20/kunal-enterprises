# Goal Completion Matrix

This matrix audits the current repository against `goal/README.md` and the three detailed goal prompts. It distinguishes build-goal evidence from optional release/operations follow-up that requires client runtime data or provider credentials.

## Scope Status

| Area | Status | Evidence |
| --- | --- | --- |
| Goal 1 Frappe foundation | Locally achieved | `docs/08-local-frappe-foundation.md`; backend smoke endpoint; backend tests; local `HTTP/1.1 200 OK` server response. |
| Goal 2 Frappe portal/backend API | Achieved for build goal | Backend app source in `apps/kunal_enterprises`; backend tests; `docs/10-backend-api.md`; `docs/11-delivery-audit.md`; optional operations checklist in `docs/12-operational-readiness-checklist.md`. |
| Goal 3 Expo mobile app | Locally achieved | Mobile app source in `apps/mobile`; `apps/mobile/README.md`; `docs/13-mobile-ui-coverage.md`; mobile tests, typecheck, audit, and Expo runtime evidence. |
| Production pilot | Optional release follow-up | `docs/16-production-pilot-signoff.md` defines evidence to collect when a pilot is run; it is not a build-goal blocker. |
| Tally/WhatsApp live proof | Excluded from current goal by instruction | `docs/12-operational-readiness-checklist.md` and `docs/15-tally-pilot-evidence-template.md` define optional operations evidence. |

## Goal 1: Install Frappe And Run

| Requirement | Current evidence | Status |
| --- | --- | --- |
| Local Frappe bench exists and can run | Working bench path `/Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench`; explicit bench executable documented in `docs/08-local-frappe-foundation.md`. | Achieved locally |
| PostgreSQL-backed Kunal site exists | `kunal.localhost`, `kunal_enterprises_frappe`, and `database_type = postgres` documented and returned by `kunal_enterprises.api.health.smoke`. | Achieved locally |
| Custom app created and installed | `apps/kunal_enterprises`; health response includes `kunal_enterprises`; backend tests run under `--app kunal_enterprises`. | Achieved locally |
| `frappe_whatsapp` installed | Health response and foundation docs list `frappe_whatsapp`; foundation docs note available upstream version metadata. | Achieved locally |
| Expected app structure exists | Backend app includes API modules, cron modules, DocTypes, fixtures, permission query hooks, document events, and tests. | Achieved locally |
| Public health/smoke function succeeds | `bench --site kunal.localhost execute kunal_enterprises.api.health.smoke` returns success with app/database/install checks. | Achieved locally |
| Minimal test suite exists and passes | Backend suite passes `Ran 86 tests` / `OK`. | Achieved locally |
| Local server responds or command is verified | `bench serve --port 8000`; `curl -I http://127.0.0.1:8000` returns `HTTP/1.1 200 OK`. | Achieved locally |
| Setup/run/test docs exist | Root README, backend README, `docs/08-local-frappe-foundation.md`, and `docs/11-delivery-audit.md`. | Achieved locally |

## Goal 2: Frappe Portal And Backend API

| Requirement | Current evidence | Status |
| --- | --- | --- |
| Required DocTypes and fixtures exist | DocTypes live under `apps/kunal_enterprises/kunal_enterprises/kunal_enterprises/doctype`; role fixtures under `fixtures/role.json`; backend tests verify required DocTypes and roles install. | Achieved locally |
| Customer lifecycle and Customer App Access | Backend tests cover signup, OTP, pending review, admin approval, Client Code checks, access removal, rejection, and mobile uniqueness. | Achieved locally |
| Sales Employee lifecycle and access | Backend tests cover active/disabled login, customer assignment rules, Product Group access, and selected Customer intersection. | Achieved locally |
| Tally master/stock/voucher sync entry points | `kunal_enterprises.cron.tally_sync` implements manual/scheduled sync entry points; backend tests cover import behavior using controlled mirror rows. | Achieved for build goal |
| Portal permissions | Backend tests cover Owner/Admin, Branch Manager, Branch Employee visibility/actions, permission query hooks, and User Permission branch checks. | Achieved locally |
| Mobile backend APIs | `docs/10-backend-api.md` documents auth, session, access, product, stock, order, profile, branch, sync, and reconciliation APIs; backend/mobile adapter tests cover the contract. | Achieved locally |
| Order creation behavior | Backend tests cover references, duplicate merge, positive quantities, over-stock/zero-stock allowance, access revalidation, immutable placed lines, and stored stock snapshots. | Achieved locally |
| PDF and WhatsApp log records | Backend tests cover PDF/WhatsApp field exclusions and Customer-only notification log records. Live provider dispatch proof is optional operations follow-up. | Achieved for build goal |
| Reconciliation | Backend tests cover partial/completed fulfillment, double-count avoidance, customer mismatch, extra item, over-fulfillment, and ambiguous duplicate Manual Review reason codes. Live Tally reference proof is optional operations follow-up. | Achieved for build goal |
| API response envelopes and HTTP status codes | `docs/10-backend-api.md`; backend tests cover `frappe.local.response["http_status_code"]`. | Achieved locally |
| Scheduled jobs and manual sync actions registered/testable | `docs/10-backend-api.md`; backend tests cover scheduler registration and Owner/Admin manual sync actions. | Achieved locally |

## Goal 3: Expo Mobile App

| Requirement | Current evidence | Status |
| --- | --- | --- |
| Expo app created and runnable | `apps/mobile`; `npx expo start --localhost --port 8081` reaches Metro and returns `HTTP/1.1 200 OK` at `127.0.0.1:8081`. | Achieved locally |
| UI-first fixture mode | Fixture adapter and tests cover deterministic Customer/Sales Employee flows without live Frappe calls. | Achieved locally |
| Frappe API integration behind client boundary | `src/api/frappeClient.mjs`; Frappe adapter tests cover backend method calls and response normalization. | Achieved locally |
| Auth/session persistence/logout/current-session refresh | Mobile tests cover OTP send/verify/resend, persisted sessions, refresh, invalid token cleanup, and revoke on logout. | Achieved locally |
| Customer flow | Tests cover signup fields, required validation, pending/access-removed states, ordering, history/detail, and editable profile fields. | Achieved locally |
| Sales Employee flow | Tests cover login, disabled state, Customer search/selection, effective access, internal note, history, detail, and read-only profile. | Achieved locally |
| Ordering/cart behavior | Tests cover merge, edit, removal, over-stock/zero-stock notes, refreshed-stock review, offline failure, and backend reference success. | Achieved locally |
| Client Code hidden from Customer/mobile display | Mobile copy/source/API tests guard Customer-facing Client Code exposure and Sales Employee search result sanitization. | Achieved locally |
| No pricing/rate/tax/value shown | Mobile copy and source tests guard monetary terms in order entry, cart, confirmation, history, and detail. | Achieved locally |
| Manual Review shown as Under Review only | Mobile tests cover status mapping and hidden internal reasons. | Achieved locally |
| Tests cover major user-visible behavior | `npm test` passes `103` tests; `npm run typecheck` passes. | Achieved locally |
| Production dependency audit clean | `npm audit --omit=dev` reports `found 0 vulnerabilities`; `postcss` override is documented and guarded. | Achieved locally |

## Local Verification Script

`scripts/verify-local.sh` reruns the repo-local backend and mobile checks:

- uses the bench at `/Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench`, whose `apps/kunal_enterprises` path points at the repo source;
- runs `kunal_enterprises.api.health.smoke`;
- runs `bench --site kunal.localhost run-tests --app kunal_enterprises`;
- runs `npm audit --omit=dev`;
- runs `npm test`;
- runs `npm run typecheck`.

## Optional Release Follow-Up

These items are not blockers for the current build goal. They remain useful when the release/operations team wants production-like client environment evidence.

| Item | Evidence to collect if needed |
| --- | --- |
| Production pilot sign-off | Complete `docs/16-production-pilot-signoff.md` with representative Customer, Sales Employee, failure-state, and final decision evidence. |
| Tally portal reference field proof | Complete `docs/15-tally-pilot-evidence-template.md` sections proving the portal Order reference reaches the connector field used by reconciliation. |
| Branch/godown mapping decisions | Close Main Location and Seetarambagh mapping decisions with operations and update Portal Branch/Godown mappings. |
| Customer ledger import filter | Confirm the production ledger filter for importable Customer aliases/Client Codes. |
| Godown-wise stock snapshot validation | Compare connector stock snapshot rows against Tally Stock Summary/Godown Summary output. |
| WhatsApp provider proof | Configure provider credentials and capture one OTP plus one Order Placed confirmation/PDF send. |

Per current instruction, Tally/WhatsApp operational proof is excluded from this goal. The build goal is complete when the repo-local backend and mobile evidence above remains green.
