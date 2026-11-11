# Order intake requests

Order Intake Request is the generic review document for requests received through external channels. WhatsApp is the first and only implemented source in the initial design. Request Type distinguishes Order, Stock Inquiry, Price Inquiry, Mixed, and Unclear. Existing Quick Orders and Orders remain unchanged.

The goal is to reduce manual work by 90–95 percent while prioritising that no actual order is silently missed. This is a target to measure during the pilot, not an accuracy guarantee or a confidence threshold for hiding requests. Uncertainty produces an editable draft or visible review task. Original messages and attachments must remain accounted for.

## Step 1 scope

Step 1 establishes two main DocTypes, three active child tables and two hidden legacy child types:

| DocType | Purpose |
| --- | --- |
| Order Intake Request | Sender metadata, selected customer and salesperson, request type, status, estimated interpretation, review notes and delivery details |
| Order Intake Item | Original phrase, optional selected SKU, quantity, unit and dispatch warehouse on the same row; original warehouse wording and source references remain in row details |
| Order Intake Warehouse | Hidden legacy evidence from the first layout; no longer an editable warehouse table |
| Order Intake Allocation | Hidden legacy evidence from the first layout; no longer an active allocation table |
| Order Intake Attachment | File, external URL or native location, review state, page count and source message |
| Order Intake Source Message | Message association and note; one message may belong to multiple requests |
| Order Intake Settings | Restricted provider credentials, model identifiers and future processing limits |

Unknown senders, blank customers, blank salesperson, missing SKUs, missing quantities and missing godowns do not prevent draft creation. A blank/zero draft quantity represents unresolved information, not a confirmed order quantity. Negative or non-finite quantities are rejected. Reviewers select the item, quantity, unit and dispatch warehouse directly on one Items table. A warehouse may remain blank. Dispatching the same item from different warehouses uses separate rows with their respective quantities. Stable item row IDs preserve identity across corrections and reordering.

The main form shows request type/status, customer/salesperson, Items and General Notes. Empty Delivery, Attachments and References, and Interpretation sections are hidden. Add Details offers Delivery Details, Attachment or Reference, and Interpretation to reveal them without changing data. Populated sections appear automatically; unresolved questions also make Interpretation visible. Empty sections opened during editing remain available until save, then hide again if still empty. Interpretation Notes is a manual clarification field, separate from the read-only AI summary. Source defaults to WhatsApp and is hidden and read-only. WhatsApp account, sender metadata, received timestamps and the source-message table are under a collapsed Details section. Development banners and the Add Allocation action are removed. There is no View Conversation button until the chat view is functional.

Earlier warehouse/allocation tables are hidden, read-only evidence. The idempotent simplification patch moves only one-to-one relationships with compatible quantities onto their item row. It never turns an unmatched warehouse phrase into a selected master. Conflicting quantities, multiple allocations and warehouse-only instructions stay visible as review questions; warehouse source-message links are retained. Hidden historical allocations no longer restrict deleting or correcting visible item rows. Legacy tables are retained to prevent data loss; new processing must use the item row's warehouse instead.

Owner, Admin and Order Coordinator can create, read and edit requests. Owner and Admin can read and change settings; Administrator retains Frappe's built-in access. No upstream master or WhatsApp permissions are broadened. Reviewer-only paginated lookup methods expose minimal customer, salesperson, account name and incoming-message identity fields so these links remain selectable without exposing account credentials or general message bodies. The on-demand conversation display is later integration work. When source messages are provided, validation requires incoming messages from one account and sender, inferring missing request metadata. There is no webhook import, scheduler, AI call, conversion endpoint, learning job or functional chat view in Step 1.

Converted to Order exists in the schema for the eventual lifecycle, but is hidden from the editable status choices and rejected by server validation. The converted Order link cannot be populated in Step 1. There is no Process or Create Order action yet. Other statuses can be recorded manually for form review; later workflow actions will own their transitions. The settings enable switch is read-only and server-guarded off. Configuring settings alone cannot activate any job.

## Agreed lifecycle

| Status | Meaning |
| --- | --- |
| Pending Review | Draft requires attention |
| In Review | Staff are completing or checking the request |
| Awaiting Confirmation | Inquiry handled but purchase confirmation is still awaited |
| Resolved | Inquiry finished without an Order |
| Converted to Order | Reviewer successfully created an actual Order |
| Dismissed | Reviewer marked the request irrelevant or duplicate |

