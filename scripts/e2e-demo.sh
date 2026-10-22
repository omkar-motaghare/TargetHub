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
ADMIN_BOOTSTRAP_TOKEN="${ADMIN_BOOTSTRAP_TOKEN:-e2e-bootstrap-${RUN_ID}}"
export ADMIN_BOOTSTRAP_TOKEN

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$ROOT_DIR/backend/.venv/bin/python" ]]; then
    PYTHON_BIN="$ROOT_DIR/backend/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

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

bootstrap_admin() {
  local username="$1"
  local password="$2"

  local payload
  payload=$(cat <<EOF
{"username":"$username","password":"$password","bootstrap_token":"$ADMIN_BOOTSTRAP_TOKEN"}
EOF
)

  local code
  code=$(curl -s -o /tmp/targethub_bootstrap.json -w "%{http_code}" \
    -X POST "${API_BASE}/auth/bootstrap" \
    -H "Content-Type: application/json" \
    -d "$payload")

  if [[ "$code" != "201" ]]; then
    echo "[e2e] Failed to bootstrap admin $username (HTTP $code)"
    cat /tmp/targethub_bootstrap.json
    exit 1
  fi
}

# Admin-only: creating a user requires an authenticated admin bearer token.
create_user() {
  local username="$1"
  local password="$2"
  local roles_csv="$3"
  local admin_token="$4"

  local payload
  payload=$(cat <<EOF
{"username":"$username","password":"$password","roles":["$roles_csv"]}
EOF
)

  local code
  code=$(curl -s -o /tmp/targethub_user_create.json -w "%{http_code}" \
    -X POST "${API_BASE}/auth/users" \
    -H "Authorization: Bearer ${admin_token}" \
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

  TOKEN_JSON="$body" "$PYTHON_BIN" - <<'PY'
import json
import os
payload = json.loads(os.environ["TOKEN_JSON"])
print(payload.get("access_token", ""))
PY
}

json_field() {
  local json="$1"
  local expr="$2"
  JSON_PAYLOAD="$json" JSON_EXPR="$expr" "$PYTHON_BIN" - <<'PY'
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

bootstrap_admin "$ADMIN_USER" "$ADMIN_PASS"
ADMIN_TOKEN="$(get_token "$ADMIN_USER" "$ADMIN_PASS")"
if [[ -z "$ADMIN_TOKEN" ]]; then
  echo "[e2e] Failed to obtain admin token"
  exit 1
fi

create_user "$USER1" "$USER1_PASS" user "$ADMIN_TOKEN"
USER_TOKEN="$(get_token "$USER1" "$USER1_PASS")"

if [[ -z "$USER_TOKEN" ]]; then
  echo "[e2e] Failed to obtain tokens"
  exit 1
fi

echo "[e2e] Enrolling Agent and publishing resources"
ENROLLMENT_RESP=$(curl -s -X POST "${API_BASE}/agents/enrollments" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"agent_name\":\"e2e-agent-${RUN_ID}\"}")
ENROLL_TOKEN="$(json_field "$ENROLLMENT_RESP" token)"
if [[ -z "$ENROLL_TOKEN" ]]; then
  echo "[e2e] Could not create agent enrollment"
  echo "$ENROLLMENT_RESP"
  exit 1
fi

ENROLL_RESP=$(curl -s -X POST "${API_BASE}/agents/enroll" \
  -H "Content-Type: application/json" \
  -d "{\"token\":\"${ENROLL_TOKEN}\",\"hostname\":\"e2e-host-${RUN_ID}\"}")
AGENT_ID="$(json_field "$ENROLL_RESP" agent.id)"
AGENT_CREDENTIAL="$(json_field "$ENROLL_RESP" credential)"
if [[ -z "$AGENT_ID" || -z "$AGENT_CREDENTIAL" ]]; then
  echo "[e2e] Could not enroll agent"
  echo "$ENROLL_RESP"
  exit 1
fi

HEARTBEAT_RESP=$(curl -s -X POST "${API_BASE}/agents/${AGENT_ID}/heartbeat" \
  -H "Authorization: Bearer ${AGENT_CREDENTIAL}" \
  -H "Content-Type: application/json" \
  -d '{"hostname":"e2e-host","resources":[{"resource_key":"/dev/ttyUSB0","resource_type":"serial","display_name":"ttyUSB0","metadata":{"path":"/dev/ttyUSB0"},"available":true},{"resource_key":"pdu/relay-1","resource_type":"power","display_name":"PDU Relay 1","metadata":{"channel":1},"available":true}]}'
)

SERIAL_RESOURCE_ID="$(json_field "$HEARTBEAT_RESP" resources.0.id)"
POWER_RESOURCE_ID="$(json_field "$HEARTBEAT_RESP" resources.1.id)"
if [[ -z "$SERIAL_RESOURCE_ID" || -z "$POWER_RESOURCE_ID" ]]; then
  echo "[e2e] Could not publish agent resources"
  echo "$HEARTBEAT_RESP"
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
  -d "{\"name\":\"Serial Console ${RUN_ID}\",\"capability_type\":\"serial\",\"provider_key\":\"serial-demo\",\"agent_id\":\"${AGENT_ID}\",\"resource_id\":\"${SERIAL_RESOURCE_ID}\"}")
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
  -d "{\"reservation_id\":\"${RES_ID}\",\"user_id\":\"${USER1}\",\"capability_type\":\"serial\",\"capability_id\":\"${CAP_ID}\"}")
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
create_user "$USER2" "$USER2_PASS" user "$ADMIN_TOKEN"
USER2_TOKEN="$(get_token "$USER2" "$USER2_PASS")"
FORBIDDEN_CODE=$(curl -s -o /tmp/targethub_forbidden.json -w "%{http_code}" \
  -H "Authorization: Bearer ${USER2_TOKEN}" \
  "${API_BASE}/sessions/${SESSION_ID}")
