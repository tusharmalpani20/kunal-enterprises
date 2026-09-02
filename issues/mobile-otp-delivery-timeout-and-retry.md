# Mobile OTP Delivery Timeout And Retry Lock

## Issue status

- **Status:** Deferred; documented for later implementation.
- **Recorded on:** 2026-09-02.
- **Last audited on:** 2026-09-02.
- **Severity:** High for login reliability; no confirmed data-loss or permission impact.
- **Affected applications:** `apps/mobile` and `apps/kunal_enterprises`.
- **Affected environment:** Mobile builds pointed at `https://ke-dev.hopnet.co.in`.
- **Related issue:** This is separate from the Tally stock-group hierarchy issue recorded in `issues/tally-stock-group-parent-hierarchy-missing.md`.
- **Scope of this note:** Investigation and implementation planning only. No application code was changed while recording this issue.

## Short description

On more than one occasion, a user tapped **Send OTP**, received an error similar to:

```text
Could not reach server
```

No OTP was received. The user then tried **Send OTP** again and was told that an OTP had already been sent or was asked to wait before trying again.

From the user's perspective, this is contradictory: the first attempt failed and no OTP was received, but the second attempt was blocked as if the first attempt had succeeded.

The repository shows that this can be caused by an ambiguous request result. The mobile app has a 15-second timeout, while the backend may have already created or queued an OTP before the response reached the device. The repository also has a separate frontend countdown bug and does not contain a complete, verifiable Mobile OTP provider-dispatch path.

The exact path taken during the reported incidents is not proven yet because the exact request timestamps, server request logs, and `Mobile OTP` rows for those attempts have not been correlated on `ke-dev`.

## User-visible symptoms

The affected flow is:

1. User enters a mobile number on the login screen.
2. User taps **Send OTP**.
3. The app waits and displays a generic server/network error.
4. No OTP is received on WhatsApp.
5. User taps **Send OTP** again.
6. The retry is blocked or reports that another OTP request already exists.

Observed impact:

- A valid user may not be able to log in immediately.
- The user cannot tell whether the OTP was sent, queued, or not processed.
- The generic error encourages an immediate retry even when the server may already have processed the request.
- A retry may create a second error because the backend cooldown is already active.
- If the UI cooldown is stale, the user may remain blocked until the app is re-rendered or restarted.

## Expected behavior

The system should distinguish these states:

```text
Request not received by backend
Request received and queued
Provider accepted or sent OTP
Provider failed to send OTP
Request result unknown because the client timed out
OTP expired
OTP verified
```

The user-facing behavior should be:

- If the backend definitely did not receive the request, allow an immediate retry.
- If the backend accepted the request, show that the request was queued and show the real retry time.
- If the provider failed, mark the request failed and allow a retry according to the defined retry policy.
- If the client timed out after the server may have processed the request, do not claim that the server was definitely unreachable. Explain that the request status is unknown and provide a safe retry/status action.
- Never show **OTP sent** when the only confirmed state is **Queued**.
- Always clear the loading state after success, failure, timeout, or cancellation.
- Automatically unlock the resend action when the cooldown ends.

## Current request flow

The current live flow is:

```text
SignInScreen
  -> OrderFlowProvider.requestOtp()
  -> createMobileApi({ call })
  -> frappeClient.postOtp()
  -> Frappe whitelisted OTP method
  -> _issue_otp_with_cooldown()
  -> _wait_for_cooldown()
  -> _issue_otp()
  -> Mobile OTP record
  -> Frappe response
```

### Initial login

For the login option, `requestOtp()` calls `requestSignInOtp()`, which calls:

```text
kunal_enterprises.api.otp.send_login_otp
```

This endpoint resolves the mobile number to either a Customer or Sales Employee and then creates the OTP.

### Customer signup

For new Customer signup, the app calls:

```text
kunal_enterprises.api.otp.start_customer_signup
```

### Explicit resend

After a successful previous request and a completed cooldown, the app calls:

```text
kunal_enterprises.api.otp.resend_otp
```

## Code references

### Mobile application

