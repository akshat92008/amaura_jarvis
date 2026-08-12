#!/bin/zsh
set -euo pipefail
cd "${0:A:h}"
if [[ ! -x .venv/bin/python ]]; then
  print -u2 "Amaura core is not installed. Run ./Install_Amaura.command first."
  exit 1
fi
if [[ ! -f .env.amaura ]]; then
  print -u2 "Amaura is not initialised. Run: .venv/bin/python -m jarvis.amaura.cli init"
  exit 1
fi
if [[ ! -d desktop-app/node_modules/electron ]]; then
  print -u2 "Desktop dependencies are missing. Run ./Install_Amaura_Desktop.command first."
  exit 1
fi
chmod 600 .env.amaura
export AMAURA_RESOURCE_PROFILE="${AMAURA_RESOURCE_PROFILE:-macbook-8gb}"
export AMAURA_JARVIS_PROACTIVE="${AMAURA_JARVIS_PROACTIVE:-0}"
export AMAURA_JARVIS_MISSION_RUNNER="${AMAURA_JARVIS_MISSION_RUNNER:-1}"
export AMAURA_JARVIS_MISSION_POLL_SECONDS="${AMAURA_JARVIS_MISSION_POLL_SECONDS:-3}"
export AMAURA_JARVIS_MISSION_MAX_GOALS="${AMAURA_JARVIS_MISSION_MAX_GOALS:-1}"
export AMAURA_COMPANY_AUTOPILOT_RUNTIME="${AMAURA_COMPANY_AUTOPILOT_RUNTIME:-0}"
export AMAURA_JARVIS_OLLAMA_PROBE="${AMAURA_JARVIS_OLLAMA_PROBE:-0}"
cd desktop-app
exec npm start
