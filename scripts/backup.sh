#!/usr/bin/env bash
# Back up the TargetHub database (SQLite online backup or PostgreSQL pg_dump).
# Usage: DATABASE_URL=... scripts/backup.sh [output-dir]
# Writes targethub-<UTC timestamp>.{sqlite3,dump} (mode 0600) plus a .sha256 file.
set -euo pipefail

: "${DATABASE_URL:?set DATABASE_URL}"
OUT_DIR="${1:-backups}"
PY="${PYTHON:-python3}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
umask 077
mkdir -p "$OUT_DIR"

case "$DATABASE_URL" in
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
