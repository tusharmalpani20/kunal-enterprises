# Foundation TDD Log

## Cycle 155: Workspace Rename And Bench Symlink

Red:
- The project workspace still lived under a path with a space, and the local Frappe bench lived in `/private/tmp` with the app copied into the bench. That meant backend commands were not running directly against the repo app source.

Green:
- Renamed the workspace folder to `/Volumes/a909SSD/Development/Kunal-Enterprises`.
- Moved the Frappe bench to `/Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench`.
- Replaced `ke-frappe-bench/apps/kunal_enterprises` with a symlink to `kunal-enterprises/apps/kunal_enterprises`.
- Repaired the bench console script and bench virtualenv `.pth` files after the move.
- Updated handoff docs and verification guards so there is no copy step for the backend app.

Verification:
```sh
./scripts/verify-local.sh
```

Result:
- Backend smoke succeeded
- Backend `Ran 86 tests` / `OK`
- Mobile audit `found 0 vulnerabilities`
- Mobile `tests 103`
- Mobile `pass 103`
- `tsc --noEmit` passed

## Cycle 154: Tally And WhatsApp Proof Excluded From Build Goal

Red:
- The handoff docs still treated external Tally/WhatsApp operational proof and production pilot sign-off as blockers, even after the current scope changed to exclude those proof gates from the build goal.

Green:
- Reclassified Tally/WhatsApp proof and production pilot sign-off as optional release/operations follow-up in the root README, delivery audit, production pilot template, and goal completion matrix.
- Updated documentation guards so completion evidence focuses on repo-local backend/mobile build verification.

Verification:
```sh
./scripts/verify-local.sh
```

Result:
- Backend smoke succeeded
- Backend `Ran 86 tests` / `OK`
- Mobile audit `found 0 vulnerabilities`
- Mobile `tests 103`
- Mobile `pass 103`
- `tsc --noEmit` passed

## Cycle 153: Executable Local Verification Script

Red:
- `scripts/verify-local.sh` existed and passed through `bash`, but the handoff was smoother if operators could run it directly and the docs/tests proved that executable bit.

Green:
- Marked `scripts/verify-local.sh` executable.
- Updated root README and delivery audit to use `./scripts/verify-local.sh`.
- Extended the documentation guard to assert the script is executable.

Verification:
```sh
./scripts/verify-local.sh
```

Result:
- Backend smoke succeeded
- Backend `Ran 86 tests` / `OK`
- Mobile audit `found 0 vulnerabilities`
- Mobile `tests 103`
- Mobile `pass 103`
- `tsc --noEmit` passed

## Cycle 152: Local Verification Script

Red:
- Backend and mobile verification commands were documented, but there was no single repo-local command that reran the main local build checks end to end.

Green:
- Added `scripts/verify-local.sh` to sync the Frappe app into the bench, run backend smoke, run backend tests, run mobile production dependency audit, run mobile tests, and run mobile typecheck.
- Linked the script from the root README, delivery audit, and goal completion matrix.
- Added a documentation guard proving the script includes the expected backend and mobile checks.

Verification:
```sh
cd apps/mobile
npm test
npm run typecheck
```

Result:
- `tests 103`
- `pass 103`
- `tsc --noEmit` passed

## Cycle 151: Mobile Environment Example

Red:
- The mobile app documented `EXPO_PUBLIC_FRAPPE_BASE_URL`, but there was no checked-in example environment file tying the operator-facing setup to the runtime config default.

Green:
- Added `apps/mobile/.env.example` with the local Frappe base URL.
- Linked the example from the root README, mobile README, and delivery audit.
- Added a runnability guard proving `.env.example`, `src/constants/config.ts`, README, and audit docs agree on the backend base URL.

Verification:
```sh
cd apps/mobile
npm test
npm run typecheck
```

Result:
- `tests 102`
- `pass 102`
- `tsc --noEmit` passed

## Cycle 150: Goal Completion Matrix

Red:
- The delivery audit had strong evidence sections, but there was no single requirement-by-requirement matrix mapping all three goal prompts to achieved evidence, deferred external gates, and the reason the full goal remains open.

Green:
- Added `docs/17-goal-completion-matrix.md` covering Goal 1, Goal 2, Goal 3, local evidence, and open production/Tally/WhatsApp gates.
- Linked the matrix from the root README and delivery audit.
- Added a documentation guard so the matrix remains part of the handoff evidence.

Verification:
```sh
cd apps/mobile
npm test
npm run typecheck
```

Result:
- `tests 101`
- `pass 101`
- `tsc --noEmit` passed

## Cycle 149: Mobile Dependency Audit Uses Patched PostCSS

Red:
- `npm audit --omit=dev` reported a moderate advisory in Expo's transitive `postcss@8.4.49`. The automatic force fix would upgrade Expo to SDK 55, which is a breaking SDK change outside the current app target.

Green:
- Added a targeted npm override for `postcss@8.5.10`, preserving Expo SDK 53 while applying the patched transitive version.
- Refreshed `package-lock.json`.
- Documented the clean production audit in the mobile README, root README, and delivery audit.
- Extended the mobile runnability guard to protect the override.

Verification:
```sh
cd apps/mobile
npm install
npm audit --omit=dev
npm ls postcss
npm test
npm run typecheck
```

Result:
- `npm audit --omit=dev`: `found 0 vulnerabilities`
- `postcss@8.5.10 overridden`
- `tests 100`
- `pass 100`
- `tsc --noEmit` passed

## Cycle 148: Backend App README Handoff

Red:
- `apps/kunal_enterprises/README.md` still contained generated Frappe scaffold instructions instead of the project-specific bench path, mirror step, test command, runtime command, and operational gate references needed for handoff.

Green:
- Replaced the scaffold README with Kunal Enterprises backend app documentation covering implemented behavior, local bench path, app mirror step, explicit bench executable, migrate/smoke/test/serve commands, verified local state, API docs, and remaining operational gates.
- Added a documentation guard so the backend app README keeps app-specific handoff content.

Verification:
```sh
cd apps/mobile
npm test
npm run typecheck
```

Result:
- `tests 100`
- `pass 100`
- `tsc --noEmit` passed

## Cycle 147: Root Repo Handoff README

Red:
- Backend and mobile app docs existed, but the repository root had no handoff entry point tying the Goal prompts to the two runnable apps, verified commands, runtime evidence, and remaining operational gates.

Green:
- Added root `README.md` covering the Frappe backend, Expo mobile app, current verification commands, handoff documents, and the still-open production/Tally/WhatsApp gates.
- Added a documentation guard requiring the root README to name both apps, key run/test commands, live mobile base URL usage, and remaining gate status.

Verification:
```sh
cd apps/mobile
npm test
npm run typecheck
```

Result:
- `tests 99`
- `pass 99`
- `tsc --noEmit` passed

## Cycle 146: Expo Startup Uses Verified Metro Command And Compatible Package Pins

Red:
- The documented `npm run start -- --web --port 19006` runtime check only proved Expo reached initial startup text. Re-running it showed the `--port` flag does not apply to web startup, and sandboxed port probing could crash before a usable dev server was listening.
- Expo also warned that semver ranges had installed package versions newer than the Expo SDK 53 compatibility set.

Green:
- Verified the mobile runtime with `npx expo start --localhost --port 8081`, which reached `Metro waiting on exp://127.0.0.1:8081`.
- Verified `curl -I http://127.0.0.1:8081` returned `HTTP/1.1 200 OK`.
- Pinned React Native, React, AsyncStorage, SVG, TypeScript, and React types to the versions Expo expected and refreshed the lockfile.
- Updated README, delivery audit, UI coverage, and runnability tests to record the stronger startup evidence.

Verification:
```sh
cd apps/mobile
npm install
npx expo start --localhost --port 8081
curl -I http://127.0.0.1:8081
npm test
npm run typecheck
```

Result:
- Metro reached `exp://127.0.0.1:8081`
- `HTTP/1.1 200 OK`
- `tests 98`
- `pass 98`
- `tsc --noEmit` passed

## Cycle 145: Production Pilot Sign-Off Evidence Template

Red:
- The delivery audit named the remaining non-deferred production pilot sign-off gate, but there was no repo-local template that operators could use to capture Customer, Sales Employee, preflight, and failure-state evidence for that gate.

Green:
- Added `docs/16-production-pilot-signoff.md` with metadata, preflight checks, Customer flow evidence, Sales Employee flow evidence, failure-state evidence, and final decision capture.
- Linked the sign-off template from the delivery audit and added a documentation guard so the template remains part of the handoff evidence.

Verification:
```sh
cd apps/mobile
npm test
npm run typecheck
```

Result:
- `tests 97`
- `pass 97`
- `tsc --noEmit` passed

## Cycle 144: Frappe Provider Clears SDK Handles Without Access Token

Red:
- The Frappe provider cleared SDK handles when `accessToken` was absent, but the source guard only protected SDK creation and interceptor behavior, not logout cleanup.

Green:
- Extended the Frappe provider contract test to require `db`, `call`, `auth`, and `file` to be reset to `null` when there is no access token.
- This keeps live API mode from lingering after logout/session removal.

Verification:
```sh
cd apps/mobile
npm test
npm run typecheck
```

Result:
- `tests 96`
- `pass 96`
- `tsc --noEmit` passed

## Cycle 143: Godown Stock Rows Show Sync Timestamp

Red:
- The mobile stock screen showed quantity as latest synced, but did not show the latest sync timestamp even though Goal 3 requires the app to show the latest available stock and last synced timestamp.

Green:
- Added `stockRowDetailForMobile` to include `synced_at` or `as_on_date` in stock row detail text.
- Wired godown stock rows to render the formatter so Customers and Sales Employees can see when the advisory stock was synced.

Verification:
```sh
cd apps/mobile
npm test
npm run typecheck
```

Result:
- `tests 96`
- `pass 96`
- `tsc --noEmit` passed

## Cycle 142: Sales Employee Item And Stock Calls Preserve Effective Access

Red:
- Sales Employee Product Groups were loaded with the Sales Employee identity, but the follow-on allowed item, item stock, and pre-submit stock refresh calls only sent the selected Customer. That could bypass the backend's Customer plus Sales Employee effective access checks.

Green:
- Added `activeSalesEmployeeContext()` in the mobile screen and passed it to `api.allowedItems(...)`, `api.itemStock(...)`, and pre-submit stock refresh when mode is Sales Employee.
- Added live Frappe client coverage proving `sales_employee` is sent to item and stock access endpoints.
- Added a source guard so the screen keeps threading Sales Employee context through those calls.

Verification:
```sh
cd apps/mobile
npm test
npm run typecheck
```

Result:
- `tests 95`
- `pass 95`
- `tsc --noEmit` passed

## Cycle 141: Protected Mobile APIs Wait For Active Session

Red:
- The mobile app could call protected Product Group, allowed Customer, History, or Profile APIs from fallback fixture identities before OTP produced a session for the active mode.

Green:
- Added `canUseProtectedMobileApi` to require a matching `identityType`, `identity`, and `accessToken`.
- Gated automatic protected list loading plus History/Profile actions behind the active-mode session check.
- Kept fallback identities available for deterministic fixture/domain behavior without using them as live protected API proof.

Verification:
```sh
cd apps/mobile
npm test
npm run typecheck
```

Result:
- `tests 93`
- `pass 93`
- `tsc --noEmit` passed

## Cycle 140: Invalid Order Quantity Shows Recoverable Mobile Validation

Red:
- The mobile stock screen passed raw `TextInput` quantity values into `addAllocation`, so blank, zero, or invalid quantities could throw instead of showing the app's validation banner.

Green:
- Added `parseOrderQuantityInput` to convert order quantity input into either a valid number or a recoverable validation state.
- Wired the godown add action to keep the user on the stock screen with `Order Quantity must be positive.` when input is invalid.

Verification:
```sh
cd apps/mobile
npm test
npm run typecheck
```

Result:
- `tests 92`
- `pass 92`
- `tsc --noEmit` passed

## Cycle 139: OTP Resend Is Scoped To The Same Auth Identity

Red:
- After an OTP request, changing the mobile number, Customer login/signup intent, or auth mode could still make the next available OTP action use `resendOtp`.

Green:
- Added `otpRequestKey` and extended `shouldUseOtpResend` so resend is allowed only for the same mode, intent, and mobile number that received the previous OTP.
- Stored the last OTP request key in the auth screen and reset it when switching modes.
- Preserved first-send/signup behavior when the current auth identity differs from the previous OTP target.

Verification:
```sh
cd apps/mobile
npm test
npm run typecheck
```

Result:
- `tests 91`
- `pass 91`
- `tsc --noEmit` passed

## Cycle 138: Mobile OTP Resend Uses Backend Resend Endpoint

Red:
- The mobile adapters exposed `resendOtp`, but the auth screen called the initial send/signup path again after the backend-defined cooldown elapsed.

