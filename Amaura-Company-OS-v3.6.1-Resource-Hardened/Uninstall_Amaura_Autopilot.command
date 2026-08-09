#!/bin/zsh
set -euo pipefail
LABEL="com.amaura.company-os"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
rm -f "$PLIST"
print "Amaura Company OS background autopilot removed."
