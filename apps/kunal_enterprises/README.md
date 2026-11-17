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

## Bulk export access

Owner, Admin, System Manager and the special Administrator account retain their existing permissions. All other users are denied list/report exports, import-data downloads, prepared-report downloads/conversions, immediate report emails, bulk contact cards, multi-document PDFs, report PDFs and attachment ZIPs. Individual document print views and PDFs retain their normal permission checks.

The app enforces this after cookie/API-key/OAuth authentication, across legacy commands and REST v1/v2 routes, before export jobs can be queued. Generic list/search requests accept at most 200 rows per request; ordinary pagination remains available. This does not prevent copying or paging through data users may legitimately view.

Export files (CSV, Excel, ODS, ZIP, JSON and generated report attachments) are kept private before their content is written, since public files bypass application authentication. Restricted accounts cannot download those artifacts. Desk also hides the corresponding export/bulk-print controls and oversized page choices. No Frappe source changes or role-grant changes are required. Clear the site cache after deployment and refresh Desk assets. When deploying onto another site, review existing public export artifacts before enabling the policy; the current local site had none.

Regression checks: `tests/test_export_guard.py` (Python unittest) and `tests/test_export_policy.mjs` (Node). Live role walkthrough evidence is separate from these automated checks.

## Customer WhatsApp contacts

Customer Contacts stores a person's name, phone and optional designation. WhatsApp intake recognizes both these contacts and the Customer's existing main mobile number. Contacts do not become mobile-app login identities or Sales Employee records. Intake reviewers can use **Link sender to Customer** on a saved, open WhatsApp request; the action verifies its incoming source messages, records the contact and fills a blank Customer selection. Correct an already different Customer selection before linking.

Customer saves prevent normalized phone duplicates across main numbers and contacts, including repeats within the same Customer. Ten-digit national numbers use the default country calling code in Order Intake Settings; explicit `+`/`00` country prefixes are preserved. WhatsApp sender IDs already include their country code and are not prefixed again. Main login numbers retain their stored format. Customer inserts/saves acquire a transaction lock before the document row lock, and duplicate checks use current reads; a conflicting stale transaction asks the user to reload rather than retrying part of a save. Contact rows must be edited through their parent Customer or the scoped intake action.

`bench migrate` installs the child table and audits existing phone ownership. Legacy collisions stop the audit with the affected Customer IDs; it never merges Customers or rewrites login numbers automatically.

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

## Voucher corrections and reconciliation

See [VOUCHER_RECONCILIATION.md](VOUCHER_RECONCILIATION.md) for the existing PostgreSQL mirror integration, correction and missing-data behavior, legacy migration and deployment order.