Green:
- Added `shouldUseOtpResend` to distinguish first OTP request from a post-cooldown resend.
- Wired Customer and Sales Employee auth to call `api.resendOtp(mobileNumber, identityType)` after a previous send and completed cooldown.
- Added live Frappe client coverage for `kunal_enterprises.api.otp.resend_otp`.

Verification:
```sh
cd apps/mobile
npm test
npm run typecheck
```

Result:
- `tests 90`
- `pass 90`
- `tsc --noEmit` passed

## Cycle 137: Customer Signup Blocks Missing Required Fields

Red:
- Customer signup collected the required fields, but the mobile app could still call the signup OTP API with blank required values.

Green:
- Added `validateCustomerSignupInput` to require Customer name, business/legal name, GSTIN, mobile number, email ID, date of birth, and date of anniversary before signup OTP.
- Wired the Customer signup button to show a recoverable validation banner and skip the API call when fields are missing.
- Kept signup payload construction trimming values and excluding Client Code.

Verification:
```sh
cd apps/mobile
npm test
npm run typecheck
```

Result:
- `tests 88`
- `pass 88`
- `tsc --noEmit` passed

## Cycle 136: Customer Signup Uses Entered Form Fields

Red:
- The mobile Customer signup path rendered a Login/Signup selector, but `requestOtp()` still built the signup payload with fixture values such as `Asha Textiles` instead of fields entered by the user.

Green:
- Added Customer signup form state and visible inputs for Customer name, business/legal name, GSTIN, email ID, date of birth, and date of anniversary.
- Changed Customer signup OTP requests to build the payload from those entered form values while keeping Customer login on the shared OTP endpoint.
- Added a mobile source guard proving the signup screen exposes the required fields and no longer embeds fixture customer defaults.

Verification:
```sh
cd apps/mobile
npm test
npm run typecheck
```

Result:
- `tests 87`
- `pass 87`
- `tsc --noEmit` passed

## Cycle 135: Existing Customer OTP Login Uses Send OTP

Red:
- The mobile Customer auth screen always called Customer signup to request an OTP. That supports first-time signup, but an existing approved Customer logging back in must use the backend `send_otp` endpoint with `identity_type = Customer`.

Green:
- Added a live Frappe client test proving existing Customer OTP login calls `kunal_enterprises.api.otp.send_otp` with `identity_type: Customer`.
- Added `startCustomerOtp` to the live and mock mobile API adapters.
- Added an explicit Customer Login/Signup switch on the auth screen. Customer Login sends OTP through the shared OTP endpoint; Customer Signup still creates the signup payload and starts the signup OTP flow.

Verification:
```sh
cd apps/mobile
npm test
npm run typecheck
```

Result:
- `tests 86`
- `pass 86`
- `tsc --noEmit` passed

## Cycle 134: Mobile Startup Validates Stored Sessions Through Frappe SDK

Red:
- The mobile session domain had refresh behavior, but the app root did not pass a validator into `AuthProvider`, so stored sessions could be exposed on app start before the backend confirmed the token was still active.
- The live Frappe client also passed current-session/logout headers as whitelisted method parameters, even though `frappe-js-sdk` sends custom `Auth-Token` headers through the Axios client.

Green:
- Added a mobile source guard proving `AuthProvider` defaults to `validateStoredMobileSession`.
- Implemented `validateStoredMobileSession` with `FrappeApp`, `APP_CONFIG.BASE_URL`, custom `Auth-Token` headers, and the existing Frappe API client.
- Changed live `currentSession` and `revokeToken` calls to rely on SDK-level headers instead of sending a `headers` request parameter.
- Updated the Frappe client test to assert current-session/logout do not leak headers into request params.

Verification:
```sh
cd apps/mobile
npm test
npm run typecheck
```

Result:
- `tests 85`
- `pass 85`
- `tsc --noEmit` passed

## Cycle 133: Mobile Token APIs Are Guest-Whitelisted

Red:
- Mobile protected endpoints use custom `Auth-Token` verification, but several were not registered as Frappe guest methods. In a real HTTP request, Frappe would require Desk login before the custom mobile token verifier could run.

Green:
- Added a backend install-visible test that checks every mobile token API is present in Frappe's `guest_methods` registry.
- Marked Customer App Access, Product Group/item/stock, Sales Employee allowed customers, Order submit/history/detail, and Profile get/update endpoints as `allow_guest=True`.
- Left Desk/branch/admin APIs session-protected.
- Documented that mobile protected APIs are guest-whitelisted for reachability and then enforce the custom mobile token inside the endpoint.

Verification:
```sh
cp -R /Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/apps/kunal_enterprises/. /Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench/apps/kunal_enterprises
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 86 tests`
- `OK`

## Cycle 132: Branch APIs Use Session Role And Branch Permission

Red:
- Branch order APIs accepted `role` and `branch` request parameters as proof of authority, so a caller could claim `Branch Manager` or query an unassigned branch.

Green:
- Added a backend public-behavior test covering:
  - a non-branch user claiming `Branch Manager`;
  - a Branch Employee querying a branch without matching `Portal Branch` `User Permission`;
  - a Branch Employee claiming `Branch Manager`;
  - a valid Branch Employee processing a visible Placed order.
- Updated branch order APIs to require the current Frappe session user to have the requested branch role and a matching active `Portal Branch` `User Permission`.
- Preserved the `Administrator` path for bench/test operations.

Verification:
```sh
cp -R /Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/apps/kunal_enterprises/. /Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench/apps/kunal_enterprises
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 85 tests`
- `OK`

## Cycle 131: Owner/Admin Sync Authorization Uses Session Roles

Red:
- Manual sync APIs enforced Owner/Admin access from a request `role` parameter, so a non-owner caller could claim `Owner` and run privileged sync work.

Green:
- Added a backend public-behavior test where a Branch Manager session claims `Owner` for `sync_masters_now` and is rejected, while a real Owner session succeeds.
- Updated manual sync authorization to require both an allowed action role and that role on the current Frappe session user.
- Applied the same session-role check to Owner/Admin order controls while preserving the Frappe `Administrator` superuser path for bench operations.

Verification:
```sh
cp -R /Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/apps/kunal_enterprises/. /Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench/apps/kunal_enterprises
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 84 tests`
- `OK`

## Cycle 130: Mobile Packaging Boundary Guard

Red:
- `apps/mobile/node_modules/` existed after the runnable Expo verification, but the repository ignore rules did not explicitly protect the mobile dependency/cache/build directories while keeping the lockfile trackable.

Green:
- Added explicit ignore rules for `apps/mobile/node_modules/`, `.expo/`, `dist/`, and `.metro/`.
- Added a mobile runnability test proving those generated runtime paths are ignored and `apps/mobile/package-lock.json` remains trackable.
- Updated the mobile delivery evidence from `83` to `84` passing tests.

Verification:
```sh
cd apps/mobile
npm test
```

Result:
- `tests 84`
- `pass 84`

## Cycle 129: Tally Pilot Evidence Template

Red:
- The readiness checklist defined the external Tally gates but did not provide a repeatable capture form with concrete SQL checks for the controlled pilot.

Green:
- Added `docs/15-tally-pilot-evidence-template.md` with pilot metadata, SQL capture steps, expected results, comparison tables, and production sign-off rows for:
  - portal reference field proof;
  - voucher line match proof;
  - Customer ledger filter proof;
  - godown and branch mapping proof;
  - godown-wise stock snapshot proof;
  - WhatsApp provider proof.
- Linked the template from the operational readiness checklist and delivery audit.
- Added a documentation guard for the template sections and SQL anchors.

Verification:
```sh
cd apps/mobile
npm test
npm run typecheck
```

Result:
- `tests 84`
- `pass 84`
- `tsc --noEmit` passed

## Cycle 128: Confirmation Artifact Monetary Exclusions

Red:
- Goal 2 requires Customer confirmation PDFs and WhatsApp payloads to exclude price, rate, tax, value, stock availability, Sales Employee internal note, and Client Code.
- Existing tests covered note, Client Code, stock snapshot value, and customer-only recipient behavior, but did not explicitly assert monetary term exclusions in the generated confirmation artifacts.

Green:
- Tightened the Order confirmation artifact test to assert the `Order PDF.summary_text` and `Order WhatsApp Notification.request_payload` do not contain `price`, `rate`, `tax`, `value`, `amount`, or `discount`.

Verification:
```sh
cp -R /Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/apps/kunal_enterprises/. /Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench/apps/kunal_enterprises
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 83 tests`
- `OK`

## Cycle 127: Response Envelope HTTP Status Metadata

Red:
- Goal 2 requires consistent success/error envelopes and HTTP status codes. The utility layer set `frappe.local.response["http_status_code"]`, but there was no focused backend test proving the returned envelope and Frappe response metadata stay synchronized.

Green:
- Added a backend test for `create_success_response` and `handle_error_response`.
- The test verifies success/error envelope shape, body `http_status_code`, actual `frappe.local.response["http_status_code"]`, and `PermissionError` mapping to `403`.
- Updated delivery audit backend verification evidence.

Verification:
```sh
cp -R /Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/apps/kunal_enterprises/. /Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench/apps/kunal_enterprises
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 83 tests`
- `OK`

## Cycle 126: Mobile Component Convention Evidence

Red:
- Goal 3 asks for `react-native-reusables` components unless the app setup proves a better local convention.
- Dependency verification had already proven the runtime `react-native-reusables` package is not publishable, but the exception and replacement convention were not explicitly documented or guarded.

Green:
- Added `docs/14-mobile-component-convention.md` explaining the unavailable runtime package, installed `@react-native-reusables/cli`, and the local React Native primitive plus `lucide-react-native` component convention.
- Linked the component convention from the mobile UI coverage audit and delivery audit.
- Added guards verifying the documentation, package dependency shape, local `Pressable`/`TextInput` primitive usage, `lucide-react-native`, `Workspace`, and `RowButton`.

Verification:
```sh
cd apps/mobile
npm test
npm run typecheck
```

Result:
- `tests 82`
- `pass 82`
- `tsc --noEmit` passed

## Cycle 125: Mobile Frappe Provider Contract Guard

Red:
- Goal 3 gives a specific Frappe provider baseline: SDK services for `FrappeDB`, `FrappeAuth`, `FrappeCall`, and `FrappeFileUpload`, an `Auth-Token` bearer header, and invalid-token logout behavior.
- The provider matched this shape, but there was no source-level guard protecting it.

Green:
- Added a mobile source test that verifies `src/providers/frappe.tsx` preserves the SDK imports, context fields, `useToken: false`, bearer `Auth-Token`, invalid-token messages, router logout redirect, and service setters.
- Updated delivery audit mobile verification counts.

Verification:
```sh
cd apps/mobile
npm test
npm run typecheck
```

Result:
- `tests 80`
- `pass 80`
- `tsc --noEmit` passed

## Cycle 124: Desk Order Permission Query Hooks

Red:
- Goal 2 requires portal row-level visibility and the app structure includes `permission_query_conditions`, but Order Desk permissions were only covered through branch API filtering.

Green:
- Registered `Order` `permission_query_conditions` and `has_permission` hooks in `hooks.py`.
- Added `permission_query_conditions/orders.py` so Owner/Admin/System Manager can see all Orders, while Branch Manager and Branch Employee Desk visibility is scoped through `Portal Branch` `User Permission` records expanded via active `Branch Godown Mapping` rows.
- Branch Employee Desk visibility is additionally limited to `Placed`, `Processing`, and `Manual Review`.
- Added backend tests for hook registration and branch user permission scoping.
- Documented the Desk permission behavior in the backend API docs and delivery audit.

Verification:
```sh
cp -R /Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/apps/kunal_enterprises/. /Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench/apps/kunal_enterprises
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 82 tests`
- `OK`

Follow-up:
- Strengthened the permission test to run real `frappe.get_list("Order")` calls as Branch Employee and Branch Manager users with `Portal Branch` `User Permission` records.
- The Branch Employee sees only branch-mapped Orders in `Placed`, `Processing`, or `Manual Review`; the Branch Manager sees branch-mapped Orders across statuses; neither sees Orders for unmapped godowns.
- Re-ran the backend suite after the stronger test: `Ran 83 tests` / `OK`.

## Cycle 123: Mobile UI Coverage Audit

Red:
- Goal 3 lists specific Customer screens, Sales Employee screens, and shared states, but the repo only documented broad mobile behavior. The current Expo app implements these as state-driven workspaces in one route, so the screen coverage needed an explicit audit.

Green:
- Added `docs/13-mobile-ui-coverage.md`, mapping the required Goal 3 screens and shared states to `apps/mobile/app/index.tsx`, providers, API adapters, storage, and domain modules.
- Linked UI screen coverage from the delivery audit.
- Added a documentation guard requiring the UI coverage audit to include Customer screens, Sales Employee screens, shared states, and the implementation path.

Verification:
```sh
cd apps/mobile
npm test
npm run typecheck
```

Result:
- `tests 79`
- `pass 79`
- `tsc --noEmit` passed

## Cycle 122: Operational Readiness Checklist

Red:
- The delivery audit listed unresolved Tally and operational questions, but the repo did not define the exact evidence required to close each one.

