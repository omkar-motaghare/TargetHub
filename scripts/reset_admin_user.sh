#!/usr/bin/env bash
set -euo pipefail

# Resets runtime DB users inside the running TargetHub container to:
# username: admin
# password: admin
# role: admin
#
# Usage:
#   ./scripts/reset_admin_user.sh
# Optional:
#   SERVICE_NAME=api ./scripts/reset_admin_user.sh

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

SERVICE_NAME="${SERVICE_NAME:-api}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is not installed or not in PATH."
  exit 1
fi

if ! docker compose ps "$SERVICE_NAME" >/dev/null 2>&1; then
  echo "Service '$SERVICE_NAME' not found. Available services:"
  docker compose ps --services || true
  exit 1
fi

docker compose exec -T "$SERVICE_NAME" python - <<'PY'
from app.db.models.user import User
from app.db.session import SessionLocal
from app.services.auth_service import AuthService

db = SessionLocal()
try:
    db.query(User).delete()
    db.commit()
    AuthService(db).create_user("admin", "admin", ["admin"])

    print("Users in runtime DB:")
    for user in db.query(User).order_by(User.id.asc()).all():
        print((user.id, user.username, user.roles))
finally:
    db.close()
PY

docker compose restart "$SERVICE_NAME"
echo "Done. Re-login with username=admin password=admin"