if [[ "$FORBIDDEN_CODE" != "403" ]]; then
  echo "[e2e] Expected 403 for non-owner session access, got $FORBIDDEN_CODE"
  cat /tmp/targethub_forbidden.json
  exit 1
fi

echo "[e2e] Adding power capability and exercising generic execute"
POWER_CAP_RESP=$(curl -s -X POST "${API_BASE}/targets/${TARGET_ID}/capabilities" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"Power ${RUN_ID}\",\"capability_type\":\"power\",\"provider_key\":\"pdu-demo\",\"agent_id\":\"${AGENT_ID}\",\"resource_id\":\"${POWER_RESOURCE_ID}\"}")
POWER_CAP_ID="$(json_field "$POWER_CAP_RESP" id)"
if [[ -z "$POWER_CAP_ID" ]]; then
  echo "[e2e] Could not create power capability"
  echo "$POWER_CAP_RESP"
  exit 1
fi

POWER_SESSION=$(curl -s -X POST "${API_BASE}/sessions" \
  -H "Authorization: Bearer ${USER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"reservation_id\":\"${RES_ID}\",\"user_id\":\"${USER1}\",\"capability_type\":\"power\",\"capability_id\":\"${POWER_CAP_ID}\"}")
POWER_SESSION_ID="$(json_field "$POWER_SESSION" id)"
if [[ -z "$POWER_SESSION_ID" ]]; then
  echo "[e2e] Could not create power session"
  echo "$POWER_SESSION"
  exit 1
fi

POWER_RESULT=$(curl -s -X POST "${API_BASE}/sessions/${POWER_SESSION_ID}/execute" \
  -H "Authorization: Bearer ${USER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"operation":"on","params":{}}')
POWER_STATE="$(json_field "$POWER_RESULT" data.power)"
if [[ "$POWER_STATE" != "on" ]]; then
  echo "[e2e] Expected power on, got '$POWER_STATE'"
  echo "$POWER_RESULT"
  exit 1
fi

echo "[e2e] Verifying observability endpoints"
HEALTH_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${API_BASE%/api/v1}/health")
READY_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${API_BASE%/api/v1}/health/ready")
METRICS_BODY=$(curl -s "${API_BASE%/api/v1}/metrics")
if [[ "$HEALTH_CODE" != "200" || "$READY_CODE" != "200" ]]; then
  echo "[e2e] Health checks failed (health=$HEALTH_CODE ready=$READY_CODE)"
  exit 1
fi
if ! echo "$METRICS_BODY" | grep -q "targethub_provider_operations_total"; then
  echo "[e2e] Expected provider operation metrics to be present"
  exit 1
fi

echo "[e2e] Verifying admin audit trail is populated"
AUDIT_BODY=$(curl -s -H "Authorization: Bearer ${ADMIN_TOKEN}" "${API_BASE}/audit?limit=50")
if ! echo "$AUDIT_BODY" | grep -q "provider.execute"; then
  echo "[e2e] Expected audit trail to include provider.execute"
  echo "$AUDIT_BODY"
  exit 1
fi

echo "[e2e] SUCCESS"
echo "  target_id: ${TARGET_ID}"
echo "  reservation_id: ${RES_ID}"
echo "  session_id: ${SESSION_ID}"
echo "  power_session_id: ${POWER_SESSION_ID}"
echo "  serial_read_http_code: ${SERIAL_CODE}"
echo "  power_state: ${POWER_STATE}"