Green:
- Added `docs/12-operational-readiness-checklist.md` with required confirmations for the Tally portal reference field, Main Location branch mapping, Seetarambagh interpretation, Customer ledger import filter, godown-wise stock snapshot validation, and WhatsApp provider credentials.
- Linked the readiness checklist from the delivery audit and expanded the unresolved operational question list to include stock snapshot validation and live WhatsApp provider credentials.
- Added a documentation guard that requires the checklist to keep evidence requirements, system actions, pilot gate, and production gate language.

Verification:
```sh
cd apps/mobile
npm test
npm run typecheck
```

Result:
- `tests 78`
- `pass 78`
- `tsc --noEmit` passed

## Cycle 121: Backend API Documentation Scope Guard

Red:
- Goal 2 requires backend API documentation with request/response examples, response envelopes, status codes, manual sync APIs, scheduler entry points, and reconciliation behavior.
- The documentation existed, but no guard explicitly protected that scope from drifting.

Green:
- Added a documentation test that verifies `docs/10-backend-api.md` covers the response envelope, HTTP status code guidance, auth header, major mobile/backend API examples, Owner/Admin order controls, manual sync APIs, five-minute scheduler entry points, and Manual Review reconciliation reason codes.
- Updated delivery audit mobile verification counts after the new guard.

Verification:
```sh
cd apps/mobile
npm test
```

Result:
- `tests 77`
- `pass 77`

## Cycle 120: Foundation Runtime Response Evidence

Red:
- The delivery audit summarized Goal 1 foundation coverage but did not explicitly carry fresh evidence for the local Frappe HTTP response acceptance check.

Green:
- Reverified current bench installed apps with `bench --site kunal.localhost list-apps`: `frappe 15.103.3`, `kunal_enterprises 0.0.1`, and `frappe_whatsapp 1.0.7`.
- Reverified the site config uses PostgreSQL via `sites/kunal.localhost/site_config.json`.
- Started `bench serve --port 8000`, verified `curl -I http://127.0.0.1:8000` returned `HTTP/1.1 200 OK` with `X-Page-Name: login`, then stopped the temporary server.
- Updated the foundation and delivery audit docs, and added a documentation guard for the local server response evidence.
- Updated the mobile verification count to the current `76` passing tests after adding the guard.

Verification:
```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost list-apps
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench serve --port 8000
curl -I http://127.0.0.1:8000
```

Result:
- `frappe 15.103.3`, `kunal_enterprises 0.0.1`, `frappe_whatsapp 1.0.7`
- `HTTP/1.1 200 OK`
- `X-Page-Name: login`
- Mobile `tests 76`
- Mobile `pass 76`

## Cycle 119: Delivery Audit Acceptance Coverage

Red:
- The delivery audit documented handoff outcomes but did not explicitly map the three `/goal` prompts to acceptance-test coverage.

Green:
- Added an `Acceptance Coverage` table to `docs/11-delivery-audit.md` covering Goal 1 foundation checks, Goal 2 backend/API behavior clusters, and Goal 3 mobile behavior clusters.
- Added a mobile documentation guard so the audit must keep the goal-prompt coverage mapping.
- Refreshed backend evidence with a 2026-05-19 `Ran 80 tests` / `OK` run and updated mobile count to the current `75` passing tests.

Verification:
```sh
.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
cd apps/mobile
npm test
```

Result:
- Backend `Ran 80 tests` / `OK`
- Mobile `tests 75`
- Mobile `pass 75`

## Cycle 118: Mobile Dependency Install And Typecheck Verification

Red:
- Ran bounded mobile dependency installation attempts and surfaced real npm resolver failures:
  - `lucide-react-native@0.468.0` did not support React 19.
  - transitive latest `react-native-screens` required React Native 0.82+.
  - `react-native-reusables` was not a published runtime package.
- After resolving dependencies, `npm run typecheck` exposed TypeScript issues in the Expo screen and JS domain boundary types.

Green:
- Updated mobile dependencies to a React 19 compatible `lucide-react-native`, added `react-native-svg`, pinned `react-native-screens` to a React Native 0.79 compatible version, and replaced the unpublished runtime package with the installable React Native Reusables CLI.
- Fixed Expo screen TypeScript errors and added JS JSDoc casts for stock-review defaults.
- Generated `apps/mobile/package-lock.json`, installed dependencies, verified `npm run typecheck`, and verified Expo startup reached `Starting project`.
- Updated delivery audit, mobile README, and runnability guards from unresolved runtime gate to verified install/typecheck/start evidence.

Verification:
```sh
cd apps/mobile
npm test
npm run typecheck
npm run start -- --web --port 19006
```

Result:
- `tests 74`
- `pass 74`
- `tsc --noEmit` passed
- Expo startup reached `Starting project`

## Cycle 117: Mobile Runtime Gate Filesystem Evidence

Red:
- Added a mobile runnability documentation test that inspects the current dependency artifact state.
- The test verifies the delivery audit's unresolved runtime gate is backed by no `node_modules` and no package lockfile in `apps/mobile`.

Green:
- The delivery audit already documented the missing install artifacts and unverified `npm install`, `npm run typecheck`, and Expo startup gates, so no audit text change was needed.

Verification:
```sh
cd apps/mobile
npm test
```

Result:
- `tests 74`
- `pass 74`

## Cycle 116: Delivery Audit Runtime Gate Accuracy

Red:
- Tightened the delivery audit guard so the audit must explicitly distinguish verified mobile tests from unverified mobile runtime/typecheck commands.
- The guard requires the audit to document that `npm run typecheck` and Expo startup remain unverified until dependencies are installed.

Green:
- Renamed the audit command section to `Commands Verified`.
- Moved mobile `npm install`, `npm run typecheck`, and Expo startup commands into `Commands Documented But Not Yet Verified`.
- Added an unresolved mobile dependency/runtime verification item tied to the absence of installed dependencies.

Verification:
```sh
cd apps/mobile
npm test
```

Result:
- `tests 74`
- `pass 74`

## Cycle 115: Delivery Audit Verification Counts

Red:
- Tightened the delivery audit documentation guard to require the current backend and mobile test counts.
- The guard now fails if the audit drifts away from `Ran 80 tests` for backend verification or `73 tests` for mobile verification.

Green:
- Updated `docs/11-delivery-audit.md` with the latest backend and mobile verification results.

Verification:
```sh
cd apps/mobile
npm test
```

Result:
- `tests 73`
- `pass 73`

## Cycle 114: Manual Review Reason Code Enforcement

Red:
- Added a public DocType validation test that tries to insert `Order Reconciliation Log` rows with `status = Manual Review` while omitting either `reason_code` or `message`.
- The behavior verifies Manual Review logs cannot exist without both structured and human-readable reasons.

Green:
- Added `OrderReconciliationLog.validate` to require `reason_code` and `message` only for Manual Review rows.
- Updated backend API docs to state that Manual Review reconciliation logs require both fields.

Verification:
```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 80 tests`
- `OK`

## Cycle 113: Branch Manual Review Reason Code Visibility

Red:
- Extended the branch visible-orders behavior test for a Manual Review order.
- The test verifies branch operations receive both `manual_review_reason` and `manual_review_reason_code` from the latest reconciliation log.

Green:
- Updated branch order serialization to return the latest Manual Review `reason_code` beside the message.
- Updated backend API docs for branch visible-orders Manual Review fields.

Verification:
```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 79 tests`
- `OK`

## Cycle 112: Manual Review Reconciliation Reason Codes

Red:
- Tightened the over-fulfillment reconciliation test to require a structured `reason_code` on the generated `Order Reconciliation Log`.
- The behavior verifies Manual Review carries both a machine-readable reason code and a human-readable message.

Green:
- Added `reason_code` to `Order Reconciliation Log`.
- Updated reconciliation logging so matched, skipped, and Manual Review outcomes write structured reason codes.
- Documented Manual Review reason codes in the backend API reference.

Verification:
```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost migrate
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `migrate` completed
- `Ran 79 tests`
- `OK`

## Cycle 111: WhatsApp Confirmation Payload Excludes Internal Order Fields

Red:
- Extended the public order-submission confirmation test to inspect the generated `Order WhatsApp Notification.request_payload`.
- The test verifies the customer-facing WhatsApp payload excludes Sales Employee internal notes, Client Code, stock snapshot field names, and stock shown at order time.

Green:
- Current confirmation payload construction already complied; no production code changes were needed.
- Updated backend API docs to state that both customer PDF and WhatsApp request payload exclude internal note, Client Code, and stock shown at order time.

Verification:
```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 79 tests`
- `OK`

## Cycle 110: Backend Quantity-Only Order Schema Guard

Red:
- Added an installed-DocType metadata test for order-facing Frappe schemas.
- The test verifies `Order`, `Order Item`, `Order Godown Allocation`, `Order PDF`, and `Order WhatsApp Notification` do not expose monetary fields such as price, rate, amount, tax, discount, value, or currency.

Green:
- Current order-facing schemas already complied with the quantity-only invariant, so no DocType changes were needed.
- Updated backend API docs to state the quantity-only schema guard explicitly.

Verification:
```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 79 tests`
- `OK`

## Cycle 109: Mobile Frappe-Only Source Boundary Guard

Red:
- Added a mobile source behavior test that scans app/source files for raw Tally PostgreSQL mirror access patterns.
- The guard blocks raw mirror table names such as `trn_*` and `rpt_*`, direct PostgreSQL client imports, and ad hoc `fetch`/`XMLHttpRequest` calls that bypass the Frappe API boundary.

Green:
- Current mobile source already used the Frappe provider/client boundary, so no production changes were needed.
- Updated the mobile README verification status to include the Frappe-only source guard.

Verification:
```sh
cd apps/mobile
npm test
```

Result:
- `tests 73`
- `pass 73`

## Cycle 108: Mobile React Native Style Type-Safety Guard

Red:
- Added a mobile source behavior test that scans React Native styles for `fontWeight` literals outside the TypeScript-supported React Native font-weight set.
- The test initially exposed an invalid `fontWeight: '750'` value in the main Expo screen.

Green:
- Replaced the invalid `750` font weight with the nearest valid React Native value.
- Fixed the source test path handling for workspace paths containing spaces.

Verification:
```sh
cd apps/mobile
npm test
```

Result:
- `tests 72`
- `pass 72`

## Cycle 107: Mobile Live Customer Selection Client Code Sanitization

Red:
- Tightened the mobile Frappe client behavior test so the allowed-customer backend fixture includes `client_code`.
- The test verifies live adapter results still omit Client Code before Sales Employee customer selection can render them.

Green:
- Reused the Sales Employee customer sanitizer inside the live Frappe API adapter.
- Live allowed-customer responses now strip Client Code at the mobile API boundary, matching fixture/domain behavior.
- Updated the mobile README with the live-mode sanitization guarantee.

Verification:
```sh
cd apps/mobile
npm test
```

Result:
- `tests 71`
- `pass 71`

## Cycle 106: Confirmed Order Line Immutability

Red:
- Added a public DocType behavior test that submits a real Order and then attempts to edit the requested item and godown allocation quantities through `Order.save()`.
- The test verifies submitted order lines cannot be changed after confirmation.

Green:
- Added `Order` controller validation that compares persisted requested item lines and godown allocations before save.
- The validation blocks edits to requested items/godowns/quantities while leaving fulfillment and status fields available for reconciliation and Owner/Admin controls.
- Updated backend API docs with the submitted-order immutability rule.

Verification:
```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 78 tests`
- `OK`

## Cycle 105: Tally Voucher Line Master Validation

Red:
- Added a public voucher sync job test for mixed valid and invalid voucher records.
- The test verifies that unknown voucher items and unknown godowns are logged to `Tally Sync Error`, invalid vouchers are not created, valid vouchers in the same run still import, and run counters reflect seen, processed, and errored records.

Green:
- Voucher line import now requires each line item to exist in `Tally Item`.
- Voucher line import now requires each line godown to exist as an active `Tally Godown`.
- Updated voucher sync docs with the item/godown master validation rule.

Verification:
```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 77 tests`
- `OK`

## Cycle 1: Public Foundation Smoke Check

Red:
- Added a public behavior test for `kunal_enterprises.api.health.smoke`.
- The test checks only install-visible/public outcomes: app identity, PostgreSQL database type, installed app list, and database reachability.

Green:
- Added `api/utils.py` response helpers.
- Added `api/health.py` with whitelisted `smoke`.
- Added foundation package folders for `api`, `cron`, `doc_events`, `permission_query_conditions`, `fixtures`, and `tests`.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 1 test`
- `OK`

## Cycle 2: Customer App Access Requires Valid Client Code

Red:
- Added public behavior tests around DocType saves and the whitelisted Customer App Access status API.
- The tests verify that Customer App Access becomes true only when a Customer is mobile verified, admin approved, Active, and mapped to an active imported `Tally Customer Ledger` by Client Code.
- The tests also verify that blank Client Code blocks app access, missing Tally Client Code is rejected, and mobile numbers are globally unique across Customer and Sales Employee records.

