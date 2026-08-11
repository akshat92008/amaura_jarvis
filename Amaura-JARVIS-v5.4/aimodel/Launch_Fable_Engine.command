#!/usr/bin/env bash
# 1-Click Mac Launcher for Claude Fable 5 Autonomous AI Engine

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=================================================================="
echo "🚀 Launching Claude Fable 5 Autonomous AI Engineering Engine"
echo "=================================================================="
echo "MacBook M3 Hardware Mode: Lightweight Orchestrator (< 150 MB RAM)"
echo "Cloud Reasoning Tier: GCP Vertex AI / Groq API / Cerebras"
echo "Web Dashboard URL: http://localhost:8085"
echo "=================================================================="

# Open default browser after 1.5 seconds
(sleep 1.5 && open "http://localhost:8085") &

# Run server
python3 server.py