An inquiry and later confirmation should remain on the same intake request where supported by evidence. The confirmation changes or proposes Request Type Order. A reviewer explicitly creates the actual Order; an inquiry does not itself create one. The AI may suggest dismissal, but cannot silently discard requests.

## Grouping and processing decisions

Frappe will coordinate background jobs, with PydanticAI used for the grouping and extraction model interactions. Both initial agents use OpenAI GPT-6 Luna, medium reasoning effort; no Sol or automatic alternative-model fallback. Provider and model configuration will support a later OpenRouter switch. Exact provider model IDs are required: `gpt-6-luna` for OpenAI and `openai/gpt-6-luna` for OpenRouter.

The proposed interval is five minutes and unresolved-context window is 120 minutes, both configurable. Chats are scoped by WhatsApp account and sender identity. Context includes new messages, recent unresolved messages, relevant open drafts and explicit replies. Schedule intervals are not order boundaries. A message may contribute to more than one request; partial association must remain visible. Age limits bound model context, not storage or review visibility. Older unresolved material moves to Needs Attention. Newly received delayed messages remain eligible. A coverage check must flag incoming messages with no intake accounting.

Retries distinguish transient connection/server errors, rate limits, credentials/balance failures and invalid model output. Proposed short provider retries are two, output correction retries two, and deferred delays 5, 15 and 60 minutes. A shared per-job model-request budget prevents multiplied retry loops. Provider failure retains messages and other chats may continue. Credential problems require action instead of repeated requests. Invalid output gets precise validation feedback in the same agent history; cached input reuse is measured, not guaranteed by conversation continuity.

Model suggestions use actual master searches and source evidence. Never invent meanings for abbreviations such as SF; MR to MR+ is a candidate match, not a universal substitution. Fevicol 20 kg describes a possible product pack, not automatically twenty ordered units. Missing information is valid. Suggested percentages are evidence indicators rather than calibrated probabilities.

## Human review and learning

Each item has separate Item Notes and Correction Reason fields in its expanded row; General Notes applies to the entire request. These fields are optional and retain their association with the item through editing and reordering. They do not yet implement structured correction history or automatic learning. Estimated interpretation and unresolved questions are separate from final reviewer selections. Future AI updates may fill unreviewed fields but must propose changes to human-confirmed values rather than overwrite them. New messages and attachments remain associated and visible. Later changes to an actual Order become a linked amendment request rather than editing confirmed Order lines.

Learning evidence is created only after successful Process/Order creation and records original text, selected customer/item/godown, context, reviewer and source Order. Cancellation removes that Order's contributions from active learning while retaining unrelated valid evidence and audit history. Processing and learning writes must be atomic. These behaviours are not implemented in Step 1.

Sender recognition will distinguish the actual sender from the customer ordered for. Sales employees may identify customers by name/code even when the customer lacks a phone number. Existing employee assignment and product scope rules remain applicable; mobile-login grants should not be a prerequisite for a reviewed WhatsApp order.

**Deferred decision and implementation:** additional unknown-sender authorization is explicitly left for later. Unknown senders and incomplete drafts are preserved now. Step 1 neither grants authorization nor implements a final-processing authorization decision. That guard must be resolved before final Order processing is enabled.

## Attachments and links

The attachment table preserves PDFs, images, external links and native WhatsApp location details. Files in the relevant chat/time window are candidate attachments; time alone cannot conclusively assign a file if several requests are in progress. Reviewers can correct associations later. Original source references remain available.

Automatic PDF extraction starts with a configurable ten-page limit, alongside input/output token limits. Larger PDFs remain attached and flagged for manual review or explicit page-range processing. Do not infer irrelevance from a filename or silently omit unprocessed pages. External links, including shortened map links, are stored only: no automatic opening, fetching, downloading or geocoding. Native coordinates delivered by WhatsApp may be retained directly.

## Credentials and deployment

Enter the provider API key in Order Intake Settings, not the Meta token field in TEST WA. It is a Frappe Password field; settings change tracking is disabled so secrets are not included in Version records. Do not commit API keys, return decrypted keys to the browser, or print them in logs. Credentials remain site-specific and must be entered again on a new server.