Green:
- Added `Tally Customer Ledger`, `Customer`, and `Sales Employee` DocTypes under the Frappe-imported `Kunal Enterprises` module.
- Added Customer validation for Client Code mapping, rejected-customer mobile reuse, and global Mobile Login Identity uniqueness against Sales Employees.
- Added Sales Employee validation for global Mobile Login Identity uniqueness against Customers.
- Added `kunal_enterprises.api.customer_access.status` for an install-visible Customer App Access checklist.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost migrate
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 5 tests`
- `OK`

## Cycle 3: Required Portal Roles Are Installed

Red:
- Added an install-visible test that checks the required portal roles exist: Owner, Admin, Branch Manager, and Branch Employee.

Green:
- Added `fixtures/role.json`.
- Registered the Role fixture filter in `hooks.py` so only the Kunal Enterprises portal roles are synced.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost migrate
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 6 tests`
- `OK`

## Cycle 4: Product Group And Item Access Filters

Red:
- Added public behavior tests for the Product Group access rules.
- The tests verify:
  - blank Customer Product Group filters return all active root Product Groups;
  - Customer Product Group filters restrict visible groups and items;
  - Sales Employee Product Group filters intersect with the selected Customer filters;
  - Sales Employee Customer Assignment limits the customer context.

Green:
- Added synced master DocTypes: `Tally Stock Group` and `Tally Item`.
- Added child table DocTypes: `Customer Product Group Access`, `Sales Employee Product Group Access`, and `Sales Employee Assigned Customer`.
- Added Product Group and Customer Assignment child tables to `Customer` and `Sales Employee`.
- Added whitelisted API functions:
  - `kunal_enterprises.api.product_groups.allowed`
  - `kunal_enterprises.api.product_groups.items`

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost migrate
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 10 tests`
- `OK`

## Cycle 5: Quantity-Only Order Submission

Red:
- Added public behavior tests for order submission through `kunal_enterprises.api.orders.submit`.
- The tests verify:
  - a Customer can submit a quantity-only Order with a `KE-YY-MM-####` reference assigned at confirmation;
  - duplicate item+godown allocations are merged;
  - Sales Employee orders store an internal note and revalidate effective item access;
  - non-positive Order Quantity is rejected;
  - the monthly reference sequence increments within the same month.

Green:
- Added Order DocTypes:
  - `Order`
  - `Order Item`
  - `Order Godown Allocation`
  - `Order Reference Sequence`
- Added `kunal_enterprises.api.orders.submit`.
- The API reuses current Customer/Sales Employee/Product Group access checks, merges duplicate allocations, allows zero-stock/over-stock quantities, and stores stock shown at order time.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost migrate
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 15 tests`
- `OK`

## Cycle 6: Mobile Order History And Detail

Red:
- Added public behavior tests for order history and order detail APIs.
- The tests verify:
  - Customer order history includes self-placed and Sales Employee-placed Orders;
  - Sales Employee order history only shows Orders placed by that Sales Employee;
  - customer-facing Order detail hides internal Sales Employee note, Client Code, and stock shown at order time;
  - `Manual Review` is returned with mobile display status `Under Review`.

Green:
- Added `kunal_enterprises.api.orders.history`.
- Added `kunal_enterprises.api.orders.detail`.
- Added mobile-facing order serializers with placed-by and status display mapping.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 19 tests`
- `OK`

## Cycle 7: Advisory Item Stock By Godown

Red:
- Added public behavior tests for item stock visibility.
- The tests verify:
  - an allowed item returns latest godown-wise stock snapshots, including zero-stock godowns;
  - stock responses explicitly mark stock as advisory;
  - an item outside the Customer's Product Group access is rejected.

Green:
- Added `Tally Stock Snapshot`.
- Added `kunal_enterprises.api.product_groups.item_stock`.
- The API reuses current Product Group access rules and returns stock by godown without imposing an ordering cap.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost migrate
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 21 tests`
- `OK`

## Cycle 8: Tally Stock Sync Bookkeeping

Red:
- Added public behavior tests for stock snapshot sync bookkeeping.
- The tests verify:
  - valid stock rows upsert `Tally Stock Snapshot` records and attach the source sync run;
  - duplicate item+godown rows are processed in order, leaving the latest quantity;
  - bad rows are logged to `Tally Sync Error` without dropping good rows from the same run;
  - sync run counters distinguish records seen, processed, and errored.

Green:
- Added `Tally Sync Run`.
- Added `Tally Sync Error`.
- Added `kunal_enterprises.cron.tally_sync.sync_stock_snapshots`.
- Registered the stock sync entrypoint in scheduler hooks for the five-minute Tally sync cadence.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost migrate
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 23 tests`
- `OK`

## Cycle 9: Customer Signup And OTP Verification

Red:
- Added public behavior tests for the mobile customer signup and OTP verification surfaces.
- The tests verify:
  - customer signup creates a `Pending OTP` Customer with the submitted signup fields;
  - rejected customer mobile numbers cannot be reused through signup;
  - OTP verification moves the Customer to `Pending Admin Review`;
  - OTP verification sets `mobile_verified` without granting Customer App Access.

Green:
- Added `kunal_enterprises.api.otp.start_customer_signup`.
- Added `Mobile OTP`.
- Added `kunal_enterprises.api.otp.verify_customer_otp`.
- Updated error envelopes so API errors expose a structured `error.message`.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost migrate
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 25 tests`
- `OK`

## Cycle 10: Customer Mobile Auth Token Revalidation

Red:
- Added a public behavior test for customer mobile session verification.
- The test verifies:
  - OTP verification for an active, approved, Client Code-mapped Customer returns a mobile access token;
  - `current_session` accepts the token and returns the Customer identity;
  - removing Client Code causes the same token to be rejected immediately.

Green:
- Added `Mobile Auth Token`.
- Added JWT-backed token issuance through `kunal_enterprises.api.token_verification.issue_token`.
- Added `kunal_enterprises.api.token_verification.current_session`.
- Added current Customer access revalidation during token verification, using current Customer fields and Tally Client Code mapping rather than trusting the stored access flag.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost migrate
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 26 tests`
- `OK`

## Cycle 11: Sales Employee OTP Login

Red:
- Added a public behavior test for Sales Employee OTP login.
- The test verifies:
  - an Active Sales Employee can verify a Sales Employee Login OTP;
  - verification returns a mobile access token and `Sales Employee` identity;
  - `current_session` accepts the Sales Employee token;
  - a Disabled Sales Employee cannot log in and does not receive an active token.

Green:
- Added `kunal_enterprises.api.otp.verify_sales_employee_otp`.
- Reused `Mobile OTP` with `Sales Employee Login` purpose.
- Reused `Mobile Auth Token` and current token verification for Sales Employee sessions.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 27 tests`
- `OK`

## Cycle 12: Sales Employee Allowed Customer Search

Red:
- Added a public behavior test for Sales Employee allowed customer search.
- The test verifies:
  - blank Sales Employee customer assignments can see all active, app-accessible Customers;
  - configured customer assignments restrict the returned list;
  - search can match Client Code;
  - Client Code is not returned in mobile customer result fields.

Green:
- Added `kunal_enterprises.api.sales_employees.allowed_customers`.
- Added `kunal_enterprises.api.sales_employees.get_allowed_customers`.
- Reused current Customer App Access checklist and Sales Employee assignment rows.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 28 tests`
- `OK`

## Cycle 13: Mobile Profile Get And Customer Update

Red:
- Added a public behavior test for mobile profile APIs.
- The test verifies:
  - Customer profile update only changes email ID, date of birth, and date of anniversary;
  - Customer profile update ignores Client Code and business/legal name changes from mobile;
  - Customer profile responses hide Client Code;
  - Sales Employee profile responses are read-only.

Green:
- Added `kunal_enterprises.api.profile.get_profile`.
- Added `kunal_enterprises.api.profile.update_customer_profile`.
- Added explicit Customer and Sales Employee mobile profile serializers.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 29 tests`
- `OK`

## Cycle 14: Mobile Logout Token Revocation

Red:
- Added a public behavior test for mobile logout.
- The test verifies:
  - logout revokes the backing `Mobile Auth Token`;
  - the same token is rejected by `current_session` after logout.

Green:
- Added `kunal_enterprises.api.token_verification.revoke_token`.
- The API verifies the current token, marks the token row `Revoked`, and records `revoked_at`.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 30 tests`
- `OK`

## Cycle 15: Order Placed PDF And WhatsApp Logs

Red:
- Added a public behavior test for Order Placed confirmation records.
- The test verifies:
  - Sales Employee-placed Orders create one customer-facing `Order PDF`;
  - the PDF summary includes requested item, godown, quantity, and placed-by value;
  - the PDF summary excludes sales employee note, Client Code, and stock shown at order time;
  - one `Order WhatsApp Notification` is logged for the Customer recipient only.

Green:
- Added `Order PDF`.
- Added `Order WhatsApp Notification`.
- Added order confirmation record creation after successful order placement.
- Added customer-safe PDF summary generation and queued WhatsApp request logging.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost migrate
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 31 tests`
- `OK`

## Cycle 16: First Voucher Reconciliation

Red:
- Added a public behavior test for the reconciliation scheduled job.
- The test verifies:
  - a matching Tally Sales Invoice by portal reference number and Customer Client Code is applied to an Order;
  - partial fulfillment updates the Order Item fulfilled and pending quantities;
  - partial fulfillment moves the Order and Order Item to `Partially Processed`.

Green:
- Added `Tally Voucher`.
- Added `Tally Voucher Line`.
- Added `Order Reconciliation Log`.
- Added `kunal_enterprises.cron.reconciliation.run_reconciliation`.
- The first implementation handles matching vouchers, Customer Client Code validation, and item-wise quantity application.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost migrate
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 32 tests`
- `OK`

## Cycle 17: Full Voucher Fulfillment

Red:
- Added a public behavior test for full Sales Invoice reconciliation.
- The test verifies:
  - invoice quantities equal to all requested item quantities mark every Order Item `Completed`;
  - pending quantities become zero;
  - the parent Order moves to `Completed`.

Green:
- Existing item-wise reconciliation logic already supported this path.
- No production code change was required for this cycle; the test locks down the expected full-fulfillment behavior.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 33 tests`
- `OK`

## Cycle 18: Over-Fulfillment Manual Review

Red:
- Added a public behavior test for over-fulfilled voucher reconciliation.
- The test verifies:
  - a Sales Invoice quantity greater than the requested Order Quantity moves the Order to `Manual Review`;
  - an `Order Reconciliation Log` records `Manual Review`;
  - the log message includes an over-fulfillment reason.

Green:
- Updated `kunal_enterprises.cron.reconciliation.run_reconciliation` to detect fulfilled quantity greater than requested quantity before applying capped fulfillment.
- Added Manual Review logging with item, requested quantity, and fulfilled quantity context.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 34 tests`
- `OK`

## Cycle 19: Extra Voucher Item Manual Review

Red:
- Added a public behavior test for a voucher containing an extra item line that was not requested on the Order.
- The test verifies:
  - extra unmatched Tally voucher items move the Order to `Manual Review`;
  - an `Order Reconciliation Log` records `Manual Review`;
  - the log message names the unmatched item.

Green:
- Updated reconciliation to compare voucher item lines against ordered items before applying fulfillment.
- Extra voucher items now stop automatic reconciliation and create a Manual Review reason.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 35 tests`
- `OK`

## Cycle 20: Customer Mismatch Manual Review Context

Red:
- Added a public behavior test for a Sales Invoice whose `party_client_code` does not match the portal Order customer's Client Code.
- The test verifies:
  - the Order moves to `Manual Review`;
  - an `Order Reconciliation Log` records `Manual Review`;
  - the log reason includes both the portal customer Client Code and the Tally party Client Code.

Green:
- Updated reconciliation mismatch logging to include the portal customer code and Tally party code in the Manual Review reason.
- This keeps automated reconciliation blocked while giving internal users enough context to resolve the mismatch.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 36 tests`
- `OK`

## Cycle 21: Cumulative Sales Invoice Fulfillment

Red:
- Added a public reconciliation test for an Order fulfilled by two distinct Sales Invoices.
- The test verifies:
  - fulfilled quantities are accumulated across vouchers for the same Order Item;
  - pending quantity reaches zero after the second voucher;
  - the parent Order moves to `Completed`.

Green:
- Updated reconciliation to add the current voucher quantity to existing fulfilled quantity instead of overwriting it.
- Kept over-fulfillment detection against the cumulative fulfilled quantity.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 37 tests`
- `OK`

## Cycle 22: Mirrored Delivery Challan And Sales Invoice Deduplication

Red:
- Added a public reconciliation test for a Delivery Challan and Sales Invoice representing the same Tally movement.
- The test verifies:
  - the Delivery Challan is skipped when a matching Sales Invoice exists;
  - the Sales Invoice fulfills the Order once;
  - the Order does not move to `Manual Review` from duplicate counting;
  - the reconciliation log records the superseded Delivery Challan reason.

Green:
- Added narrow duplicate movement detection for Delivery Challans superseded by Sales Invoices with the same reference, customer, tracking number, item, godown, and quantity signature.
- Reconciliation now prefers the Sales Invoice for that movement and logs the skipped Delivery Challan.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 38 tests`
- `OK`

