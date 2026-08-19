#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
ENV_FILE="${AMAURA_ENV_FILE:-.env.amaura}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE. ARCH requires a private runtime environment." >&2
  exit 1
fi
if [[ -x .venv/bin/python ]]; then
  PYTHON_BIN=.venv/bin/python
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi
exec "$PYTHON_BIN" -m jarvis.arch --env-file "$ENV_FILE" --headless --no-web "$@"
