# Tally Pilot Evidence Template

Use this template during the controlled Tally pilot to capture the external evidence needed to close `docs/12-operational-readiness-checklist.md`.

Do not mark the production gate complete from verbal confirmation alone. Attach query output, screenshots, exported CSV files, or Frappe record names for each section.

## Pilot Run Metadata

| Field | Value |
| --- | --- |
| Pilot date/time | |
| Tally company name | |
| Connector run ID or timestamp | |
| Frappe site | |
| Frappe bench/app version | |
| Operator names | |
| Portal test Order reference | `KE-YY-MM-####` |

## 1. Portal Reference Field Proof

Goal: prove the portal Order reference entered in Tally reaches the connector field used by reconciliation.

Capture:

- Portal Order reference.
- Tally Delivery Challan voucher type and voucher number.
- Tally Sales Invoice voucher type and voucher number.
- The exact Tally screen/field where the operator entered the portal reference.
- Connector sync timestamp.

SQL evidence:

```sql
select
    guid,
    date,
    voucher_type,
    voucher_number,
    reference_number,
    party_name,
    is_inventory_voucher,
    is_invoice
from trn_voucher
where reference_number = '<KE-YY-MM-####>'
order by date, voucher_type, voucher_number;
```

Expected result:

- At least one Delivery Challan or Sales Invoice row has `reference_number = '<KE-YY-MM-####>'`.
- If the reference appears in a different exported field, record the field name and keep production blocked until voucher sync/reconciliation is changed and retested.

## 2. Voucher Line Match Proof

Goal: prove the matched voucher exposes line item, godown, quantity, and tracking context needed by reconciliation.

SQL evidence:

```sql
select
    v.voucher_type,
    v.voucher_number,
    v.reference_number,
    v.party_name,
    i.item,
    i.godown,
    i.quantity,
    i.tracking_number,
    i.order_number
from trn_voucher v
join trn_inventory i on i.guid = v.guid
where v.reference_number = '<KE-YY-MM-####>'
order by v.voucher_type, v.voucher_number, i.item, i.godown;
```

Expected result:

- The voucher lines include the ordered item names.
- Quantities match the controlled order fulfillment.
- `tracking_number` is present when Delivery Challan and Sales Invoice represent the same physical movement.

## 3. Customer Ledger Filter Proof

Goal: confirm the production filter for importable Customer ledgers and Client Codes.

Capture:

- The selected group or primary-group filter.
- At least five included Customer ledger rows with non-empty aliases.
- At least five excluded non-customer/internal/supplier ledger rows.

SQL evidence:

```sql
select
    name,
    parent,
    primary_group,
    alias,
    mobile,
    gstn
from mst_ledger
where alias is not null
  and alias <> ''
  and <customer-ledger-filter>
order by name
limit 20;
```

```sql
select
    name,
    parent,
    primary_group,
    alias
from mst_ledger
where not (<customer-ledger-filter>)
order by name
limit 20;
```

Expected result:

- Included rows are orderable Customers.
- Excluded rows are not valid Customer App Access accounts.
- The final sync filter can be implemented without relying on party name, GSTIN, or mobile number as automatic identity keys.

## 4. Godown And Branch Mapping Proof

Goal: close Main Location and Seetarambagh mapping decisions before branch visibility goes live.

SQL evidence:

```sql
select
    name,
    parent,
    address
from mst_godown
order by name;
```

```sql
select
    voucher_type,
    count(*) as voucher_count
from trn_voucher
where voucher_type ilike '%Seetarambagh%'
   or voucher_type ilike '%Goshamahal%'
   or voucher_type ilike '%Kukatpally%'
   or voucher_type ilike '%Main%'
group by voucher_type
order by voucher_type;
```

Decision table:

| Tally label | Confirmed meaning | Portal Branch | Godown mapping | Include in ordering? |
| --- | --- | --- | --- | --- |
| Goshamahal | | | | |
| Kukatpally | | | | |
| Main Location | | | | |
| Seetarambagh | | | | |

Expected result:

- Every active ordering godown maps to exactly one intended Portal Branch.
- Any reporting-only or ambiguous location is explicitly excluded from ordering and branch visibility.

## 5. Godown-Wise Stock Snapshot Proof

Goal: prove mobile stock comes from Tally-computed stock by godown, not naive voucher summation.

Capture:

- Tally Stock Summary/Godown Summary timestamp.
- Connector stock snapshot timestamp.
- Ten representative items across active godowns.
- Screenshots or exported Tally report rows for comparison.

SQL evidence, once the stock snapshot export table exists:

```sql
select
    item,
    godown,
    quantity,
    uom,
    as_on_date
from rpt_stock_godown_balance
where item in (
    '<item-1>',
    '<item-2>',
    '<item-3>'
)
order by item, godown;
```

Comparison table:

| Item | Godown | Tally report quantity | Connector snapshot quantity | Difference | Accepted? |
| --- | --- | ---: | ---: | ---: | --- |
| | | | | | |

Expected result:

- Differences are zero or within a documented rounding tolerance.
- If the snapshot table does not exist, production mobile stock remains blocked.

## 6. WhatsApp Provider Proof

Goal: prove live OTP and Order Placed confirmation dispatch can leave the Frappe site.

Frappe evidence:

```sql
select
    name,
    mobile_number,
    purpose,
    provider,
    provider_status,
    provider_response,
    created_at
from "tabMobile OTP"
where mobile_number = '<pilot-mobile-number>'
order by created_at desc
limit 5;
```

```sql
select
    name,
    "order",
    recipient_type,
    recipient_customer,
    mobile_number,
    status,
    order_pdf,
    provider_response,
    created_at
from "tabOrder WhatsApp Notification"
where "order" = '<KE-YY-MM-####>'
order by created_at desc;
```

Expected result:

- OTP provider status reaches the provider's accepted/sent state.
- Order Placed notification references an `Order PDF` and reaches accepted/sent state.
- Provider failures include enough response detail for retry/troubleshooting.

## Production Sign-Off

| Gate | Evidence attached? | Accepted by | Date |
| --- | --- | --- | --- |
| Portal reference field proof | | | |
| Voucher line match proof | | | |
| Customer ledger filter proof | | | |
| Godown and branch mapping proof | | | |
| Godown-wise stock snapshot proof | | | |
| WhatsApp provider proof | | | |