Future Python dependencies belong in the app's `pyproject.toml`; `hooks.py` is for scheduler and document-event registrations. Step 1 adds no package dependency or new hook. Installing on another server requires updating the app, installing declared bench-environment dependencies when introduced, migrating the site, building assets and restarting normally. Do not enable Tally sync as a side effect of WhatsApp development. The new DocTypes can be loaded locally for review without changing production.

## Implementation sequence and review gates

1. Data structures, settings and initial form layout (this change); review before moving ahead.
2. Message capture, coverage tracking and sender identification.
3. Scheduling, context selection, locking, retries and duplicate protection.
4. Luna grouping/extraction with schema validation.
5. Scoped search tools and confirmed-selection learning.
6. Reviewer workflow, on-demand escaped HTML chat view and attachment/page review.
7. Manual Order conversion, inquiry actions and cancellation handling.
8. Pilot against all six distinct order examples, late messages, ambiguity and failures; measure reviewer effort, missed requests, grouping errors, latency and cost.

The development feature starts with fresh test messages and examples; historical backfill is not a launch requirement. Existing test messages may be selected explicitly. Steps 2–3 and 4–5 can be developed against the agreed schema after review, but none are enabled by Step 1.

## Step 1 verification on 11 November 2026

The DocTypes were loaded into the local `kunal_frappe` development site. Sixteen focused database tests and eight form-behaviour tests passed, covering incomplete drafts, item/warehouse pairing across corrections and reordering, legacy quantity preservation, protection of already corrected warehouses and migration idempotence, warehouse-only source evidence, invalid numeric values, reviewer-role permissions, restricted settings, blocked premature conversion/processing, source-chat separation formatted sender lookups, optional-section visibility and actions, document-switch isolation, and escaped interpretation rendering. Database test records were rolled back.

Audit fixes added scoped selectors for users without upstream master permissions, rejected mixed-chat source references even when request metadata started blank, kept the empty interpretation panel visible, and normalised formatted phone numbers without guessing country codes.

The explicitly labelled `KE-OIR-00001` review example contains an unmatched item phrase and warehouse instruction. Its earlier allocated quantity of two was retained on the item row, while the old evidence remains hidden. It is an intake draft only, not an actual Order. A local backup was taken before simplifying existing drafts. The site-specific API key and saved settings values were not modified by this layout change. Processing remains disabled. Chat rendering and automatic intake are still deferred. No production site, scheduler configuration, package dependency or existing Order workflow was changed. Work stops here for review before Step 2.

## Step 2: intake tracking on WhatsApp Message

The agreed simplification uses **WhatsApp Message itself**. There is no separate Order Intake Message or Order Intake Conversation DocType. Related messages are obtained by receiving WhatsApp account plus sender number; a chat can contain multiple orders and inquiries. Logical order grouping, scheduled processing and AI extraction remain later steps.

The custom application installs read-only tracking fields in a collapsed **Intake Details** section on incoming WhatsApp Messages. These include intake state, recognized customer/salesperson, recognition status, original incoming payload, media references, timestamps and native coordinates. Existing text, attachment, account and reply fields remain the primary source. No original messaging-app source files are edited, and permissions on WhatsApp Message are not broadened. The form offers **View Sender Messages** and **Refresh Sender Match**; the list offers **Check Coverage** and **Prepare Existing Messages** for bounded, explicit preparation of historical incoming records.

The existing callback URL still works. The wrapper passes each incoming event to the installed WhatsApp parser individually and adds intake metadata to the resulting WhatsApp Message. If the parser fails or silently skips an unsupported event/media download, the wrapper creates an Incoming WhatsApp Message containing readable escaped content, exact original JSON and a Needs Attention flag. Unsupported types map to a supported display type while retaining their actual type and raw content. Media processing/extraction is not implemented here; an unsuccessful download keeps its provider media references for review. No external links are fetched.

Provider message IDs are deduplicated within the receiving business phone/account. Re-delivery reuses the existing message. Missing IDs use a payload-derived event key. Conflicting deliveries retain additional evidence on that same record and flag it for review. A database unique constraint arbitrates concurrent events. Storage errors propagate rather than acknowledging missing data. An unmapped receiving business phone rejects the callback for Meta to retry after configuration is corrected; it is never assigned to a default account. This can delay other events in that callback transaction until the mapping is fixed.

