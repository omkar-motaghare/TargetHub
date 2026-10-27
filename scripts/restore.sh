#!/usr/bin/env bash
# Restore a backup made by scripts/backup.sh. Destructive: requires --yes.
# Compose stack (default): scripts/restore.sh --yes <backup-file>
#   stops the api, restores into the `db` container with pg_restore, then starts the api again.
# Direct database: DATABASE_URL=... scripts/restore.sh --yes <backup-file>  (stop the API first)
# The checksum next to the backup is verified before anything is touched.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ "${1:-}" = "--yes" ] || { echo "refusing to overwrite the database without --yes" >&2; exit 2; }
BACKUP="${2:?backup file required}"
[ -f "$BACKUP" ] || { echo "no such file: $BACKUP" >&2; exit 1; }
[ -f "$BACKUP.sha256" ] || { echo "missing $BACKUP.sha256" >&2; exit 1; }
(cd "$(dirname "$BACKUP")" && sha256sum -c "$(basename "$BACKUP").sha256" >/dev/null) \
  || { echo "checksum mismatch; backup is corrupt" >&2; exit 1; }

if [ -z "${DATABASE_URL:-}" ]; then
  DATABASE_URL=compose
fi
BACKUP="$(cd "$(dirname "$BACKUP")" && pwd)/$(basename "$BACKUP")"

case "$DATABASE_URL" in
  compose)
    cd "$ROOT"
    docker compose stop api
    docker compose exec -T db sh -c \
      'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --single-transaction --exit-on-error' \
      <"$BACKUP" || { echo "pg_restore failed; the api was left stopped" >&2; exit 1; }
    docker compose up -d --wait api
    ;;
  sqlite:///*)
    TARGET="${DATABASE_URL#sqlite:///}"
    if [ -f "$TARGET" ]; then
      cp -p "$TARGET" "$TARGET.pre-restore"
    fi
    rm -f "$TARGET-wal" "$TARGET-shm" "$TARGET-journal"
    cp "$BACKUP" "$TARGET"
    ;;
  postgres://* | postgresql://* | postgresql+*://*)
    command -v pg_restore >/dev/null || { echo "pg_restore not found" >&2; exit 1; }
    pg_restore --clean --if-exists --no-owner --dbname="${DATABASE_URL/+psycopg2/}" "$BACKUP"
    ;;
  *)
    echo "unsupported DATABASE_URL scheme" >&2
    exit 1
    ;;
esac
echo "restored from $BACKUP"
