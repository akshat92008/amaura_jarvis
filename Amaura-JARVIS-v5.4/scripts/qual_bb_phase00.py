#!/usr/bin/env python3
"""Phase 0 — Build Freeze"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

from jarvis.amaura.runtime import load_amaura_env
from jarvis.tools.registry import ALL_TOOL_DEFINITIONS, get_tool_count

load_amaura_env()

EVIDENCE_DIR = Path(__file__).parent.parent / "qualification_evidence" / "20260813_blackbox"
PHASE_DIR = EVIDENCE_DIR / "phase00_freeze"
PHASE_DIR.mkdir(parents=True, exist_ok=True)
RUN_ID = "20260813_blackbox"
TS = datetime.datetime.now(datetime.UTC).isoformat()


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, **kw)
    return r.stdout.strip(), r.stderr.strip(), r.returncode


print(f"[Phase 0] Build Freeze — {TS}")
git_status, _, _ = run(["git", "status", "--porcelain"])
git_head, _, _ = run(["git", "rev-parse", "HEAD"])
git_tree, _, _ = run(["git", "rev-parse", "HEAD^{tree}"])
git_log, _, _ = run(["git", "log", "-3", "--oneline"])
py_version = sys.version
uname_out, _, _ = run(["uname", "-a"])

venv_python = Path(__file__).parent.parent / ".venv" / "bin" / "python"
if venv_python.exists():
    pip_out, _, _ = run([str(venv_python), "-m", "pip", "list", "--format=json"])
    try:
        packages = json.loads(pip_out)
    except Exception:
        packages = []
else:
    packages = []

tracked = [
    "JARVIS",
    "AMAURA",
    "OMNIROUTE",
    "NVIDIA",
    "OPENAI",
    "ANTHROPIC",
    "TELEGRAM",
    "SMTP",
    "COMFY",
    "SEARX",
    "WHATSAPP",
    "GOOGLE_CLIENT",
    "GROQ",
    "OPENROUTER",
]
env_audit = {k: ("SET" if v else "EMPTY") for k, v in os.environ.items() if any(p in k.upper() for p in tracked)}

try:
    import httpx

    resp = httpx.get("http://127.0.0.1:20128/v1/models", timeout=5)
    omniroute_status = resp.status_code
    omniroute_models = len(resp.json().get("data", []))
except Exception as e:
    omniroute_status = -1
    omniroute_models = 0
    print(f"  OmniRoute error: {e}")

binaries = {}
for b in ["agy", "playwright", "ffmpeg", "ffprobe", "python3", "git", "node"]:
    out, _, rc = run(["which", b])
    binaries[b] = out if rc == 0 else "NOT_FOUND"

tool_counts = get_tool_count()
tool_names = [d["function"]["name"] for d in ALL_TOOL_DEFINITIONS]

agy_ver, _, _ = run(["agy", "--version"])

freeze = {
    "run_id": RUN_ID,
    "timestamp": TS,
    "git": {
        "head": git_head,
        "tree": git_tree,
        "status_lines": len(git_status.splitlines()),
        "status": git_status,
        "recent_log": git_log,
    },
    "python_version": py_version,
    "platform": uname_out,
    "packages_count": len(packages),
    "packages": packages,
    "environment_variables": env_audit,
    "omniroute": {"url": "http://127.0.0.1:20128", "status": omniroute_status, "model_count": omniroute_models},
    "binaries": binaries,
    "agy_version": agy_ver,
    "tool_registry": {"counts_by_category": tool_counts, "total": tool_counts.get("total", 0), "all_names": tool_names},
}
(PHASE_DIR / "build_freeze.json").write_text(json.dumps(freeze, indent=2))
(PHASE_DIR / "git_status.txt").write_text(git_status)
print(f"[Phase 0] COMPLETE — tools={tool_counts.get('total')}, omniroute_models={omniroute_models}")
print(f"  Evidence: {PHASE_DIR}")
