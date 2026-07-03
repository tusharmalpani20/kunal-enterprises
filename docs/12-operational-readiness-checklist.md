# Operational Readiness Checklist

This checklist defines the external operational evidence needed before the Kunal Enterprises system can be called production-ready against the client Tally company.

The backend and mobile app can run locally with deterministic tests, but the items below require confirmation from the live Tally operating process and production-style connector data. Until these are closed, fulfillment automation should be treated as ready for controlled pilot only.

Use `docs/15-tally-pilot-evidence-template.md` during the controlled pilot to capture SQL output, screenshots, exported rows, and Frappe record names for these gates.

## Required Confirmations

| Item | Why it matters | Evidence required | System action after confirmation |
| --- | --- | --- | --- |
| Tally portal reference field | Reconciliation matches portal Orders to Tally vouchers using the portal reference number. Demo data showed `trn_voucher.reference_number` was empty for main sales vouchers and populated on only 2 delivery challans. | Create one controlled portal Order, enter its `KE-YY-MM-####` reference into the agreed Tally Delivery Challan and Sales Invoice field, run the connector sync, and capture the resulting `trn_voucher.reference_number` rows for both voucher types. | If the value appears in `trn_voucher.reference_number`, keep the current reconciliation key. If it appears in another exported field, update voucher sync and reconciliation before production use. |
| Main Location branch mapping | `Main Location` exists in `mst_godown` but has no confirmed branch meaning. Branch visibility and order processing depend on godown-to-branch mapping. | Operations must decide whether `Main Location` maps to an existing Portal Branch, a separate Portal Branch, or should be excluded from mobile/branch workflows. | Create or update `Portal Branch` and `Branch Godown Mapping` records, or mark the godown inactive/excluded from ordering if it is not operationally valid. |
| Seetarambagh interpretation | Demo vouchers include `Sales Seetarambagh` and `Delivery Challan Seetarambagh`, but the discovered godown list did not expose a clear Seetarambagh godown. | Operations must confirm whether Seetarambagh is a branch, a voucher naming convention, a missing/inactive godown, or a mapping to another godown such as `Main Location`. | Add the correct Portal Branch/godown mapping, or document that Seetarambagh vouchers are reporting labels only and should not create branch visibility. |
| Customer ledger import filter | Customer App Access depends on `Customer.client_code = mst_ledger.alias`. Demo ledgers appeared to roll up under `Sundary Debtors`, but the exact production filter is not confirmed. | Run a production-style ledger export and confirm the exact group/primary-group filter that includes orderable Customers and excludes suppliers, internal ledgers, and non-ordering accounts. Capture sample included and excluded ledgers with aliases. | Configure the Tally customer ledger sync filter and use it as the source of valid Client Codes for Customer App Access. |
| Godown-wise stock snapshot | Mobile stock by godown must come from Tally-computed stock, not naive voucher summation, because demo Sales/DC rows duplicate movements. | Produce a Tally-computed stock-by-godown snapshot for at least 10 representative items across active godowns and compare it to Tally's Stock Summary/Godown Summary report at the same sync time. | Import the validated snapshot into `Tally Stock Snapshot`; do not expose transaction-derived godown stock unless it matches Tally reports within accepted tolerance. |
| WhatsApp provider credentials | OTP and Order Placed confirmation logs are implemented, but live dispatch depends on provider configuration. | Configure provider credentials in the Frappe site and send one Customer OTP plus one Order Placed confirmation/PDF in a controlled test. Capture `Mobile OTP` and `Order WhatsApp Notification` provider statuses. | Enable live Customer onboarding and order confirmation notifications. |

## Pilot Gate

A controlled pilot can start when:

- the Frappe backend is migrated and tests pass on the target site;
- the mobile app points to the target Frappe base URL;
- Customer App Access is configured for pilot Customers;
- manual sync APIs have imported masters, stock snapshots, and vouchers from a known connector run;
- the reference-field test proves at least one Tally voucher can be reconciled to one portal Order;
- any unmapped godown is explicitly excluded from ordering and branch visibility.

## Production Gate

Production readiness requires all Required Confirmations above to be closed with captured evidence. If any item remains unresolved, keep it listed in `docs/11-delivery-audit.md` as an operational question and avoid claiming full completion.
