#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON_BIN="${AMAURA_PYTHON:-$PWD/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="${PYTHON_BIN_FALLBACK:-python3}"
fi
export PYTHONDONTWRITEBYTECODE=1
export PYTEST_ADDOPTS="${PYTEST_ADDOPTS:-} -p no:cacheprovider"
# Source tests run against explicit test settings rather than the operator's
# generated production secrets and strict launch configuration.
export AMAURA_SKIP_ENV_AUTOLOAD=1
export AMAURA_STRICT_EVIDENCE=0
export AMAURA_STRICT_REVIEW=0
export AMAURA_STRICT_GIT=0
# Source regression must not require an operator cloud route.  Individual model
# routing tests set their own explicit balanced/cloud configuration.
export AMAURA_MODEL_MODE=local
"$PYTHON_BIN" -m compileall -q jarvis aimodel scripts tests
"$PYTHON_BIN" -m pytest -q
"$PYTHON_BIN" scripts/release_gate.py --static-only
