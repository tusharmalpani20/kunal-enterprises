# Frappe App Patterns From SF-DPMS

These notes summarize the implementation patterns observed in `sf-dpms/dpms_sf`. Use them as conventions for the Kunal Enterprise Frappe app when creating APIs, DocTypes, cron jobs, document events, fixtures, hooks, permission query conditions, token verification, OTP, and shared utilities.

## Folder Layout

Follow the same responsibility split:

- `hooks.py`: app metadata, Desk JS bindings, permission query condition registration, DocType overrides, document events, and scheduler entries.
- `<app>/<app>/api/`: whitelisted mobile/portal API modules grouped by feature.
- `<app>/<app>/api/utils.py`: shared response helpers, request/header normalization, and domain utility functions.
- `<app>/<app>/api/otp.py`: OTP login, resend, verification, and token creation.
- `<app>/<app>/api/token_verification.py`: JWT extraction, validation, token refresh, and revoke.
- `<app>/<app>/doctype/<doctype>/`: one folder per custom DocType with `.json`, `.py`, `.js`, and optional tests/list scripts.
- `<app>/<app>/cron/`: scheduled jobs, each grouped by business area.
- `<app>/doc_events/`: hook handlers for standard or custom DocType lifecycle events.
- `<app>/permission_query_conditions/`: one file per DocType that needs row-level visibility.
- `<app>/fixtures/`: exported roles, permissions, workflows, salary components, workspace records, and other install-time seed data.
- `<app>/overrides/doctypes/`: custom subclasses for standard ERPNext/Frappe DocTypes when hook-based events are not enough.

## Hooks

Keep `hooks.py` as the central registry, not a place for business logic.

Key patterns:

- Use `doctype_js` and `doctype_list_js` for standard Desk customization, for example binding custom scripts to `Employee`, `Attendance`, and list views.
- Register row-level permissions under `permission_query_conditions` with fully qualified dotted paths.
- Use `override_doctype_class` only when behavior belongs inside a standard DocType class, for example custom `Employee` or `Attendance Request` behavior.
- Use `doc_events` for lifecycle handlers such as `before_save`, `before_submit`, and `on_submit`.
- Use `scheduler_events` for background jobs:
  - simple intervals such as `hourly`;
  - explicit cron expressions under `cron` for exact schedules.
- Keep commented hook examples only if useful as scaffolding; active hooks should be short and easy to audit.

When adding a new module, wire it in `hooks.py` only after the target function exists and can be imported.

## API Modules

SF-DPMS APIs use module-level whitelisted functions with consistent response dictionaries.

Use this shape:

```python
@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_something():
    try:
        is_valid, token_data = verify_token(frappe.request.headers)
        if not is_valid:
            frappe.local.response["http_status_code"] = token_data.get("http_status_code", 401)
            return token_data

        # validate inputs
        # query/create/update documents
        return create_success_response("Message", data)
    except Exception as e:
        return handle_error_response(e, "User-facing error message", 500)
```

Keypoints:

- Put each business area in its own API file, for example `employee.py`, `attendance.py`, `leaves.py`, `salary_slip.py`.
- Use `@frappe.whitelist(allow_guest=True, methods=[...])` for mobile endpoints that authenticate with custom JWT instead of Frappe login.
- Start protected endpoints with `verify_token(frappe.request.headers)`.
- Read GET params from `frappe.request.args`.
- Read POST JSON from `frappe.request.json`; reject missing bodies before using fields.
- Validate every required field explicitly and return a `400` response for client mistakes.
- Check referenced records with `frappe.db.exists` before creating linked documents.
- Prefer `frappe.db.get_list` / `frappe.get_all` for list APIs and `frappe.get_doc` when document behavior is needed.
- Use `insert()`, `save()`, and `submit()` when DocType validations and hooks must run.
- Use `frappe.db.set_value` for targeted status/timestamp updates where document reload conflicts are possible.
- Return created document names and relevant fields, not raw Frappe documents.
- Include pagination for list endpoints: `page_size`, `page_number`, `limit_start`, `limit_page_length`, and `total_count`.
- Cap page size, for example max `100`, to protect mobile APIs.
- Convert dates to strings in API responses when clients need JSON-safe values.
- Keep internal helper functions private with `_helper_name`.

