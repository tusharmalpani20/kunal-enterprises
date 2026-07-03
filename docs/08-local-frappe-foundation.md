# Local Frappe Foundation

This documents the Goal 1 foundation setup completed on 2026-05-19.

## Runtime Paths

- Repo: `/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises`
- Working bench: `/Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench`
- Custom app source in repo and symlinked into bench: `apps/kunal_enterprises`
- Bench executable: `/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench`

The workspace was renamed from `Kunal Enterprises` to `Kunal-Enterprises` so Frappe tooling can run from a path without spaces. The working bench now lives beside the repo, and `ke-frappe-bench/apps/kunal_enterprises` points directly to the repo app source at `apps/kunal_enterprises`.

## Versions

- Frappe: `15.103.3`
- Frappe Bench: `5.29.1`
- Python: `3.11.0`
- PostgreSQL: `14.15`
- Site: `kunal.localhost`
- Frappe app database: `kunal_enterprises_frappe`
- Custom app: `kunal_enterprises`
- WhatsApp app: `frappe_whatsapp`

`frappe_whatsapp` target was `1.0.12`, but the documented upstream repository did not expose a `v1.0.12` tag. The highest available tag was `v1.0.11`, so the local bench fetched that tag. Its hook metadata reports `app_version = 1.0.7`.

## Commands

Use the explicit bench executable because `/opt/homebrew/bin/bench` is an unrelated RSS benchmark binary on this machine.

```sh
cd /Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost list-apps
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost execute kunal_enterprises.api.health.smoke
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench --site kunal.localhost run-tests --app kunal_enterprises
/Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/.venv-bench/bin/bench serve --port 8000
```

## Verified Acceptance Checks

- `bench --site kunal.localhost list-apps` includes `frappe`, `kunal_enterprises`, and `frappe_whatsapp`; this was reverified on 2026-05-19 with `frappe 15.103.3`, `kunal_enterprises 0.0.1`, and `frappe_whatsapp 1.0.7`.
- `kunal_enterprises.api.health.smoke` returns success, installed app names, `database_type = postgres`, and database reachability.
- `sites/kunal.localhost/site_config.json` contains `db_type = postgres` and `db_name = kunal_enterprises_frappe`.
- `bench --site kunal.localhost run-tests --app kunal_enterprises` passes.
- Server response was reverified on 2026-05-19 by starting `bench serve --port 8000` and running `curl -I http://127.0.0.1:8000`; the response included `HTTP/1.1 200 OK` and `X-Page-Name: login`.

## Notes

- PostgreSQL was started with `brew services start postgresql@14`.
- Frappe PostgreSQL setup required a local maintenance database named `amol909`; it was created with `createdb amol909`.
- `frappe_whatsapp` required Homebrew `libmagic`.
- Frappe v15 prints a warning that PostgreSQL support is limited to Frappe v16 and above. The goal explicitly required Frappe `15.103.3` with PostgreSQL, so the warning is documented rather than changing the stack.
