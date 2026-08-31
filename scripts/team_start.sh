#!/usr/bin/env sh
set -eu

# team_start.sh
# Pull latest from git, build images, start services and wait for API readiness.

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
COMPOSE_FILE="$ROOT_DIR/docker-compose.team.yml"

echo "Running from root: $ROOT_DIR"

if [ ! -f "$COMPOSE_FILE" ]; then
  echo "Compose file not found: $COMPOSE_FILE"
  exit 1
fi

cd "$ROOT_DIR"

# 1) Pull latest changes
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
echo "Pulling latest changes for branch $BRANCH..."
git pull origin "$BRANCH" || echo "git pull failed or no remote; continuing with local state"

# 2) Ensure .env exists
if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    echo "Creating .env from .env.example"
    cp .env.example .env
  else
    echo "No .env or .env.example found — continuing without .env"
  fi
fi

echo "Building docker images (may take a while)..."
docker compose -f "$COMPOSE_FILE" build --pull

echo "Starting services..."
docker compose -f "$COMPOSE_FILE" up -d --remove-orphans

# 3) Wait for API readiness (http://localhost:8000/)
API_URL=${API_URL:-http://127.0.0.1:8000/}
TIMEOUT=${TIMEOUT:-120}
SLEEP=2
elapsed=0
echo "Waiting for API at $API_URL (timeout=${TIMEOUT}s)"
while true; do
  if curl -sSf "$API_URL" >/dev/null 2>&1; then
    echo "API is available"
    break
  fi
  if [ "$elapsed" -ge "$TIMEOUT" ]; then
    echo "Timeout waiting for API after ${TIMEOUT}s"
    docker compose -f "$COMPOSE_FILE" logs --tail=200 api || true
    exit 2
  fi
  sleep $SLEEP
  elapsed=$((elapsed + SLEEP))
done

echo "Smoke test: GET /"
curl -sSf "$API_URL" | sed -n '1,200p'

echo "All done. To view logs: docker compose -f $COMPOSE_FILE logs -f api"

exit 0
