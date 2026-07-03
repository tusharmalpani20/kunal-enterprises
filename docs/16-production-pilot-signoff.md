# Production Pilot Sign-Off

Use this optional document to capture production pilot evidence for the Kunal Enterprises Frappe backend and mobile app.

This sign-off does not close the optional Tally and WhatsApp operational proof checklist listed in `docs/12-operational-readiness-checklist.md`. It proves the built portal/backend and mobile app are usable against the target runtime setup with representative users and data when the release team wants that evidence.

## Pilot Metadata

| Field | Value |
| --- | --- |
| Pilot date/time | |
| Frappe site URL | |
| Frappe app version or commit | |
| Mobile app version or commit | |
| Expo/Frappe base URL used by mobile app | |
| Pilot Customer names | |
| Pilot Sales Employee names | |
| Accepted by | |
| Acceptance date | |

## Preflight Evidence

| Gate | Evidence |
| --- | --- |
| Backend migration completed on target site | |
| Backend tests passed on current app build | |
| Mobile tests passed on current app build | |
| Mobile typecheck passed on current app build | |
| Mobile app points to target Frappe base URL | |
| Pilot Customers have active Customer App Access | |
| Pilot Sales Employees are active and assigned intended Customers/Product Groups | |
| Product Groups, Items, Godowns, and Stock Snapshots exist for pilot data | |

## Customer Flow Evidence

Capture one complete Customer run.

| Step | Expected result | Evidence |
| --- | --- | --- |
| Customer signup submits name, business/legal name, GSTIN, mobile number, email ID, date of birth, and date of anniversary | Customer reaches OTP or pending review flow without Client Code shown | |
| Existing Customer OTP login | Active Customer reaches order home | |
| Pending or access-removed Customer login | Customer is blocked with a user-facing access state | |
| Product Group list | Only backend-allowed Product Groups appear | |
| Item search/list | Only backend-allowed Items appear | |
| Godown stock screen | Positive-stock godowns appear before zero-stock godowns and show latest sync timestamp | |
| Cart and confirmation | Quantity-only cart shows no prices/rates/taxes/values and shows advisory stock notes when relevant | |
| Final Customer order submit | App shows backend Order reference in `KE-YY-MM-####` format | |
| Customer order history/detail | Self-placed and Sales Employee-placed Orders are visible, Manual Review appears as Under Review, and internal reasons are hidden | |
| Customer profile update | Only email ID, date of birth, and date of anniversary are editable | |

## Sales Employee Flow Evidence

Capture one complete Sales Employee run.

| Step | Expected result | Evidence |
| --- | --- | --- |
| Sales Employee OTP login | Active Sales Employee reaches Customer selection | |
| Disabled Sales Employee login | Sales Employee is blocked with a user-facing access state | |
| Customer search by name/business name/Client Code | Search can find intended Customer but Client Code is not displayed | |
| Customer selection before ordering | Ordering screens stay blocked until a Customer is selected | |
| Product Group and Item visibility | Results reflect selected Customer plus Sales Employee effective access | |
| Godown stock screen | Stock is advisory and zero-stock godown allocation remains allowed | |
| Cart and optional internal note | Note is accepted for Sales Employee order and remains internal | |
| Final Sales Employee order submit | App shows backend Order reference in `KE-YY-MM-####` format | |
| Sales Employee order history/detail | History includes only Orders placed by that Sales Employee | |
| Sales Employee profile | Profile is read-only | |

## Failure-State Evidence

Capture at least one run for each state before production rollout.

| State | Expected result | Evidence |
| --- | --- | --- |
| No network or backend unavailable during final submit | Recoverable error appears and no fake confirmed Order is shown | |
| Expired or invalid token | App logs out or returns to login without exposing protected data | |
| Backend validation error | User-facing validation copy appears without stack traces | |
| Stock changed since screen loaded | Confirmation requires review of refreshed stock note before final submit | |
| Disabled/access-removed account after login | Protected data loading is blocked on next backend check | |

## Final Decision

| Decision | Owner | Date | Notes |
| --- | --- | --- | --- |
| Accept for controlled production use | | | |
| Reject / more work required | | | |

Keep this document as release/operations evidence when a pilot is run; it is not a blocker for the current build goal.
