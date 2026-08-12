#!/usr/bin/env python3
"""Run every pytest node in isolated, bounded operating-system processes.

Each shard is launched through ``python -m pytest`` rather than embedding
``pytest.main``. That distinction is important for tests that use the
``multiprocessing`` spawn start method: spawned children must not inherit a
custom in-process pytest host as their main module.
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _collect(extra: list[str]) -> list[str]:
    command = [sys.executable, "-m", "pytest", "--collect-only", "-q", *extra]
    env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        raise SystemExit(result.returncode)
    nodes = [
        line.strip()
        for line in result.stdout.splitlines()
        if "::" in line and not line.startswith("<")
    ]
    if not nodes:
        raise SystemExit("No tests were collected")
    return nodes


def _run_shard(command: list[str], *, env: dict[str, str], timeout: int, log_path: Path) -> int:
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=(os.name == "posix"),
        )
        try:
            returncode = int(process.wait(timeout=timeout))
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            else:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    process.kill()
                process.wait(timeout=10)
            returncode = 124
    output = log_path.read_text(encoding="utf-8", errors="replace")
    if output:
        print(output, end="" if output.endswith("\n") else "\n", flush=True)
    return returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard-size", type=int, default=45)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--shard-index", type=int, default=0, help="Run one 1-based shard only")
    args, extra = parser.parse_known_args()

    nodes = _collect(extra)
    shard_size = max(1, min(args.shard_size, 200))
    total = (len(nodes) + shard_size - 1) // shard_size
    if args.shard_index and not 1 <= args.shard_index <= total:
        raise SystemExit(f"--shard-index must be between 1 and {total}")
    indices = [args.shard_index - 1] if args.shard_index else list(range(total))
    print(f"Collected {len(nodes)} tests; running {len(indices)} of {total} isolated shards", flush=True)

    for index in indices:
        shard = nodes[index * shard_size : (index + 1) * shard_size]
        with tempfile.TemporaryDirectory(prefix=f"amaura-tests-{index + 1}-") as tmp:
            tmp_path = Path(tmp)
            env = {
                **os.environ,
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "PYTHONWARNINGS": "ignore::DeprecationWarning",
            }
            command = [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-W",
                "ignore::DeprecationWarning",
                "--basetemp",
                str(tmp_path / "pytest"),
                *shard,
            ]
            print(f"[{index + 1}/{total}] {len(shard)} tests", flush=True)
            returncode = _run_shard(command, env=env, timeout=args.timeout, log_path=tmp_path / "pytest.log")
            if returncode == 124:
                print(f"Shard {index + 1} exceeded {args.timeout}s and was terminated", file=sys.stderr)
                return 124
            if returncode != 0:
                return returncode

    verified = len(nodes) if not args.shard_index else len(nodes[(args.shard_index - 1) * shard_size:args.shard_index * shard_size])
    print(f"Verified {verified} tests in isolated shards", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
