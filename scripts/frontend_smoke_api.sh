#!/usr/bin/env bash
set -euo pipefail

# API smoke flow for React workflow parity:
# login -> configure target -> reserve -> open session -> execute/read -> close -> release

BASE_URL="${TARGETHUB_BASE_URL:-http://localhost:8000}"
API_URL="${BASE_URL%/}/api/v1"
ADMIN_USER="${TARGETHUB_ADMIN_USER:-admin}"
ADMIN_PASS="${TARGETHUB_ADMIN_PASS:-change-me-now}"
TARGET_NAME="smoke-target-$(date +%s)-$RANDOM"
TARGET_SERIAL="SMOKE-$(date +%s)-$RANDOM"

json_field() {
  local json="$1"
  local field="$2"
  python3 - <<'PY' "$json" "$field"
import json, sys
payload = json.loads(sys.argv[1])
field = sys.argv[2]
value = payload
for part in field.split('.'):
    if isinstance(value, dict):
        value = value.get(part)
    else:
        value = None
        break
if value is None:
    print("")
else:
    print(value)
PY
}

now_iso() {
  python3 - <<'PY'
from datetime import datetime, timezone
print(datetime.now(timezone.utc).isoformat())
PY
}

later_iso() {
  python3 - <<'PY'
from datetime import datetime, timedelta, timezone
print((datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
PY
}

echo "[1/8] Logging in as ${ADMIN_USER}"
login_res=$(curl -fsS -X POST "${API_URL}/auth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=${ADMIN_USER}&password=${ADMIN_PASS}&grant_type=")
TOKEN=$(json_field "$login_res" "access_token")
if [[ -z "$TOKEN" ]]; then
  echo "Failed to obtain token"
  exit 1
fi

auth=(-H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json")

echo "[2/8] Creating target ${TARGET_NAME}"
create_target_payload=$(cat <<JSON
{
  "name": "${TARGET_NAME}",
  "description": "Smoke target",
  "vendor": "TargetHub",
  "board_model": "SmokeBoard",
  "serial_number": "${TARGET_SERIAL}",
  "lab_name": "SmokeLab",
  "location": "Rack-A1",
  "status": "available",
  "enabled": true,
  "capabilities": [
    {
      "name": "serial-console",
      "capability_type": "serial",
      "provider_key": "serial-demo",
      "provider_config": {},
      "enabled": true
    }
  ]
}
JSON
)

target_res=$(curl -fsS -X POST "${API_URL}/targets" "${auth[@]}" -d "$create_target_payload")
TARGET_ID=$(json_field "$target_res" "id")
if [[ -z "$TARGET_ID" ]]; then
  echo "Target creation failed"
  exit 1
fi

echo "[3/8] Creating reservation"
reservation_payload=$(cat <<JSON
{
  "target_id": "${TARGET_ID}",
  "user_id": "${ADMIN_USER}",
  "starts_at": "$(now_iso)",
  "ends_at": "$(later_iso)"
}
JSON
)
reservation_res=$(curl -fsS -X POST "${API_URL}/reservations" "${auth[@]}" -d "$reservation_payload")
RESERVATION_ID=$(json_field "$reservation_res" "id")

echo "[4/8] Opening serial session"
session_payload=$(cat <<JSON
{
  "reservation_id": "${RESERVATION_ID}",
  "user_id": "${ADMIN_USER}",
  "capability_type": "serial"
}
JSON
)
session_res=$(curl -fsS -X POST "${API_URL}/sessions" "${auth[@]}" -d "$session_payload")
SESSION_ID=$(json_field "$session_res" "id")

echo "[5/8] Discovering operations"
if ops_res=$(curl -sS -f "${API_URL}/sessions/${SESSION_ID}/operations" -H "Authorization: Bearer ${TOKEN}" 2>/dev/null); then
  echo "Operations: ${ops_res}"
else
  echo "Operations endpoint unavailable on this runtime; continuing with serial read fallback"
fi

echo "[6/8] Executing serial read"
curl -sS -X POST "${API_URL}/sessions/${SESSION_ID}/serial/open" -H "Authorization: Bearer ${TOKEN}" >/dev/null || true
curl -fsS "${API_URL}/sessions/${SESSION_ID}/serial/read" -H "Authorization: Bearer ${TOKEN}" >/dev/null

echo "[7/8] Closing session and releasing reservation"
curl -fsS -X POST "${API_URL}/sessions/${SESSION_ID}/close?user_id=${ADMIN_USER}" -H "Authorization: Bearer ${TOKEN}" >/dev/null
curl -fsS -X POST "${API_URL}/reservations/${RESERVATION_ID}/release?user_id=${ADMIN_USER}" -H "Authorization: Bearer ${TOKEN}" >/dev/null

echo "[8/8] Cleaning up target"
curl -fsS -X DELETE "${API_URL}/targets/${TARGET_ID}" -H "Authorization: Bearer ${TOKEN}" >/dev/null

echo "Frontend/API smoke flow passed."
