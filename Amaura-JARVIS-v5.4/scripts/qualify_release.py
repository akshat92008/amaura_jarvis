#!/usr/bin/env python3
"""Generate reproducible qualification evidence for the current Amaura source tree.

The script deliberately writes evidence outside the repository. A qualified run
requires a clean Git commit, runs every pytest node in isolated OS processes,
compiles distributable Python sources, runs the repository security scanner, and
executes the static source-certification gate. All reports are generated from the
same in-memory result so version and test totals cannot drift.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
REPORT_NAMES = (
    "TEST_REPORT.json",
    "QUALIFICATION_REPORT.json",
    "QUALIFICATION_EVIDENCE.json",
    "RELEASE_VERIFICATION.json",
)


def _version() -> str:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(project["project"]["version"])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git() -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True, timeout=15,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, check=True,
        capture_output=True, text=True, timeout=15,
    ).stdout.strip()
    return {"available": True, "commit": commit, "dirty": bool(status), "status": status.splitlines()}


def _run(command: list[str], *, timeout: int, log_path: Path) -> dict[str, Any]:
    started = time.monotonic()
    env = {
        **os.environ,
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONWARNINGS": "error",
        "PYTHONHASHSEED": "0",
    }
    try:
        result = subprocess.run(
            command, cwd=ROOT, env=env, text=True, capture_output=True,
            timeout=timeout, check=False,
        )
        returncode = int(result.returncode)
        output = (result.stdout or "") + (result.stderr or "")
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        output = ((exc.stdout or "") if isinstance(exc.stdout, str) else "") + ((exc.stderr or "") if isinstance(exc.stderr, str) else "")
        timed_out = True
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(output, encoding="utf-8")
    return {
        "command": command,
        "returncode": returncode,
        "timed_out": timed_out,
        "duration_seconds": round(time.monotonic() - started, 3),
        "log": log_path.name,
        "log_sha256": _sha256(log_path),
        "passed": returncode == 0,
    }


def _collect_nodes(log_dir: Path) -> tuple[list[str], dict[str, Any]]:
    record = _run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        timeout=180,
        log_path=log_dir / "pytest-collect.log",
    )
    if not record["passed"]:
        raise RuntimeError("Pytest collection failed")
    text = (log_dir / "pytest-collect.log").read_text(encoding="utf-8", errors="replace")
    nodes = [line.strip() for line in text.splitlines() if "::" in line and not line.startswith("<")]
    if not nodes:
        raise RuntimeError("No tests were collected")
    record["collected_tests"] = len(nodes)
    return nodes, record


def _write_final_reports(
    *,
    output: Path,
    logs: Path,
    version: str,
    git: dict[str, Any],
    nodes: list[str],
    collection: dict[str, Any],
    shard_size: int,
    shards: list[dict[str, Any]],
    allow_dirty: bool,
) -> bool:
    verified = sum(int(item["tests"]) for item in shards if item.get("passed"))
    compile_record = _run(
        [sys.executable, "-m", "compileall", "-q", "-f", "jarvis", "aimodel", "scripts", "tests"],
        timeout=180,
        log_path=logs / "compileall.log",
    )

    from jarvis.amaura.doctor import scan_repository
    from scripts.release_gate import _run as release_gate_run

    security = scan_repository(ROOT)
    static_gate = release_gate_run(True)
    shard_total = (len(nodes) + shard_size - 1) // shard_size
    tests_passed = (
        len(shards) == shard_total
        and verified == len(nodes)
        and all(item.get("passed") for item in shards)
    )
    source_certified = bool(
        tests_passed
        and compile_record["passed"]
        and security.get("ok")
        and static_gate.get("source_certified")
        and not git["dirty"]
    )
    shard_started = [str(item.get("started_at", "")) for item in shards if item.get("started_at")]
    started_at = min(shard_started) if shard_started else datetime.now(UTC).isoformat()
    finished_at = datetime.now(UTC).isoformat()

    common = {
        "schema_version": 1,
        "version": version,
        "started_at": started_at,
        "finished_at": finished_at,
        "source_certified": source_certified,
        "production_ready": False,
        "git": git,
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "executable": sys.executable,
        },
        "tests": {
            "collected": len(nodes),
            "verified": verified,
            "passed": tests_passed,
            "shard_size": shard_size,
            "shard_total": shard_total,
            "collection": collection,
            "shards": shards,
        },
        "compilation": compile_record,
        "security_scan": security,
        "static_release_gate": static_gate,
        "evidence_policy": {
            "warnings_as_errors": True,
            "pytest_plugin_autoload_disabled": True,
            "isolated_os_process_shards": True,
            "clean_git_required": not allow_dirty,
            "generated_from_single_commit": True,
            "shard_records_are_digest_bound": True,
        },
    }

    reports = {
        "TEST_REPORT.json": {
            "version": version,
            "collected_tests": len(nodes),
            "verified_tests": verified,
            "passed": tests_passed,
            "shards": shards,
            "collection": collection,
        },
        "QUALIFICATION_REPORT.json": common,
        "QUALIFICATION_EVIDENCE.json": {
            **common,
            "log_files": {
                path.name: {"sha256": _sha256(path), "bytes": path.stat().st_size}
                for path in sorted(logs.glob("*.log"))
            },
            "shard_records": {
                path.name: {"sha256": _sha256(path), "bytes": path.stat().st_size}
                for path in sorted(output.glob("shard-*.json"))
            },
        },
        "RELEASE_VERIFICATION.json": {
            "version": version,
            "release_name": f"Amaura Company OS v{version} — Free-First Human-Reviewed Integrations",
            "source_certified": source_certified,
            "production_ready": False,
            "automated_tests": verified,
            "collected_tests": len(nodes),
            "all_tests_passed": tests_passed,
            "security_ok": bool(security.get("ok")),
            "compilation_ok": bool(compile_record["passed"]),
            "static_gate_ok": bool(static_gate.get("source_certified")),
            "git": git,
            "shards": [
                {
                    "index": item["index"],
                    "tests": item["tests"],
                    "passed": item["passed"],
                    "duration_seconds": item["duration_seconds"],
                    "log_sha256": item["log_sha256"],
                }
                for item in shards
            ],
        },
    }
    for name, payload in reports.items():
        (output / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )

    ledger = output / "EVIDENCE_SHA256SUMS"
    ledger.write_text(
        "".join(f"{_sha256(output / name)}  {name}\n" for name in REPORT_NAMES),
        encoding="utf-8",
    )
    print(json.dumps({
        "version": version,
        "source_certified": source_certified,
        "tests": {"collected": len(nodes), "verified": verified},
        "security_ok": security.get("ok"),
        "static_gate_ok": static_gate.get("source_certified"),
        "output": str(output),
    }, indent=2, sort_keys=True))
    return source_certified


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shard-size", type=int, default=45)
    parser.add_argument("--shard-timeout", type=int, default=300)
    parser.add_argument("--shard-index", type=int, default=0, help="Run and persist one 1-based shard")
    parser.add_argument("--finalize", action="store_true", help="Assemble reports from persisted shard records")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    if args.shard_index and args.finalize:
        raise SystemExit("--shard-index and --finalize are mutually exclusive")

    output = args.output.expanduser().resolve()
    if not args.shard_index and not args.finalize and output.exists():
        import shutil
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    logs = output / "logs"
    logs.mkdir(exist_ok=True)

    version = _version()
    git = _git()
    if git["dirty"] and not args.allow_dirty:
        raise SystemExit("Qualification requires a clean Git worktree")

    nodes, collection = _collect_nodes(logs)
    shard_size = max(1, min(int(args.shard_size), 200))
    shard_total = (len(nodes) + shard_size - 1) // shard_size

    if args.shard_index:
        index = int(args.shard_index)
        if not 1 <= index <= shard_total:
            raise SystemExit(f"--shard-index must be between 1 and {shard_total}")
        count = len(nodes[(index - 1) * shard_size:index * shard_size])
        started_at = datetime.now(UTC).isoformat()
        record = _run(
            [
                sys.executable, "scripts/run_verified_tests.py",
                "--shard-size", str(shard_size),
                "--timeout", str(args.shard_timeout),
                "--shard-index", str(index),
            ],
            timeout=args.shard_timeout + 90,
            log_path=logs / f"pytest-shard-{index}.log",
        )
        record.update({
            "index": index,
            "tests": count,
            "version": version,
            "git_commit": git["commit"],
            "collected_tests": len(nodes),
            "shard_size": shard_size,
            "shard_total": shard_total,
            "started_at": started_at,
            "finished_at": datetime.now(UTC).isoformat(),
        })
        target = output / f"shard-{index}.json"
        target.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(record, indent=2, sort_keys=True))
        return 0 if record["passed"] else 1

    if args.finalize:
        shards: list[dict[str, Any]] = []
        for index in range(1, shard_total + 1):
            path = output / f"shard-{index}.json"
            if not path.is_file():
                raise SystemExit(f"Missing persisted qualification shard: {path.name}")
            record = json.loads(path.read_text(encoding="utf-8"))
            expected = {
                "index": index,
                "version": version,
                "git_commit": git["commit"],
                "collected_tests": len(nodes),
                "shard_size": shard_size,
                "shard_total": shard_total,
            }
            for key, value in expected.items():
                if record.get(key) != value:
                    raise SystemExit(f"Shard {index} metadata mismatch for {key}")
            if record.get("log_sha256") != _sha256(logs / f"pytest-shard-{index}.log"):
                raise SystemExit(f"Shard {index} log digest mismatch")
            shards.append(record)
        return 0 if _write_final_reports(
            output=output,
            logs=logs,
            version=version,
            git=git,
            nodes=nodes,
            collection=collection,
            shard_size=shard_size,
            shards=shards,
            allow_dirty=args.allow_dirty,
        ) else 1

    shards = []
    for index in range(1, shard_total + 1):
        count = len(nodes[(index - 1) * shard_size:index * shard_size])
        started_at = datetime.now(UTC).isoformat()
        record = _run(
            [
                sys.executable, "scripts/run_verified_tests.py",
                "--shard-size", str(shard_size),
                "--timeout", str(args.shard_timeout),
                "--shard-index", str(index),
            ],
            timeout=args.shard_timeout + 90,
            log_path=logs / f"pytest-shard-{index}.log",
        )
        record.update({
            "index": index,
            "tests": count,
            "version": version,
            "git_commit": git["commit"],
            "collected_tests": len(nodes),
            "shard_size": shard_size,
            "shard_total": shard_total,
            "started_at": started_at,
            "finished_at": datetime.now(UTC).isoformat(),
        })
        (output / f"shard-{index}.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        shards.append(record)
        if not record["passed"]:
            break
    return 0 if _write_final_reports(
        output=output,
        logs=logs,
        version=version,
        git=git,
        nodes=nodes,
        collection=collection,
        shard_size=shard_size,
        shards=shards,
        allow_dirty=args.allow_dirty,
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
