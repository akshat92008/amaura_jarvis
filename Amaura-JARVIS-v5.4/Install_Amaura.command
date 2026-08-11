#!/bin/zsh
set -euo pipefail
cd "${0:A:h}"

if [[ -z "${PYTHON_BIN:-}" ]]; then
  if command -v python3.13 >/dev/null 2>&1; then
    PYTHON_BIN="python3.13"
  elif command -v python3.12 >/dev/null 2>&1; then
    PYTHON_BIN="python3.12"
  else
    PYTHON_BIN="python3"
  fi
fi
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  print -u2 "Python 3.11+ is required. Install it, then rerun this file."
  exit 1
fi
"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit(f"Python 3.11+ is required; found {sys.version.split()[0]}")
PY

if ! command -v uv >/dev/null 2>&1; then
  print -u2 "The reproducible installer requires uv so dependencies come from the bundled uv.lock."
  print -u2 "Install it with: brew install uv"
  exit 1
fi

# Fail closed if pyproject.toml and uv.lock disagree. Never perform an unlocked pip install.
uv sync --frozen --extra dev --extra voice --python "$PYTHON_BIN"

if [[ ! -f .env.amaura ]]; then
  .venv/bin/python -m jarvis.amaura.cli init
else
  chmod 600 .env.amaura
  print "Existing .env.amaura preserved."
fi

if command -v agy >/dev/null 2>&1; then
  print "Antigravity CLI detected. Run ./Setup_Amaura_Antigravity.command once to enable safe unattended coding."
else
  print "Antigravity CLI not detected. JARVIS can still run non-coding/company missions; coding_backend=antigravity will wait for configuration."
fi

./scripts/verify_amaura.sh
./Setup_Amaura_Runtime.command

print "\nAmaura installation and live certification completed."
print "Start with: ./Launch_Amaura.command"