| Reference | Relevant behavior |
| --- | --- |
| `apps/mobile/src/constants/config.ts:1-3` | Defines `MOBILE_API_TIMEOUT_MS = 15000`. |
| `apps/mobile/src/providers/frappe.tsx:112-127` | Applies the 15-second Axios timeout to the Frappe client. |
| `apps/mobile/src/api/frappeClient.mjs:5-11` | Maps mobile OTP actions to the backend methods. |
| `apps/mobile/src/api/frappeClient.mjs:39-55` | Sends initial login and resend OTP calls. |
| `apps/mobile/src/api/frappeClient.mjs:197-205` | Unwraps responses but throws away most structured error metadata. |
| `apps/mobile/src/api/frappeClient.mjs:208-216` | Converts timeout/network failures into `Unable to reach the server`. |
| `apps/mobile/src/api/mobileApi.mjs:4-12` | Selects the live Frappe adapter only when a Frappe `call` object exists; otherwise it falls back to the mock adapter. |
| `apps/mobile/src/api/frappeClient.mjs:5-23` and `apps/kunal_enterprises/kunal_enterprises/api/otp.py` | Expose send, resend, and verify operations, but no OTP status or request-result lookup method. |
| `apps/mobile/src/flow/OrderFlowProvider.tsx:143-150` | Stores OTP timestamps, cooldown, loading state, and in-flight guards. |
| `apps/mobile/src/flow/OrderFlowProvider.tsx:425-437` | Calculates resend state from `Date.now()` during React renders. |
| `apps/mobile/src/flow/OrderFlowProvider.tsx:719-800` | Blocks, sends, handles errors, and clears the OTP request loading state; the early block returns silently. |
| `apps/mobile/app/(auth)/sign-in.tsx:143-175` | Disables Send/Resend actions and displays the cooldown text. |
| `apps/mobile/src/domain/authAccessFlow.mjs:115-151` | Implements the pure cooldown, request-key, and resend-gate helpers. |

### Backend application

| Reference | Relevant behavior |
| --- | --- |
| `apps/kunal_enterprises/kunal_enterprises/api/otp.py:93-108` | Implements `send_otp`. |
| `apps/kunal_enterprises/kunal_enterprises/api/otp.py:111-127` | Implements `send_login_otp`. |
| `apps/kunal_enterprises/kunal_enterprises/api/otp.py:130-145` | Implements `resend_otp`. |
| `apps/kunal_enterprises/kunal_enterprises/api/otp.py:333-354` | Blocks requests when an open OTP exists within the cooldown. |
| `apps/kunal_enterprises/kunal_enterprises/api/otp.py:357-387` | Adds the per-mobile, per-purpose database lock. |
| `apps/kunal_enterprises/kunal_enterprises/api/otp.py:395-443` | Expires older open records and inserts a new `Mobile OTP` record as `Open` and `Queued`. |
| `apps/kunal_enterprises/kunal_enterprises/api/otp.py:450-455` | Determines Sales Employee OTP type. |
| `apps/kunal_enterprises/kunal_enterprises/api/otp.py:157-220` | Verifies Customer and Sales Employee OTPs. |
| `apps/kunal_enterprises/kunal_enterprises/api/otp.py:251-262` | Returns cooldown and expiry values, but does not return the created `Mobile OTP` name or a request reference. |
| `apps/kunal_enterprises/kunal_enterprises/api/utils.py:17-29` | Logs backend exceptions and returns structured error envelopes. |
| `apps/kunal_enterprises/kunal_enterprises/kunal_enterprises/doctype/mobile_otp/mobile_otp.json:55-77` | Defines `Open`, `Verified`, `Expired`, `Failed` and provider states `Queued`, `Sent`, `Failed`. |
| `apps/kunal_enterprises/kunal_enterprises/kunal_enterprises/doctype/mobile_otp/mobile_otp.json:22-105` | Stores OTP and provider state, but has no dedicated client request ID or idempotency-key field. |
| `apps/kunal_enterprises/kunal_enterprises/kunal_enterprises/doctype/mobile_otp/mobile_otp.py:8-13` | Validates that OTP codes contain four digits. |