## Cycle 23: Branch Manager Order Visibility

Red:
- Added a public branch order visibility test for a Branch Manager.
- The test verifies:
  - Portal Branch and Branch Godown Mapping records define branch-visible godowns;
  - orders with allocations in mapped godowns are returned;
  - orders in other godowns are hidden;
  - Branch Manager visibility includes `Manual Review` orders.

Green:
- Added `Portal Branch` and `Branch Godown Mapping` DocTypes.
- Added `kunal_enterprises.api.branch_orders.visible_orders` to return orders linked to mapped godowns.
- Branch order responses include the mobile-safe display status mapping for `Manual Review`.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost migrate
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 39 tests`
- `OK`

## Cycle 24: Branch Employee Processing Transition

Red:
- Added a public branch action test for a Branch Employee.
- The test verifies:
  - a branch-visible `Placed` order can be moved to `Processing`;
  - the updated order remains visible to the Branch Employee;
  - the branch order API returns the updated status.

Green:
- Added `kunal_enterprises.api.branch_orders.mark_processing`.
- The action reuses branch/godown visibility checks and only allows the `Placed` to `Processing` transition for `Branch Employee`.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 40 tests`
- `OK`

## Cycle 25: Branch Roles Cannot Perform Owner/Admin Order Controls

Red:
- Added a public order control test proving Branch Manager and Branch Employee roles cannot cancel, partially close, or resolve Manual Review orders.
- The test verifies:
  - each forbidden action returns a failed response;
  - the Order status remains unchanged.

Green:
- Added `kunal_enterprises.api.order_controls` with Owner/Admin role enforcement for privileged Order actions.
- Branch roles are rejected before any status change is saved.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost migrate
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 42 tests`
- `OK`

## Cycle 26: Owner Manual Review Resolution

Red:
- Added a public Owner action test for resolving a Manual Review Order with a note.
- The test verifies:
  - Owner can move a `Manual Review` Order back to `Processing`;
  - an `Order Status Log` captures from-status, to-status, role, and resolution note.

Green:
- Added `Order Status Log` DocType for audited Order status transitions.
- Added `resolve_manual_review`, plus shared transition logging used by cancel and partial-close actions.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 42 tests`
- `OK`

## Cycle 27: Tally Master Sync For Units, Godowns, And Stock Categories

Red:
- Added a public sync job test for Tally master import.
- The test verifies:
  - `Tally Unit`, `Tally Godown`, and `Tally Stock Category` rows are upserted;
  - a `Tally Sync Run` records records seen, processed, errors, and completion status.

Green:
- Added `Tally Unit`, `Tally Godown`, and `Tally Stock Category` DocTypes.
- Added `kunal_enterprises.cron.tally_sync.sync_tally_masters` for importing these master records.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost migrate
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 45 tests`
- `OK`

## Cycle 28: Owner/Admin Manual Sync Actions And Scheduler Coverage

Red:
- Added public admin action tests for manual sync controls.
- The tests verify:
  - Owner can run Sync Masters Now, Sync Stock Now, and Run Reconciliation Now;
  - Branch Manager cannot run sync actions;
  - the five-minute scheduler registers master sync, stock sync, and reconciliation.

Green:
- Added `kunal_enterprises.api.sync_admin` with Owner/Admin-only wrappers for the three sync actions.
- Updated scheduler hooks to run master sync, stock sync, and reconciliation every five minutes.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 45 tests`
- `OK`

## Cycle 29: Backend API Documentation

Red:
- Identified the Goal 2 deliverable requiring mobile backend APIs to be documented with request and response examples.
- The repo did not have a backend API reference for the implemented whitelisted endpoints.

Green:
- Added `docs/10-backend-api.md` covering:
  - response envelope shape and mobile token header;
  - auth, Customer App Access, Sales Employee customer selection, Product Group/item/stock APIs;
  - order submission/history/detail APIs;
  - profile APIs;
  - branch order APIs;
  - Owner/Admin order controls;
  - manual sync APIs and scheduler entrypoints;
  - reconciliation behavior notes.

Verification:

```sh
rg -n "kunal_enterprises\\.api\\.[a-z_]+\\.[a-z_]+|sync_tally_masters|run_reconciliation" docs/10-backend-api.md
```

Result:
- API reference includes all currently implemented whitelisted endpoint groups.

## Cycle 30: Tally Voucher Sync For Reconciliation

Red:
- Added public sync job tests for importing Tally voucher headers and child lines.
- The tests verify:
  - `Tally Voucher` records are upserted by voucher number;
  - child `Tally Voucher Line` rows are replaced on update;
  - voucher sync run counters are recorded;
  - Owner can run Sync Vouchers Now;
  - the five-minute scheduler includes voucher sync before reconciliation.

Green:
- Added `kunal_enterprises.cron.tally_sync.sync_tally_vouchers`.
- Added `kunal_enterprises.api.sync_admin.sync_vouchers_now`.
- Registered voucher sync in scheduler hooks.
- Updated backend API docs with Sync Vouchers Now and scheduler entry.

Verification:

```sh
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 47 tests`
- `OK`

## Cycle 31: Mobile App Scaffold And Customer Order Tracer

Red:
- Added mobile behavior tests for the first UI-first customer order tracer:
  - duplicate item+godown allocations merge locally;
  - over-stock and zero-stock quantities produce soft confirmation notes;
  - backend `Manual Review` status displays to mobile users as `Under Review`.

Green:
- Added `apps/mobile` Expo / React Native TypeScript scaffold.
- Added Frappe provider shell using `frappe-js-sdk` with `Auth-Token` bearer header and invalid-token logout behavior.
- Added deterministic mocked API data for Product Groups, Items, item stock, and order submission.
- Added a first customer ordering screen: Product Group -> Item -> Godown stock -> Summary -> Success.
- Added local cart/domain behavior for quantity-only ordering.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `3` mobile behavior tests passed.

## Cycle 32: Mobile Sales Employee Customer Context

Red:
- Added mobile behavior tests for Sales Employee ordering:
  - customer search can match Client Code;
  - Client Code is not displayed in Sales Employee customer results;
  - order submission payload includes selected Customer, Sales Employee, and optional internal note;
  - Sales Employee order history only includes orders placed by that employee.

Green:
- Added `salesEmployeeFlow` domain behavior for customer search sanitization, Sales Employee order payloads, and scoped history.
- Extended mocked API fixtures with Sales Employee customers and history.
- Added a Sales Employee mode to the mobile UI with Customer selection, selected Customer context, and internal note on summary.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `6` mobile behavior tests passed.

## Cycle 33: Mobile Customer Signup, OTP, And Pending Access

Red:
- Added mobile behavior tests for the Customer auth/access path:
  - signup captures required customer fields and never sends Client Code;
  - OTP verification without Customer App Access routes to pending access;
  - OTP verification with Customer App Access creates a Customer session;
  - invalid-token backend errors trigger mobile logout.

Green:
- Added `authAccessFlow` domain behavior for signup payloads, OTP next-step decisions, session creation, and invalid-token handling.
- Extended mocked API with Customer signup and OTP verification fixtures.
- Added a Customer WhatsApp OTP panel and Pending Admin Review screen to the mobile UI.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `10` mobile behavior tests passed.

## Cycle 34: Mobile Profile, Order History, And Order Detail Privacy

Red:
- Added mobile behavior tests for profile/history/detail:
  - Customer profile hides Client Code and only allows email/date fields to be edited;
  - Sales Employee profile is read-only;
  - order summaries map `Manual Review` to `Under Review`;
  - Customer order detail hides sales employee note, Client Code, and stock internals.

Green:
- Added `profileHistoryFlow` domain behavior for safe profile serialization, editable profile patches, order summary display status, and customer-safe order detail.
- Extended mocked API with Customer/Sales Employee profiles, order history, and order detail fixtures.
- Added History and Profile sections to the mobile UI.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `14` mobile behavior tests passed.

## Cycle 35: Mobile Shared Request And Access States

Red:
- Added mobile behavior tests for shared app states:
  - loading vs slow request timing;
  - no network, expired session, access removed, and backend validation error classification;
  - stock changed since the screen loaded;
  - user-facing state banners without backend/internal labels.

Green:
- Added `sharedStateFlow` domain behavior for request timing, API failure classification, stock-change notes, and banner copy.
- Added a compact operational banner to the mobile UI.
- Added quick UI triggers for no-network and access-changed states while the app is still fixture-backed.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `18` mobile behavior tests passed.

## Cycle 36: Mobile Frappe API Client Adapter

Red:
- Added mobile adapter behavior tests with a fake Frappe `call` object.
- The tests verify:
  - order submission calls `kunal_enterprises.api.orders.submit` with the expected payload;
  - Sales Employee allowed customer loading calls the backend customer-selection endpoint and does not expose Client Code;
  - backend error envelopes are unwrapped into thrown mobile errors.

Green:
- Added `createFrappeApiClient` as the typed mobile adapter over Frappe `call.get` and `call.post`.
- Mapped implemented backend endpoints for auth, session, Customer Access, Product Groups/items/stock, orders, and profiles.
- Added common response-envelope unwrapping for success and error responses.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `21` mobile behavior tests passed.

## Cycle 37: Mobile Session And Local Cart Storage

Red:
- Added mobile storage behavior tests:
  - mobile session token persists and clears on logout;
  - local cart allocations persist per Customer/Sales Employee context;
  - unrelated cart contexts do not leak into each other.

Green:
- Added AsyncStorage-compatible `mobileStorage` helpers for session and cart persistence.
- Updated `AuthProvider` to load stored session on startup, save active sessions, and clear storage on logout.
- Documented mobile session/cart storage in the mobile README.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `23` mobile behavior tests passed.

## Cycle 38: Mobile API Runtime Selection

Red:
- Added mobile API selection tests:
  - the app uses fixture-backed API behavior when no Frappe `call` object is available;
  - the app uses the live Frappe API adapter when `call` is available;
  - live Product Group loading calls the backend `kunal_enterprises.api.product_groups.allowed` method.

Green:
- Added `createMobileApi` and `mobileApiMode` as the runtime API boundary.
- Split the mock adapter into a JavaScript runtime module plus TypeScript re-export.
- Updated the mobile screen to use the selected API adapter instead of importing `mockApi` directly.
- Documented fixture/live API selection in the mobile README.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `25` mobile behavior tests passed.

## Cycle 39: Sales Employee Mobile OTP And Resend State

Red:
- Added mobile auth behavior tests for Sales Employee OTP login.
- The tests verify:
  - an active Sales Employee OTP response creates a Sales Employee session;
  - a disabled Sales Employee is routed to blocked access;
  - OTP resend state enforces the countdown before a resend is available.

Green:
- Added Sales Employee OTP step/session helpers alongside the Customer auth helpers.
- Added a reusable OTP resend countdown state helper.
- Added Sales Employee OTP fixtures and send/verify methods to the mobile mock API.
- Updated the mobile screen so Sales Employee mode starts at OTP login instead of jumping directly to Customer selection.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `28` mobile behavior tests passed.

## Cycle 40: Backend OTP Send And Resend APIs

Red:
- Added backend behavior tests for the missing public OTP send/resend surfaces.
- The tests verify:
  - Customer signup creates an open Customer Signup OTP;
  - Customer OTP resend is blocked during the backend cooldown window;
  - Sales Employee OTP send creates a Sales Employee Login OTP for active employees;
  - disabled Sales Employees cannot receive login OTPs.

Green:
- Added whitelisted `send_otp` and `resend_otp` APIs in `api/otp.py`.
- Shared OTP creation through a single helper that expires older open OTPs before creating a new one.
- Added backend-defined `cooldown_seconds` and `expires_in_seconds` response fields.
- Updated the live mobile Frappe adapter so Sales Employee OTP send calls the backend `send_otp` endpoint.

Verification:

```sh
bench --site kunal.localhost run-tests --app kunal_enterprises
cd apps/mobile
npm test
```

Result:
- `50` backend tests passed.
- `28` mobile behavior tests passed.

## Cycle 41: Mobile Cart Quantity Editing And Removal

Red:
- Added mobile cart behavior tests for the remaining cart management requirements.
- The tests verify:
  - an existing item+godown allocation quantity can be edited;
  - a single godown allocation can be removed;
  - removing an item removes all godown allocations for that item;
  - setting a non-positive quantity is rejected.

Green:
- Added `updateAllocationQuantity` and `removeAllocation` to the mobile order domain module.
- Updated the order summary UI with compact quantity decrement/increment controls.
- Added item removal from the summary UI.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `30` mobile behavior tests passed.

Note:
- TypeScript dependencies are not installed in `apps/mobile`, so `tsc --noEmit` could not be run locally.

