# Backup and restore

`scripts/backup.sh` and `scripts/restore.sh` operate on whatever `DATABASE_URL` points at.

| Backend | Backup | Restore |
| --- | --- | --- |
| SQLite | online `sqlite3` backup API (safe while the API runs) | file copy; previous DB kept as `<db>.pre-restore` |
| PostgreSQL | `pg_dump --format=custom` | `pg_restore --clean --if-exists` |

```bash
export DATABASE_URL=...            # same value the API uses
scripts/backup.sh /var/backups/targethub     # prints the file it wrote
scripts/restore.sh --yes /var/backups/targethub/targethub-20260101T000000Z.dump
```

- Backups are written with mode `0600` and have a `.sha256` file next to them; restore
  verifies it first and refuses to touch the database on mismatch.
- Restore is destructive and requires `--yes`. Stop the API before restoring, then run
  `alembic upgrade head` if the backup came from an older release.
- Backups contain password hashes and agent credential hashes: store them encrypted and
  off the hub host. Rotate `SECRET_KEY` only after confirming users can still log in.
- Schedule with cron or a systemd timer, e.g. `0 2 * * * DATABASE_URL=... /opt/targethub/scripts/backup.sh /var/backups/targethub`,
  and prune old files yourself.

## Verification status

The SQLite round trip (backup, mutate, restore, corrupt-checksum rejection) is covered by
`backend/tests/test_backup_restore.py`. The PostgreSQL path is implemented with the standard
client tools but has **not** been exercised in this repository's CI or on the development host
(no PostgreSQL available); do a restore drill on a staging copy before relying on it.
