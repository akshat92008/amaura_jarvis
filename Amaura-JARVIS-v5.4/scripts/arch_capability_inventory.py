#!/usr/bin/env python3
"""Build a truthful capability-certification inventory for ARCH.

This script deliberately distinguishes three different claims:
- implemented: the capability is present in the published registry;
- automated_test_reference: maintained tests exercise/reference the capability;
- real_e2e_certified: exact-SHA evidence proves the capability through ARCH's
  normal founder-facing front door on the target machine.

A tool is NEVER promoted to real_e2e_certified merely because code/tests exist.
Real evidence files must explicitly contain:
    {"capability":"<tool>", "status":"PASS", "front_door":"arch",
     "candidate_sha":"<current 40-char sha>"}
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [Path.cwd(), *here.parents]:
        if (candidate / "jarvis").is_dir() and (candidate / "tests").is_dir():
            return candidate.resolve()
    raise RuntimeError("Could not locate ARCH repository root")


ROOT = repo_root()
sys.path.insert(0, str(ROOT))

from jarvis.tools.registry import ALL_TOOL_DEFINITIONS, get_tool_count  # noqa: E402


def current_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip()


def test_corpus() -> str:
    chunks: list[str] = []
    for path in sorted((ROOT / "tests").rglob("test_*.py")):
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="strict"))
        except OSError:
            continue
    return "\n".join(chunks)


def _walk_json(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk_json(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_json(item)


def real_e2e_evidence(capability: str, sha: str) -> list[str]:
    evidence_root = ROOT / "qualification_evidence"
    if not evidence_root.is_dir() or len(sha) != 40:
        return []
    matches: list[str] = []
    for path in evidence_root.rglob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        for row in _walk_json(payload):
            if (
                str(row.get("capability") or "") == capability
                and str(row.get("status") or "").upper() == "PASS"
                and str(row.get("front_door") or "").lower() == "arch"
                and str(row.get("candidate_sha") or "") == sha
            ):
                matches.append(str(path.relative_to(ROOT)))
                break
    return sorted(set(matches))


def build_inventory() -> dict[str, Any]:
    sha = current_sha()
    corpus = test_corpus()
    names = [str(item.get("function", {}).get("name") or "") for item in ALL_TOOL_DEFINITIONS]
    names = sorted(name for name in names if name)
    rows: list[dict[str, Any]] = []
    for name in names:
        evidence = real_e2e_evidence(name, sha)
        rows.append(
            {
                "capability": name,
                "implemented": True,
                "automated_test_reference": name in corpus,
                "real_e2e_certified": bool(evidence),
                "real_e2e_evidence": evidence,
            }
        )
    return {
        "candidate_sha": sha,
        "front_door_required": "arch",
        "registry_counts": get_tool_count(),
        "summary": {
            "implemented": len(rows),
            "automated_test_reference": sum(1 for row in rows if row["automated_test_reference"]),
            "real_e2e_certified": sum(1 for row in rows if row["real_e2e_certified"]),
            "real_e2e_remaining": sum(1 for row in rows if not row["real_e2e_certified"]),
        },
        "capabilities": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inventory ARCH capability certification truthfully")
    parser.add_argument("--output", default="", help="Optional JSON output path")
    parser.add_argument("--require-real-e2e", action="store_true", help="Fail unless every capability has exact-SHA ARCH evidence")
    args = parser.parse_args(argv)

    payload = build_inventory()
    text = json.dumps(payload, indent=2, sort_keys=True)
    print(text)
    if args.output:
        output = Path(args.output).expanduser()
        if not output.is_absolute():
            output = ROOT / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")

    if args.require_real_e2e and payload["summary"]["real_e2e_remaining"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
