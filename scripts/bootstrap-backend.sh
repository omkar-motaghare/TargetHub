#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
VENV_DIR="${TARGETHUB_BACKEND_VENV:-$BACKEND_DIR/.venv}"
PYTHON_BIN="${PYTHON_BIN:-$VENV_DIR/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[bootstrap] Creating backend virtual environment at $VENV_DIR"
  python3 -m venv "$VENV_DIR"
  PYTHON_BIN="$VENV_DIR/bin/python"
fi

echo "[bootstrap] Upgrading pip"
"$PYTHON_BIN" -m pip install --upgrade pip

echo "[bootstrap] Installing backend dependencies"
"$PYTHON_BIN" -m pip install -r "$BACKEND_DIR/requirements.txt" pytest pytest-asyncio httpx black ruff isort

echo "[bootstrap] Backend environment ready"
echo "[bootstrap] Activate with: source $VENV_DIR/bin/activate"