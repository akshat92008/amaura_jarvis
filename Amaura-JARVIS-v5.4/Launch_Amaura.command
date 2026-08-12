#!/bin/zsh
set -euo pipefail
cd "${0:A:h}"

if [[ ! -x .venv/bin/python ]]; then
  print -u2 "Amaura is not installed. Run ./Install_Amaura.command first."
  exit 1
fi
if [[ ! -f .env.amaura ]]; then
  print -u2 "Amaura is not initialised. Run: .venv/bin/python -m jarvis.amaura.cli init"
  exit 1
fi

chmod 600 .env.amaura
source .venv/bin/activate
export AMAURA_RESOURCE_PROFILE="${AMAURA_RESOURCE_PROFILE:-macbook-8gb}"
export AMAURA_JARVIS_PROACTIVE="${AMAURA_JARVIS_PROACTIVE:-0}"
export AMAURA_JARVIS_MISSION_RUNNER="${AMAURA_JARVIS_MISSION_RUNNER:-1}"
export AMAURA_JARVIS_MISSION_POLL_SECONDS="${AMAURA_JARVIS_MISSION_POLL_SECONDS:-3}"
export AMAURA_JARVIS_MISSION_MAX_GOALS="${AMAURA_JARVIS_MISSION_MAX_GOALS:-1}"
export AMAURA_COMPANY_AUTOPILOT_RUNTIME="${AMAURA_COMPANY_AUTOPILOT_RUNTIME:-0}"
export AMAURA_JARVIS_OLLAMA_PROBE="${AMAURA_JARVIS_OLLAMA_PROBE:-0}"
# This launcher is for the local control surface.  Full doctor runs the
# authenticated production model-evaluation pack and is intentionally a
# release gate, not a prerequisite for opening the interactive UI.
python -m jarvis.amaura.cli doctor --static

# The bootstrap is idempotent. It creates the complete recurring company
# objective portfolio only when it has not already been created.
BOOTSTRAPPED=$(python - <<'PY'
import json
import subprocess
result = subprocess.run(
    ["python", "-m", "jarvis.amaura.cli", "company", "status"],
    check=True,
    capture_output=True,
    text=True,
)
print("1" if json.loads(result.stdout).get("bootstrapped") else "0")
PY
)
if [[ "$BOOTSTRAPPED" != "1" ]]; then
  print "Creating Amaura's governed company objective portfolio..."
  python -m jarvis.amaura.cli company bootstrap --repository "$PWD" >/dev/null
fi

mkdir -p .amaura-data/logs
SERVER_LOG=".amaura-data/logs/server.log"
python -m jarvis.server >>"$SERVER_LOG" 2>&1 &
SERVER_PID=$!

cleanup() {
  if kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

read HOST PORT < <(python - <<'PY'
from jarvis.amaura.runtime import load_amaura_env
load_amaura_env(require_private_permissions=True)
import os
print(
    os.environ.get("JARVIS_HOST", "127.0.0.1"),
    os.environ.get("JARVIS_PORT", "8000"),
)
PY
)

HEALTH_URL="http://${HOST}:${PORT}/api/health"
for _ in {1..40}; do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    print "Amaura control surface: http://${HOST}:${PORT}"
    print "Server log: $SERVER_LOG"
    print "The server owns MissionRunner, proactive cognition, and Company Autopilot."
    print "Press Control-C to stop the single runtime."
    wait "$SERVER_PID"
    exit $?
  fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    print -u2 "Amaura server failed to start. Last log lines:"
    tail -40 "$SERVER_LOG" >&2 || true
    exit 1
  fi
  sleep 0.25
done

print -u2 "Amaura server did not become healthy at $HEALTH_URL"
tail -40 "$SERVER_LOG" >&2 || true
exit 1
