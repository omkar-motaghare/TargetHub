#!/usr/bin/env bash
# One command to set up TargetHub: checks prerequisites, installs and starts the Docker stack,
# waits until it is healthy, and creates the first admin account. Then prints where to sign in.
#
# Usage: scripts/setup.sh [install options] [--admin-user NAME] [--no-admin]
#
#   --admin-user NAME   username of the first admin (default: admin); prompted if not given
#   --no-admin          skip creating the admin (you can do it later in the browser)
#   Any other option is passed to scripts/install.sh, for example:
#   --port 8080   --url http://lab-server.local:8080   --domain hub.example.com   --image REF
#
# The admin password is read from the TARGETHUB_ADMIN_PASSWORD environment variable if set, otherwise
# prompted for (hidden). It is never written to disk or printed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ADMIN_USER=""
CREATE_ADMIN=1
INSTALL_ARGS=()

die() { echo "setup.sh: $*" >&2; exit 1; }
step() { echo; echo "==> $*"; }

usage() { sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --admin-user) ADMIN_USER="${2:?--admin-user needs a value}"; shift 2 ;;
    --no-admin) CREATE_ADMIN=0; shift ;;
    -h | --help) usage; exit 0 ;;
    *) INSTALL_ARGS+=("$1"); shift ;;
  esac
done

# 1. Prerequisites ----------------------------------------------------------------------------------
step "Checking prerequisites"
command -v docker >/dev/null || die "Docker is not installed. Install Docker (Docker Desktop on macOS/Windows) and run this again."
docker info >/dev/null 2>&1 || die "Docker is installed but not running. Start Docker and run this again."
docker compose version >/dev/null 2>&1 || die "The Docker Compose v2 plugin is required (docker compose version)."
command -v curl >/dev/null || die "curl is required."
if [ "$CREATE_ADMIN" -eq 1 ]; then
  command -v python3 >/dev/null || die "python3 is required to create the admin account (or use --no-admin)."
fi
echo "Docker, Docker Compose and curl found."

# 2. Install and start the stack -----------------------------------------------------------------------
step "Installing and starting TargetHub (the first build takes a few minutes)"
"$ROOT/scripts/install.sh" "${INSTALL_ARGS[@]}"

env_value() { { grep -E "^$1=" .env || true; } | tail -n1 | cut -d= -f2-; }
PUBLIC_URL="$(env_value TARGETHUB_PUBLIC_URL)"
PORT="$(env_value TARGETHUB_PORT)"
LOCAL_URL="http://127.0.0.1:${PORT:-8000}"

# 3. Confirm the server answers ----------------------------------------------------------------------------
step "Waiting for the server to answer"
ready=0
for _ in $(seq 1 60); do
  if curl -fsS "$LOCAL_URL/health/ready" >/dev/null 2>&1; then ready=1; break; fi
  sleep 2
done
[ "$ready" -eq 1 ] || die "the server did not answer on $LOCAL_URL. Check: docker compose logs --tail=100 api"
echo "Server is ready."

# 4. First admin account -------------------------------------------------------------------------------------
SETUP_REQUIRED="$(curl -fsS "$LOCAL_URL/api/v1/auth/setup-status" | python3 -c 'import json,sys;print("yes" if json.load(sys.stdin).get("setup_required") else "no")')"
ADMIN_CREATED=0
if [ "$CREATE_ADMIN" -eq 0 ]; then
  echo "Skipping admin creation (--no-admin)."
elif [ "$SETUP_REQUIRED" != "yes" ]; then
  echo "An admin account already exists; skipping admin creation."
else
  step "Creating the first admin account"
  if [ -z "$ADMIN_USER" ]; then
    read -rp "Admin username [admin]: " ADMIN_USER
    ADMIN_USER="${ADMIN_USER:-admin}"
  fi
  if [ -n "${TARGETHUB_ADMIN_PASSWORD:-}" ]; then
    ADMIN_PASSWORD="$TARGETHUB_ADMIN_PASSWORD"
  else
    while true; do
      read -rsp "Admin password (min 8 characters): " ADMIN_PASSWORD; echo
      read -rsp "Repeat password: " CONFIRM; echo
      [ "$ADMIN_PASSWORD" = "$CONFIRM" ] || { echo "Passwords do not match, try again."; continue; }
      [ "${#ADMIN_PASSWORD}" -ge 8 ] || { echo "Password must be at least 8 characters."; continue; }
      break
    done
  fi
  BODY="$(ADMIN_USER="$ADMIN_USER" ADMIN_PASSWORD="$ADMIN_PASSWORD" BOOTSTRAP_TOKEN="$(env_value ADMIN_BOOTSTRAP_TOKEN)" \
    python3 -c 'import json,os;print(json.dumps({"username":os.environ["ADMIN_USER"],"password":os.environ["ADMIN_PASSWORD"],"bootstrap_token":os.environ["BOOTSTRAP_TOKEN"]}))')"
  RESP="$(mktemp)"
  HTTP_CODE="$(curl -sS -o "$RESP" -w '%{http_code}' -H 'Content-Type: application/json' \
    -d "$BODY" "$LOCAL_URL/api/v1/auth/bootstrap" || true)"
  rm -f "$RESP"
  unset ADMIN_PASSWORD CONFIRM BODY
  case "$HTTP_CODE" in
    201) ADMIN_CREATED=1; echo "Admin account '$ADMIN_USER' created." ;;
    *) die "could not create the admin account (HTTP ${HTTP_CODE:-none}). Create it in the browser with the bootstrap token from .env." ;;
  esac
fi

# 5. Done ---------------------------------------------------------------------------------------------------
step "TargetHub is set up"
echo "Open:          ${PUBLIC_URL:-$LOCAL_URL}/app"
if [ "$ADMIN_CREATED" -eq 1 ]; then
  echo "Sign in as:    $ADMIN_USER (the password you just chose)"
elif [ "$SETUP_REQUIRED" = "yes" ] && [ "$CREATE_ADMIN" -eq 0 ]; then
  echo "Create the admin in the browser with the bootstrap token in .env (ADMIN_BOOTSTRAP_TOKEN)."
fi
echo
echo "Next steps:"
echo "  1. Admin -> Targets: add your boards and their capabilities (serial, power, deploy)."
echo "  2. Admin -> Agents or Power: connect hardware (see the README, 'Connect hardware')."
echo "  3. Admin -> Users: create accounts for your team."
echo
echo "Secrets are in $ROOT/.env (readable only by you). Keep it safe and back it up."
echo "Backups: scripts/backup.sh backups/   Reset a lost admin password: scripts/reset_admin_user.sh reset <user>"
