# Kunal Enterprises Frappe App

Custom Frappe app for the Kunal Enterprises Tally-connected order system.

This app implements:

- Customer signup, OTP verification, admin approval, Customer App Access, and Client Code checks.
- Sales Employee OTP login, Customer assignment, and Product Group access.
- Product Group, item, godown stock, order submission, order history/detail, and profile APIs for the mobile app.
- Quantity-only Orders with `KE-YY-MM-####` references, immutable placed lines, advisory stock snapshots, branch visibility, and Owner/Admin controls.
- PDF and WhatsApp notification log records for Customer order confirmations.
- Tally master, stock snapshot, voucher sync entry points, scheduler hooks, and fulfillment reconciliation.
- Guarded Tally-ledger Customer auto-onboarding for Sales Employee ordering without requiring customer mobile numbers.

The mobile app must consume this Frappe API boundary only. It must not read the raw Tally PostgreSQL mirror.

## Tally Customer Auto-Onboarding

Before enabling it, an Owner or Admin can call `kunal_enterprises.api.sync_admin.preview_tally_customer_onboarding` to review the non-mutating preview, including counts grouped by unclassified Tally parent. This installation contains accounting ledgers alongside customer ledgers, and the source does not provide a dependable customer-type flag, so auto-onboarding also requires an explicit ancestor-group allowlist. A ledger is eligible when its immediate parent or any ancestor matches a configured group. Configure only the reviewed Tally parent groups:

```json
{
  "enable_tally_customer_auto_onboarding": 1,
  "tally_customer_parent_groups": ["Reviewed Customer Parent"]
}
```

The feature is disabled by default. If the allowlist is empty, no Customers are created and the sync records a configuration error. The master import reads the Tally `mst_group` hierarchy and stores each ledger's resolved root-to-immediate parent path on `Tally Customer Ledger`. When enabled with a reviewed allowlist, matching Tally ledgers present in a complete source snapshot create Active, Admin Approved Customers with `Onboarding Source = Tally`, no mobile/OTP/token, and Sales Employee ordering access. A source row marked inactive or with a clearly `CLOSED` ledger name loses Sales Employee ordering access; malformed source rows are rejected before Customer writes; unresolved/cyclic group-path rows are also rejected and their imported ledger rows are marked inactive; a ledger moved outside the configured ancestor groups loses access; and a matching ledger missing from a complete snapshot also loses Sales Employee ordering access. Customer records are not deleted. Because this Tally mirror does not expose a reliable ledger active/type flag, the ancestor allowlist and conservative closed-name handling must be reviewed before enabling the feature. Non-matching ledgers remain only as imported `Tally Customer Ledger` records.

After deploying the DocType change and running `bench migrate`, run the normal Tally master import once to backfill paths on existing `Tally Customer Ledger` rows. This backfill does not create Customers while `enable_tally_customer_auto_onboarding` is disabled.

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
