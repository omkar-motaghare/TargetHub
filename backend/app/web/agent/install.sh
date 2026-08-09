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

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required." >&2
  exit 1
fi

BASE_DIR="/opt/targethub-agent"
CONFIG_DIR="/etc/targethub-agent"
mkdir -p "$BASE_DIR" "$CONFIG_DIR"

curl -fsSL "${TARGETHUB_URL%/}/web/agent/targethub_agent.py" -o "$BASE_DIR/targethub_agent.py"
chmod 0755 "$BASE_DIR/targethub_agent.py"

cat > "$CONFIG_DIR/config.json" <<EOF
{
  "targethub_url": "${TARGETHUB_URL%/}",
  "enrollment_token": "$ENROLLMENT_TOKEN",
  "heartbeat_interval": 15,
  "resources": []
}
EOF
chmod 0600 "$CONFIG_DIR/config.json"

cat > /etc/systemd/system/targethub-agent.service <<EOF
[Unit]
Description=TargetHub Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 $BASE_DIR/targethub_agent.py --config $CONFIG_DIR/config.json
Restart=always
RestartSec=5
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now targethub-agent.service

echo
echo "TargetHub Agent installed and started."
echo "Check status with: systemctl status targethub-agent"
echo "View logs with:   journalctl -u targethub-agent -f"
