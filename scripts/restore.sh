#!/usr/bin/env bash
# Restore a backup made by scripts/backup.sh. Destructive: requires --yes.
# Usage: DATABASE_URL=... scripts/restore.sh --yes <backup-file>
# Stop the API first. The checksum next to the backup is verified before anything is touched.
set -euo pipefail

: "${DATABASE_URL:?set DATABASE_URL}"
[ "${1:-}" = "--yes" ] || { echo "refusing to overwrite the database without --yes" >&2; exit 2; }
BACKUP="${2:?backup file required}"
[ -f "$BACKUP" ] || { echo "no such file: $BACKUP" >&2; exit 1; }
[ -f "$BACKUP.sha256" ] || { echo "missing $BACKUP.sha256" >&2; exit 1; }
(cd "$(dirname "$BACKUP")" && sha256sum -c "$(basename "$BACKUP").sha256" >/dev/null) \
  || { echo "checksum mismatch; backup is corrupt" >&2; exit 1; }

case "$DATABASE_URL" in
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