Response convention:

- Success: `success=True`, `status="success"`, `message`, optional `data`, and `http_status_code`.
- Error: `success=False`, `status="error"`, `message`, optional `code` / `error`, and `http_status_code`.
- Always set `frappe.local.response["http_status_code"]` to match the returned body.

## API Utilities

Centralize repeatable API mechanics in `api/utils.py`.

Observed helpers:

- `handle_error_response(error, error_message, status_code=500, log_title=None)`
  - truncates log titles to Frappe-safe length;
  - logs detailed traceback with `frappe.log_error`;
  - sets `frappe.local.response["http_status_code"]`;
  - returns a standard error dict.
- `create_success_response(message, data=None, status_code=200)`
  - sets HTTP status;
  - wraps data in a standard response envelope.
- `convert_month_year_to_dates(month, year)`
  - accepts numeric month or `Jan`/`Feb` style abbreviations;
  - returns first and last date for the month.
- `conver_headers_to_dict(headers)`
  - normalizes Werkzeug/Frappe headers to a plain dict.
- Domain math helpers like `calculate_total_distance(coordinates)` belong here when reused by APIs and cron jobs.

For Kunal Enterprise, keep this file small and shared. Do not put feature-specific business workflows in `utils.py`.

## OTP Pattern

OTP login in SF-DPMS is backed by two DocTypes: `Mobile OTP` and `Auth Token`.

Flow:

1. `send_otp(phone_number, app_name, app_version)`
   - validates the app configuration;
   - enforces latest app version;
   - normalizes phone number;
   - finds an active Employee by phone;
   - checks designation access from the app configuration;
   - expires existing active OTPs for the phone;
   - creates a new OTP record with a short expiry;
   - sends SMS through a provider;
   - returns a standard response.
2. `verify_otp(phone_number, otp_code, app_name, app_version)`
   - validates app and version again;
   - finds a matching unexpired OTP;
   - marks the OTP verified;
   - finds the active user/employee/customer;
   - expires existing active tokens for the same app and identity;
   - creates an `Auth Token` row with a temporary token;
   - signs a JWT containing `token_id`, identity, and expiry;
   - updates the token row with the JWT;
   - returns the identity and token.
3. `resend_otp(...)`
   - performs the same app/user/access checks;
   - delegates to `send_otp`.

Keypoints for Kunal Enterprise:

- Replace Employee-specific checks with Customer / Sales Employee / Mobile Login Identity rules from `CONTEXT.md`.
- OTP verification is not the same as Customer App Access approval. Keep those states separate.
- Expire old OTPs before creating a new one.
- Expire old active tokens for the same identity and app before issuing a new one.
- Store provider, send time, expiry time, verified time, app name, and app version on the OTP record.
- Use masked phone numbers in logs.
- Keep any test bypass clearly isolated and avoid enabling it in production.
- Use `Asia/Kolkata` consistently if business timestamps are expected in IST.

## Token Verification Pattern

Protected mobile APIs rely on `api/token_verification.py`.

`verify_token(headers)` does the following:

- normalizes headers;
- reads `Auth-Token`;
- requires `Bearer <jwt>`;
- decodes JWT with `frappe.conf.get("jwt_secret_key")`;
- loads the backing `Auth Token` DocType by `token_id`;
- rejects missing, inactive, or expired tokens;
- marks expired token rows as `Expired`;
- verifies the linked identity is still active;
- checks the token app version against the app configuration;
- expires tokens from outdated app versions;
- sets `frappe.session.user` for downstream Frappe operations;
- returns `(True, token_data)` or `(False, error_response)`.

Also provide:

- `refresh_token(headers)`: verify current token, extend expiry, update last login, return a new JWT.
- `revoke_token(headers)`: verify current token and mark it expired for logout.

Keypoints:

- JWT secret must live in site config as `jwt_secret_key`.
- Store the JWT in the database only after the `Auth Token` document name is known.
- JWT payload should include the backing token document id, not just the user identity.
- Treat app update requirements as `403`.
- Treat missing/invalid/expired tokens as `401`.
- Treat missing server config as `500`.
- Log enough context for admins, but do not leak secrets or full OTPs in user-facing messages.

## DocType Pattern

Most simple DocType Python classes extend `Document` and use `pass`. Put logic in the class only when it owns validation or side effects.

Observed DocType conventions:

- Use one folder per DocType under `<app>/<app>/doctype/<doctype>/`.
- Keep generated files together: `doctype.json`, `doctype.py`, optional `.js`, optional `test_*.py`, optional list JS.
- Use expression-based naming where natural:
  - `autoname: "format:{app_name}"` for app config;
  - `autoname: "format:{employee}"` for one assignment per employee;
  - `autoname: "format:SF-Route-{######}"` for numbered operational masters.
- Use Section Break and Column Break fields to keep Desk forms readable.
- Use Table MultiSelect child DocTypes for assignment lists such as allowed designations, zones, routes, or departments.
- Mark operational list fields with `in_list_view`.
- Mark integration IDs as read-only.
- Use `unique: 1` on natural one-to-one links, for example assignment by employee.
- Keep permissions restrictive by default, commonly System Manager only, then add app roles through fixtures/custom doc permissions.

When adding DocType class logic:

- Put duplicate or consistency validation in `validate`.
- Use `before_save` to capture previous child-table state when `on_update` needs to know what changed.
- Use `on_update` for side effects caused by saved assignments.
- Use `frappe.throw` with a clear title for validation failures.
- When updating many related records, use `ignore_permissions=True` deliberately and document why.
- Avoid `frappe.db.commit()` inside document hooks unless there is a strong reason; SF-DPMS does it in some update loops, but for new code prefer Frappe's transaction boundary.

## Document Events

Use `doc_events` for cross-DocType workflows that should run on standard documents or when logic should stay outside a DocType class.

SF-DPMS examples:

- `Employee Promotion.before_save`: prevents duplicate promotions in the same month.
- `Employee Promotion.before_submit`: repeats critical validation at submit time.
- `Employee Promotion.on_submit`: creates/cancels salary structure assignments, salary slips, and additional salary entries after promotion.
- `Version.before_insert`: strips sensitive fields from Version history before the Version row is inserted.

Keypoints:

- Event functions must accept `(doc, method)`.
- Keep pure validation in small helpers and call them from multiple lifecycle events.
- Re-check critical validations on submit, not only on save.
- Use database savepoints for large multi-step submit workflows so failures can roll back cleanly.
- Return gracefully for non-critical missing configuration only when the source document can still be valid.
- Throw for critical failures where partial side effects would corrupt business state.
- For privacy, modify `Version.data` before insert to remove sensitive field changes from audit history.

## Permission Query Conditions

Permission query condition files expose:

```python
def get_permission_query_conditions(user):
    ...
    return "SQL condition"
```

Observed access model:

- `System Manager` and `Administrator`: no restriction, return `""` or `" and ".join([])`.
- `Read Only`: no restriction in SF-DPMS.
- `Plant HR`: restrict to departments configured in `DPMS Configuration`; return `1=0` if no configured departments or no matching employees.
- Users with Employee records: restrict by designation and hierarchy.
- `City Head`: branch-level access.
- `Last Mile Zonal Head`: zones from `Employee Zone Assignment` and `Zone Multiselect`.
- `Last Mile Executive`: own point/route/zone access.
- Other managers: use recursive Employee hierarchy via `reports_to`, including self.

Keypoints:

- Register every condition in `hooks.py`.
- Return `1=0` for explicit no-access cases.
- Use table-qualified fields when Frappe list queries need them, for example `` `tabRoute`.zone ``.
- Escape values with `frappe.db.escape` when interpolating dynamic lists.
- Prefer parameterized SQL for hierarchy queries.
- Keep the same access rule consistent across related DocTypes. If Customer access is branch-based in one list, order and item access should not silently use a different rule.

For Kunal Enterprise, map the same pattern to:

