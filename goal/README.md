# Goal Prompts

These files are standalone `/goal` prompts for building the Kunal Enterprise system in three stages.

1. `01-install-frappe-and-run.md`: install and run the Frappe/PostgreSQL foundation, create the custom app, install `frappe_whatsapp`, and add smoke tests.
2. `02-build-frappe-portal-and-backend-api.md`: build the full custom Frappe portal, DocTypes, mobile backend APIs, Tally sync, and reconciliation behavior.
3. `03-build-mobile-app.md`: build the Expo / React Native mobile app UI first, then connect it to the Frappe APIs.

Each prompt requires the TDD workflow from `/Users/amol909/.agents/skills/tdd/SKILL.md`: one public behavior test, minimal implementation, pass, then repeat.