### Documentation and tests

| Reference | Relevant evidence or gap |
| --- | --- |
| `docs/10-backend-api.md:124` | Describes OTP records as queued for `frappe_whatsapp` and says login/resend creation is cooldown protected. |
| `docs/10-backend-api.md:126-140` | Documents `send_login_otp` and says it creates the OTP. |
| `docs/10-backend-api.md:176-208` | Documents resend and HTTP 429 cooldown behavior. |
| `docs/12-operational-readiness-checklist.md:18` | States that live WhatsApp credentials and controlled Customer/Sales Employee OTP tests are still required. |
| `apps/mobile/tests/frappe-client.test.mjs:233-243` | Tests conversion of a no-response error into the generic retryable message. |
| `apps/mobile/tests/auth-access-flow.test.mjs:187-208` | Tests cooldown calculations and resend gating as pure functions. |
| `apps/mobile/tests/api-selection.test.mjs` | Tests live/mock adapter selection, but does not prove that the production login screen cannot run against the mock adapter before the live Frappe call is ready. |
| `apps/kunal_enterprises/kunal_enterprises/tests/test_foundation.py:418-451` | Verifies that signup creates an open OTP with provider status `Queued`. |
| `apps/kunal_enterprises/kunal_enterprises/tests/test_foundation.py:474-486` | Verifies that resend is blocked during the cooldown. |
| `apps/kunal_enterprises/kunal_enterprises/tests/test_foundation.py:1135-1163` | Verifies Sales Employee OTP creation and `Queued` state. |
| `apps/kunal_enterprises/kunal_enterprises/tests/test_foundation.py:1194-1228` | Verifies that a second Sales Employee request is blocked while an open OTP exists. |

## Confirmed findings

### 1. The mobile timeout is ambiguous

The Frappe Axios client times out after 15 seconds. The mobile client then replaces timeout and network errors with:

```text
Unable to reach the server. Please check your connection and try again.
```

This message only proves that the mobile app did not receive a usable response. It does not prove that the backend did not receive or process the request.

A request can fail from the app's perspective after the backend has already committed the OTP record.

### 2. OTP creation and OTP delivery are not the same state

The backend inserts a `Mobile OTP` record with:

```text
status: Open
provider_status: Queued
```

The API response is labelled:

```text
OTP sent
```

`Queued` means that the application has recorded a dispatch request. It does not prove that WhatsApp delivered the message.

### 3. The cooldown is based on `Open`, not delivery success

The backend looks for the latest record matching:

```text
mobile_number = requested number
purpose = current OTP purpose
status = Open
```

If the record is less than 45 seconds old, the backend rejects the next request. It does not check whether `provider_status` is `Sent` or `Failed`.

Therefore, a queued or provider-failed OTP can still block a retry.

### 4. The provider dispatch path is not present in this repository

The local backend code creates a queued `Mobile OTP` record, but there is no visible call in this repository that sends the OTP through `frappe_whatsapp`, enqueues a Mobile OTP job, or updates the OTP provider status after dispatch.

The `frappe_whatsapp` app is listed as installed and the health check verifies that it is installed, but installation alone does not prove that Mobile OTP records are connected to a working dispatch hook or worker on `ke-dev`.

The live provider path must be checked on the server and in the installed `frappe_whatsapp` app.

### 5. The frontend loading guard is cleared on a normal error

The request function sets the in-flight guard and loading state before the API call. Its `finally` block clears both after the promise settles.

This means a normal rejected request should not permanently display `Sending OTP...`.

If the spinner remains indefinitely, possible explanations include:

- The request promise has not settled as expected.
- The installed APK contains older code.
- The Frappe SDK call is not respecting the configured timeout in the running build.
- A separate screen/state transition is hiding the state reset.

### 6. The resend countdown has no periodic re-render

The provider calculates the countdown using `Date.now()` during render, but there is no `setInterval` or equivalent timer that updates React state every second.

