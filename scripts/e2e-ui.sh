#!/usr/bin/env bash
# Browser smoke test: builds the SPA, serves it from a real hub on a scratch SQLite DB and
# drives it with Playwright using the system Chrome (no browser download, no sudo).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-$ROOT/backend/.venv/bin/python}"
[ -x "$PY" ] || PY=python3
PORT="${PORT:-18765}"
WORK="$ROOT/.e2e/ui-$$"
REACT_DIR="$ROOT/backend/app/web/react"
mkdir -p "$WORK"

cleanup() {
  [ -n "${HUB_PID:-}" ] && kill "$HUB_PID" 2>/dev/null || true
  rm -rf "$WORK"
  [ "${KEEP_REACT:-}" = "1" ] || rm -rf "$REACT_DIR"
}
trap cleanup EXIT

(cd "$ROOT/frontend" && npm run build >/dev/null)
rm -rf "$REACT_DIR"
cp -r "$ROOT/frontend/dist" "$REACT_DIR"

export SECRET_KEY="$("$PY" -c 'import secrets; print(secrets.token_hex(32))')"
export ADMIN_BOOTSTRAP_TOKEN="$("$PY" -c 'import secrets; print(secrets.token_hex(16))')"
export ENVIRONMENT=production
export DATABASE_URL="sqlite:///$WORK/hub.sqlite3"
(cd "$ROOT/backend" && "$PY" -m alembic upgrade head >/dev/null)
(cd "$ROOT/backend" && exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning >"$WORK/hub.log" 2>&1) &
HUB_PID=$!

for _ in $(seq 1 60); do
  curl -fsS "http://127.0.0.1:$PORT/health/ready" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -fsS "http://127.0.0.1:$PORT/health/ready" >/dev/null

cd "$ROOT/frontend"
TARGETHUB_URL="http://127.0.0.1:$PORT" npx playwright test "$@"
