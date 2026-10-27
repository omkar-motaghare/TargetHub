#!/usr/bin/env bash
# Regain admin access to a running TargetHub stack without touching other accounts.
#
#   scripts/reset_admin_user.sh                 # list users
#   scripts/reset_admin_user.sh reset alice     # new random password for alice
#   scripts/reset_admin_user.sh create bob      # new admin bob with a random password
#   scripts/reset_admin_user.sh enable alice    # re-enable a disabled account
#
# Runs `python -m app.manage` inside the API container (SERVICE_NAME, default: api).
set -euo pipefail
cd "$(dirname "$0")/.."
SERVICE_NAME="${SERVICE_NAME:-api}"
command -v docker >/dev/null || { echo "docker is not installed" >&2; exit 1; }

case "${1:-list}" in
  list) exec docker compose exec -T "$SERVICE_NAME" python -m app.manage list-users ;;
  reset) exec docker compose exec -T "$SERVICE_NAME" python -m app.manage reset-password "${2:?username}" ;;
  create) exec docker compose exec -T "$SERVICE_NAME" python -m app.manage create-admin "${2:?username}" ;;
  enable) exec docker compose exec -T "$SERVICE_NAME" python -m app.manage enable-user "${2:?username}" ;;
  *) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
