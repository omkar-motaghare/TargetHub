#!/usr/bin/env bash
# Back up the TargetHub database.
# Compose stack (default): scripts/backup.sh [output-dir]
#   runs pg_dump inside the stack's `db` container (no host PostgreSQL client needed);
#   the stack is selected by .env / COMPOSE_PROJECT_NAME in the repository root.
# Direct database: DATABASE_URL=... scripts/backup.sh [output-dir]  (SQLite or host pg_dump)
# Writes targethub-<UTC timestamp>.{sqlite3,dump} (mode 0600) plus a .sha256 file.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-backups}"
PY="${PYTHON:-python3}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
umask 077
mkdir -p "$OUT_DIR"

if [ -z "${DATABASE_URL:-}" ]; then
  DATABASE_URL=compose
fi

case "$DATABASE_URL" in
  compose)
    DEST="$OUT_DIR/targethub-$STAMP.dump"
    if ! (cd "$ROOT" && docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner') >"$DEST.partial"; then
      rm -f "$DEST.partial"
      echo "pg_dump failed (is the stack running? check COMPOSE_PROJECT_NAME)" >&2
      exit 1
    fi
    mv "$DEST.partial" "$DEST"
    ;;
  sqlite:///*)
    DEST="$OUT_DIR/targethub-$STAMP.sqlite3"
    "$PY" - "${DATABASE_URL#sqlite:///}" "$DEST" <<'PYEOF'
import sqlite3
import sys

source, dest = sys.argv[1:3]
with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src, sqlite3.connect(dest) as dst:
    src.backup(dst)
PYEOF
    ;;
  postgres://* | postgresql://* | postgresql+*://*)
    command -v pg_dump >/dev/null || { echo "pg_dump not found" >&2; exit 1; }
    DEST="$OUT_DIR/targethub-$STAMP.dump"
    pg_dump --format=custom --no-owner --file="$DEST" "${DATABASE_URL/+psycopg2/}"
    ;;
  *)
    echo "unsupported DATABASE_URL scheme" >&2
    exit 1
    ;;
esac

(cd "$OUT_DIR" && sha256sum "$(basename "$DEST")" >"$(basename "$DEST").sha256")
echo "$DEST"