The resend button is disabled when `resend.canResend` is false. Without a periodic re-render, the displayed countdown and disabled state can remain stale until another interaction triggers a render.

This is a confirmed frontend defect, separate from the backend delivery problem.

### 7. There is no OTP status lookup or request correlation identifier

The mobile API method map contains send, resend, and verify operations, but no method that can query a previously submitted OTP request. The `Mobile OTP` DocType stores OTP and provider fields, but has no dedicated client request ID or idempotency key.

Although each created DocType row has a Frappe name, the current OTP response does not return that name or another request reference. The client also sends no idempotency key before creation. After a timeout, the app therefore cannot ask whether the request was created, queued, sent, failed, or expired. Logs can only correlate the attempt manually using timestamps, mobile numbers, and endpoint data. Any request ID added by a future fix must be opaque and must never contain the OTP code or an authentication token.

### 8. Structured error details are discarded

The backend currently returns an error envelope containing:

- A top-level error message
- The underlying exception message in `error.message`
- The HTTP status code in `http_status_code`

For cooldown failures, the remaining seconds are currently embedded in the human-readable error message. There is no dedicated `retry_after_seconds` field in the current response.

The mobile `unwrap()` helper reduces this to a JavaScript `Error` containing only a message. The UI therefore cannot reliably distinguish:

- 400 validation error
- 429 cooldown error
- 500 backend error
- Network timeout
- Provider failure

### 9. `resend_otp` classifies every exception as 429

The `resend_otp` handler always returns HTTP status `429` in its exception path. A provider error or validation error can therefore appear to the client as a rate-limit error.

### 10. Advertised OTP expiry is not enforced

The backend returns:

```text
expires_in_seconds: 300
```

But the verification methods only require an OTP record with `status = Open`. They do not compare the current time with the OTP creation or modification time.

This is not the cause of the reported retry incident, but it is a related OTP lifecycle gap that should be addressed in the same backend work.

### 11. Live and mock API selection is a diagnostic risk

`createMobileApi({ call })` returns the live Frappe adapter when `call` exists and the fixture/mock adapter otherwise. This is useful for UI-first development, but it means a screen rendered before the live Frappe call is ready can execute mock behavior instead of contacting `ke-dev`.

The reported `Could not reach server` message indicates that a network-aware live call was probably used for that attempt, but the running APK must still be verified. A production build should expose its live/mock mode or prevent mock mode from being reachable in a production configuration.

This is a diagnostic and release-safety gap, not proof that the reported incident used the mock adapter.

### 12. The request gate can silently ignore a tap

`requestOtp()` returns immediately when its in-flight or cooldown gate rejects the request. It does not update the system state or show a reason.

The visible Resend control is normally disabled at the same time, but stale or inconsistent state can make the action appear to do nothing. The eventual fix should make the blocked reason explicit and keep the UI state derived from the same authoritative cooldown data.

### 13. The API documentation does not exactly match the current login caller

The current mobile login path calls `send_login_otp` through `startLoginOtp`. The backend documentation also describes `send_otp` as the starting point for Sales Employee login. `send_otp` remains a backend API, but it is not the endpoint used by the current generic login screen.

This mismatch can cause the server investigation to inspect the wrong endpoint or purpose. The deployed request must be identified from logs rather than inferred from the older documentation.

## How the reported incident could happen

### Scenario A: Backend processed the request, but the response timed out

This is the most important possibility:

1. The app calls `send_login_otp`.
2. The backend validates the identity.
3. The backend creates `Mobile OTP` with `status = Open` and `provider_status = Queued`.
4. The provider or request processing is slow, or the HTTP response is lost.
5. The mobile app reaches its 15-second timeout and shows `Could not reach server`.
6. The user receives no WhatsApp message because dispatch did not happen or failed.
7. The user retries.
8. The backend sees the open record and rejects the retry during the 45-second cooldown.

In this scenario, the user's observation is valid: no OTP was received, but the backend still has an active request.

### Scenario B: The first request failed before creating a record