**Default Country Calling Code** is configurable and defaults to **+91** in both the settings form and matching logic; saving it blank restores +91. Matching compares normalized phone numbers, using the configured prefix for existing 10-digit national numbers, without changing Customer or Sales Employee records. Unique customer/salesperson matches are recorded; multiple candidates remain Ambiguous and unmatched senders remain Unknown. Recognition does not authorize an order. A salesperson is not assumed to be the customer they are ordering for. Unknown-sender authorization remains explicitly deferred.

Install/migrate hooks create these custom fields on other servers. The patch `simplify_order_intake_capture` preserves earlier capture evidence in a private owner-readable JSON backup and on the corresponding WhatsApp Message before unregistering the two obsolete DocTypes. Linked original messages keep their original fields; raw-only evidence becomes an Incoming message. Attachment references are moved where a corresponding message exists. Historical SQL tables remain as Frappe normally leaves them when removing a DocType; they are not used by the application. The obsolete source directories are removed so migration cannot recreate those DocTypes.

### Verification on 11 November 2026

The simplified focused database suite passes **38 tests**: incoming metadata, sender matching/default country, ambiguity, duplicate IDs, historical preparation, permissions, migration preservation, per-message callback isolation, unsupported events, media references, coordinates, conflicting payloads and storage failure handling, plus existing request-form backend validation. The eight existing form checks also pass. Audit fixes include escaping migrated HTML-editor text, respecting message record permissions in manual APIs, and handling database unique-key races.

The local migration preserved all **four earlier intake receipts** and verified that the **three linked original WhatsApp Messages** kept their original text, type, account, attachment and provider ID. Both obsolete DocType registrations were removed; rerunning the patch is safe. The saved country code is +91. Private backups are under the local site's `private/backups/order-intake-before-simplification-*.json` directory. Two local HTTP deliveries of three new synthetic text/location/contacts events produced exactly three WhatsApp Messages, preserved raw evidence and no intake requests. API keys were unchanged and production was untouched.

An earlier broad test discovery exposed unrelated legacy numbering assumptions and MariaDB cancellation/reconciliation errors; those workflows were not changed. No AI calls, automatic draft creation or scheduler changes are included. Work stops here for review before Step 3.

## Deployment and access audit on 11 November 2026

The 24 intake custom fields on WhatsApp Message are exported in `fixtures/custom_field.json`, with a scoped Custom Field fixture filter in hooks. The schema setup remains idempotently registered on after_install/after_migrate. Importing this fixture through Frappe and rerunning setup twice succeeded locally. The request/settings/child DocTypes and their standard DocPerm rows are shipped in their DocType JSON files; they do not require duplicate Custom DocPerm fixtures. The existing Role and Role Profile fixtures include Owner, Admin and Order Coordinator. Child tables inherit access from the parent request.

Effective permissions verified against the local database:

| Document | Current roles | Access |
| --- | --- | --- |
| Order Intake Request | Owner, Admin, Order Coordinator | Read/select, create and edit; no delete/submit/cancel |
| Order Intake Settings | Owner, Admin | Read and edit |
| Intake item/attachment/source and legacy child tables | Parent request roles | Through the parent request |
| WhatsApp Message | Owner/Admin: create/read/select/write; Order Coordinator: read/select | No delete for these Kunal roles; System Manager keeps existing access |
| WhatsApp Account | Owner/Admin: create/read/select/write; Order Coordinator: read/select | Credentials restricted to Owner/Admin/System Manager |
| WhatsApp Settings | Owner/Admin: read/select/write; Order Coordinator: read/select | Single configuration document; no delete for Kunal roles |

Administrator is the built-in superuser, distinct from the custom Admin role. Profiles group roles; permissions are attached to roles. The shipped Owner/Admin profiles include Order Coordinator and Godown Allocator; the Order Coordinator profile also includes Godown Allocator. Branch Manager, Branch Employee and Godown Allocator alone do not grant intake-request/settings access.

**Approved access applied:** Owner/Admin can create, read, select and edit WhatsApp Messages and Accounts, and read/select/edit WhatsApp Settings. Order Coordinator has read/select on all three. These Kunal roles have no delete, share, import or export grants; existing System Manager/Administrator privileges are preserved. Permissions remain additive when users hold multiple roles. Account `token` and `webhook_verify_token` use permission level 1, granted only to Owner/Admin/System Manager, so coordinator document responses exclude those credential fields. Password values stay masked under normal Frappe behaviour; no credential values are fixtures.

