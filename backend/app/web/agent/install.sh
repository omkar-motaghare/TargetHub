#!/usr/bin/env bash
set -euo pipefail

TARGETHUB_URL=""
ENROLLMENT_TOKEN=""
AGENT_SHA256=""
ALLOW_INSECURE_HTTP="0"
SERVICE_USER="targethub"
PREFIX=""

usage() {
  cat >&2 <<USAGE
Usage: install.sh --targethub-url URL --enrollment-token TOKEN --agent-sha256 SHA256 [options]

Options:
  --allow-insecure-http   Permit a plain http:// TargetHub URL (lab testing only)
  --service-user NAME     Dedicated service account (default: targethub)
  --prefix DIR            Stage files under DIR without root, user creation or
                          systemd (dry run / packaging): DIR/opt, DIR/etc
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --targethub-url) TARGETHUB_URL="$2"; shift 2 ;;
    --enrollment-token) ENROLLMENT_TOKEN="$2"; shift 2 ;;
    --agent-sha256) AGENT_SHA256="$2"; shift 2 ;;
    --allow-insecure-http) ALLOW_INSECURE_HTTP="1"; shift ;;
    --service-user) SERVICE_USER="$2"; shift 2 ;;
    --prefix) PREFIX="${2%/}"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ -z "$TARGETHUB_URL" || -z "$ENROLLMENT_TOKEN" || -z "$AGENT_SHA256" ]]; then
  usage
  exit 2
fi

if [[ ! "$AGENT_SHA256" =~ ^[0-9a-fA-F]{64}$ ]]; then
  echo "--agent-sha256 must be a 64-character hex digest." >&2
  exit 2
fi

case "$TARGETHUB_URL" in
  https://*) ;;
  http://*)
    if [[ "$ALLOW_INSECURE_HTTP" != "1" ]]; then
      echo "Refusing plain http:// TargetHub URL; use https:// or pass --allow-insecure-http." >&2
      exit 2
    fi
    ;;
  *) echo "--targethub-url must start with https:// (or http:// with --allow-insecure-http)." >&2; exit 2 ;;
esac

if [[ -z "$PREFIX" && "$(id -u)" -ne 0 ]]; then
  echo "Please run the installer with sudo." >&2
  exit 1
fi

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "TargetHub Agent requires a Linux-based machine." >&2
  exit 1
fi

for tool in python3 curl sha256sum; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "$tool is required." >&2
    exit 1
  fi
done

if [[ -z "$PREFIX" ]] && ! command -v systemctl >/dev/null 2>&1; then
  echo "systemd/systemctl is required for the TargetHub Agent service." >&2
  exit 1
fi

BASE_DIR="$PREFIX/opt/targethub-agent"
CONFIG_DIR="$PREFIX/etc/targethub-agent"
UNIT_FILE="$PREFIX/etc/systemd/system/targethub-agent@.service"
INSTANCE="$(printf '%s' "$ENROLLMENT_TOKEN" | sha256sum | cut -c1-16)"
CONFIG_PATH="$CONFIG_DIR/${INSTANCE}.json"
SERVICE_NAME="targethub-agent@${INSTANCE}.service"
AGENT_PATH="$BASE_DIR/targethub_agent.py"
TEMP_AGENT_PATH="$BASE_DIR/targethub_agent.py.tmp"
CREATED_CONFIG="0"

cleanup_on_error() {
  rm -f "$TEMP_AGENT_PATH"
  if [[ "$CREATED_CONFIG" == "1" ]]; then
    rm -f "$CONFIG_PATH"
  fi
}
trap cleanup_on_error ERR

mkdir -p "$BASE_DIR" "$CONFIG_DIR" "$(dirname "$UNIT_FILE")"

curl -fsSL "${TARGETHUB_URL%/}/web/agent/targethub_agent.py" -o "$TEMP_AGENT_PATH"
ACTUAL_SHA256="$(sha256sum "$TEMP_AGENT_PATH" | cut -d' ' -f1)"
if [[ "${ACTUAL_SHA256,,}" != "${AGENT_SHA256,,}" ]]; then
  echo "Agent checksum mismatch (expected ${AGENT_SHA256}, got ${ACTUAL_SHA256}); aborting." >&2
  rm -f "$TEMP_AGENT_PATH"
  exit 1
fi
python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$TEMP_AGENT_PATH"
chmod 0755 "$TEMP_AGENT_PATH"
mv "$TEMP_AGENT_PATH" "$AGENT_PATH"

if [[ -z "$PREFIX" ]]; then
  if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --home-dir "$BASE_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
  fi
  for group in dialout gpio plugdev; do
    if getent group "$group" >/dev/null 2>&1; then
      usermod -aG "$group" "$SERVICE_USER"
    fi
  done
fi

if [[ ! -f "$CONFIG_PATH" ]] || ! grep -q '"agent_id"' "$CONFIG_PATH"; then
  (
    umask 0077
    cat > "$CONFIG_PATH" <<JSON
{
  "targethub_url": "${TARGETHUB_URL%/}",
  "enrollment_token": "$ENROLLMENT_TOKEN",
  "heartbeat_interval": 15,
  "operation_poll_wait_seconds": 5,
  "request_timeout": 15,
  "allow_insecure_http": $([[ "$ALLOW_INSECURE_HTTP" == "1" ]] && echo true || echo false),
  "resources": []
}
JSON
  )
  CREATED_CONFIG="1"
fi

if [[ -z "$PREFIX" ]]; then
  chown -R "$SERVICE_USER":"$SERVICE_USER" "$CONFIG_DIR"
  chmod 0700 "$CONFIG_DIR"
  chmod 0600 "$CONFIG_PATH"
fi

cat > "$UNIT_FILE" <<UNIT
[Unit]
Description=TargetHub Agent (%i)
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
NotifyAccess=main
User=$SERVICE_USER
ExecStart=/usr/bin/python3 /opt/targethub-agent/targethub_agent.py --config /etc/targethub-agent/%i.json
Restart=always
RestartSec=5
WatchdogSec=120
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
ReadWritePaths=/etc/targethub-agent -/sys/class/gpio
MemoryMax=64M

[Install]
WantedBy=multi-user.target
UNIT

if [[ -z "$PREFIX" ]]; then
  systemctl daemon-reload
  systemctl enable --now "$SERVICE_NAME"
fi
trap - ERR

echo
if [[ -z "$PREFIX" ]]; then
  echo "TargetHub Agent instance installed and started: $SERVICE_NAME"
  echo "Check status with: systemctl status $SERVICE_NAME"
  echo "View logs with:   journalctl -u $SERVICE_NAME -f"
else
  echo "TargetHub Agent files staged under $PREFIX (service not started)."
fi
echo "Config: $CONFIG_PATH"
