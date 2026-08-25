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

# After the migration, make the private env file the single configuration
# boundary. Stale exports from an older Nova/OmniRoute setup must not override
# the persisted production profile during doctor/bootstrap.
unset AMAURA_MODEL_PROVIDER AMAURA_MODEL_MODE AMAURA_LOCAL_MODEL AMAURA_LOCAL_REVIEW_MODEL
unset AMAURA_CLOUD_WORKER_MODEL AMAURA_CLOUD_REVIEW_MODEL AMAURA_REVIEW_MODE
unset AMAURA_JARVIS_PROVIDER AMAURA_JARVIS_MODEL AMAURA_NVIDIA_MODEL
unset AMAURA_OMNIROUTE_API_KEY AMAURA_OMNIROUTE_BASE_URL AMAURA_OMNIROUTE_MODEL
unset AMAURA_OMNIROUTE_REVIEW_MODEL AMAURA_OMNIROUTE_FALLBACK_MODEL
unset OMNIROUTE_API_KEY OMNIROUTE_BASE_URL OMNIROUTE_MODEL
unset NVIDIA_API_KEY NVIDIA_REVIEW_API_KEY NVIDIA_WORKER_API_KEY

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
