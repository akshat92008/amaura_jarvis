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
  print "Antigravity CLI not detected. Non-coding missions remain available; coding waits safely for configuration."
fi

# Source/regression verification is safe before provider configuration and does
# not consume or depend on the operator's private production routing.
./scripts/verify_amaura.sh

# A clean clone intentionally contains no OmniRoute secret. Core installation
# must therefore finish successfully instead of falling through to an obsolete
# local-model pull. If a complete production route already exists, resume the
# runtime bootstrap automatically; otherwise print the exact finalization path.
if .venv/bin/python - <<'PY'
from pathlib import Path
values = {}
for raw in Path('.env.amaura').read_text(encoding='utf-8').splitlines():
    line = raw.strip()
    if line and not line.startswith('#') and '=' in line:
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip()
required = (
    'AMAURA_OMNIROUTE_BASE_URL',
    'AMAURA_OMNIROUTE_API_KEY',
    'AMAURA_OMNIROUTE_MODEL',
    'AMAURA_OMNIROUTE_REVIEW_MODEL',
)
raise SystemExit(0 if all(values.get(name) for name in required) else 1)
PY
then
  print "Existing OmniRoute production route detected; continuing runtime setup…"
  ./Setup_Amaura_Runtime.command
  print "\nAmaura core and production runtime setup completed."
  print "Final certification: .venv/bin/python -m jarvis.amaura.deployment_gate"
else
  print "\nAmaura core installation completed successfully."
  print "Nova/Ollama are not part of the production path."
  print "Finish ARCH setup with:"
  print "  1. ./Setup_Amaura_OmniRoute.command"
  print "  2. ./Setup_Amaura_Antigravity.command"
  print "  3. ./Setup_Amaura_Runtime.command"
  print "  4. .venv/bin/python -m jarvis.amaura.deployment_gate"
fi