## Cycle 42: Recoverable Mobile Order Submission Failure

Red:
- Added a mobile order submission behavior test for offline final submission.
- The test verifies:
  - a network failure returns a recoverable `no_network` state;
  - no backend reference number is invented when submission fails.

Green:
- Added `finalizeOrderSubmission` to the mobile order domain module.
- Reused the shared API failure classifier so no-network, expired-session, access-removed, and validation errors resolve to existing banner states.
- Updated the order summary submit path to keep the user on the summary screen and show the banner when final submission fails.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `31` mobile behavior tests passed.

## Cycle 43: Mobile Order Detail Screen And Placed-By Label

Red:
- Added mobile order detail behavior tests for the placed-by presentation rule.
- The tests verify:
  - Customer-viewed self-placed orders show `You`;
  - Customer-viewed Sales Employee orders show the Sales Employee name;
  - Sales Employee-viewed self-placed orders show `You`.

Green:
- Added `orderPlacedByLabel` to the profile/history domain module.
- Added `placed_by_label` to sanitized customer order details.
- Added an explicit `detail` screen state in the mobile UI instead of mutating the history list when a row is opened.
- Rendered backend order reference, status, placed-by label, and godown allocations in the detail workspace.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `32` mobile behavior tests passed.

## Cycle 44: Mobile Monetary Field Sanitization

Red:
- Added a mobile presentation-safety test for the no-price/no-value rule.
- The test verifies:
  - order history summaries remove amount, tax, and discount fields;
  - order detail removes rate fields;
  - nested godown allocations remove price fields before rendering.

Green:
- Added a recursive order presentation sanitizer in the profile/history domain module.
- Applied the sanitizer to order summaries and customer order details.
- Preserved quantity, status, placed-by, and allocation fields while stripping monetary fields from unexpected backend payloads.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `33` mobile behavior tests passed.

## Cycle 45: Mobile Session Refresh And Logout/Revoke

Red:
- Added mobile session behavior tests for app-start refresh and logout.
- The tests verify:
  - a stored session calls the backend current-session endpoint with the custom `Auth-Token` bearer header;
  - invalid/stale stored sessions are cleared locally after backend rejection;
  - logout calls backend token revoke before clearing local session storage.

Green:
- Added `sessionFlow` helpers for auth headers, stored-session refresh, and revoke-then-clear logout.
- Exposed the current session from `AuthProvider`.
- Saved verified Customer and Sales Employee OTP sessions through `AuthProvider`.
- Added a mobile Logout action that revokes the backend token when a session exists, then clears local state and returns to auth.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `36` mobile behavior tests passed.

## Cycle 46: Mobile Session API Boundary Parity

Red:
- Added mobile API boundary tests for session refresh and revoke.
- The tests verify:
  - the live Frappe adapter calls `current_session` and `revoke_token` with the custom auth headers;
  - fixture mode exposes the same `currentSession` and `revokeToken` public methods.

Green:
- Added fixture-mode `currentSession` and `revokeToken` implementations.
- Added deterministic mock Customer and Sales Employee session fixtures keyed by token.
- Preserved the same public API shape for mock and live mobile modes.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `37` mobile behavior tests passed.

## Cycle 47: Mobile Customer Profile Update

Red:
- Added mobile API boundary tests for Customer profile update.
- The tests verify:
  - the live Frappe adapter calls `kunal_enterprises.api.profile.update_customer_profile` with Customer and payload;
  - fixture mode exposes `updateCustomerProfile` through the same public API boundary.

Green:
- Added fixture-mode Customer profile update support.
- Added editable Customer profile fields to the Profile workspace.
- Wired the Profile workspace save action through `editableCustomerProfilePatch` so only email ID, date of birth, and date of anniversary are sent.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `38` mobile behavior tests passed.

## Cycle 48: Backend-Defined OTP Cooldown In Mobile

Red:
- Added mobile auth behavior tests for backend-defined OTP cooldown extraction.
- The tests verify:
  - positive `cooldown_seconds` values from OTP send/signup responses override the local fallback;
  - missing or invalid cooldown values preserve the fallback.

Green:
- Added `otpCooldownSecondsFromResponse` to the auth domain module.
- Stored OTP cooldown seconds in the mobile screen state.
- Updated Customer signup and Sales Employee OTP send paths to use backend-provided cooldowns for resend countdowns.
- Reset the cooldown fallback when switching login modes.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `39` mobile behavior tests passed.

## Cycle 49: Customer Order Payload Boundary

Red:
- Added a mobile order payload behavior test for Customer submissions.
- The test verifies:
  - Customer order payloads include Customer and quantity-only allocations;
  - Customer order payloads never include Customer notes or Sales Employee internal notes.

Green:
- Added `buildCustomerOrderPayload` to the mobile order domain module.
- Updated the mobile submit path to use the Customer payload builder instead of an inline object.
- Kept Sales Employee payload building isolated in the Sales Employee domain module.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `40` mobile behavior tests passed.

## Cycle 50: Mobile Godown Stock Ordering

Red:
- Added mobile stock-list behavior tests for godown ordering.
- The tests verify:
  - positive-stock godowns appear before zero-stock godowns;
  - godowns are stable-sorted by name within each stock bucket;
  - the live Frappe adapter normalizes backend stock rows before returning them to the screen.

Green:
- Added `sortGodownStockForMobile` to the mobile order domain module.
- Updated fixture-mode item stock to use the shared stock sorter.
- Updated the live Frappe API adapter to normalize `item_stock` responses before UI rendering.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `42` mobile behavior tests passed.

## Cycle 51: Mobile Item Search

Red:
- Added mobile item-list behavior tests for item search.
- The tests verify:
  - item search can match item code;
  - item search can match display name;
  - item search can match Product Group/root stock group;
  - blank search preserves the current allowed item list.

Green:
- Added `searchItemsForMobile` to the mobile order domain module.
- Added item search state to the mobile screen.
- Added a search input to the item selection workspace and rendered filtered allowed items.
- Reset item search when entering a new Product Group.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `43` mobile behavior tests passed.

## Cycle 52: Mobile Auth Bootstrap Validation

Red:
- Added mobile session bootstrap behavior tests.
- The tests verify:
  - a stored session can be validated before being exposed to app state;
  - invalid stored sessions are cleared and never applied to app state.

Green:
- Added `bootstrapStoredSession` to the session domain module.
- Updated `AuthProvider` to bootstrap through the shared session flow instead of directly loading storage.
- Added an injectable `validateStoredSession` hook for app-start current-session refresh while preserving local fixture startup behavior.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `45` mobile behavior tests passed.

## Cycle 66: Mobile Clear Local Cart After Placement

Red:
- Added a storage behavior test for clearing a persisted local cart after final order placement.
- The test verifies that loading the cart after `clearCart` returns an empty quantity-only cart.

Green:
- Added `clearCart` to the mobile storage module and TypeScript wrapper.
- Updated successful mobile order submission to remove the persisted cart for the active order context before clearing in-memory cart state.
- Reset the cart-loaded marker after clearing storage so placed orders cannot be revived as editable local drafts.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `58` mobile behavior tests passed.

## Cycle 67: Mobile Order Success Requires Backend Reference

Red:
- Added a Customer order behavior test for final submission responses that omit `portal_reference_number`.
- The test verifies the app does not show a success state or fake/blank reference when the backend response lacks the required order reference.

Green:
- Updated `finalizeOrderSubmission` to require `portal_reference_number` before returning success.
- Missing references now produce a recoverable validation state with no local success reference.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `59` mobile behavior tests passed.

## Cycle 69: Mobile Stock-Changed Confirmation Notes

Red:
- Added a Customer order behavior test for confirmation notes when latest stock has changed since the godown screen loaded.
- The test verifies the summary notes include a changed-stock message alongside the existing over-stock and zero-stock soft warnings.

Green:
- Updated `buildConfirmationNotes` to accept latest stock rows and include `detectStockChanges` output.
- Wired the mobile summary screen to pass current `stockRows` into confirmation note construction.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `60` mobile behavior tests passed.

## Cycle 70: Mobile Confirmation Notes Use Latest Stock

Red:
- Added a Customer order behavior test for rows where synced stock changes after the godown screen loaded and the requested quantity exceeds the new latest stock.
- The test verifies confirmation notes evaluate over-stock against the newest stock row when available, while still reporting that stock changed from the original snapshot.

Green:
- Updated `buildConfirmationNotes` to use latest stock rows for availability checks when provided.
- Preserved `stockShownAtOrderTime` as the fallback when no newer stock row is available.
- Kept changed-stock notes alongside over-stock/zero-stock notes.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `61` mobile behavior tests passed.

## Cycle 71: Mobile Pre-Submit Stock Refresh Items

Red:
- Added a Customer order behavior test for determining which cart items need latest stock refresh before final confirmation.
- The test verifies duplicate item+godown cart rows produce one refresh request per distinct item.

Green:
- Added `stockRefreshItemsForCart` to the mobile order domain module.
- Wired final mobile submission to refresh stock for each distinct cart item before submitting the backend order.
- Updated the mobile README to describe latest-stock-changed confirmation notes and pre-submit stock refresh.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `62` mobile behavior tests passed.

## Cycle 72: Mobile Review Gate After Stock Refresh

Red:
- Added a Customer order behavior test for final submission after refreshed stock creates new confirmation notes.
- The test verifies:
  - newly discovered stock notes require returning to the summary screen;
  - final submission is paused with a reviewable validation state instead of placing the order immediately.

Green:
- Added `stockReviewAfterRefresh` to the mobile order domain module.
- Updated final mobile submission to refresh latest stock, compare notes against the notes already shown, and return to summary when new stock notes appear.
- Updated the mobile README to document the pre-submit stock refresh review gate.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `63` mobile behavior tests passed.

## Cycle 73: Mobile Reviewed Stock Notes Regression

Red:
- Added a Customer order behavior test for confirming again after refreshed stock notes have already been reviewed on the summary screen.
- The test verifies reviewed stock notes do not repeatedly block the next final confirmation.

Green:
- Existing `stockReviewAfterRefresh` behavior already compared refreshed notes against the notes currently shown on the summary screen.
- No implementation change was needed after adding the regression coverage.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `64` mobile behavior tests passed.

## Cycle 74: Mobile Recoverable Stock Refresh Failure

Red:
- Added a Customer order behavior test for final submission when pre-submit stock refresh fails.
- The test verifies stock refresh failures return a recoverable request state instead of escaping as an uncaught submit error.

Green:
- Added `prepareStockReviewBeforeSubmit` to refresh latest stock, run refreshed-stock review, and classify refresh failures.
- Updated final mobile submission to use the helper before calling the backend order submit endpoint.
- Updated the mobile README to describe recoverable pre-submit stock refresh.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `65` mobile behavior tests passed.

## Cycle 75: Backend Disabled Customer Order Regression

Red:
- Added a backend order submission behavior test for a Customer whose app access is removed after setup by disabling the Customer.
- The test verifies final order submission rejects disabled Customer access and returns a Customer App Access error instead of creating an Order.

Green:
- Existing backend Product Group/access revalidation already rejected the disabled Customer.
- No implementation change was needed after adding the regression coverage.

Verification:

```sh
bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `52` backend/Frappe tests passed.

## Cycle 76: Backend Disabled Sales Employee Order Regression

Red:
- Added a backend order submission behavior test for a disabled Sales Employee trying to place an order for an assigned Customer and allowed Product Group.
- The test verifies final order submission rejects disabled Sales Employee access instead of creating an Order.

Green:
- Existing backend Sales Employee/Product Group access revalidation already rejected the disabled Sales Employee.
- No implementation change was needed after adding the regression coverage.

Verification:

```sh
bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `53` backend/Frappe tests passed.

## Cycle 77: Backend Item Stock Rejects Removed Customer Access

Red:
- Added a backend Product Group/stock API behavior test for a Customer whose app access is removed before calling `item_stock`.
- The test verifies protected stock reads reject removed Customer App Access instead of returning advisory stock rows.

Green:
- Existing Product Group access validation already rejected the removed Customer App Access.
- No implementation change was needed after adding the regression coverage.

Verification:

```sh
bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `54` backend/Frappe tests passed.

## Cycle 78: Backend Item Stock Rejects Disabled Sales Employee

Red:
- Added a backend Product Group/stock API behavior test for a disabled Sales Employee calling `item_stock` for an assigned Customer and allowed Product Group.
- The test verifies protected stock reads reject disabled Sales Employee access instead of returning advisory stock rows.

Green:
- Existing Sales Employee access validation already rejected the disabled employee.
- No implementation change was needed after adding the regression coverage.

Verification:

```sh
bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `55` backend/Frappe tests passed.

## Cycle 79: Backend Item Stock Rejects Unassigned Sales Employee Customer

Red:
- Added a backend Product Group/stock API behavior test for an active Sales Employee requesting item stock for a Customer outside their assigned customer list.
- The test verifies protected stock reads reject the unassigned Customer context instead of returning advisory stock rows.

