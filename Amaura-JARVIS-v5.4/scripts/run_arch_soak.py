#!/usr/bin/env python3
"""Target-Mac resource and unattended soak gate for the single ARCH runtime.

This monitor is intentionally read-only. It never sends, publishes, deploys,
spends, or invokes an executive task. It proves that the installed
``com.amaura.arch`` service remains singular, healthy, and bounded on the
8-GB target while ARCH's own background autonomy runs normally.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

LABEL = "com.amaura.arch"
LEGACY_MARKERS = ("jarvis.amaura.company_daemon", "amaura-company")
ARCH_MARKER = "jarvis.arch"
_PID_PATTERN = re.compile(r"(?m)^\s*pid\s*=\s*(\d+)\s*$")
_SWAP_PATTERN = re.compile(r"\bused\s*=\s*([0-9.]+)([MG])\b", re.IGNORECASE)


def find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [Path.cwd(), *here.parents]:
        if (candidate / "jarvis").is_dir() and (candidate / "pyproject.toml").is_file():
            return candidate.resolve()
    raise RuntimeError("Could not locate ARCH repo root")


ROOT = find_repo_root()


def _run(*args: str, timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), capture_output=True, text=True, check=False, timeout=timeout)


def git_sha() -> str:
    result = _run("git", "rev-parse", "HEAD")
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "git rev-parse failed").strip())
    return result.stdout.strip()


def tracked_dirty() -> bool:
    result = _run("git", "status", "--porcelain", "--untracked-files=no")
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "git status failed").strip())
    return bool(result.stdout.strip())


def launchd_pid() -> int | None:
    result = _run("launchctl", "print", f"gui/{os.getuid()}/{LABEL}")
    if result.returncode != 0:
        return None
    match = _PID_PATTERN.search("\n".join([result.stdout, result.stderr]))
    return int(match.group(1)) if match else None


def swap_used_mb() -> float | None:
    result = _run("sysctl", "vm.swapusage")
    if result.returncode != 0:
        return None
    match = _SWAP_PATTERN.search(result.stdout)
    if match is None:
        return None
    value = float(match.group(1))
    return value * 1024.0 if match.group(2).upper() == "G" else value


def process_rows() -> list[dict[str, Any]]:
    result = _run("ps", "-axo", "pid=,ppid=,rss=,command=")
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "ps failed").strip())
    rows: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(maxsplit=3)
        if len(parts) < 4:
            continue
        try:
            pid, ppid, rss_kb = (int(parts[0]), int(parts[1]), int(parts[2]))
        except ValueError:
            continue
        rows.append({"pid": pid, "ppid": ppid, "rss_kb": rss_kb, "command": parts[3]})
    return rows


def _arch_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if ARCH_MARKER in row["command"] and "run_arch_soak.py" not in row["command"]]


def _legacy_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if any(marker in row["command"] for marker in LEGACY_MARKERS)]


def _descendants(rows: list[dict[str, Any]], root_pid: int) -> list[dict[str, Any]]:
    by_parent: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        by_parent.setdefault(int(row["ppid"]), []).append(row)
    found: list[dict[str, Any]] = []
    stack = [root_pid]
    seen = {root_pid}
    while stack:
        parent = stack.pop()
        for child in by_parent.get(parent, []):
            pid = int(child["pid"])
            if pid in seen:
                continue
            seen.add(pid)
            found.append(child)
            stack.append(pid)
    return found


def health_status() -> tuple[bool, str]:
    host = os.environ.get("JARVIS_HOST", "127.0.0.1").strip() or "127.0.0.1"
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    port = int(os.environ.get("JARVIS_PORT", "8000"))
    try:
        response = httpx.get(f"http://{host}:{port}/api/health", timeout=3.0)
        return response.status_code == 200, f"http={response.status_code}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def collect_sample() -> dict[str, Any]:
    rows = process_rows()
    arches = _arch_rows(rows)
    legacy = _legacy_rows(rows)
    service_pid = launchd_pid()
    swap = swap_used_mb()
    health_ok, health_detail = health_status()

    aggregate_rss_mb = 0.0
    children: list[dict[str, Any]] = []
    if len(arches) == 1:
        children = _descendants(rows, int(arches[0]["pid"]))
        aggregate_rss_mb = (int(arches[0]["rss_kb"]) + sum(int(row["rss_kb"]) for row in children)) / 1024.0

    return {
        "ts": time.time(),
        "launchd_pid": service_pid,
        "arch_pids": [row["pid"] for row in arches],
        "arch_count": len(arches),
        "legacy_pids": [row["pid"] for row in legacy],
        "child_count": len(children),
        "aggregate_rss_mb": round(aggregate_rss_mb, 2),
        "swap_used_mb": None if swap is None else round(swap, 2),
        "health_ok": health_ok,
        "health_detail": health_detail,
    }


def sample_failures(
    sample: dict[str, Any],
    *,
    baseline_swap_mb: float | None,
    max_rss_mb: float,
    max_swap_growth_mb: float,
    max_child_count: int,
) -> list[str]:
    failures: list[str] = []
    if sample["arch_count"] != 1:
        failures.append(f"expected exactly one ARCH process, found {sample['arch_count']}")
    elif sample["launchd_pid"] != sample["arch_pids"][0]:
        failures.append(
            f"launchd pid {sample['launchd_pid']!r} does not match ARCH pid {sample['arch_pids'][0]!r}"
        )
    if sample["legacy_pids"]:
        failures.append(f"legacy split-runtime processes present: {sample['legacy_pids']}")
    if float(sample["aggregate_rss_mb"]) > max_rss_mb:
        failures.append(f"ARCH process tree RSS {sample['aggregate_rss_mb']} MB exceeds {max_rss_mb} MB")
    if int(sample["child_count"]) > max_child_count:
        failures.append(f"ARCH child count {sample['child_count']} exceeds {max_child_count}")
    current_swap = sample.get("swap_used_mb")
    if baseline_swap_mb is not None and current_swap is not None:
        growth = float(current_swap) - baseline_swap_mb
        sample["swap_growth_mb"] = round(growth, 2)
        if growth > max_swap_growth_mb:
            failures.append(f"swap grew by {growth:.2f} MB, above {max_swap_growth_mb} MB")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an exact-SHA ARCH target-Mac soak/resource gate")
    parser.add_argument("--hours", type=float, default=2.0)
    parser.add_argument("--duration-seconds", type=float, default=0.0, help="Testing override for --hours")
    parser.add_argument("--sample-seconds", type=float, default=30.0)
    parser.add_argument("--expected-sha", default="")
    parser.add_argument("--evidence-dir", default="qualification_evidence")
    parser.add_argument("--max-rss-mb", type=float, default=2048.0)
    parser.add_argument("--max-swap-growth-mb", type=float, default=192.0)
    parser.add_argument("--max-child-count", type=int, default=32)
    parser.add_argument("--allowed-health-failures", type=int, default=3)
    args = parser.parse_args(argv)

    if platform.system() != "Darwin":
        raise SystemExit("ARCH soak qualification must run on the target macOS machine")
    if tracked_dirty():
        raise SystemExit("Tracked checkout is dirty; refuse to create exact-SHA soak evidence")

    candidate = git_sha()
    expected = args.expected_sha.strip()
    if expected and candidate != expected:
        raise SystemExit(f"Expected SHA {expected}, found {candidate}")

    duration = args.duration_seconds if args.duration_seconds > 0 else args.hours * 3600.0
    if duration <= 0:
        raise SystemExit("Soak duration must be positive")
    interval = max(1.0, args.sample_seconds)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    evidence_base = Path(args.evidence_dir).expanduser()
    if not evidence_base.is_absolute():
        evidence_base = ROOT / evidence_base
    run_dir = evidence_base / f"{stamp}_ARCH_SOAK"
    run_dir.mkdir(parents=True, exist_ok=False)
    samples_path = run_dir / "samples.jsonl"
    summary_path = run_dir / "summary.json"

    baseline_swap = swap_used_mb()
    started = time.time()
    deadline = started + duration
    samples: list[dict[str, Any]] = []
    failures: list[str] = []
    health_failures = 0
    interrupted = False

    try:
        while True:
            sample = collect_sample()
            sample_errors = sample_failures(
                sample,
                baseline_swap_mb=baseline_swap,
                max_rss_mb=args.max_rss_mb,
                max_swap_growth_mb=args.max_swap_growth_mb,
                max_child_count=args.max_child_count,
            )
            if not sample["health_ok"]:
                health_failures += 1
                if health_failures > args.allowed_health_failures:
                    sample_errors.append(
                        f"health failures {health_failures} exceed allowed {args.allowed_health_failures}"
                    )
            sample["failures"] = sample_errors
            samples.append(sample)
            with samples_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(sample, sort_keys=True) + "\n")
            if sample_errors:
                failures.extend(sample_errors)
                break
            if time.time() >= deadline:
                break
            time.sleep(min(interval, max(0.0, deadline - time.time())))
    except KeyboardInterrupt:
        interrupted = True
        failures.append("soak interrupted by user")

    ended = time.time()
    max_rss = max((float(item["aggregate_rss_mb"]) for item in samples), default=0.0)
    max_children = max((int(item["child_count"]) for item in samples), default=0)
    swap_growths = [float(item["swap_growth_mb"]) for item in samples if item.get("swap_growth_mb") is not None]
    summary = {
        "candidate_sha": candidate,
        "front_door": "arch",
        "platform": platform.platform(),
        "label": LABEL,
        "status": "PASS" if not failures and not interrupted and ended >= deadline else "FAIL",
        "requested_duration_seconds": duration,
        "observed_duration_seconds": round(ended - started, 2),
        "sample_count": len(samples),
        "health_failures": health_failures,
        "max_aggregate_rss_mb": round(max_rss, 2),
        "max_child_count": max_children,
        "baseline_swap_mb": baseline_swap,
        "max_swap_growth_mb": round(max(swap_growths), 2) if swap_growths else None,
        "limits": {
            "max_rss_mb": args.max_rss_mb,
            "max_swap_growth_mb": args.max_swap_growth_mb,
            "max_child_count": args.max_child_count,
            "allowed_health_failures": args.allowed_health_failures,
        },
        "failures": failures,
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"Evidence: {summary_path}")
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
