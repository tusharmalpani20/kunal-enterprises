# Kunal Enterprises Backend API

This document describes the implemented Frappe whitelisted API surface for the Kunal Enterprises portal/mobile backend.

Base path:

```text
/api/method/<python.dotted.path>
```

Example:

```text
/api/method/kunal_enterprises.api.orders.submit
```

## Response Envelope

All implemented APIs return the same envelope shape.

Success:

```json
{
  "success": true,
  "status": "success",
  "message": "Order placed",
  "http_status_code": 200,
  "data": {}
}
```

Error:

```json
{
  "success": false,
  "status": "error",
  "message": "Unable to submit order",
  "http_status_code": 400,
  "error": {
    "message": "Item is not allowed"
  }
}
```

Validation/business-rule errors return `400`, permission errors return `403`, missing documents return `404`, invalid mobile tokens return `401`, and unexpected server failures return `500`.

Mobile protected APIs are Frappe guest-whitelisted so mobile clients can reach them without Desk login, then they verify the custom mobile token inside the endpoint. The mobile client must send:

```http
Auth-Token: Bearer <access_token>
```

The token verifier accepts either `Auth-Token` or `Authorization`.

## Health

### Smoke

```http
GET /api/method/kunal_enterprises.api.health.smoke
```

Response:

```json
{
  "success": true,
  "message": "Kunal Enterprises app is installed",
  "data": {
    "app": "kunal_enterprises",
    "database_type": "postgres",
    "installed_apps": ["frappe", "frappe_whatsapp", "kunal_enterprises"],
    "checks": {
      "custom_app_installed": true,
      "frappe_whatsapp_installed": true
    }
  }
}
```

## Auth And OTP

### Start Customer Signup

```http
POST /api/method/kunal_enterprises.api.otp.start_customer_signup
```

Request:

```json
{
  "payload": {
    "customer_name": "Asha Textiles",
    "business_legal_name": "Asha Textiles Pvt Ltd",
    "gstin": "27ABCDE1234F1Z5",
    "mobile_number": "9000000001",
    "email_id": "asha@example.com",
    "date_of_birth": "1990-01-02",
    "date_of_anniversary": "2015-03-04"
  }
}
```

Response:

```json
{
  "success": true,
  "http_status_code": 201,
  "message": "Customer signup started",
  "data": {
    "customer": "9000000001",
    "status": "Pending OTP",
    "next_step": "verify_otp",
    "cooldown_seconds": 45,
    "expires_in_seconds": 300
  }
}
```

Customer signup, Customer OTP send/resend, and Sales Employee OTP send/resend create a `Mobile OTP` record queued for the `frappe_whatsapp` provider. The record stores the OTP request payload, provider response metadata, provider status, cooldown, expiry, and verification status so OTP dispatch has an install-visible audit trail.

### Send OTP

```http
POST /api/method/kunal_enterprises.api.otp.send_otp
```

Request:

```json
{
  "mobile_number": "9000000002",
  "identity_type": "Sales Employee"
}
```

`identity_type` is `Customer` or `Sales Employee`. Customer signup normally sends the first Customer OTP, while Sales Employee login starts here.

Response:

```json
{
  "success": true,
  "message": "OTP sent",
  "data": {
    "mobile_number": "9000000002",
    "identity_type": "Sales Employee",
    "purpose": "Sales Employee Login",
    "cooldown_seconds": 45,
    "expires_in_seconds": 300,
    "next_step": "verify_otp"
  }
}
```

### Resend OTP

```http
POST /api/method/kunal_enterprises.api.otp.resend_otp
```

Request:

```json
{
  "mobile_number": "9000000002",
  "identity_type": "Sales Employee"
}
```

The backend enforces the cooldown. A request inside the cooldown returns an error envelope with HTTP status `429`.

Successful response:

```json
{
  "success": true,
  "message": "OTP resent",
  "data": {
    "mobile_number": "9000000002",
    "identity_type": "Sales Employee",
    "purpose": "Sales Employee Login",
    "cooldown_seconds": 45,
    "expires_in_seconds": 300,
    "next_step": "verify_otp"
  }
}
```

### Verify Customer OTP

