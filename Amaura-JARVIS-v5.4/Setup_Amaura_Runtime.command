#!/bin/zsh
set -euo pipefail
cd "${0:A:h}"

if [[ ! -x .venv/bin/python ]]; then
  print -u2 "Run ./Install_Amaura.command first so the Python environment exists."
  exit 1
fi
if [[ ! -f .env.amaura ]]; then
  .venv/bin/python -m jarvis.amaura.cli init
fi
chmod 600 .env.amaura

print "Configuring hosted-only production runtime…"
.venv/bin/python scripts/bootstrap_hosted_production.py

# Docker is not required on the target Mac when the native sandbox verifier is
# available. The production profile uses verifier=auto and sandbox=auto so we
# avoid wasting RAM/disk on a Docker image unless the platform actually needs it.
if [[ "$(uname -s)" != "Darwin" ]]; then
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    .venv/bin/python -m jarvis.amaura.cli build-sandbox
  else
    print -u2 "A non-macOS production host requires a healthy Docker verifier."
    exit 1
  fi
fi

print "Running live production doctor…"
.venv/bin/python -m jarvis.amaura.cli doctor

print "Bootstrapping company objective portfolio…"
.venv/bin/python -m jarvis.amaura.cli company bootstrap --repository "$PWD" >/dev/null

print "Amaura hosted production runtime and company objective portfolio are ready."