The custom application exports these Custom DocPerm rows and the two field-permission Property Setters as scoped fixtures, and reapplies the permissions from the installation/migration setup. The original WhatsApp application is unchanged. Write permission is checked server-side before webhook subscriptions or read receipts. Read-only message viewers do not see Reply/Mark as read and do not trigger automatic read receipts; account subscription controls require write access. Owner/Admin replies retain the receiving account. No live Meta action was performed during permission tests.

For a target server, update the custom application code, ensure frappe_whatsapp and kunal_enterprises are installed on the target site, then run `bench --site <site-name> migrate` and `bench build --app kunal_enterprises`; restart the bench production processes normally. Migration imports fixtures, syncs DocType permissions, runs the evidence-consolidation patch where needed, and reapplies field setup/default country code. No new dependency was added in Step 2. API keys, WhatsApp tokens/accounts and site-specific settings are not exported as fixtures; configure them on each target or restore them securely as part of a full site backup. A migration does not assign role profiles to individual users.

Step 3 remains on hold. Schema and permission portability are verified. The approved role grants and credential Property Setters were exported and successfully reimported. The focused database suite passes **47 tests**, including nine permission cases; **17 Node form checks** pass, including nine permission/action cases. Tests cover actual role permissions, credential serialization, denied coordinator writes and external actions, permitted administrator-role delegation without network, and repeated setup preserving System Manager access.


## Step 3: scheduling and context preparation

Step 3 adds no DocType and makes no model calls. It extends the existing WhatsApp Message with a context-preparation state, retry/lease metadata and a context reference on one message in each prepared batch. It does not create intake requests, classify messages as orders/inquiries, convert orders or mark any message processed.

**Enable Scheduled Context Preparation** is a separate Owner/Admin setting, default OFF. The existing AI enable switch remains guarded OFF. A one-minute scheduler hook checks the configured interval (five minutes by default) against a database-persisted last-tick value; concurrent ticks serialize on the settings row. No bench-wide scheduler configuration or Tally flags are changed. Registration takes effect through the normal site migration. The new job is also registered locally, with automatic preparation OFF; no existing Tally job state was changed.

The coordinator selects prepared, canonical Incoming messages by receiving WhatsApp account and normalized sender. Outgoing, duplicate and not-yet-prepared historical messages are excluded. New/retry input triggers a job; recent Context Ready messages are included again when a new continuation arrives, but unchanged context does not produce another job. The configured 120-minute window uses local receipt time, so a newly received message with an old provider timestamp is still eligible. Older unresolved messages are retained and flagged Needs Attention for manual review. Unknown senders remain eligible. Missing sender/account mappings are flagged instead of guessed or silently omitted.

**Mobile application access is separate from WhatsApp intake.** Customer approval, mobile verification/login access and disabled/blocked master status are informative identity metadata, not capture or context-preparation gates. Staff can receive and review WhatsApp orders for those parties. Tally/customer mapping and actual order-conversion requirements remain later work; Step 3 does not change existing Order conversion or mobile authorization.

Claims serialize on the receiving account row and use unique job tokens plus ten-minute leases. Queued input is not rescheduled while the claim is live; new arrivals wait for a later context. Worker claims are fenced so a late worker cannot release or overwrite a newer job. Publication happens only after the claiming transaction commits. Queue publication failures have a separate post-commit persistence path; missing publications and crashed workers also recover through expired leases. Retry delays are the configured 5, 15 and 60 minutes, then Needs Attention. These are preparation/queue retries, not implemented provider retries: no provider is called in Step 3. Failure notes contain fixed explanations rather than raw exceptions, keys or message bodies.

The coordinator examines at most 20 eligible chats per tick and the worker handles at most 100 primary messages per chat. Chats blocked by a live claim or future retry are excluded from candidate slots. A chat exceeding 100 recent messages is not treated as a complete automatic context: bounded groups are visibly marked for manual review, including later rows and arrivals, with no truncated tail submitted as a complete order. This is a deliberate first-version safety limit, not a model confidence threshold.

A prepared context contains chronological message IDs, up to 20 explicit same-sender/account reply references and up to 20 recent manual-review message references. Recent terminal/manual messages remain available as context for a new continuation without resetting their manual-review state. Missing/ambiguous/overflow references produce warnings. Related open requests must have explicit source associations; all their source messages are rechecked against the same account/sender, so a matching name or time alone cannot pull another customer's chat. Related requests are limited to 20. Bounds produce warnings; no source message is deleted. The context digest includes source evidence as well as reference IDs, so changed content does not look identical to an earlier preparation.