```http
POST /api/method/kunal_enterprises.api.otp.verify_customer_otp
```

Request:

```json
{
  "mobile_number": "9000000001",
  "otp_code": "123456"
}
```

If the customer is still pending admin approval, no token is returned:

```json
{
  "success": true,
  "message": "Customer mobile number verified",
  "data": {
    "customer": "9000000001",
    "status": "Pending Admin Review",
    "customer_app_access": false
  }
}
```

If Customer App Access is active, the response also includes `access_token`, `token`, `identity_type`, `identity`, and `expires_at`.

### Verify Sales Employee OTP

```http
POST /api/method/kunal_enterprises.api.otp.verify_sales_employee_otp
```

Request:

```json
{
  "mobile_number": "9000000002",
  "otp_code": "123456"
}
```

Response:

```json
{
  "success": true,
  "message": "Sales Employee mobile number verified",
  "data": {
    "sales_employee": "SE-0001",
    "status": "Active",
    "access_token": "<jwt>",
    "token": "MAT-00001",
    "identity_type": "Sales Employee",
    "identity": "SE-0001",
    "expires_at": "2027-05-19 10:00:00"
  }
}
```

### Current Session

```http
GET /api/method/kunal_enterprises.api.token_verification.current_session
Auth-Token: Bearer <access_token>
```

Response:

```json
{
  "success": true,
  "message": "Current mobile session loaded",
  "data": {
    "identity_type": "Customer",
    "identity": "9000000001",
    "customer": "9000000001"
  }
}
```

### Logout

```http
POST /api/method/kunal_enterprises.api.token_verification.revoke_token
Auth-Token: Bearer <access_token>
```

Response:

```json
{
  "success": true,
  "message": "Mobile token revoked",
  "data": {
    "token": "MAT-00001",
    "status": "Revoked"
  }
}
```

## Customer Access

### Customer App Access Status

```http
GET /api/method/kunal_enterprises.api.customer_access.status?customer=9000000001
Auth-Token: Bearer <access_token>
```

Post-login status checks require a Customer token matching `customer`. Signup/OTP flows may call the same business status logic before a token exists.

Response:

```json
{
  "success": true,
  "message": "Customer App Access status",
  "data": {
    "customer": "9000000001",
    "status": "Active",
    "customer_app_access": true,
    "checklist": {
      "mobile_verified": true,
      "admin_approved": true,
      "valid_client_code": true,
      "account_active": true
    }
  }
}
```

## Sales Employee Customer Selection

### Allowed Customers

```http
GET /api/method/kunal_enterprises.api.sales_employees.allowed_customers?sales_employee=SE-0001&search=asha
Auth-Token: Bearer <access_token>
```

Search matches Client Code, customer name, and business/legal name, but Client Code is not returned.
The token must be a Sales Employee token matching `sales_employee`.

Response:

```json
{
  "success": true,
  "message": "Allowed Customers",
  "data": {
    "sales_employee": "SE-0001",
    "customers": [
      {
        "customer": "9000000001",
        "customer_name": "Asha Textiles",
        "business_legal_name": "Asha Textiles Pvt Ltd"
      }
    ]
  }
}
```

## Product Groups, Items, And Stock

### Allowed Product Groups

```http
GET /api/method/kunal_enterprises.api.product_groups.allowed?customer=9000000001
Auth-Token: Bearer <access_token>
```

For sales employee ordering, include `sales_employee`.
Customer requests require a matching Customer token. Sales Employee requests require a matching Sales Employee token.

Response:

```json
{
  "success": true,
  "message": "Allowed Product Groups",
  "data": {
    "customer": "9000000001",
    "sales_employee": null,
    "product_groups": [
      {
        "name": "Cotton Fabric",
        "group_name": "Cotton Fabric",
        "full_path": "Cotton Fabric",
        "product_group_logo": "/files/cotton_fabric_logo.jpeg"
      }
    ]
  }
}
```

`product_group_logo` is the attached image URL for the root product group. It is `null` when no logo is attached. Mobile clients should build a root-name-to-logo map from this response and use it when rendering both product groups and their items (items resolve via `root_stock_group`).

