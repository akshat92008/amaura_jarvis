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

print "Configuring final OmniRoute production runtime…"
.venv/bin/python scripts/bootstrap_hosted_production.py

# The private file is the single runtime configuration boundary. Remove stale
# shell exports from previous Nova/direct-provider experiments so readiness,
# launchd and ARCH consume exactly the persisted production profile.
unset AMAURA_MODEL_PROVIDER AMAURA_MODEL_MODE AMAURA_LOCAL_MODEL AMAURA_LOCAL_REVIEW_MODEL
unset AMAURA_CLOUD_WORKER_MODEL AMAURA_CLOUD_REVIEW_MODEL AMAURA_REVIEW_MODE
unset AMAURA_JARVIS_PROVIDER AMAURA_JARVIS_MODEL AMAURA_NVIDIA_MODEL
unset AMAURA_OMNIROUTE_API_KEY AMAURA_OMNIROUTE_BASE_URL AMAURA_OMNIROUTE_MODEL
unset AMAURA_OMNIROUTE_CHAT_MODEL AMAURA_OMNIROUTE_REVIEW_MODEL AMAURA_OMNIROUTE_FALLBACK_MODEL
unset AMAURA_OMNIROUTE_REVIEW_FALLBACK_MODEL
unset OMNIROUTE_API_KEY OMNIROUTE_BASE_URL OMNIROUTE_MODEL
unset NVIDIA_API_KEY NVIDIA_REVIEW_API_KEY NVIDIA_WORKER_API_KEY

# Docker is unnecessary on the target Mac when the native isolated verifier is
# available. Non-macOS production hosts still fail closed without Docker.
if [[ "$(uname -s)" != "Darwin" ]]; then
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    .venv/bin/python -m jarvis.amaura.cli build-sandbox
  else
    print -u2 "A non-macOS production host requires a healthy Docker verifier."
    exit 1
  fi
fi

# Validate real configuration/provider/isolation posture without running the
# full private model evaluation twice. jarvis-company-ready remains the sole
# authoritative expensive certification.
print "Running live OmniRoute production readiness preflight…"
.venv/bin/python - <<'PY'
import json
from jarvis.amaura.runtime import load_amaura_env
load_amaura_env('.env.amaura', override=True, require_private_permissions=True)
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.readiness import production_readiness
control = AmauraControlPlane()
try:
    report = production_readiness(control, live=True)
finally:
    control.close()
details = report.get('details') or {}
live = details.get('live') or {}
summary = {
    'ready': report.get('ready'),
    'blockers': report.get('blockers'),
    'live_checks': report.get('live_checks'),
    'interactive_cognition': live.get('interactive_cognition'),
    'reviewer_route': details.get('reviewer_route'),
    'antigravity_ready': (details.get('antigravity_governed_backend') or {}).get('ready'),
}
print(json.dumps(summary, indent=2, sort_keys=True))
if not report.get('ready'):
    raise SystemExit('Live production readiness preflight failed; resolve the blockers above before deployment.')
PY

print "Bootstrapping governed company objective portfolio…"
.venv/bin/python -m jarvis.amaura.cli company bootstrap --repository "$PWD" >/dev/null

print "Amaura OmniRoute runtime and company portfolio are ready for final company certification."
print "Next: .venv/bin/python -m jarvis.amaura.deployment_gate"