On success the primary messages show **Context Ready**, with a link to their context anchor; the anchor contains collapsed technical context references. Intake status remains New or its existing Needs Attention state: Context Ready is not Processed. A late attachment, changed body, sender/account correction or genuinely changed raw evidence makes a ready message Pending again. Identical webhook redelivery does not reopen an unchanged context. Original text, files, coordinates and raw data remain on WhatsApp Message.

### Local review controls

Open Order Intake Settings and use **Preview Sender Context**, selecting the receiving account and sender. Preview changes nothing and does not contact Redis or any model. **Prepare Sender Context** prepares that one visible chat synchronously without enabling automatic scheduling. Manual runs enforce Owner/Admin and per-record read/write permissions and do not expire or recover unrelated historical messages. Empty/manual-only/overflow previews return without pretending preparation succeeded. Results show simple ready/retry/reference counts and warnings, with **View Sender Messages** filtering on the normalized sender and selected account; technical job tokens/hashes are not displayed in this result screen.

The local setting remains OFF for the review gate. To deploy, update the application and run the normal `bench --site <site-name> migrate`, asset build and restart. The 35 WhatsApp Message intake custom-field definitions are exported as scoped fixtures; install/migrate setup also recreates fields and indexes. The new Single settings fields and their Owner/Admin permissions ship in DocType JSON. No new dependency or API key configuration is required for Step 3.

### Step 3 verification

The focused queue suite covers cadence and duplicate dispatch, chronological context, continuation handling, live/new and stale claims, publication failures, bounded retries, overflow-tail visibility, old/delayed timestamps, missing/unknown identities, source deletion, separate-chat failures, read-only preview, manual scope/role access, terminal-evidence inclusion and mobile-approval independence. The settings form tests cover preview GET, explicit manual POST, escaped result display and normalized sender-history navigation. Root audit tests exercise additional concurrency and raw-evidence invalidation paths. Automatic preparation, AI and Tally remain disabled for review. Stop before Step 4 until the user reviews this result.

### Final audit and local review on 12 November 2026

The combined focused suite passes **76 database tests** (20 preparation, nine additional audit cases and 47 earlier intake/permission cases), plus **21 Node form checks**. The source-change regression uses a late attachment because upstream WhatsApp message text is set-only-once. Audit fixes cover fenced failure updates, blocked-chat fairness, bounded overflow-tail review, source-key corrections, changed-evidence invalidation with current-row locking, terminal-evidence references, manual permission checks and accurate retry results.

A real local webhook received two synthetic messages under **Step 3 preparation review**, sender `919000000069`, receiving account `TEST WA`. A post-commit publication reached the local short-queue worker and both messages became Context Ready with intake status still New. An unchanged second dispatch queued nothing. No Order Intake Request or Order was created and no model was called. Automatic preparation remains off. Browser review verified Preview Sender Context using formatted input `+91 90000 00069`, showing two messages and no related requests. At the current browser width these controls appear under the form's **Menu**. Use that same account/sender to review the sample.

For WhatsApp, mobile customer approval, mobile login availability and salesperson/customer blocked flags do not gate capture, draft preparation or eventual intake eligibility. The customer's Tally connection remains required for actual Order creation later; missing identity/mapping must stay visible for review instead of discarding the received message. Existing mobile workflows are unchanged. Step 4 remains unstarted pending user review.

## Audit fixes 1–11 on 12 November 2026

All eleven reviewed issues were addressed; the clean-server deployment exercise (12) remains explicitly deferred.

