#!/usr/bin/env python3
"""Bind ARCH Truth v2 to one exact clean v7 commit.

This target-Mac wrapper refuses a moved or dirty tracked checkout, hashes the
strict v2 benchmark before and after, runs it through the normal JARVIS front
door, validates the emitted v2 evidence, and writes an exact-SHA binding.

An automated v2 PASS is provisional until raw evidence is independently audited.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = REPO_ROOT / "scripts" / "arch_truth_benchmark_v2.py"
_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git command failed").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout.strip()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_exact_candidate(expected_sha: str) -> str:
    expected = expected_sha.strip().lower()
    if not _SHA_PATTERN.fullmatch(expected):
        raise RuntimeError("--expected-sha must be a full 40-character lowercase Git commit SHA")
    head = _git("rev-parse", "HEAD").lower()
    if head != expected:
        raise RuntimeError(f"ARCH Truth candidate mismatch: expected {expected}, checkout is {head}")
    tracked = _git("status", "--porcelain", "--untracked-files=no")
    if tracked:
        raise RuntimeError("ARCH Truth qualification requires a clean tracked worktree")
    if not BENCHMARK.is_file():
        raise RuntimeError(f"ARCH Truth v2 benchmark is missing: {BENCHMARK}")
    return head


def _benchmark_runs() -> set[Path]:
    root = REPO_ROOT / "qualification_evidence"
    if not root.exists():
        return set()
    return {path.resolve() for path in root.glob("*_ARCH_TRUTH_V2_BENCHMARK") if path.is_dir()}


def _read_results(evidence_dir: Path) -> dict[str, Any]:
    target = evidence_dir / "TRUTH_V2_RESULTS.json"
    if not target.is_file():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_binding(evidence_dir: Path, payload: dict[str, Any]) -> Path:
    target = evidence_dir / "V7_EXACT_SHA_BINDING.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run ARCH Truth v2 against one exact clean v7 candidate")
    parser.add_argument("--expected-sha", required=True, help="Full candidate SHA recorded in PR #6")
    args = parser.parse_args(argv)

    head_before = _assert_exact_candidate(args.expected_sha)
    benchmark_sha_before = _file_sha256(BENCHMARK)
    before_runs = _benchmark_runs()
    environment = os.environ.copy()
    environment["AMAURA_V7_QUALIFIED_SHA"] = head_before
    environment["AMAURA_ARCH_TRUTH_VERSION"] = "2"

    result = subprocess.run(
        [sys.executable, str(BENCHMARK)],
        cwd=REPO_ROOT,
        env=environment,
        check=False,
    )

    head_after = _git("rev-parse", "HEAD").lower()
    tracked_after = _git("status", "--porcelain", "--untracked-files=no")
    benchmark_sha_after = _file_sha256(BENCHMARK)
    exact_candidate_unchanged = head_after == head_before and not tracked_after
    benchmark_unchanged = benchmark_sha_after == benchmark_sha_before

    created = _benchmark_runs() - before_runs
    evidence_dir = max(created, key=lambda path: path.stat().st_mtime) if created else None
    results = _read_results(evidence_dir) if evidence_dir is not None else {}
    benchmark_version = results.get("benchmark_version")
    benchmark_version_ok = benchmark_version == 2
    automated_gate_pass = bool(results.get("automated_gate_pass"))

    binding = {
        "expected_sha": args.expected_sha.strip().lower(),
        "head_before": head_before,
        "head_after": head_after,
        "tracked_worktree_clean_after": not bool(tracked_after),
        "exact_candidate_unchanged": exact_candidate_unchanged,
        "benchmark_path": str(BENCHMARK.relative_to(REPO_ROOT)),
        "benchmark_sha256_before": benchmark_sha_before,
        "benchmark_sha256_after": benchmark_sha_after,
        "benchmark_unchanged": benchmark_unchanged,
        "benchmark_version": benchmark_version,
        "benchmark_version_ok": benchmark_version_ok,
        "benchmark_exit_code": result.returncode,
        "benchmark_score": results.get("score", ""),
        "v9_counts": results.get("v9_counts", {}),
        "v9_benchmark_sha256_before": results.get("v9_benchmark_sha256_before", ""),
        "v9_benchmark_sha256_after": results.get("v9_benchmark_sha256_after", ""),
        "v9_benchmark_unchanged": results.get("v9_benchmark_unchanged", False),
        "automated_gate_pass": automated_gate_pass,
        "evidence_audit_required": True,
        "evidence_audit_status": results.get("evidence_audit_status", "PENDING"),
        "release_qualified": False,
        "release_qualification_note": "Raw ARCH Truth v2 evidence must be independently audited before release qualification.",
    }
    if evidence_dir is not None:
        path = _write_binding(evidence_dir, binding)
        print(f"Exact-SHA binding: {path}")
        print(f"Evidence audit checklist: {evidence_dir / 'EVIDENCE_AUDIT_CHECKLIST.md'}")
    else:
        print("WARNING: ARCH Truth v2 evidence directory was not discovered; exact-SHA binding file was not written")

    if not exact_candidate_unchanged:
        print("ERROR: candidate HEAD or tracked worktree changed during ARCH Truth v2 qualification", file=sys.stderr)
        return 3
    if not benchmark_unchanged:
        print("ERROR: ARCH Truth v2 benchmark changed during qualification", file=sys.stderr)
        return 4
    if not benchmark_version_ok:
        print("ERROR: ARCH Truth evidence is not benchmark_version=2", file=sys.stderr)
        return 5
    if result.returncode != 0 or not automated_gate_pass:
        return int(result.returncode or 1)

    print("AUTOMATED ARCH Truth v2 gate passed. This is provisional until raw evidence audit is complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
