# Kunal Enterprises Frappe App

Custom Frappe app for the Kunal Enterprises Tally-connected order system.

This app implements:

- Customer signup, OTP verification, admin approval, Customer App Access, and Client Code checks.
- Sales Employee OTP login, Customer assignment, and Product Group access.
- Product Group, item, godown stock, order submission, order history/detail, and profile APIs for the mobile app.
- Quantity-only Orders with `KE-YY-MM-####` references, immutable placed lines, advisory stock snapshots, branch visibility, and Owner/Admin controls.
- PDF and WhatsApp notification log records for Customer order confirmations.
- Tally master, stock snapshot, voucher sync entry points, scheduler hooks, and fulfillment reconciliation.

The mobile app must consume this Frappe API boundary only. It must not read the raw Tally PostgreSQL mirror.

## Local Bench

The working bench for this repository is:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench
```

The bench lives beside the repository. Its app path points directly at this repo source:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench/apps/kunal_enterprises -> /Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/apps/kunal_enterprises
```

Use the explicit bench executable:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench
```

## Commands

```sh
cd /Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost migrate
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost execute kunal_enterprises.api.health.smoke
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench serve --port 8000
```

## Verified Local State

- Site: `kunal.localhost`
- Frappe app database: `kunal_enterprises_frappe`
- Database type: PostgreSQL
- Installed apps: `frappe`, `kunal_enterprises`, `frappe_whatsapp`
- Backend tests: `Ran 86 tests` / `OK`
- Local server: `curl -I http://127.0.0.1:8000` returns `HTTP/1.1 200 OK`

## API Documentation

See `../../docs/10-backend-api.md` for the whitelisted API contract and `../../docs/11-delivery-audit.md` for current delivery evidence.

## Operational Gates

Tally and WhatsApp live proof gates are documented in `../../docs/12-operational-readiness-checklist.md` and `../../docs/15-tally-pilot-evidence-template.md`.

The remaining non-deferred production pilot sign-off template is `../../docs/16-production-pilot-signoff.md`.
