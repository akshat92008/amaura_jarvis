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

read MODELS < <(.venv/bin/python - <<'PY'
import os
from jarvis.amaura.runtime import load_amaura_env
load_amaura_env('.env.amaura', require_private_permissions=True)
print(
    os.environ.get('AMAURA_REVIEW_MODE', 'local'),
    os.environ.get('AMAURA_LOCAL_MODEL', 'nova:3b'),
    os.environ.get('AMAURA_LOCAL_REVIEW_MODEL', 'qwen2.5-coder:3b'),
)
PY
)
REVIEW_MODE="${MODELS%% *}"
REMAINDER="${MODELS#* }"
WORKER_MODEL="${REMAINDER%% *}"
REVIEWER_MODEL="${REMAINDER#* }"

if ! command -v ollama >/dev/null 2>&1; then
  print -u2 "Ollama is required. Install it with: brew install ollama"
  exit 1
fi

if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  if [[ "$(uname -s)" == "Darwin" ]] && [[ -d /Applications/Ollama.app ]]; then
    open -a Ollama
  else
    nohup ollama serve >.amaura-data/ollama.log 2>&1 &
  fi
  for _ in {1..60}; do
    curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
    sleep 1
  done
fi
if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  print -u2 "Ollama is installed but its local server is not reachable. Open Ollama and rerun this file."
  exit 1
fi

if [[ "$REVIEW_MODE" == "local" ]]; then
  if ! ollama list | awk 'NR>1 {print $1}' | grep -Fxq "$REVIEWER_MODEL"; then
    print "Installing independent reviewer model: $REVIEWER_MODEL"
    ollama pull "$REVIEWER_MODEL"
  fi
fi
if ! ollama list | awk 'NR>1 {print $1}' | grep -Fxq "$WORKER_MODEL"; then
  print "Worker model '$WORKER_MODEL' is not installed. Attempting Ollama pull."
  if ! ollama pull "$WORKER_MODEL"; then
    print -u2 "The custom worker model '$WORKER_MODEL' must be created/imported in Ollama before Amaura can launch."
    exit 1
  fi
fi
if [[ "$REVIEW_MODE" == "local" ]] && [[ "$WORKER_MODEL" == "$REVIEWER_MODEL" ]]; then
  print -u2 "Worker and reviewer models must be different. Edit .env.amaura and rerun."
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  print -u2 "Docker Desktop is required. Install it with: brew install --cask docker"
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  if [[ "$(uname -s)" == "Darwin" ]] && [[ -d /Applications/Docker.app ]]; then
    open -a Docker
    for _ in {1..90}; do
      docker info >/dev/null 2>&1 && break
      sleep 1
    done
  fi
fi
if ! docker info >/dev/null 2>&1; then
  print -u2 "Docker is installed but the daemon is not running. Open Docker Desktop and rerun this file."
  exit 1
fi

.venv/bin/python -m jarvis.amaura.cli build-sandbox
.venv/bin/python -m jarvis.amaura.cli doctor
.venv/bin/python -m jarvis.amaura.cli company bootstrap --repository "$PWD" >/dev/null
print "Amaura local runtime and company objective portfolio are certified."
