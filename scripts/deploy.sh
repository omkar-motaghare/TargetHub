#!/usr/bin/env bash
set -euo pipefail

# One-command deploy helper for local development
# - stops existing containers (backend and optional experimental frontend)
# - pulls latest Git changes for current branch
# - optionally builds experimental frontend and serves it with nginx container
# - builds and starts backend via docker-compose

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "[deploy] Starting deploy at $(date --iso-8601=seconds)"
EXPERIMENTAL_FRONTEND="${ENABLE_EXPERIMENTAL_FRONTEND:-0}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[deploy] Required command not found: $1" >&2
    exit 1
  fi
}

require_cmd git
require_cmd docker

# prefer 'docker compose' if available, fall back to 'docker-compose'
DC_CMD=""
if docker compose version >/dev/null 2>&1; then
  DC_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC_CMD="docker-compose"
else
  echo "[deploy] Neither 'docker compose' nor 'docker-compose' available" >&2
  exit 1
fi

stop_if_running() {
  local name="$1"
  cid=$(docker ps -q --filter "name=^/${name}$" || true)
  if [ -n "$cid" ]; then
    echo "[deploy] Stopping container $name ($cid)"
    docker stop "$cid" || true
    docker rm -f "$cid" || true
  fi
}

echo "[deploy] Stopping existing frontend and backend containers (if any)"
stop_if_running targethub_frontend || true
stop_if_running targethub || true

echo "[deploy] Fetching latest code from remote"
BRANCH=$(git rev-parse --abbrev-ref HEAD)
git fetch origin --prune
git pull --ff-only origin "$BRANCH" || git pull origin "$BRANCH" || true

# Build and run experimental frontend only when explicitly enabled
if [ "$EXPERIMENTAL_FRONTEND" = "1" ]; then
  if [ -f frontend/package.json ]; then
    echo "[deploy] Building experimental frontend"
    cd frontend
    if command -v npm >/dev/null 2>&1; then
      # prefer npm ci for reproducible installs
      if [ -f package-lock.json ]; then
        npm ci
      else
        npm install
      fi
      npm run build
    else
      echo "[deploy] npm not found; skipping frontend build" >&2
    fi
    cd "$REPO_ROOT"

    if [ -d frontend/dist ]; then
      echo "[deploy] Serving experimental frontend/dist via nginx container on http://localhost:3000"
      # Remove any existing frontend container
      stop_if_running targethub_frontend || true
      docker run -d --name targethub_frontend -p 3000:80 -v "$REPO_ROOT/frontend/dist":/usr/share/nginx/html:ro --restart unless-stopped nginx:alpine
    else
      echo "[deploy] frontend/dist not found after build; skipping nginx serve" >&2
    fi
  else
    echo "[deploy] No frontend/package.json found — skipping frontend build/serve"
  fi
else
  echo "[deploy] Experimental frontend is disabled (set ENABLE_EXPERIMENTAL_FRONTEND=1 to enable)"
fi

echo "[deploy] Building and starting backend via docker-compose"
# Build and start backend service defined in docker-compose.yml
if [ -f docker-compose.yml ]; then
  # build image
  $DC_CMD build --pull --no-cache || $DC_CMD build || true
  # start service (detached)
  $DC_CMD up -d
else
  echo "[deploy] docker-compose.yml not found — cannot start backend container" >&2
  exit 1
fi

echo "[deploy] Waiting a few seconds for containers to settle..."
sleep 3

echo "[deploy] Current relevant containers:"
docker ps --filter "name=targethub" --filter "name=targethub_frontend" --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"

echo "[deploy] Done. Canonical dashboard: http://localhost:8000/dashboard"
echo "[deploy] API docs: http://localhost:8000/docs"
if [ "$EXPERIMENTAL_FRONTEND" = "1" ]; then
  echo "[deploy] Experimental frontend: http://localhost:3000"
fi
