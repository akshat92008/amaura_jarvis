#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Missing .venv. Run: uv sync --frozen --extra dev --python python"
  exit 2
fi

export AMAURA_DISABLE_CLOUD="${AMAURA_DISABLE_CLOUD:-1}"
export JARVIS_LEGACY_TOOL_MODE="${JARVIS_LEGACY_TOOL_MODE:-disabled}"

exec .venv/bin/python scripts/arch_holdout_v10.py
