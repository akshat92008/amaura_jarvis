#!/bin/bash
# ─────────────────────────────────────────────────────────────────────
#  J.A.R.V.I.S. — Just A Rather Very Intelligent System
#  Launch script for macOS
# ─────────────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# ── Create virtual environment if it doesn't exist ───────────────────
if [ ! -d "$VENV_DIR" ]; then
    echo "⚡ Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    source "$VENV_DIR/bin/activate"
    echo "📦 Installing dependencies..."
    pip install --upgrade pip -q
    pip install -r "$SCRIPT_DIR/requirements.txt" -q
    echo "✅ Setup complete."
else
    source "$VENV_DIR/bin/activate"
fi

# ── Load environment variables ───────────────────────────────────────
if [ -f "$SCRIPT_DIR/.env" ]; then
    export $(grep -v '^#' "$SCRIPT_DIR/.env" | xargs)
fi

# ── Launch Jarvis ────────────────────────────────────────────────────
cd "$SCRIPT_DIR"

if [ "$1" = "web" ] || [ "$1" = "hud" ]; then
    shift
    python -m jarvis --web "$@"
else
    python -m jarvis --no-web "$@"
fi