If the server confirms that no matching `Mobile OTP` record exists, the first request may have failed before `_issue_otp()` inserted the record. A record lookup must use the exact normalized mobile number and the exact purpose used by the endpoint.

In that case, the second block would need another explanation, such as:

- A previous open OTP for the same number and purpose.
- A lookup using a different normalized mobile number.
- A mismatch between `Customer Signup` and `Sales Employee Login` purpose filters.
- A different endpoint or server release handling the second request.
- A stale frontend state from an earlier successful request.
- An older APK with different retry logic.
- The live/mock adapter selection using a mock call before the Frappe call was ready.
- An API gateway or provider-side rate limit not represented by the `Mobile OTP` table.

The current repository does not contain the literal phrase “OTP has already been sent.” The backend's current cooldown message is based on “Please wait X seconds before requesting another OTP.” If the exact phrase was shown, capture the full response body and confirm which deployed release produced it.

### Scenario C: The frontend still had an older successful request state

The frontend stores `otpSentAtMs` and `lastOtpRequestKey` in provider memory. A failed request does not clear an older successful request state.

If the user had already successfully requested an OTP for the same mobile number and identity on the same screen, a later failed attempt can still be affected by the previous state.

For a clean first attempt, the current failure path should clear the loading state and should not create a new cooldown timestamp. This must be tested in the running APK, not only inferred from source. If the request gate rejects a tap, the app currently gives no explicit reason.

## Evidence still required from `ke-dev`

The exact incident cannot be closed from local source inspection alone. The server agent should capture the following for one reproduced attempt:

### Mobile request evidence

- Timestamp in UTC and IST.
- Exact endpoint called.
- Mobile number after normalization, masked in shared logs.
- HTTP status.
- Full response envelope with OTP code and tokens removed.
- Whether the client error was a timeout, DNS failure, TLS failure, connection reset, or HTTP response error.
- App version and build number.
- Confirmation that the build points to `https://ke-dev.hopnet.co.in`.
- Confirmation from logs or a diagnostic build that the call used the live Frappe adapter rather than the mock adapter.

### Frappe database evidence

In a controlled server console session, inspect both OTP purposes for the affected number:

```python
frappe.get_all(
    "Mobile OTP",
    filters={"mobile_number": "<normalized-mobile-number>"},
    fields=[
        "name",
        "mobile_number",
        "purpose",
        "otp_type",
        "status",
        "provider",
        "provider_status",
        "provider_response",
        "creation",
        "modified",
    ],
    order_by="modified desc",
    limit_page_length=20,
)
```

Check specifically for:

```text
Customer Signup
Sales Employee Login
```

The OTP code itself must not be copied into logs, issue comments, screenshots, or chat messages.

### Provider and worker evidence

Verify on `ke-dev`:

- `frappe_whatsapp` credentials and configuration.
- The provider/template configuration used for OTP.
- The hook or job that consumes Mobile OTP records.
- Worker process health.
- Queue backlog and failed jobs.
- Provider response/status updates.
- Whether failed dispatches set `provider_status = Failed`.
- Whether failed dispatches set `status = Failed` or otherwise stop the cooldown.
- Frappe Error Logs for the same timestamp.

## Recommended fix plan

The implementation should be done in phases. The backend/provider contract must be clarified before changing the mobile retry behavior.

### Phase 1: Reproduce and classify the incident

1. Use a controlled test mobile number on `ke-dev`.
2. Record the exact request time and endpoint.
3. Capture the HTTP response or timeout from the device.
4. Query `Mobile OTP` immediately after the attempt.
5. Check Frappe logs and provider/worker logs.
6. Repeat with a deliberate network interruption after the request is sent to reproduce the ambiguous-result case.
7. Confirm whether the record is absent, queued, sent, failed, or open from an older attempt.
8. Confirm whether the app used `send_login_otp` or another endpoint; do not rely only on the screen label.
9. Confirm whether the running build used the live adapter and whether the base URL was the expected `ke-dev` instance.

This phase decides whether the first implementation target is provider delivery, backend state handling, mobile timeout handling, or multiple areas.

### Phase 2: Define the OTP state contract