### Allowed Items

```http
GET /api/method/kunal_enterprises.api.product_groups.items?customer=9000000001&product_group=Cotton%20Fabric
Auth-Token: Bearer <access_token>
```

Response:

```json
{
  "success": true,
  "message": "Allowed Items",
  "data": {
    "customer": "9000000001",
    "product_group": "Cotton Fabric",
    "items": [
      {
        "name": "ITEM-COTTON-001",
        "item_name": "Cotton 40s",
        "root_stock_group": "Cotton Fabric",
        "uom": "PCS",
        "total_closing_balance": 125
      }
    ]
  }
}
```

### Item Stock By Godown

```http
GET /api/method/kunal_enterprises.api.product_groups.item_stock?customer=9000000001&item=ITEM-COTTON-001
Auth-Token: Bearer <access_token>
```

Stock is advisory. Zero-stock and over-stock orders are allowed at order submission.

Response:

```json
{
  "success": true,
  "message": "Item stock by godown",
  "data": {
    "customer": "9000000001",
    "item": "ITEM-COTTON-001",
    "stock_is_advisory": true,
    "godowns": [
      {
        "godown": "Main Godown",
        "quantity": 12,
        "uom": "PCS",
        "as_on_date": "2026-05-19",
        "synced_at": "2026-05-19 12:05:00"
      }
    ]
  }
}
```

## Orders

### Submit Order

```http
POST /api/method/kunal_enterprises.api.orders.submit
Auth-Token: Bearer <access_token>
```

Customer submissions require a Customer token matching `customer`. Sales Employee submissions require a Sales Employee token matching `sales_employee`.

Submission revalidates Customer App Access, Sales Employee status/assignment, Product Group item access, positive quantity, and active Tally Godown membership. Active zero-stock godowns remain valid because stock is advisory; inactive or unknown godowns are rejected once Tally Godown masters have been synced.

After submission, requested Order item lines and godown allocation quantities are immutable. Reconciliation and Owner/Admin controls can still update fulfillment/status fields without changing the original request.

Order-facing DocTypes remain quantity-only and do not expose price, rate, amount, tax, discount, value, or currency fields.

Customer order request:

```json
{
  "customer": "9000000001",
  "allocations": [
    {
      "item": "ITEM-COTTON-001",
      "godown": "Main Godown",
      "quantity": 5,
      "stock_shown_at_order_time": 12,
      "stock_snapshot_at": "2026-05-19 12:05:00"
    }
  ]
}
```

Sales Employee order request:

```json
{
  "customer": "9000000001",
  "sales_employee": "SE-0001",
  "sales_employee_note": "Customer asked for dispatch this week",
  "allocations": [
    {
      "item": "ITEM-COTTON-001",
      "godown": "Main Godown",
      "quantity": 5
    }
  ]
}
```

Response:

```json
{
  "success": true,
  "message": "Order placed",
  "data": {
    "order": "KE-26-05-0001",
    "portal_reference_number": "KE-26-05-0001",
    "status": "Placed",
    "total_item_count": 1,
    "total_quantity": 5
  }
}
```

Order placement also creates:

- an `Order PDF` record for the Customer;
- an `Order WhatsApp Notification` record for the Customer only.

The customer PDF and WhatsApp request payload exclude Sales Employee internal notes, Client Code, and stock shown at order time.

The notification log stores `request_payload`, `provider_response`, `status`, and the `order_pdf` attachment reference. The initial provider response is queued for `frappe_whatsapp` with `retry_count: 0`; later dispatch workers can update the same log to `Sent` or `Failed`.

### Order History

```http
GET /api/method/kunal_enterprises.api.orders.history?customer=9000000001
Auth-Token: Bearer <access_token>
```

Customer history is scoped by `customer` and includes both self-placed orders and orders placed by Sales Employees for that Customer.

Sales Employee history can be requested without a Customer filter:

```http
GET /api/method/kunal_enterprises.api.orders.history?sales_employee=SE-0001
Auth-Token: Bearer <access_token>
```

Only orders placed by that Sales Employee are returned, spanning all Customers visible through the employee's own order activity. A Customer filter may still be included when the caller needs that employee's orders for one selected Customer.
Customer history requires a matching Customer token. Sales Employee history requires a matching Sales Employee token.

