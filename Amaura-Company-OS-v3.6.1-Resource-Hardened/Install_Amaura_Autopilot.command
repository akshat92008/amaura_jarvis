#!/bin/zsh
set -euo pipefail
cd "${0:A:h}"

if [[ ! -x .venv/bin/python ]]; then
  print -u2 "Run ./Install_Amaura.command before installing the background service."
  exit 1
fi
if [[ ! -f .env.amaura ]]; then
  print -u2 "Amaura is not initialised. Run ./Install_Amaura.command first."
  exit 1
fi

chmod 600 .env.amaura
.venv/bin/python -m jarvis.amaura.cli doctor
.venv/bin/python -m jarvis.amaura.cli company bootstrap --repository "$PWD" >/dev/null

LABEL="com.amaura.company-os"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="$PWD/.amaura-data/logs"
mkdir -p "${PLIST:h}" "$LOG_DIR"

.venv/bin/python -m jarvis.amaura.macos_service --repository "$PWD" --destination "$PLIST" --label "$LABEL"

launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

print "Amaura Company OS background autopilot installed."
print "Status: launchctl print gui/$(id -u)/$LABEL"
print "Logs: $LOG_DIR"
print "Remove it with: ./Uninstall_Amaura_Autopilot.command"