Agree on the meaning of each state:

| State | Meaning | Can user retry? |
| --- | --- | --- |
| `Queued` | Backend accepted the request and has handed it to a dispatch path or queue. | Only after the defined cooldown, unless the queue marks it failed. |
| `Sent` | Provider accepted or delivered the message, according to the provider's actual guarantee. | After cooldown. |
| `Failed` | Provider or backend could not dispatch the message. | Yes, according to a short retry policy. |
| `Expired` | OTP is no longer valid. | Yes; a new OTP may be requested. |
| `Verified` | OTP was successfully used. | Not applicable. |
| `Unknown` | Client-side outcome only: the client timed out and cannot know the server result. This is not currently a stored backend `Mobile OTP` status. | Must use a safe status/retry path; must not claim success. |

These values are not currently one unified state field. The backend `status` field tracks the OTP lifecycle (`Open`, `Verified`, `Expired`, or `Failed`), while `provider_status` tracks dispatch state (`Queued`, `Sent`, or `Failed`). `Unknown` exists only in the proposed client behavior. The implementation must define which combinations are valid and how they map to user-visible copy.

The provider may not support a true delivered state. If it only supports accepted/queued, the UI copy must say that clearly.

### Phase 3: Make backend creation and delivery failure-safe

1. Verify or implement the actual Mobile OTP dispatch through the installed `frappe_whatsapp` integration.
2. Persist provider status transitions and provider responses.
3. Mark records `Failed` when dispatch fails.
4. Do not block retries based on records that are definitively failed.
5. Keep the per-mobile lock, but ensure it only covers the short request/dispatch critical section.
6. Return a request ID or OTP request reference that does not expose the OTP code.
7. Return `cooldown_seconds` or `retry_after_seconds` on cooldown errors.
8. Preserve structured HTTP status and error data through the mobile client to the UI.
9. Correct `resend_otp` so validation/provider errors are not all reported as 429.
10. Enforce the five-minute OTP expiry during Customer and Sales Employee verification.
11. Add stale queued-record handling so a queue failure cannot leave an indefinite active request.
12. Ensure an incomplete or unavailable provider configuration fails explicitly rather than silently leaving a queued record with no dispatch path.
13. Store the request ID/idempotency key and use it when matching retries or status checks.

### Phase 4: Make retry behavior safe for timeouts

A timeout cannot prove that the backend did not process the request. The preferred design is to add an idempotent request key:

1. The app generates an opaque request ID for each OTP attempt and retains it if the result becomes unknown.
2. The request ID is sent to the backend and stored with the OTP request.
3. A status lookup can query that request ID and return the current request state without exposing the OTP.
4. Repeating the same request ID returns the existing request result instead of creating an ambiguous duplicate.
5. A new request ID is used only after the existing request is failed, expired, or safely eligible for resend.

The request ID must be scoped to the normalized mobile number and OTP purpose, rate-limited, and treated as an opaque reference. A status endpoint must not allow an unauthenticated caller to enumerate mobile numbers, OTP values, or unrelated users' provider details. It should require enough binding data to prove that the caller is checking the same attempt, while still supporting the guest login flow.

If the provider cannot support status lookup immediately, the minimum safe behavior is:

- Return a clear “request status unknown” response to the app after a timeout.
- Tell the user when the next retry is safe.
- Keep server-side cooldown authoritative.
- Avoid falsely claiming that the server was unreachable.

Simply increasing the timeout is not a complete fix. It may reduce false timeouts but cannot eliminate lost responses or provider failures.

### Phase 5: Fix mobile request and resend state

1. Keep the existing in-flight guard to prevent duplicate taps.
2. Add a real one-second timer while the cooldown is active.
3. Stop the timer at zero and enable Resend automatically.
4. Preserve OTP state only for the same mobile number, mode, and intent.
5. Clear stale state when changing login identity or starting a clean flow.
6. Preserve structured backend status and retry information instead of only the error string.
7. Show distinct copy for:
   - Server unreachable before processing could occur.
   - Request timed out and may have been processed.
   - OTP request queued.
   - OTP provider failure.
   - Retry cooldown active.