Response:

```json
{
  "success": true,
  "message": "Order history",
  "data": {
    "orders": [
      {
        "name": "KE-26-05-0001",
        "portal_reference_number": "KE-26-05-0001",
        "order_source": "Customer",
        "customer": "9000000001",
        "sales_employee": null,
        "status": "Placed",
        "display_status": "Placed",
        "total_item_count": 1,
        "total_quantity": 5
      }
    ]
  }
}
```

### Order Detail

```http
GET /api/method/kunal_enterprises.api.orders.detail?order=KE-26-05-0001&customer=9000000001
Auth-Token: Bearer <access_token>
```

Customer detail responses hide Client Code, sales employee note, and stock shown at order time. `Manual Review` is returned with `display_status` as `Under Review`.
Customer detail requires a matching Customer token. Sales Employee detail requires a matching Sales Employee token.

Response:

```json
{
  "success": true,
  "message": "Order detail",
  "data": {
    "name": "KE-26-05-0001",
    "portal_reference_number": "KE-26-05-0001",
    "status": "Manual Review",
    "display_status": "Under Review",
    "placed_by": "Sales Employee Name",
    "items": [
      {
        "item": "ITEM-COTTON-001",
        "item_name": "Cotton 40s",
        "requested_quantity": 5,
        "fulfilled_quantity": 0,
        "pending_quantity": 5,
        "status": "Placed"
      }
    ],
    "godown_allocations": [
      {
        "item": "ITEM-COTTON-001",
        "godown": "Main Godown",
        "requested_quantity": 5,
        "fulfilled_quantity": 0,
        "pending_quantity": 5
      }
    ]
  }
}
```

## Profile

### Get Profile

```http
GET /api/method/kunal_enterprises.api.profile.get_profile?identity_type=Customer&identity=9000000001
Auth-Token: Bearer <access_token>
```

The token identity must match `identity_type` and `identity`.

Response:

```json
{
  "success": true,
  "message": "Customer profile",
  "data": {
    "identity_type": "Customer",
    "customer": "9000000001",
    "customer_name": "Asha Textiles",
    "business_legal_name": "Asha Textiles Pvt Ltd",
    "mobile_number": "9000000001",
    "email_id": "asha@example.com",
    "customer_app_access": true,
    "editable_fields": ["email_id", "date_of_birth", "date_of_anniversary"]
  }
}
```

Sales Employee profile responses return `editable_fields: []`.

### Update Customer Profile

```http
POST /api/method/kunal_enterprises.api.profile.update_customer_profile
Auth-Token: Bearer <access_token>
```

The token must be a Customer token matching `customer`.

Request:

```json
{
  "customer": "9000000001",
  "payload": {
    "email_id": "new@example.com",
    "date_of_birth": "1990-01-02",
    "date_of_anniversary": "2015-03-04"
  }
}
```

## Branch Portal APIs

### Branch Visible Orders

```http
GET /api/method/kunal_enterprises.api.branch_orders.visible_orders?branch=Main%20Location&role=Branch%20Manager
```

The current Frappe session user must actually have the requested `Branch Manager` or `Branch Employee` role and a `User Permission` row where `allow = Portal Branch` and `for_value = branch`. The `role` and `branch` request parameters select the branch action context; they are not trusted as proof of authorization.

Branch Manager sees orders across all statuses for mapped godowns. Branch Employee sees only `Placed`, `Processing`, and `Manual Review`. When a visible order is in `Manual Review`, the response includes the latest `manual_review_reason_code` and `manual_review_reason` from `Order Reconciliation Log` for branch operations; mobile Customer/Sales Employee APIs still expose only `Under Review`.

Desk Order list/detail visibility is also registered through Frappe `permission_query_conditions` and `has_permission` hooks. Owner, Admin, and System Manager see all Orders. Branch Manager and Branch Employee visibility is scoped by `User Permission` records where `allow = Portal Branch`; the allowed Portal Branches are expanded through active `Branch Godown Mapping` rows. Branch Employee Desk visibility is additionally limited to `Placed`, `Processing`, and `Manual Review`.

