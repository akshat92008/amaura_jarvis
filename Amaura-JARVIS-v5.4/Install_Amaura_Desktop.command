#!/bin/zsh
set -euo pipefail
cd "${0:A:h}"

if [[ ! -x .venv/bin/python ]]; then
  print "Installing Amaura core first..."
  ./Install_Amaura.command
fi
if ! command -v npm >/dev/null 2>&1; then
  print -u2 "Node.js/npm is required for the Amaura desktop app. Install Node.js, then rerun this file."
  exit 1
fi
cd desktop-app
ELECTRON_VERSION="${AMAURA_ELECTRON_VERSION:-31.0.0}"
npm install --no-save --no-package-lock "electron@${ELECTRON_VERSION}"
print "\nAmaura JARVIS Desktop installed."
print "Launch with: ./Launch_Amaura_Desktop.command"
