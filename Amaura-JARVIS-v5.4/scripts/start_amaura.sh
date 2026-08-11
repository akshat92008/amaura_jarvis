#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
ENV_FILE="${AMAURA_ENV_FILE:-.env.amaura}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE. Run: python -m jarvis.amaura.cli init" >&2
  exit 1
fi
if [[ -x .venv/bin/python ]]; then
  PYTHON_BIN=.venv/bin/python
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi
"$PYTHON_BIN" -m jarvis.amaura.cli --env-file "$ENV_FILE" doctor
exec "$PYTHON_BIN" -m jarvis.amaura.cli --env-file "$ENV_FILE" worker "$@"
