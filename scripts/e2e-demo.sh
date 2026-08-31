#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_BASE="${API_BASE:-http://127.0.0.1:8000/api/v1}"
RUN_ID="$(date +%s)"
ADMIN_USER="admin_${RUN_ID}"
ADMIN_PASS="admin1234"
USER1="user1_${RUN_ID}"
USER1_PASS="user12345"
USER2="user2_${RUN_ID}"
USER2_PASS="user23456"

cd "$ROOT_DIR"

echo "[e2e] Starting TargetHub API stack"
docker compose up -d --build

echo "[e2e] Waiting for API readiness"
for i in $(seq 1 60); do
  if curl -sf "${API_BASE%/api/v1}/" >/dev/null; then
    break
  fi
  sleep 1
  if [[ "$i" == "60" ]]; then
    echo "[e2e] API did not become ready in time"
    exit 1
  fi
done

create_user() {
  local username="$1"
  local password="$2"
  local roles_csv="$3"

  local payload
  payload=$(cat <<EOF
{"username":"$username","password":"$password","roles":["$roles_csv"]}
EOF
)

  local code
  code=$(curl -s -o /tmp/targethub_user_create.json -w "%{http_code}" \
    -X POST "${API_BASE}/auth/users" \
    -H "Content-Type: application/json" \
    -d "$payload")

  if [[ "$code" != "200" && "$code" != "201" && "$code" != "400" ]]; then
    echo "[e2e] Failed to create user $username (HTTP $code)"
    cat /tmp/targethub_user_create.json
    exit 1
  fi
}

get_token() {
  local username="$1"
  local password="$2"

  local body
  body=$(curl -s -X POST "${API_BASE}/auth/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=${username}&password=${password}&grant_type=")

  TOKEN_JSON="$body" /home/omkar_motaghare/TargetHub/backend/.venv/bin/python - <<'PY'
import json
import os
payload = json.loads(os.environ["TOKEN_JSON"])
print(payload.get("access_token", ""))
PY
}

json_field() {
  local json="$1"
  local expr="$2"
  JSON_PAYLOAD="$json" JSON_EXPR="$expr" /home/omkar_motaghare/TargetHub/backend/.venv/bin/python - <<'PY'
import json
import os
payload = json.loads(os.environ["JSON_PAYLOAD"])
expr = os.environ["JSON_EXPR"].split('.')
cur = payload
for part in expr:
    if isinstance(cur, list):
        cur = cur[int(part)]
    else:
        cur = cur.get(part)
print("" if cur is None else cur)
PY
}

create_user "$ADMIN_USER" "$ADMIN_PASS" admin
create_user "$USER1" "$USER1_PASS" user

ADMIN_TOKEN="$(get_token "$ADMIN_USER" "$ADMIN_PASS")"
USER_TOKEN="$(get_token "$USER1" "$USER1_PASS")"

if [[ -z "$ADMIN_TOKEN" || -z "$USER_TOKEN" ]]; then
  echo "[e2e] Failed to obtain tokens"
  exit 1
fi

echo "[e2e] Creating target as admin"
TARGET_RESP=$(curl -s -X POST "${API_BASE}/targets" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"BOARD-01-${RUN_ID}\",\"vendor\":\"ST\",\"board_model\":\"Nucleo\",\"description\":\"E2E board\"}")

TARGET_ID="$(json_field "$TARGET_RESP" id)"
if [[ -z "$TARGET_ID" ]]; then
  echo "[e2e] Could not create/read target id"
  echo "$TARGET_RESP"
  exit 1
fi

echo "[e2e] Adding serial capability"
CAP_RESP=$(curl -s -X POST "${API_BASE}/targets/${TARGET_ID}/capabilities" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"Serial Console ${RUN_ID}\",\"capability_type\":\"serial\",\"provider_key\":\"serial-demo\"}")
CAP_ID="$(json_field "$CAP_RESP" id)"
if [[ -z "$CAP_ID" ]]; then
  echo "[e2e] Could not create capability"
  echo "$CAP_RESP"
  exit 1
fi

echo "[e2e] Creating reservation as user"
NOW_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
END_ISO=$(date -u -d '+30 minutes' +"%Y-%m-%dT%H:%M:%SZ")
RES_RESP=$(curl -s -X POST "${API_BASE}/reservations" \
  -H "Authorization: Bearer ${USER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"target_id\":\"${TARGET_ID}\",\"user_id\":\"${USER1}\",\"starts_at\":\"${NOW_ISO}\",\"ends_at\":\"${END_ISO}\"}")
RES_ID="$(json_field "$RES_RESP" id)"
if [[ -z "$RES_ID" ]]; then
  echo "[e2e] Could not create reservation"
  echo "$RES_RESP"
  exit 1
fi

echo "[e2e] Creating session as reservation owner"
SESSION_RESP=$(curl -s -X POST "${API_BASE}/sessions" \
  -H "Authorization: Bearer ${USER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"reservation_id\":\"${RES_ID}\",\"user_id\":\"${USER1}\",\"capability_type\":\"serial\"}")
SESSION_ID="$(json_field "$SESSION_RESP" id)"
if [[ -z "$SESSION_ID" ]]; then
  echo "[e2e] Could not create session"
  echo "$SESSION_RESP"
  exit 1
fi

echo "[e2e] Verifying token enforcement"
UNAUTH_CODE=$(curl -s -o /tmp/targethub_unauth.json -w "%{http_code}" "${API_BASE}/targets")
if [[ "$UNAUTH_CODE" != "401" ]]; then
  echo "[e2e] Expected 401 for unauthenticated /targets, got $UNAUTH_CODE"
  exit 1
fi

echo "[e2e] Verifying session owner can call serial endpoint (configuration may still be missing)"
SERIAL_CODE=$(curl -s -o /tmp/targethub_serial_read.json -w "%{http_code}" \
  -H "Authorization: Bearer ${USER_TOKEN}" \
  "${API_BASE}/sessions/${SESSION_ID}/serial/read")

if [[ "$SERIAL_CODE" != "200" && "$SERIAL_CODE" != "409" ]]; then
  echo "[e2e] Unexpected serial read response code $SERIAL_CODE"
  cat /tmp/targethub_serial_read.json
  exit 1
fi

echo "[e2e] Verifying non-owner cannot access the session"
create_user "$USER2" "$USER2_PASS" user
USER2_TOKEN="$(get_token "$USER2" "$USER2_PASS")"
FORBIDDEN_CODE=$(curl -s -o /tmp/targethub_forbidden.json -w "%{http_code}" \
  -H "Authorization: Bearer ${USER2_TOKEN}" \
  "${API_BASE}/sessions/${SESSION_ID}")
if [[ "$FORBIDDEN_CODE" != "403" ]]; then
  echo "[e2e] Expected 403 for non-owner session access, got $FORBIDDEN_CODE"
  cat /tmp/targethub_forbidden.json
  exit 1
fi

echo "[e2e] SUCCESS"
echo "  target_id: ${TARGET_ID}"
echo "  reservation_id: ${RES_ID}"
echo "  session_id: ${SESSION_ID}"
echo "  serial_read_http_code: ${SERIAL_CODE}"