- portal users with broad administrative roles;
- sales employees limited by Customer Assignment and Item Access;
- customers limited to their own Customer, Customer Business, Orders, and allowed Product Groups;
- branch/internal users limited by branch if branch ownership becomes part of the model.

## Cron Jobs

Cron jobs live in `<app>/<app>/cron/` and are registered in `hooks.py`.

Observed cron styles:

- Data import jobs, for example importing route hierarchy from an external analytics API.
- Daily operational jobs, for example marking attendance absent/submitting drafts.
- Cleanup jobs, for example deleting old location tracking records in batches.
- Index/maintenance jobs, for example ensuring expected DB indexes exist.
- Payroll/derived-data jobs, for example calculating incentives or additional salary.

Keypoints:

- Each scheduled function should be importable by dotted path and take no required arguments. Optional arguments are acceptable for manual bench execution.
- Read external API URLs and keys from `frappe.conf`, never hard-code credentials.
- Validate configuration at the start.
- Track `start_time`, counters, skipped counts, error counts, and summaries.
- Log progress with `frappe.logger().info`.
- Log failures with `frappe.log_error` and continue per record where possible.
- Make jobs idempotent:
  - map external IDs to existing records;
  - check for existing derived documents before creating new ones;
  - skip already processed records.
- Use batches for deletes and large updates.
- Commit intentionally after bounded batches or successful processing chunks.
- Return stats from cron functions so manual runs are inspectable.
- Handle external API cache/refresh cases with retries when needed.

For Kunal Enterprise, likely cron candidates:

- Tally mirror sync status checks.
- Product Group / item snapshot refresh.
- Order fulfillment reconciliation from Tally Delivery Challan and Sales Invoice.
- Manual Review reason generation.
- Cleanup of expired OTPs/tokens.

## Fixtures

Fixtures in SF-DPMS seed the app with operational configuration:

- roles;
- role profiles;
- custom doc permissions;
- workflows, states, and actions;
- salary components;
- leave types;
- payroll settings;
- designations;
- workspaces.

Keypoints:

- Export fixtures as JSON under `<app>/fixtures`.
- Keep role and permission fixtures in sync with hooks and DocType permissions.
- Use workflow fixtures when document lifecycle is business-critical and must install consistently.
- Treat fixtures as install/migration artifacts, not runtime mutable business data.
- Review large fixtures for accidental environment-specific values before committing.
- For Kunal Enterprise, likely fixtures include roles, workspace, custom doc permissions, workflow states for Customer review and Order lifecycle, and any standard lookup records required by the app.

## Security And Privacy

Important SF-DPMS practices to preserve:

- Use JWT plus backing database token rows so tokens can be revoked.
- Check active identity status on every protected request.
- Check app version on OTP send, OTP verify, and token verification.
- Store auth metadata in DocTypes, not only in stateless JWTs.
- Hide sensitive field changes from Version records when necessary.
- Use `frappe.log_error` for server diagnostics while returning simple user-safe messages.
- Avoid returning stack traces to clients except in clearly internal/dev-only APIs.
- Use explicit HTTP status codes.

Improvements to apply while following the pattern:

- Escape all dynamic SQL values in permission conditions.
- Avoid granting Guest permissions on token storage DocTypes unless the endpoint truly requires it; whitelisted methods can create rows server-side without giving broad DocType access.
- Do not keep production OTP bypasses.
- Avoid raw `print` in cron jobs for new code; use `frappe.logger()`.
- Prefer Frappe transaction boundaries instead of frequent commits inside hooks.

## New Feature Checklist

When adding a new API-backed feature:

1. Create or update the DocType JSON and Python class.
2. Add server-side validation in the DocType class if the rule belongs to that document.
3. Add API functions in a feature-specific file under `api/`.
4. Use `verify_token` for protected mobile endpoints.
5. Use shared success/error helpers.
6. Add permission query condition files for any listable DocType with row-level access.
7. Register permissions, events, overrides, and cron jobs in `hooks.py`.
8. Add fixtures for roles, permissions, workflows, and workspace records if install-time setup is required.
9. Add document events only for cross-document lifecycle workflows.
10. Add focused tests for validation, permission behavior, token/auth behavior, and cron idempotency.

