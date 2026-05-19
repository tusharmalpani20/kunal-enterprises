# /goal Prompt: Install Frappe And Run

Use this as the first independent `/goal` prompt.

## Prompt

You are working in `/Users/amol909/development/kunal-enterprise/kunal-enterprises`.

Goal: install the Frappe foundation for the Kunal Enterprise order system and leave it running locally with a custom Frappe app installed. This includes environment setup, PostgreSQL setup, Frappe bench setup, site/database creation, custom app creation, app installation, `frappe_whatsapp` installation, and a tested local smoke path.

This goal is only the foundation. Do not build the full portal, full mobile API, reconciliation engine, or mobile app in this goal. Create enough app structure and tests so Goal 2 can start cleanly.

## Source Context To Read First

- `CONTEXT.md`
- `docs/01-overall-problem-statement.md`
- `docs/07-frappe-app-patterns-from-sf-dpms.md`
- `docs/adr/0001-use-frappe-custom-app-not-erpnext.md`
- `docs/adr/0002-use-postgresql-as-raw-tally-mirror-and-frappe-as-application-model.md`
- `docs/adr/0010-use-postgresql-for-frappe.md`
- `/Users/amol909/.agents/skills/tdd/SKILL.md`

Use the project language from `CONTEXT.md`. Do not call the first selector Brand or Category; the canonical term is Product Group.

## Non-Negotiable Decisions

- Backend and portal are a custom Frappe app, not ERPNext.
- Frappe must use PostgreSQL as its application database.
- The Tally connector PostgreSQL mirror is a separate logical database/store from the Frappe application database.
- The custom app should be prepared for mobile APIs, portal DocTypes, scheduled jobs, fixtures, permission query conditions, document events, and tests.
- Use the documented stack target from `docs/01-overall-problem-statement.md`: Frappe `15.103.3` and `frappe_whatsapp` `1.0.12` unless the install tooling proves a patch-level adjustment is required.
- Do not store pricing/rates/tax/value in the foundation schema or fixtures.

## TDD Rules For This Goal

Follow `/Users/amol909/.agents/skills/tdd/SKILL.md`.

- Write tests through public behavior and install-visible outcomes.
- Do not write all tests first. Use vertical tracer bullets: one failing test or smoke check, minimal implementation, pass, then repeat.
- Mock only true external boundaries if needed. Do not mock the app's own setup or public behavior.
- Keep a running note of each red-green-refactor cycle in a local implementation log if the goal takes multiple cycles.

## Expected Work

1. Inspect local prerequisites and determine the least invasive install path for macOS:
   - Python, Node, Redis, PostgreSQL, wkhtmltopdf or equivalent Frappe requirements.
   - Frappe bench installation.
   - PostgreSQL service availability.
2. Create or configure a Frappe bench for this project.
3. Create a PostgreSQL-backed Frappe site for Kunal Enterprise.
4. Create a custom app with a stable app name aligned to the project, for example `kunal_enterprises`.
5. Install the custom app on the site.
6. Install `frappe_whatsapp` on the site.
7. Add initial app structure matching `docs/07-frappe-app-patterns-from-sf-dpms.md`:
   - `hooks.py`
   - app package
   - `api/`
   - `api/utils.py`
   - `api/otp.py` placeholder module if appropriate
   - `api/token_verification.py` placeholder module if appropriate
   - `cron/`
   - `doc_events/`
   - `permission_query_conditions/`
   - `fixtures/`
   - app test package
8. Add a minimal public health/smoke endpoint or bench-executable function that proves:
   - Frappe imports the app.
   - The site can reach the PostgreSQL-backed Frappe database.
   - The custom app is installed on the site.
   - `frappe_whatsapp` is installed on the site.
9. Add a first small test suite for the custom app foundation. It should verify behavior using public Frappe APIs or bench-visible execution, not internal implementation details.
10. Start the local Frappe server and provide the local URL.

## Required Outcomes

The goal is complete only when these outcomes are true:

- A local Frappe bench exists and can run.
- A Kunal Enterprise Frappe site exists and uses PostgreSQL.
- The custom app is created and installed on the site.
- `frappe_whatsapp` is installed on the site.
- The app has the expected module folders for APIs, cron, document events, permission query conditions, fixtures, and tests.
- A health/smoke endpoint or bench-executable public function succeeds.
- A minimal test suite exists and passes.
- The local Frappe server is running, or the exact command to run it is verified.
- Setup commands, site name, app name, database names, and run/test commands are documented in a repo-local file.

## Acceptance Tests

Implement and run tests/checks that prove:

- `bench --site <site> list-apps` includes Frappe, the custom app, and `frappe_whatsapp`.
- A public health/smoke function returns success and includes the installed app name and database type.
- A database check confirms the Frappe site is using PostgreSQL.
- The custom app test suite passes with `bench --site <site> run-tests --app <custom_app>`.
- The server responds locally at the expected URL.

## Deliverable

Leave the repo with:

- Installed/runnable Frappe bench and site.
- Custom app installed.
- Passing foundation tests.
- Clear setup/run/test documentation.
- A final summary with commands run, URL, site name, app name, and any remaining blockers.

