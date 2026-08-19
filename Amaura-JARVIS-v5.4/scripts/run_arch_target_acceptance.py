#!/usr/bin/env python3
"""Real target-Mac acceptance for the converged ARCH front door.

This is intentionally a black-box product test. It starts exactly one ARCH
process (optional), talks only to the normal authenticated local HTTP front door,
and independently verifies a small set of convergence invariants:

- JARVIS API authentication is enough for the local founder session; the test
  never sends AMAURA_OPERATOR_KEY over HTTP;
- current Amaura questions are grounded in the authoritative WorldModel;
- a natural-language macOS app request really opens Safari;
- the embedded MissionRunner is enabled;
- no standalone company-daemon process is simultaneously running.

It does not test or approve external consequences. It never sends, publishes,
deploys, spends, or changes accounts.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx


def find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [Path.cwd(), *here.parents]:
        if (candidate / "jarvis").is_dir() and (candidate / "pyproject.toml").is_file():
            return candidate.resolve()
    raise RuntimeError("Could not locate ARCH repo root")


ROOT = find_repo_root()
sys.path.insert(0, str(ROOT))

from jarvis.amaura.runtime import load_amaura_env  # noqa: E402


def git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def headers() -> dict[str, str]:
    # Deliberately omit AMAURA_OPERATOR_KEY. The test proves ARCH's local
    # founder-session convergence rather than bypassing it.
    key = os.environ.get("JARVIS_API_KEY", "").strip()
    return {"X-Jarvis-Key": key} if key else {}


def base_url() -> str:
    host = os.environ.get("JARVIS_HOST", "127.0.0.1").strip() or "127.0.0.1"
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    port = int(os.environ.get("JARVIS_PORT", "8000"))
    return f"http://{host}:{port}"


def wait_ready(proc: subprocess.Popen[str] | None, timeout: float = 45.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(f"ARCH exited during startup with code {proc.returncode}")
        try:
            response = httpx.get(f"{base_url()}/api/health", timeout=1.0)
            if response.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.25)
    raise RuntimeError("ARCH did not become ready within the startup deadline")


def start_arch(env_file: Path) -> subprocess.Popen[str]:
    python = ROOT / ".venv" / "bin" / "python"
    if not python.is_file():
        raise RuntimeError(f"Virtualenv Python not found: {python}")
    return subprocess.Popen(
        [str(python), "-m", "jarvis.arch", "--env-file", str(env_file), "--no-web"],
        cwd=ROOT,
        env=os.environ.copy(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def request_json(method: str, path: str, *, body: dict[str, Any] | None = None, timeout: float = 30.0) -> dict[str, Any]:
    response = httpx.request(
        method,
        f"{base_url()}{path}",
        headers=headers(),
        json=body,
        timeout=timeout,
    )
    if response.status_code != 200:
        raise RuntimeError(f"{method} {path} returned HTTP {response.status_code}: {response.text[:500]}")
    return response.json()


def chat(message: str, *, timeout: float = 60.0) -> dict[str, Any]:
    return request_json(
        "POST",
        "/api/chat",
        body={
            "message": message,
            "session_id": "arch-target-acceptance",
            "autonomy": "execute_until_approval",
            "coding_backend": "antigravity",
        },
        timeout=timeout,
    )


def standalone_company_daemon_pids() -> list[int]:
    result = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=5)
    if result.returncode != 0:
        return []
    pids: list[int] = []
    for line in result.stdout.splitlines():
        if "jarvis.amaura.company_daemon" not in line and "amaura-company" not in line:
            continue
        parts = line.strip().split(maxsplit=1)
        try:
            pids.append(int(parts[0]))
        except (IndexError, ValueError):
            continue
    return pids


def safari_running() -> bool:
    if platform.system() != "Darwin":
        return False
    result = subprocess.run(["pgrep", "-x", "Safari"], capture_output=True, text=True, timeout=5)
    return result.returncode == 0 and bool(result.stdout.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run real converged ARCH target-Mac acceptance")
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--use-running", action="store_true", help="Test an already-running ARCH instead of starting one")
    parser.add_argument("--evidence-dir", default="qualification_evidence")
    args = parser.parse_args(argv)

    env_file = Path(args.env_file).expanduser().resolve()
    if not env_file.is_file():
        raise SystemExit(f"Environment file not found: {env_file}")
    load_amaura_env(env_file, override=True, require_private_permissions=True)

    if platform.system() != "Darwin":
        raise SystemExit("Target acceptance must run on macOS")
    if not os.environ.get("JARVIS_API_KEY", "").strip():
        raise SystemExit("JARVIS_API_KEY is required")
    if not os.environ.get("AMAURA_OPERATOR_KEY", "").strip():
        raise SystemExit("AMAURA_OPERATOR_KEY is required inside the private ARCH environment")

    candidate = git_sha()
    proc: subprocess.Popen[str] | None = None
    started_here = False
    results: list[dict[str, Any]] = []

    def record(name: str, passed: bool, detail: str, **extra: Any) -> None:
        results.append({"name": name, "status": "PASS" if passed else "FAIL", "detail": detail, **extra})

    try:
        if not args.use_running:
            if standalone_company_daemon_pids():
                record(
                    "single_runtime_precondition",
                    False,
                    "A standalone company daemon is already running; stop/migrate it before ARCH acceptance.",
                    pids=standalone_company_daemon_pids(),
                )
                raise RuntimeError("split runtime detected before ARCH startup")
            proc = start_arch(env_file)
            started_here = True
        wait_ready(proc)

        # Proves JARVIS auth -> ARCH founder session -> operator API promotion.
        world = request_json("GET", "/api/amaura/jarvis/world")
        record(
            "unified_founder_auth",
            isinstance(world.get("counts"), dict),
            "Operator-protected world endpoint succeeded using only X-Jarvis-Key.",
        )

        grounded = chat("What is the current state of Amaura Labs and what should we work on first?")
        executive = grounded.get("executive") or {}
        grounding = (executive.get("result") or {}).get("grounding")
        record(
            "authoritative_company_grounding",
            grounding == "authoritative_world_model",
            f"grounding={grounding!r}; response={str(grounded.get('response') or '')[:300]}",
        )

        runner = request_json("GET", "/api/amaura/jarvis/runner")
        record(
            "embedded_mission_runner",
            runner.get("enabled") is True,
            f"runner enabled={runner.get('enabled')!r}",
        )

        app_result = chat("Open Safari")
        app_exec = app_result.get("executive") or {}
        app_state = str(app_exec.get("state") or "")
        opened = safari_running()
        app_pass = app_state == "completed" and opened
        record(
            "natural_language_open_safari",
            app_pass,
            f"state={app_state!r}; safari_running={opened}; response={str(app_result.get('response') or '')[:300]}",
            capability="open_app",
            front_door="arch",
            candidate_sha=candidate,
        )

        daemon_pids = standalone_company_daemon_pids()
        record(
            "single_runtime_no_company_daemon",
            not daemon_pids,
            "No standalone company daemon process found." if not daemon_pids else f"Standalone daemon PIDs: {daemon_pids}",
            pids=daemon_pids,
        )

    except Exception as exc:
        if not results or results[-1].get("status") != "FAIL":
            record("acceptance_exception", False, f"{type(exc).__name__}: {exc}")
    finally:
        if started_here and proc is not None:
            if proc.stdin:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

    payload = {
        "candidate_sha": candidate,
        "front_door": "arch",
        "platform": platform.platform(),
        "started_arch_for_test": started_here,
        "passed": all(item["status"] == "PASS" for item in results),
        "results": results,
    }
    stamp = time.strftime("%Y%m%d_%H%M%S")
    evidence_dir = Path(args.evidence_dir).expanduser()
    if not evidence_dir.is_absolute():
        evidence_dir = ROOT / evidence_dir
    run_dir = evidence_dir / f"{stamp}_ARCH_TARGET_ACCEPTANCE"
    run_dir.mkdir(parents=True, exist_ok=False)
    path = run_dir / "acceptance.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(payload, indent=2, sort_keys=True))
    print(f"Evidence: {path}")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