Response:

```json
{
  "success": true,
  "message": "Branch visible orders",
  "data": {
    "orders": [
      {
        "name": "KE-26-05-0001",
        "portal_reference_number": "KE-26-05-0001",
        "status": "Manual Review",
        "display_status": "Under Review",
        "manual_review_reason_code": "CUSTOMER_CLIENT_CODE_MISMATCH",
        "manual_review_reason": "Customer Client Code mismatch",
        "total_item_count": 1,
        "total_quantity": 5
      }
    ]
  }
}
```

### Branch Employee Mark Processing

```http
POST /api/method/kunal_enterprises.api.branch_orders.mark_processing
```

The current Frappe session user must have `Branch Employee` and a matching `Portal Branch` `User Permission` for `branch`.

Request:

```json
{
  "branch": "Main Location",
  "order": "KE-26-05-0001",
  "role": "Branch Employee"
}
```

Response:

```json
{
  "success": true,
  "message": "Order moved to Processing",
  "data": {
    "order": "KE-26-05-0001",
    "status": "Processing"
  }
}
```

## Owner/Admin Order Controls

Only `Owner` and `Admin` roles can use these actions. Branch roles receive an error response and the Order status remains unchanged.

### Cancel Order

```http
POST /api/method/kunal_enterprises.api.order_controls.cancel_order
```

Request:

```json
{
  "order": "KE-26-05-0001",
  "role": "Owner",
  "note": "Cancelled after customer confirmation"
}
```

### Partially Close Order

```http
POST /api/method/kunal_enterprises.api.order_controls.partially_close_order
```

Request:

```json
{
  "order": "KE-26-05-0001",
  "role": "Admin",
  "note": "Remaining quantity will not be supplied"
}
```

### Resolve Manual Review

```http
POST /api/method/kunal_enterprises.api.order_controls.resolve_manual_review
```

Request:

```json
{
  "order": "KE-26-05-0001",
  "role": "Owner",
  "resolution_note": "Verified in Tally and resumed processing"
}
```

`resolution_note` is required. Successful resolution writes an `Order Status Log` with the note and moves the Order from `Manual Review` back to `Processing`.

Response:

```json
{
  "success": true,
  "message": "Manual Review resolved",
  "data": {
    "order": "KE-26-05-0001",
    "status": "Processing"
  }
}
```

Each successful control action writes an `Order Status Log`.

## Owner/Admin Product Group Logos

Only `Owner` and `Admin` roles can attach logos to `Tally Stock Group` rows. The `Tally Stock Group` doctype itself remains read-only for Owner/Admin; logos must be set through this controlled endpoint.

### Set Product Group Logo

```http
POST /api/method/kunal_enterprises.api.product_group_logos.set_product_group_logo
```

Request:

```json
{
  "group": "Merino Industries Limited",
  "file_url": "/files/merino830151.jpeg"
}
```

`group` is the `name` (and `group_name`) of the `Tally Stock Group`. `file_url` is the uploaded file URL, typically created through the Frappe `File` doctype.

Response:

```json
{
  "success": true,
  "message": "Logo attached",
  "data": {
    "group": "Merino Industries Limited",
    "product_group_logo": "/files/merino830151.jpeg"
  }
}
```

Rejects with `403` when called by non-Owner/Admin roles and with `400` when `group` or `file_url` is missing.

A one-off upload script is available at `kunal_enterprises.patches.upload_product_group_logos.upload` to attach the source logos in `ke-enterprises-product-logos/` to their mapped groups.

## Owner/Admin Sync APIs

Only `Owner` and `Admin` roles can run manual sync actions.

### Sync Masters Now

```http
POST /api/method/kunal_enterprises.api.sync_admin.sync_masters_now
```

Request:

