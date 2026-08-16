#!/usr/bin/env python3
"""Safe local capability qualification runner for the current Amaura checkout."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = os.environ.get("AMAURA_QUAL_RUN_ID") or datetime.now().strftime("%Y%m%d_%H%M%S")
EVIDENCE_DIR = ROOT / "qualification_evidence" / RUN_ID / "full_capability_audit"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_text(rel: str, content: str) -> Path:
    path = EVIDENCE_DIR / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def write_json(rel: str, value: Any) -> Path:
    return write_text(rel, json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")


def run_command(command: list[str], *, timeout: int = 60, env: dict[str, str] | None = None) -> dict[str, Any]:
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return {
        "command": command,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "exit_code": completed.returncode,
        "duration_seconds": round(time.monotonic() - started, 4),
    }


def evidence_record(evidence_id: str, capability: str, status: str, **fields: Any) -> dict[str, Any]:
    record = {
        "evidence_id": evidence_id,
        "capability": capability,
        "status": status,
        "created_at": datetime.now(UTC).isoformat(),
        **fields,
    }
    write_json(f"evidence/{evidence_id}.json", record)
    return record


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def binary_available(name: str) -> bool:
    return shutil.which(name) is not None


def main() -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    matrix: list[dict[str, Any]] = []

    source = {
        "VERSION": run_command([sys.executable, "-c", "import importlib.metadata as m; print(m.version('jarvis'))"]),
        "GIT_COMMIT": run_command(["git", "rev-parse", "HEAD"]),
        "GIT_TREE": run_command(["git", "rev-parse", "HEAD^{tree}"]),
        "GIT_CLEAN": run_command(["git", "status", "--porcelain"]),
        "PYTHON": sys.executable,
        "PLATFORM": platform.platform(),
    }
    write_json("source_identity.json", source)

    from jarvis.amaura.capabilities import EXECUTABLE_EMPLOYEE_TOOLS
    from jarvis.amaura.registry import V1_AGENTS
    from jarvis.amaura.workflows import WORKFLOWS
    from jarvis.tools.registry import ALL_DISPATCH, ALL_TOOL_DEFINITIONS, execute_tool, get_tool_count

    counts = {
        "REGISTERED_TOOLS": len(ALL_TOOL_DEFINITIONS),
        "CAPABILITY_ADAPTERS": len(EXECUTABLE_EMPLOYEE_TOOLS),
        "AGENTS": len(V1_AGENTS),
        "WORKFLOWS": len(WORKFLOWS),
        "tool_categories": get_tool_count(),
    }
    write_json("counts.json", counts)

    def add(capability: str, status: str, evidence_id: str, **fields: Any) -> None:
        evidence_record(evidence_id, capability, status, **fields)
        matrix.append(
            {
                "capability": capability,
                "status": status,
                "evidence_id": evidence_id,
                "summary": fields.get("summary", ""),
            }
        )

    # Core CLI and local commands.
    cli_help = run_command([sys.executable, "-m", "jarvis.cli", "--help"])
    add(
        "JARVIS CLI help entrypoint",
        "PASS_REAL_E2E" if cli_help["exit_code"] == 0 else "FAIL",
        "E-CLI-001",
        request="python -m jarvis.cli --help",
        entrypoint="jarvis.cli",
        execution=cli_help,
        summary="CLI entrypoint responds locally.",
    )

    amaura_status = run_command([sys.executable, "-m", "jarvis.amaura.cli", "status"], timeout=90)
    add(
        "Amaura status command",
        "PASS_REAL_E2E" if amaura_status["exit_code"] == 0 else "FAIL",
        "E-AMA-STATUS-001",
        request="amaura status",
        entrypoint="jarvis.amaura.cli",
        execution=amaura_status,
        summary="Control-plane status executed through CLI.",
    )

    pytest_result = run_command([sys.executable, "-m", "pytest", "-q"], timeout=600)
    write_text("raw/pytest_stdout.txt", pytest_result["stdout"])
    write_text("raw/pytest_stderr.txt", pytest_result["stderr"])
    add(
        "Repository pytest suite",
        "PASS_UNIT_ONLY" if pytest_result["exit_code"] == 0 else "FAIL",
        "E-PYTEST-001",
        request="python -m pytest -q",
        execution={**pytest_result, "stdout_path": "raw/pytest_stdout.txt", "stderr_path": "raw/pytest_stderr.txt"},
        summary="Full checked-in pytest suite.",
    )

    # Safe tool execution samples through the actual registry dispatch.
    safe_tool_args: dict[str, dict[str, Any]] = {
        "get_project_structure": {"path": str(ROOT), "max_depth": 1},
        "find_files": {"pattern": "*.py", "directory": str(ROOT / "jarvis")},
        "search_code": {"pattern": "def ", "directory": str(ROOT / "jarvis"), "file_pattern": "*.py"},
        "read_file": {"path": str(ROOT / "README.md")},
        "git_diff": {},
        "amaura_company_status": {},
        "amaura_company_blueprint": {},
        "amaura_capability_health": {},
        "amaura_resource_inventory": {},
        "amaura_daily_briefing": {},
        "amaura_supervisor_status": {},
    }
    for index, (name, args) in enumerate(safe_tool_args.items(), start=1):
        started = time.monotonic()
        raw = execute_tool(name, args)
        parsed = json.loads(raw)
        status = "PASS_CONTROLLED_FIXTURE" if parsed.get("ok") is True else "FAIL"
        add(
            f"tool:{name}",
            status,
            f"E-TOOL-{index:03d}",
            request={"tool": name, "args": args},
            entrypoint="jarvis.tools.registry.execute_tool",
            execution={"raw_result": parsed, "duration_seconds": round(time.monotonic() - started, 4)},
            independent_verification="ToolResult JSON parsed and ok field inspected.",
            summary=f"{name} dispatched via registry.",
        )

    # Agents and workflows are configuration contracts unless a workflow is actually executed.
    for agent in V1_AGENTS:
        missing_tools = sorted(set(agent.tools) - set(ALL_DISPATCH))
        status = "CONFIG_ONLY" if not missing_tools else "FAIL"
        add(
            f"agent:{agent.agent_id}",
            status,
            f"E-AGENT-{agent.agent_id}",
            entrypoint="jarvis.amaura.registry.V1_AGENTS",
            routing={"agent": agent.agent_id, "tools": agent.tools},
            independent_verification={"missing_tools": missing_tools},
            summary="Agent profile contract inspected; no live delegation performed.",
        )

    for key, workflow in WORKFLOWS.items():
        missing_agents = sorted({step.owner_id for step in workflow.steps} - {agent.agent_id for agent in V1_AGENTS})
        status = "CONFIG_ONLY" if not missing_agents else "FAIL"
        add(
            f"workflow:{key}",
            status,
            f"E-WORKFLOW-{key}",
            entrypoint="jarvis.amaura.workflows.WORKFLOWS",
            routing={"steps": [step.key for step in workflow.steps]},
            independent_verification={"missing_agents": missing_agents},
            summary="Workflow template inspected; no live external workflow executed.",
        )

    # Priority optional integrations and local dependencies.
    priority = {
        "Crawl4AI": ("module", "crawl4ai"),
        "Browser Use": ("module", "browser_use"),
        "SearXNG": ("env", "SEARXNG_URL"),
        "Docling": ("module", "docling"),
        "PaddleOCR": ("module", "paddleocr"),
        "LlamaIndex": ("module", "llama_index"),
        "FFmpeg": ("binary", "ffmpeg"),
        "Remotion": ("binary", "npx"),
        "faster-whisper": ("module", "faster_whisper"),
        "Kokoro": ("module", "kokoro"),
        "ComfyUI": ("env", "COMFYUI_URL"),
        "Langfuse": ("module", "langfuse"),
        "MCP": ("module", "mcp"),
        "yt-dlp": ("binary", "yt-dlp"),
        "voice hardware": ("module", "speech_recognition"),
        "vision/camera hardware": ("module", "cv2"),
        "email": ("env", "AMAURA_GMAIL_ACCESS_TOKEN"),
        "Telegram": ("env", "TELEGRAM_BOT_TOKEN"),
        "WhatsApp/webhooks": ("env", "AMAURA_N8N_WEBHOOK_URL"),
        "CRM": ("code", "jarvis/amaura/company.py"),
        "n8n": ("env", "AMAURA_N8N_BASE_URL"),
    }
    for index, (name, (kind, requirement)) in enumerate(priority.items(), start=1):
        ok = (
            module_available(requirement)
            if kind == "module"
            else binary_available(requirement)
            if kind == "binary"
            else bool(os.environ.get(requirement))
            if kind == "env"
            else (ROOT / requirement).exists()
        )
        status = "CONFIG_ONLY" if ok and kind in {"module", "binary", "code"} else "NOT_CONFIGURED"
        if name == "FFmpeg" and ok:
            probe = run_command(["ffmpeg", "-version"], timeout=20)
            status = "PASS_REAL_E2E" if probe["exit_code"] == 0 else "FAIL"
        add(
            f"priority:{name}",
            status,
            f"E-PRIORITY-{index:03d}",
            dependency_requirement={"kind": kind, "value": requirement},
            current_runtime_configuration="present" if ok else "missing",
            configuration_classification="CAN_CONFIGURE_SAFELY_NOW" if ok else "CANNOT_CONFIGURE_WITHOUT_USER_ACTION",
            summary=f"{name} investigated for supported local availability.",
        )

    write_json("CAPABILITY_MATRIX.json", matrix)
    lines = [
        "# Capability Matrix",
        "",
        f"Run ID: `{RUN_ID}`",
        "",
        "| Capability | Status | Evidence | Summary |",
        "|---|---|---|---|",
    ]
    for row in matrix:
        lines.append(f"| {row['capability']} | {row['status']} | {row['evidence_id']} | {row['summary']} |")
    write_text("CAPABILITY_MATRIX.md", "\n".join(lines) + "\n")
    index_lines = ["# Evidence Index", "", f"Run ID: `{RUN_ID}`", "", json.dumps(counts, indent=2), ""]
    for row in matrix:
        index_lines.append(f"- {row['evidence_id']}: {row['capability']} => {row['status']}")
    write_text("EVIDENCE_INDEX.md", "\n".join(index_lines) + "\n")

    sums: list[str] = []
    for path in sorted(EVIDENCE_DIR.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            sums.append(f"{sha256_bytes(path.read_bytes())}  {path.relative_to(EVIDENCE_DIR)}")
    write_text("SHA256SUMS.txt", "\n".join(sums) + "\n")
    print(json.dumps({"run_id": RUN_ID, "evidence_dir": str(EVIDENCE_DIR), "capabilities": len(matrix)}, indent=2))
    return 0 if all(row["status"] != "FAIL" for row in matrix) else 1


if __name__ == "__main__":
    raise SystemExit(main())
