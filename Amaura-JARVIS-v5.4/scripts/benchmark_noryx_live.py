#!/usr/bin/env python3
"""Live JARVIS→Noryx qualification harness for private/unseen repository cases.

Case JSONL schema:
{"id":"case1","repository":"/path/to/fixture","objective":"...","acceptance_criteria":["..."],"verify":[["pytest","-q"]]}

Each fixture is copied to an isolated temporary directory before Noryx runs. The
strong Noryx bridge verifies Git/test evidence first; this harness then executes
case-owned verification commands independently. Keep real benchmark cases private
so the coding backend cannot train against the release qualification set.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from jarvis.amaura.noryx_bridge import NoryxDeliveryAdapter


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", type=Path)
    parser.add_argument("--output", type=Path, default=Path("NORYX_LIVE_BENCHMARK.json"))
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    adapter = NoryxDeliveryAdapter()
    if not adapter.configured:
        raise SystemExit("Noryx is not configured. Set AMAURA_NORYX_COMMAND or install the noryx executable.")
    rows = []
    for line in args.cases.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        case_id = str(case.get("id") or f"case-{len(rows) + 1}")
        source = Path(str(case["repository"])).expanduser().resolve()
        started = time.monotonic()
        row = {"id": case_id, "objective": case["objective"], "passed": False, "verification": []}
        try:
            with tempfile.TemporaryDirectory(prefix=f"amaura-noryx-bench-{case_id}-") as temp:
                repo = Path(temp) / "repo"
                shutil.copytree(source, repo, symlinks=True)
                result = adapter.run_with_result(
                    repository_path=str(repo),
                    objective=str(case["objective"]),
                    acceptance_criteria=[str(v) for v in case.get("acceptance_criteria", [])],
                    idempotency_key=f"benchmark:{case_id}",
                    timeout_seconds=args.timeout,
                )
                row["noryx"] = result.to_dict()
                all_ok = True
                for command in case.get("verify", []):
                    if not isinstance(command, list) or not command:
                        raise ValueError("verify entries must be non-empty argv lists")
                    completed = subprocess.run(
                        [str(v) for v in command],
                        cwd=repo,
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                        timeout=600,
                        check=False,
                    )
                    check = {
                        "argv": command,
                        "exit_code": completed.returncode,
                        "stdout": completed.stdout[-8000:],
                        "stderr": completed.stderr[-8000:],
                        "passed": completed.returncode == 0,
                    }
                    row["verification"].append(check)
                    all_ok = all_ok and check["passed"]
                row["passed"] = all_ok
        except Exception as exc:
            row["error"] = str(exc)
        row["duration_seconds"] = round(time.monotonic() - started, 3)
        rows.append(row)
    report = {
        "cases": len(rows),
        "passed": sum(1 for row in rows if row["passed"]),
        "all_passed": bool(rows) and all(row["passed"] for row in rows),
        "results": rows,
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("cases", "passed", "all_passed")}, indent=2))
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