```json
{
  "role": "Owner",
  "records": {
    "units": [{"unit_name": "PCS", "symbol": "PCS", "is_active": 1}],
    "godowns": [{"godown_name": "Main Godown", "is_active": 1}],
    "stock_categories": [{"category_name": "Fabric", "is_active": 1}],
    "stock_groups": [
      {
        "group_name": "Fabrics",
        "is_root": 1,
        "depth": 0,
        "full_path": "Fabrics",
        "is_active": 1
      }
    ],
    "items": [
      {
        "item_name": "Cotton Roll",
        "immediate_stock_group": "Fabrics",
        "root_stock_group": "Fabrics",
        "stock_category": "Fabric",
        "uom": "PCS",
        "total_closing_balance": 12,
        "is_active": 1
      }
    ],
    "customer_ledgers": [
      {
        "client_code": "CUST-001",
        "ledger_name": "Asha Textiles",
        "is_active": 1
      }
    ]
  }
}
```

Master sync upserts Tally Units, Godowns, Stock Categories, Stock Groups, Items, and Customer Ledgers. Customer Ledger `client_code` is the alias used by Customer App Access.

### Sync Stock Now

```http
POST /api/method/kunal_enterprises.api.sync_admin.sync_stock_now
```

Request:

```json
{
  "role": "Owner",
  "records": [
    {
      "item": "ITEM-COTTON-001",
      "godown": "Main Godown",
      "quantity": 12,
      "uom": "PCS",
      "as_on_date": "2026-05-19",
      "source_company": "Kunal Enterprises"
    }
  ]
}
```

Stock sync requires the `item` to exist in `Tally Item` and the `godown` to exist as an active `Tally Godown`. Invalid rows are written to `Tally Sync Error`; valid rows in the same run still upsert `Tally Stock Snapshot`.

### Sync Vouchers Now

```http
POST /api/method/kunal_enterprises.api.sync_admin.sync_vouchers_now
```

Request:

```json
{
  "role": "Owner",
  "records": [
    {
      "voucher_type": "Sales Invoice",
      "voucher_number": "SI-0001",
      "reference_number": "KE-26-05-0001",
      "party_client_code": "CUST-001",
      "tracking_number": "TRACK-001",
      "voucher_date": "2026-05-19",
      "lines": [
        {
          "item": "ITEM-COTTON-001",
          "godown": "Main Godown",
          "quantity": 5,
          "tracking_number": "TRACK-001"
        }
      ]
    }
  ]
}
```

This upserts `Tally Voucher` and `Tally Voucher Line` records used by reconciliation. Voucher lines require the `item` to exist in `Tally Item` and the `godown` to exist as an active `Tally Godown`. Invalid voucher records are written to `Tally Sync Error`; valid vouchers in the same run still import.

### Run Reconciliation Now

```http
POST /api/method/kunal_enterprises.api.sync_admin.run_reconciliation_now
```

Request:

```json
{
  "role": "Owner"
}
```

Sync responses include the `Tally Sync Run` summary:

```json
{
  "success": true,
  "message": "Stock sync completed",
  "data": {
    "run": "TSR-00001",
    "sync_type": "Stock",
    "status": "Completed",
    "records_seen": 1,
    "records_processed": 1,
    "errors_count": 0
  }
}
```

## Scheduler Entry Points

The following jobs are registered every five minutes:

```text
kunal_enterprises.cron.tally_sync.sync_tally_masters
kunal_enterprises.cron.tally_sync.sync_stock_snapshots
kunal_enterprises.cron.tally_sync.sync_tally_vouchers
kunal_enterprises.cron.reconciliation.run_reconciliation
```

## Reconciliation Behavior

Reconciliation runs from synced `Tally Voucher` records.

- Match Order by portal reference number.
- Validate Customer using Customer `client_code` against voucher `party_client_code`.
- Apply fulfillment item-wise, not godown-wise.
- Accumulate multiple Sales Invoices for the same Order.
- Prefer Sales Invoice over mirrored Delivery Challan for the same tracking movement.
- Move to `Manual Review` with a reason when customer mismatches, extra item lines exist, over-fulfillment occurs, or duplicate movement is ambiguous.
- `Order Reconciliation Log` stores both `reason_code` and `message`; Manual Review logs require both fields. Examples include `CUSTOMER_CLIENT_CODE_MISMATCH`, `EXTRA_VOUCHER_ITEM`, `OVER_FULFILLMENT`, and `AMBIGUOUS_DUPLICATE_MOVEMENT`.
