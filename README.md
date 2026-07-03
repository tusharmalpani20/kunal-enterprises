# Kunal Enterprises

Kunal Enterprises is a Tally-connected order system built from the prompts in `goal/README.md`.

The repository contains two runnable apps:

- `apps/kunal_enterprises`: custom Frappe backend, portal DocTypes, mobile APIs, scheduled Tally sync entry points, order workflow, PDF/WhatsApp logs, and reconciliation logic.
- `apps/mobile`: Expo / React Native app for Customers and Sales Employees placing quantity-only order requests through the Frappe APIs.

The mobile app never reads Tally or the raw Tally PostgreSQL mirror. Tally-derived data is imported into Frappe DocTypes and exposed through backend APIs.

## Backend

The local Frappe bench now lives beside the repo at `/Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench`.
The bench app path `ke-frappe-bench/apps/kunal_enterprises` is a symlink to this repo's `apps/kunal_enterprises`, so backend commands run against the code in this repository without a copy step.

Use the explicit bench executable because `/opt/homebrew/bin/bench` is an unrelated binary on this machine.

```sh
cd /Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost execute kunal_enterprises.api.health.smoke
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench serve --port 8000
```

Verified local backend evidence is recorded in `docs/08-local-frappe-foundation.md` and `docs/11-delivery-audit.md`.

## Mobile

```sh
cd apps/mobile
npm install
npm test
npm run typecheck
npx expo start --localhost --port 8081
```

For live backend mode, point the app at the Frappe site:

```sh
cd apps/mobile
EXPO_PUBLIC_FRAPPE_BASE_URL=http://127.0.0.1:8000 npx expo start --localhost --port 8081
```

`apps/mobile/.env.example` provides the local Frappe base URL starter value. `apps/mobile/README.md` documents fixture mode, live Frappe mode, and the backend methods used by the mobile API client.

## Current Verification

Run the local verification suite:

```sh
./scripts/verify-local.sh
```

- Backend tests: `bench --site kunal.localhost run-tests --app kunal_enterprises` passes `Ran 86 tests` / `OK`.
- Backend smoke: `kunal_enterprises.api.health.smoke` confirms PostgreSQL and installed `frappe`, `kunal_enterprises`, and `frappe_whatsapp`.
- Backend server: `curl -I http://127.0.0.1:8000` returns `HTTP/1.1 200 OK`.
- Mobile tests: `npm test` passes `103` tests.
- Mobile typecheck: `npm run typecheck` passes.
- Mobile runtime: `npx expo start --localhost --port 8081` reaches `Metro waiting on exp://127.0.0.1:8081`; `curl -I http://127.0.0.1:8081` returns `HTTP/1.1 200 OK`.
- Mobile dependency audit: `npm audit --omit=dev` reports `found 0 vulnerabilities`.

## Handoff Documents

- `docs/10-backend-api.md`: backend API request/response contract.
- `docs/11-delivery-audit.md`: current delivery evidence and unresolved operational gates.
- `docs/12-operational-readiness-checklist.md`: optional external Tally and WhatsApp proof checklist for production operations.
- `docs/13-mobile-ui-coverage.md`: Goal 3 screen/state coverage.
- `docs/15-tally-pilot-evidence-template.md`: optional Tally/WhatsApp pilot evidence capture.
- `docs/16-production-pilot-signoff.md`: optional production pilot sign-off capture.
- `docs/17-goal-completion-matrix.md`: requirement-by-requirement goal audit.

## Remaining Gates

The repo-local backend and mobile build evidence is current. Per current scope, external Tally/WhatsApp operational proof and production pilot sign-off are not blockers for the build goal; they remain optional release/operations follow-up artifacts.