Green:
- Existing Sales Employee customer-assignment validation already rejected the unassigned Customer context.
- No implementation change was needed after adding the regression coverage.

Verification:

```sh
bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `56` backend/Frappe tests passed.

## Cycle 68: Backend And Mobile History Contract Documentation

Red:
- Audited backend API and mobile README documentation after adding Sales Employee history across Customers.
- Found that the backend API docs still emphasized Customer-scoped order history and did not show the Sales Employee-only history request shape.

Green:
- Updated `docs/10-backend-api.md` to document:
  - Customer history scoped by `customer`;
  - Sales Employee history using `sales_employee` without a Customer filter;
  - optional Customer filter for one selected Customer.
- Updated `apps/mobile/README.md` to reflect session-derived identity routing, Sales Employee history across Customers, and local cart persistence coverage.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `59` mobile behavior tests passed.

Additional check:
- `rg -n "history\\?sales_employee|Sales Employee history|local cart persistence|session-derived" docs/10-backend-api.md apps/mobile/README.md` confirms the updated documentation paths.

Additional check:
- `rg -n "clearCart|cartKeyForOrderContext|setCartLoadedKey" apps/mobile/src/storage apps/mobile/app/index.tsx apps/mobile/tests/storage-flow.test.mjs` confirms storage implementation, TypeScript export, screen usage, and behavior coverage.

## Cycle 64: Mobile TypeScript Session Export Parity

Red:
- Audited the Expo TypeScript wrapper modules after adding session-derived identity routing.
- Found that `app/index.tsx` depends on `src/domain/sessionFlow.ts`, but the wrapper did not re-export `activeIdentityForMode` from the tested `.mjs` module.

Green:
- Updated `src/domain/sessionFlow.ts` to re-export `activeIdentityForMode`.
- Confirmed the implementation, TypeScript wrapper, app import, and session behavior test now reference the same public helper.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `56` mobile behavior tests passed.

## Cycle 65: Mobile Local Cart Persistence Wiring

Red:
- Added a storage behavior test for deriving local cart keys from the active ordering context.
- The test verifies:
  - Customer carts are scoped by Customer identity;
  - Sales Employee carts are scoped by Sales Employee plus selected Customer;
  - Sales Employee mode does not persist a cart before a Customer is selected.

Green:
- Added `cartKeyForOrderContext` to the mobile storage module and TypeScript wrapper.
- Wired the mobile screen to load the cart from AsyncStorage when the order context changes.
- Wired cart changes back to AsyncStorage after the relevant cart has been loaded.
- Cleared the local cart after a successful final order submission so placed orders are not editable as drafts.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `57` mobile behavior tests passed.

Additional check:
- `rg -n "cartKeyForOrderContext|loadCart|saveCart|cartStorageKey|cartLoadedKey" apps/mobile/src/storage apps/mobile/app/index.tsx apps/mobile/tests/storage-flow.test.mjs` confirms implementation, TypeScript wrapper, screen wiring, and behavior tests.

Additional check:
- `rg -n "activeIdentityForMode" apps/mobile/src/domain/sessionFlow.ts apps/mobile/src/domain/sessionFlow.mjs apps/mobile/app/index.tsx apps/mobile/tests/session-flow.test.mjs` shows the wrapper export, implementation, app usage, and behavior test.
- `tsc --noEmit` was not run because `apps/mobile/node_modules/typescript` is not installed in this workspace.

## Cycle 58: Mobile Customer-Facing Internal Code Copy

Red:
- Added mobile screen-copy behavior tests to ensure customer-facing access messages do not expose internal Client Code or ledger terminology.
- The tests verify:
  - Customer header and pending-access copy avoid internal access mechanics;
  - Sales Employee customer-selection copy explains search without displaying internal identifiers.

Green:
- Added `screenCopy.mjs` for tested user-facing mobile copy.
- Replaced hardcoded header and pending-access strings in the mobile screen.
- Cleared the Sales Employee customer-search default so the UI no longer starts with an internal-looking fixture query.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `51` mobile behavior tests passed.

Additional check:
- `rg -n "Client Code|client code|ledger-001|ledger" apps/mobile/app apps/mobile/src/domain apps/mobile/src/providers apps/mobile/src/storage apps/mobile/src/constants apps/mobile/src/types.ts` returned no matches.

## Cycle 59: Mobile Live Order Response Safety

Red:
- Added a Frappe client behavior test for live order history/detail normalization.
- The test verifies:
  - Manual Review displays as Under Review;
  - monetary fields are stripped from live history/detail responses;
  - Sales Employee internal note, manual review reason, and Client Code are not exposed through the mobile adapter.

Green:
- Routed live Frappe `orderHistory` responses through `orderSummaryForMobile`.
- Routed live Frappe `orderDetail` responses through `customerOrderDetailForMobile`.
- Added `manual_review_reason` to the recursive blocked order fields list.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `52` mobile behavior tests passed.

## Cycle 60: Mobile Viewer-Aware Order Detail

Red:
- Added a mobile profile/history behavior test for Sales Employee order-detail viewing.
- The test verifies:
  - orders placed by the viewing Sales Employee are labeled as `You`;
  - the Sales Employee internal note remains available to the Sales Employee viewer;
  - stock snapshot internals remain hidden from detail rows.

Green:
- Added `orderDetailForMobile` with explicit viewer identity context.
- Kept `customerOrderDetailForMobile` as the Customer-safe wrapper.
- Updated fixture and live Frappe API adapters to pass Customer versus Sales Employee viewer context into order-detail normalization.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `53` mobile behavior tests passed.

## Cycle 61: Mobile Customer Empty-Cart Submit Guard

Red:
- Added a Customer order behavior test for final-submit readiness.
- The test verifies:
  - Customer submit is blocked when the cart has no allocations;
  - a cart with at least one allocation can proceed to final submission.

Green:
- Added `customerOrderGuard` to the Customer order domain flow.
- Wired Customer submit through the guard before building the backend order payload.
- Kept backend validation authoritative while avoiding an avoidable empty-cart backend submission from the mobile UI.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `54` mobile behavior tests passed.

## Cycle 62: Sales Employee History Across Customers

Red:
- Added a backend order-history behavior test for Sales Employee history without a Customer filter.
- Added a mobile Frappe client behavior test for requesting Sales Employee history without sending a placeholder Customer.
- The tests verify:
  - Sales Employee order history spans multiple Customers;
  - orders placed by other Sales Employees are excluded;
  - the mobile live adapter can call the backend with `sales_employee` only.

Green:
- Updated `kunal_enterprises.api.orders.history` so `customer` is optional when `sales_employee` is provided.
- Kept Customer history access validation intact for Customer-scoped calls.
- Updated the mobile History action to request Sales Employee history without hardcoding `CUST-001`.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `55` mobile behavior tests passed.

```sh
bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `51` backend/Frappe tests passed.

## Cycle 63: Mobile Session Identity Routing

Red:
- Added a mobile session behavior test for resolving the active identity from the stored session.
- The test verifies:
  - Customer mode uses the Customer identity from the active session;
  - Sales Employee mode uses the Sales Employee identity from the active session;
  - fixture fallback identities are used only when the session does not match the current mode.

Green:
- Added `activeIdentityForMode` to the session domain module.
- Replaced post-login hardcoded Customer/Sales Employee ids in the mobile screen for Product Groups, allowed Customers, order submit, history, detail, and profile calls.
- Preserved deterministic fixture fallbacks for unauthenticated mock-mode use.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `56` mobile behavior tests passed.

## Cycle 57: Mobile Sales Employee Customer Selection Guard

Red:
- Added a Sales Employee mobile behavior test for submit readiness before a Customer is selected.
- The test verifies:
  - Sales Employees are routed back to Customer selection when no Customer context exists;
  - a selected Customer with cart allocations is allowed to continue confirming the order.

Green:
- Added `salesEmployeeOrderGuard` to centralize selected-Customer and cart readiness behavior.
- Wired the mobile submit path through the guard before building the Sales Employee order payload.
- Preserved the backend payload boundary while giving the UI a deterministic validation state and route.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `49` mobile behavior tests passed.

## Cycle 56: Active Customer Auth Route Composition

Red:
- Added mobile auth behavior tests for the full active-Customer OTP routing decision.
- The tests verify:
  - active Customer OTP creates a Customer session;
  - the app checks Customer App Access status before routing;
  - active access routes to the Product Group/order home step.

Green:
- Added `customerOtpRouteAfterAccessCheck` to the auth domain module.
- Updated Customer OTP handling to use the composed route helper.
- Kept pending/removed access routing inside the same public auth behavior instead of splitting it only across UI code.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `48` mobile behavior tests passed.

## Cycle 104: Manual Review Resolution Requires Note

Red:
- Added backend order-control coverage requiring Owner/Admin Manual Review resolution to include a non-empty resolution note.
- The backend suite failed because a blank note still moved the Order from Manual Review to Processing.

Green:
- Added `resolution_note` validation before Manual Review resolution transitions.
- Verified successful resolution preserves the note in `Order Status Log`.
- Documented the required resolution note in the backend API docs.

Verification:

```sh
cp -R /Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/apps/kunal_enterprises/. /Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench/apps/kunal_enterprises
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 76 tests`
- `OK`

## Cycle 103: Branch Manual Review Reason Visibility

Red:
- Tightened branch-visible order coverage so a Branch Manager viewing a visible `Manual Review` order receives the latest Manual Review reason.
- The backend suite failed because branch order serialization returned `display_status` but no `manual_review_reason`.

Green:
- Added latest `Order Reconciliation Log` message lookup for branch-visible `Manual Review` orders.
- Documented that branch APIs expose Manual Review reasons while mobile Customer/Sales Employee APIs still show only `Under Review`.

Verification:

```sh
cp -R /Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/apps/kunal_enterprises/. /Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench/apps/kunal_enterprises
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 75 tests`
- `OK`

## Cycle 102: Branch Processing Status Log

Red:
- Tightened branch order workflow coverage so a Branch Employee moving a visible Placed order to Processing must create an `Order Status Log`.
- The backend suite failed because the Processing transition updated the Order status without writing a log record.

Green:
- Added status-log creation to the Branch Employee `mark_processing` API.
- The log records `Placed -> Processing`, role `Branch Employee`, and an operational note.

Verification:

```sh
cp -R /Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/apps/kunal_enterprises/. /Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench/apps/kunal_enterprises
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 75 tests`
- `OK`

## Cycle 101: Stock Snapshot Sync Validates Godown Masters

Red:
- Added public stock sync coverage requiring unknown godown rows to be logged as sync errors without dropping valid rows.
- The backend suite failed because stock snapshot sync accepted an unknown godown and completed without errors.

Green:
- Added active `Tally Godown` validation to stock snapshot upsert.
- Updated stock sync tests so valid rows use an imported active godown master.
- Documented that stock sync requires existing active Tally Item and Tally Godown rows, and logs invalid rows to `Tally Sync Error`.

Verification:

```sh
cp -R /Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/apps/kunal_enterprises/. /Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench/apps/kunal_enterprises
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 75 tests`
- `OK`

## Cycle 100: Mobile Typecheck Handoff Command

Red:
- Added a mobile runnability documentation guard requiring package scripts for Expo start, behavior tests, and TypeScript typecheck.
- The mobile suite failed because `package.json` did not expose `npm run typecheck` and the README did not document it.

Green:
- Added `typecheck: tsc --noEmit` to the mobile package scripts.
- Updated the mobile README to include `npm run typecheck` after dependency installation and distinguish the pure Node behavior suite from the dependency-backed TypeScript compile gate.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `71` mobile behavior tests passed.

Note:
- An attempted `npm install` in this workspace produced no output and did not create `node_modules`; `killall node` stopped the Node process, but the shell tool session remained stuck. Typecheck/start verification still requires a successful dependency install.

## Cycle 99: Tally Master Sync Covers Product And Customer Masters

Red:
- Added public master sync coverage for Tally Stock Groups, Tally Items, and Tally Customer Ledgers.
- The backend suite failed because `sync_tally_masters` ignored those record groups and only imported units, godowns, and stock categories.

Green:
- Extended master record flattening and upsert naming to include stock groups, items, and customer ledgers.
- Verified synced stock groups preserve root/parent/depth/full-path fields, items preserve immediate/root group and closing balance, and customer ledgers preserve Client Code aliases.
- Updated backend API docs to show the expanded master sync payload.

Verification:

```sh
cp -R /Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/apps/kunal_enterprises/. /Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench/apps/kunal_enterprises
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 74 tests`
- `OK`

## Cycle 98: Backend Order Godown Revalidation

Red:
- Added public order-submission coverage for Tally Godown validation.
- The test verifies an active zero-stock godown can be ordered from, while inactive and unknown godowns are rejected after Tally Godown masters exist.
- The backend suite failed because order submission accepted the inactive godown.

Green:
- Added active Tally Godown validation to order submission.
- The validation preserves fixture/dev behavior before godown masters are synced, but once Tally Godown records exist, submitted godowns must be active imported masters.
- Documented the order submission revalidation rule in the backend API docs.

Verification:

