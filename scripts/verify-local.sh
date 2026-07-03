#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_DIR="/Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench"
BENCH_BIN="$REPO_ROOT/.venv-bench/bin/bench"
SITE_NAME="kunal.localhost"

echo "== Backend: smoke =="
cd "$BENCH_DIR"
"$BENCH_BIN" --site "$SITE_NAME" execute kunal_enterprises.api.health.smoke

echo "== Backend: tests =="
"$BENCH_BIN" --site "$SITE_NAME" run-tests --app kunal_enterprises

echo "== Mobile: audit, tests, typecheck =="
cd "$REPO_ROOT/apps/mobile"
npm audit --omit=dev
npm test
npm run typecheck

echo "== Local verification complete =="
