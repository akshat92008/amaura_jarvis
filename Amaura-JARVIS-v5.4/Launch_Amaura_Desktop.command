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
cd desktop-app
exec npm start