```sh
cp -R /Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/apps/kunal_enterprises/. /Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench/apps/kunal_enterprises
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 73 tests`
- `OK`

## Cycle 97: Backend OTP WhatsApp Dispatch Evidence

Red:
- Tightened the Customer signup/OTP behavior test to require the issued `Mobile OTP` record to store WhatsApp provider metadata.
- The backend suite failed because `Mobile OTP` had no provider/dispatch fields.

Green:
- Added provider, provider status, request payload, and provider response fields to `Mobile OTP`.
- Updated OTP issuance to queue records for `frappe_whatsapp` with an install-visible payload and initial queued provider response.
- Documented OTP dispatch metadata in the backend API docs.

Verification:

```sh
cp -R /Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/apps/kunal_enterprises/. /Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench/apps/kunal_enterprises
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost migrate
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 72 tests`
- `OK`

## Cycle 96: Owner/Admin Desk Permissions For Core Portal DocTypes

Red:
- Added an install-visible backend test requiring Owner/Admin Desk permissions on core portal, Tally master/sync, and order evidence DocTypes.
- The backend suite failed because `Customer` only exposed `System Manager` permissions.

Green:
- Added Owner/Admin DocType permissions to Customer, Sales Employee, Tally customer ledger, Tally stock group/item/category/godown/unit/snapshot, Tally voucher, Tally sync run/error, Order PDF, Order WhatsApp Notification, and Order Reconciliation Log.
- Kept existing branch read permissions on Order, Portal Branch, Branch Godown Mapping, and Order Status Log.

Verification:

```sh
cp -R /Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/apps/kunal_enterprises/. /Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench/apps/kunal_enterprises
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost migrate
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `Ran 72 tests`
- `OK`

## Cycle 95: Delivery Handoff Audit

Red:
- Added a public documentation guard that requires the final delivery audit to mention the backend and mobile handoff evidence from the goal prompts.
- The mobile suite failed because `docs/11-delivery-audit.md` did not exist.

Green:
- Added `docs/11-delivery-audit.md` with backend deliverable evidence for implementation, tests, API docs, fixtures/migrations, and scheduler/manual jobs.
- Added mobile deliverable evidence for the runnable Expo app, launch instructions, test results, backend environment configuration, and remaining setup assumptions.
- Captured commands run, tests run, implemented behavior summary, and unresolved operational questions around Tally reference field proof, Main Location mapping, Seetarambagh mapping, and exact customer ledger filter.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `69` mobile behavior tests passed.

## Cycle 94: Mobile Visible Pricing Copy Guard

Red:
- Added mobile UI copy coverage for the no-pricing requirement.
- The test scans visible `Text`, `Workspace` title, and template detail copy in the app screen for pricing terms.

Green:
- Existing visible app copy already avoided price, rate, tax, value, amount, and discount terms.
- The test now protects the Customer and Sales Employee order screens from accidentally introducing pricing copy.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `67` mobile behavior tests passed.

## Cycle 93: Backend Required DocType Install Evidence

Red:
- Added install-visible backend coverage for required Goal 2 DocTypes.
- The test verifies Frappe has installed every required custom DocType for Customer access, Sales Employee access, Tally masters/sync, branch mapping, Orders, PDFs, WhatsApp logs, status logs, reconciliation, and reference sequencing.

Green:
- Existing DocType migrations already satisfied the required model set.
- The test now protects against missing DocTypes during future migrations/install runs.

Verification:

```sh
.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `71` backend tests passed.

## Cycle 92: Backend WhatsApp Provider Log Metadata

Red:
- Tightened the Order Placed PDF/WhatsApp behavior test.
- The test now verifies the WhatsApp notification log stores:
  - Customer-only recipient;
  - PDF attachment reference;
  - request payload with `Order Placed` event;
  - provider response metadata;
  - queued status and retry count.

Green:
- Added initial `provider_response` JSON to the Order WhatsApp Notification record.
- The queued provider response records `frappe_whatsapp`, `Queued`, `retry_count: 0`, and a dispatch message.
- Updated backend API docs to describe notification/PDF side effects and provider log fields.

Verification:

```sh
.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `70` backend tests passed.

## Cycle 91: Backend Token Verification Reads Request Headers

Red:
- Added backend session/logout coverage for real request-header token extraction.
- The test verifies `current_session()` and `revoke_token()` work when the token is present in `frappe.local.request.headers` and no explicit `headers` argument is passed.

Green:
- Updated token extraction to fall back to `frappe.local.request.headers`.
- Preserved explicit `headers` arguments for direct service tests and mobile adapter unit coverage.

Verification:

```sh
.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `70` backend tests passed.

## Cycle 90: Backend Token-Gated Customer Access Status

Red:
- Added backend token coverage for Customer App Access status.
- The test verifies:
  - a supplied empty header set is rejected as missing token;
  - a Customer token for a different Customer is rejected;
  - a matching Customer token can load the access checklist/status.

Green:
- Added token identity validation to the Customer App Access status wrapper.
- Preserved tokenless direct calls for pre-login/signup flow tests by validating only when request/supplied headers exist.
- Documented the post-login `Auth-Token` requirement.

Verification:

```sh
.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `69` backend tests passed.

## Cycle 89: Backend Token-Gated Profile And Customer Selection APIs

Red:
- Added backend token coverage for profile and Sales Employee customer selection.
- The tests verify:
  - Allowed Customers rejects missing and mismatched Sales Employee tokens;
  - matching Sales Employee tokens can load assigned Customers;
  - Customer profile read/update reject missing or mismatched Customer tokens;
  - matching Customer tokens can read and update editable profile fields.

Green:
- Added token identity validation to profile read/update wrappers.
- Added token identity validation to Sales Employee allowed-customer wrapper.
- Documented `Auth-Token` requirements for profile and allowed-customer endpoints.

Verification:

```sh
.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `68` backend tests passed.

## Cycle 88: Backend Token-Gated Product And Stock APIs

Red:
- Added backend product/read coverage for custom mobile token verification.
- The test verifies:
  - Allowed Product Groups rejects a missing token when headers are supplied;
  - Allowed Items rejects a Customer token for a different Customer;
  - Item Stock rejects a Customer token for a different Customer;
  - matching Customer tokens can read groups, items, and advisory stock.

Green:
- Added token identity validation to Product Group, item, and stock API wrappers.
- Enforced Customer-token identity for Customer requests and Sales Employee-token identity for Sales Employee context requests.
- Documented `Auth-Token` requirements for Product Group, item, and stock endpoints.

Verification:

```sh
.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `66` backend tests passed.

## Cycle 87: Backend Token-Gated Order History And Detail

Red:
- Added backend order read coverage for custom mobile token verification.
- The tests verify:
  - Customer order history requires a matching Customer token when headers are supplied;
  - Customer order detail requires a matching Customer token when headers are supplied;
  - missing tokens return `401`;
  - mismatched Customer tokens are rejected;
  - matching Customer tokens can read the expected data.

Green:
- Reused a shared order token validator across submit, history, and detail.
- Updated history/detail wrappers to verify supplied/request headers and enforce Customer or Sales Employee token identity.
- Documented `Auth-Token` requirements for history and detail endpoints.

Verification:

```sh
.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `65` backend tests passed.

## Cycle 86: Backend Token-Gated Order Submission

Red:
- Added backend order submission coverage for custom mobile token verification.
- The test verifies:
  - an explicitly token-gated submit request without a token returns `401`;
  - a Customer token for a different Customer is rejected;
  - a matching Customer token can place the Order.

Green:
- Updated the whitelisted order submit wrapper to verify supplied/request headers with `verify_token`.
- Enforced Customer-token identity for Customer submissions and Sales Employee-token identity for Sales Employee submissions.
- Kept the lower-level order service callable for direct business-rule tests.
- Documented the submit endpoint `Auth-Token` requirement and identity matching rule.

Verification:

```sh
.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `63` backend tests passed.

## Cycle 85: Backend API Validation Status Codes

Red:
- Added backend API envelope coverage for a validation failure.
- The test verifies non-positive Order Quantity returns a consistent error envelope with `http_status_code` 400.

Green:
- Updated the shared API error helper to infer status codes for common Frappe errors:
  - validation/business-rule errors: 400;
  - permission errors: 403;
  - missing documents: 404;
  - unexpected errors: 500.
- Preserved explicit endpoint status codes such as invalid token 401, signup conflict 409, and OTP cooldown 429.
- Updated backend API docs to describe the status-code mapping.

Verification:

```sh
.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `62` backend tests passed.

## Cycle 84: Backend Customer Client Code Lifecycle

Red:
- Added public Customer lifecycle coverage for Client Code rules.
- The test verifies:
  - a Client Code can be assigned to only one Customer;
  - removing Client Code from an active approved Customer recalculates `customer_app_access` to false;
  - the Customer App Access status API reports the missing Client Code requirement.

Green:
- Added explicit Customer DocType validation for duplicate Client Code before the database unique constraint.
- Existing Customer validation recalculated access on save after Client Code removal.

Verification:

```sh
.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `62` backend tests passed.

## Cycle 83: Backend Owner/Admin Order Control Success Coverage

Red:
- Added public backend behavior coverage for privileged Order controls.
- The tests verify:
  - Owner can cancel a placed Order and writes an `Order Status Log`;
  - Admin can partially close a partially processed Order and writes an `Order Status Log`.

Green:
- Existing Owner/Admin order-control implementation already satisfied the new behavior.
- The test evidence now covers both privileged success paths and branch-role rejection paths.

Verification:

```sh
.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `61` backend tests passed.

## Cycle 82: Backend Ambiguous Duplicate Reconciliation

Red:
- Added a reconciliation acceptance test for two Sales Invoices with the same portal reference, Customer Client Code, tracking number, item, godown, and quantity.
- The test verifies the second matching movement is treated as ambiguous instead of being counted as independent fulfillment.

Green:
- Added duplicate movement detection against already reconciled Tally vouchers.
- Preserved Delivery Challan supersession by Sales Invoice so legitimate mirrored DC/Sales movement still de-duplicates without Manual Review.
- Ambiguous duplicate movements now move the Order to `Manual Review` with a reason log.

Verification:

```sh
.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `59` backend tests passed.

## Cycle 81: Mobile Profile Access Failure Handling

Red:
- Added mobile profile behavior coverage for backend access failures.
- The test verifies profile load and Customer profile save failures are classified as recoverable access-changed states.

Green:
- Added `loadProfileForMobile` and `saveCustomerProfileForMobile` helpers around profile API calls.
- Sanitized Customer profile save patches inside the save helper.
- Updated the app profile screen to set request/banner state and avoid throwing when profile access is removed.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `66` mobile behavior tests passed.

## Cycle 80: Backend Profile Access Guards

Red:
- Added backend profile regressions for protected mobile identity state.
- The tests verify:
  - Customer profile reads are rejected after Customer App Access is removed;
  - Customer profile updates cannot mutate editable fields after access removal;
  - disabled Sales Employees cannot load profile data.

Green:
- Added Customer App Access validation before Customer profile serialization.
- Added the same Customer validation before applying profile updates.
- Added Sales Employee active-status validation before profile serialization.

Verification:

```sh
.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
```

Result:
- `58` backend tests passed.

## Cycle 55: Mobile Customer Access Status Routing

Red:
- Added mobile auth behavior tests for Customer App Access status routing.
- The tests verify:
  - active Customer App Access routes to the Product Group/order home step;
  - inactive or removed Customer App Access routes to pending access.

Green:
- Added `nextStepFromCustomerAccessStatus` to the auth domain module.
- Updated Customer OTP success handling to call `customerAccessStatus` before entering the order flow.
- Routed Customers with inactive access back to the pending access screen instead of assuming active ordering access after token creation.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `47` mobile behavior tests passed.

## Cycle 54: Mobile Customer Access Status API Parity

Red:
- Added mobile API boundary tests for Customer App Access status.
- The tests verify:
  - the live Frappe adapter calls `kunal_enterprises.api.customer_access.status` with the Customer;
  - fixture mode exposes the same `customerAccessStatus` method.

Green:
- Added deterministic fixture Customer App Access status responses.
- Added active and pending fixture checklist states.
- Preserved fixture/live API parity for access-status checks used by disabled/access-removed handling.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `46` mobile behavior tests passed.

## Cycle 53: Mobile Run And API Environment Documentation

Red:
- Audited the mobile README against the Goal 3 deliverables.
- The README still described an early Customer-only slice and did not document:
  - fixture/live API mode behavior;
  - Expo Frappe base URL configuration;
  - covered backend method names;
  - session, history/detail, profile, and failure-state support;
  - current verification limits.

Green:
- Updated `apps/mobile/README.md` with the current Customer and Sales Employee mobile scope.
- Documented `EXPO_PUBLIC_FRAPPE_BASE_URL` and the default local Frappe URL.
- Documented fixture mode, live Frappe mode, supported backend methods, run/test commands, and verification status.

Verification:

```sh
cd apps/mobile
npm test
```

Result:
- `45` mobile behavior tests passed.
