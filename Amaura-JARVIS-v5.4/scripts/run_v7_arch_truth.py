#!/usr/bin/env python3
"""Bind the independent ARCH Truth benchmark to one exact clean v7 commit.

This wrapper is intentionally not part of Ubuntu CI qualification. It is for the
real target-machine gate, where the normal JARVIS front door, OS permissions and
provider configuration can be exercised. It refuses to qualify a moved or dirty
tracked checkout and writes the exact SHA binding into the benchmark evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
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
    return head


def _benchmark_runs() -> set[Path]:
    root = REPO_ROOT / "qualification_evidence"
    if not root.exists():
        return set()
    return {path.resolve() for path in root.glob("*_ARCH_TRUTH_BENCHMARK") if path.is_dir()}


def _write_binding(evidence_dir: Path, payload: dict[str, Any]) -> Path:
    target = evidence_dir / "V7_EXACT_SHA_BINDING.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run ARCH Truth against one exact clean v7 candidate")
    parser.add_argument("--expected-sha", required=True, help="Full candidate SHA recorded in PR #6")
    args = parser.parse_args(argv)

    head_before = _assert_exact_candidate(args.expected_sha)
    before_runs = _benchmark_runs()
    environment = os.environ.copy()
    environment["AMAURA_V7_QUALIFIED_SHA"] = head_before

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "arch_truth_benchmark.py")],
        cwd=REPO_ROOT,
        env=environment,
        check=False,
    )

    head_after = _git("rev-parse", "HEAD").lower()
    tracked_after = _git("status", "--porcelain", "--untracked-files=no")
    exact_candidate_unchanged = head_after == head_before and not tracked_after

    created = _benchmark_runs() - before_runs
    evidence_dir = max(created, key=lambda path: path.stat().st_mtime) if created else None
    binding = {
        "expected_sha": args.expected_sha.strip().lower(),
        "head_before": head_before,
        "head_after": head_after,
        "tracked_worktree_clean_after": not bool(tracked_after),
        "exact_candidate_unchanged": exact_candidate_unchanged,
        "benchmark_exit_code": result.returncode,
    }
    if evidence_dir is not None:
        path = _write_binding(evidence_dir, binding)
        print(f"Exact-SHA binding: {path}")
    else:
        print("WARNING: ARCH Truth evidence directory was not discovered; exact-SHA binding file was not written")

    if not exact_candidate_unchanged:
        print("ERROR: candidate HEAD or tracked worktree changed during ARCH Truth qualification", file=sys.stderr)
        return 3
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