| Issue | Final behaviour |
| --- | --- |
| 1. Unauthenticated webhooks | POST verifies X-Hub-Signature-256 against the exact raw body and configured per-account Meta App Secret before any writes. Missing/invalid signatures or secrets are rejected. GET verification remains unchanged. No unsigned-development bypass exists. |
| 2. Public attachments | New media downloads are private. The historical privacy patch moves exact public WhatsApp file URLs, repairs Attach/Attach Image references and preserves rollback; it refuses conflicting private bytes or a shared public-page/settings use requiring review. It avoids Frappe's global same-hash URL rewrite. |
| 3. Bulk retry permission bypass | Both the upstream retry endpoint override and bulk controller/worker methods require write access before enqueueing/sending. |
| 4. Mutable intake evidence | A server-side guard rejects changes to intake evidence/queue metadata from normal document saves, including Owner/Admin API writes. Trusted capture code uses a server-only flag; payload flags are reserved and cannot bypass it. |
| 5. Blocking media downloads | The webhook captures the incoming message/raw payload first and publishes download work only after commit. Downloads have explicit connect/read timeouts, bounded size and restricted HTTPS destinations without redirects. |
| 6. Attachment recovery | Failed/stale downloads retain media IDs, have visible generic failure notes and support bounded redelivery attempts plus a write-protected Retry Attachment Download action. |
| 7. Preparation recovery | Owner/Admin can Retry Selected Context for 1–100 explicitly selected messages, including old/terminal records. Original timestamps are retained, live jobs cannot be overwritten, partial expired batches are rejected, and unchanged exact ready batches are not repeated. Manually recovered ready context is not immediately aged out. |
| 8. Missing related drafts | Every child-level item/warehouse/attachment source reference is validated and normalized into the main source ledger. An idempotent historical repair updates only that ledger and missing chat metadata, preserving notes/status/items. Duplicate removal reindexes source rows to preserve reload order. |
| 9. Long links | External URLs use Small Text; HTTP(S)-only storage validation remains. |
| 10. History filtering | The message form and settings history actions both use the normalized sender key and receiving account. |
| 11. Country default | Whitespace-only migration values correctly normalize to +91. |

The local source/privacy repair patches completed successfully. Updated fixtures contain 41 WhatsApp Message fields plus the protected Meta App Secret account field (42 total); import and idempotent setup were verified without exporting credentials. Permissions still ship as existing scoped fixtures/DocType JSON. No new dependency or DocType was introduced.

Verification: **111 focused database tests passed**, including signature, private-media, evidence-integrity, outgoing-permission, old-context recovery, long-link/source normalization and historical privacy cases. **24 Node form checks passed.** The browser recovery test found and fixed a real dialog edge: Frappe's trailing blank table row is filtered before submitting explicitly selected messages. Repeating the corrected browser action on the two labelled Step 3 messages showed Context Ready and confirmed no duplicate work. Automatic preparation and AI remain OFF; no actual Order was created and production was untouched.

### Deferred credential entry and live test

The user requested entering the real secret at the end. In Meta application 2194160327857465, open App Settings > Basic and obtain **App Secret**. In local WhatsApp Account **TEST WA**, save that value in **Meta App Secret** (`intake_app_secret`). This is not the Meta access token, webhook verification token, or OpenAI key. Do not paste the secret in chat or fixtures. Until this is saved, real POST callbacks are intentionally rejected; signed synthetic test cases use disposable secrets only. After the user completes it, verify one real incoming phone message and its private attachment download separately. Step 4 remains unstarted pending review.

## Final follow-up fixes and verification on 12 November 2026

Captured incoming message provider IDs and direction are now protected on server saves, including Owner/Admin API saves. Ordinary label/status updates and outgoing message retries remain supported. Related-draft lookup now checks the original normalized sender when a historical source has no intake key, retaining strict receiving-account and cross-chat checks without automatically importing that historical message.

Both regressions were reproduced before the fix. The final focused suite passes **114 database tests and 24 Node form checks**; independent review found no further issue in these two fixes. The user saved the Meta App Secret. Its presence/decryption was verified without displaying or exporting it. A local HTTP callback signed with that configured secret returned 200; the same unsigned payload returned 403, and exactly one synthetic message was saved with no request/order creation. This checks the local receiver/configuration, not a fresh real-phone attachment delivery. The configured secret was checked absent from all repository files before committing.

Automatic context preparation remains OFF and Step 4 remains unstarted. Fresh-server installation/migration verification remains deferred as agreed. The earlier broad legacy-suite numbering and reconciliation failures remain outside this focused suite and were not changed by these fixes.

### Final Step 3 UI review

The three settings dialogs now explain Preview Sender Context, Prepare Sender Context and Retry Selected Context before their inputs. Intake Details is appended after the final original WhatsApp Message field, keeping the original message, content type and account visible when intake metadata is collapsed or hidden for outgoing messages. The fixture and install/migrate setup use the same placement. Ten focused security/layout tests and five settings-form checks pass; browser review confirmed the message stays visible while Intake Details opens and closes. Step 3 is complete for its agreed scope; automatic preparation and AI remain OFF pending the next review gate.
