#!/usr/bin/env bash
set -euo pipefail

TARGETHUB_URL=""
ENROLLMENT_TOKEN=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --targethub-url) TARGETHUB_URL="$2"; shift 2 ;;
    --enrollment-token) ENROLLMENT_TOKEN="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$TARGETHUB_URL" || -z "$ENROLLMENT_TOKEN" ]]; then
  echo "Usage: install.sh --targethub-url URL --enrollment-token TOKEN" >&2
  exit 2
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Please run the installer with sudo." >&2
  exit 1
fi

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "TargetHub Agent requires a Linux-based machine." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required." >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required." >&2
  exit 1
fi

if ! command -v sha256sum >/dev/null 2>&1; then
  echo "sha256sum is required." >&2
  exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemd/systemctl is required for the TargetHub Agent service." >&2
  exit 1
fi

BASE_DIR="/opt/targethub-agent"
CONFIG_DIR="/etc/targethub-agent"
UNIT_FILE="/etc/systemd/system/targethub-agent@.service"
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

mkdir -p "$BASE_DIR" "$CONFIG_DIR"
chmod 0700 "$CONFIG_DIR"

curl -fsSL "${TARGETHUB_URL%/}/web/agent/targethub_agent.py" -o "$TEMP_AGENT_PATH"
python3 -m py_compile "$TEMP_AGENT_PATH"
chmod 0755 "$TEMP_AGENT_PATH"
mv "$TEMP_AGENT_PATH" "$AGENT_PATH"

if [[ ! -f "$CONFIG_PATH" ]] || ! grep -q '"agent_id"' "$CONFIG_PATH"; then
  cat > "$CONFIG_PATH" <<EOF
{
  "targethub_url": "${TARGETHUB_URL%/}",
  "enrollment_token": "$ENROLLMENT_TOKEN",
  "heartbeat_interval": 15,
  "operation_poll_wait_seconds": 5,
  "request_timeout": 15,
  "resources": []
}
EOF
  chmod 0600 "$CONFIG_PATH"
  CREATED_CONFIG="1"
fi

cat > "$UNIT_FILE" <<'EOF'
[Unit]
Description=TargetHub Agent (%i)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/targethub-agent/targethub_agent.py --config /etc/targethub-agent/%i.json
Restart=always
RestartSec=5
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"
trap - ERR

echo
echo "TargetHub Agent instance installed and started: $SERVICE_NAME"
echo "Config: $CONFIG_PATH"
echo "Check status with: systemctl status $SERVICE_NAME"
echo "View logs with:   journalctl -u $SERVICE_NAME -f"
echo "Multiple Agent enrollments can run side-by-side on this Linux host."
