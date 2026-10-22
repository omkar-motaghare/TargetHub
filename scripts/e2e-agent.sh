#!/usr/bin/env bash
# Live hub + real agent E2E (pty serial, fake sysfs GPIO). Needs backend/.venv or an active venv.
set -euo pipefail
cd "$(dirname "$0")/../backend"
PY="${PYTHON:-.venv/bin/python}"
[ -x "$PY" ] || PY=python3
exec "$PY" -m pytest -m e2e tests/e2e -q "$@"