8. Show `Sending OTP...` only while the request promise is genuinely active.
9. Add a retry or status action appropriate to the backend contract.
10. Do not show `OTP sent` when the response only confirms queue creation.
11. Make live/mock mode explicit and prevent mock OTP behavior in release builds.
12. Replace silent request-gate returns with a recoverable user-facing state.

### Phase 6: Add automated coverage

#### Backend tests

- Successful Customer OTP creation.
- Successful Sales Employee OTP creation.
- Provider accepted/queued status.
- Provider failure transitions to `Failed`.
- Failed records do not block a new request.
- Open queued records enforce the intended cooldown.
- Cooldown response includes the remaining retry time.
- Simultaneous requests are serialized.
- Structured HTTP statuses are correct.
- OTPs older than five minutes cannot be verified.
- Repeated request IDs return the existing request result.
- Status lookup returns the current request/provider state for a known request ID without exposing the OTP.

#### Mobile tests

- Loading clears after success.
- Loading clears after a rejected API promise.
- Timeout is classified as an unknown-result retry state, not definite server absence.
- A failed first attempt can be retried.
- An existing previous OTP does not block a different mobile number.
- Resend is scoped to the same identity, mode, and number.
- Countdown updates automatically without unrelated user interaction.
- 429 responses display the server-provided remaining cooldown.
- Queued responses do not display “OTP sent.”
- Customer and Sales Employee endpoint selection remains correct.
- Production/release builds cannot silently use the mock adapter.

#### Live acceptance tests

- Customer login receives an OTP on `ke-dev`.
- Sales Employee login receives an OTP on `ke-dev`.
- Deliberate network loss after request submission produces a safe retry message.
- A provider failure allows retry after the defined policy.
- Repeated taps do not create multiple active OTPs.
- The resend button unlocks without typing or navigating away.
- Expired OTPs cannot be verified.
- The request reaches the expected live endpoint and no fixture/mock OTP is used.

### Phase 7: Roll out safely

1. Deploy backend/provider changes to `ke-dev` first.
2. Run controlled Customer and Sales Employee tests.
3. Confirm database/provider status transitions.
4. Build the mobile APK with the `ke-dev` base URL.
5. Test on a connected Android device.
6. Review Frappe Error Logs and provider logs.
7. Release to a small pilot group.
8. Monitor OTP request outcomes, timeout rates, provider failures, and retry blocks.

## Temporary operational workaround

Until this issue is fixed:

1. If the app says `Could not reach server`, do not immediately tap Send OTP repeatedly.
2. Check whether an OTP arrived after a short delay.
3. Wait at least the server cooldown period of 45 seconds before retrying.
4. If the resend control remains visibly locked, force-close and reopen the app.
5. If the problem repeats, capture the exact time and mobile number and ask the server agent to inspect the `Mobile OTP` record and provider logs.

This workaround does not solve the underlying ambiguity and should not be considered production behavior.

## What this issue is not

- It is not confirmed to be caused by incorrect Customer or Sales Employee permissions.
- It is not confirmed to be caused by the mobile device losing internet throughout the entire request.
- The generic `Could not reach server` message does not prove that the backend did not receive the request.
- Increasing the timeout alone is not a complete solution.
- Removing the backend cooldown is not a safe solution.
- Bypassing the provider or creating OTPs only in the mobile app is not acceptable.

## Definition of done

This issue can be closed when:

- A live OTP request has a traceable request status from mobile through Frappe and the provider.
- The user is never told an OTP was sent when only queue creation is known.
- A failed provider request does not incorrectly block retries.
- A timeout has a safe, explicit unknown-result flow.
- A timed-out request can be checked by request ID, or the documented fallback safely handles an unknown result.
- The resend countdown unlocks automatically.
- The backend returns accurate status codes and retry information.
- OTP expiry is enforced.
- Customer and Sales Employee live tests pass on `ke-dev`.
- Backend and mobile automated tests cover the failure and retry paths.
