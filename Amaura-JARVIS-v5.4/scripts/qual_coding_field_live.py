#!/usr/bin/env python3
"""Exact-SHA live coding field qualification for Amaura JARVIS.

The qualification uses the production Antigravity delivery adapter against a
brand-new disposable Git repository. It proves a real code defect is repaired,
that the declared test passes independently, and that the test itself was not
modified. No production repository or CompanyStore data is writable by this
probe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


def find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [Path.cwd(), *here.parents]:
        if (candidate / "jarvis").is_dir() and (candidate / "pyproject.toml").is_file():
            return candidate.resolve()
    raise RuntimeError("Could not locate JARVIS repository root")


ROOT = find_repo_root()
sys.path.insert(0, str(ROOT))

from jarvis.amaura.antigravity_bridge import AntigravityDeliveryAdapter  # noqa: E402
from jarvis.amaura.runtime import load_amaura_env  # noqa: E402


def _run(*args: str, cwd: Path, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, check=False, timeout=timeout)


def _git_sha() -> str:
    result = _run("git", "rev-parse", "HEAD", cwd=ROOT)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "git rev-parse failed").strip())
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _init_fixture(repository: Path) -> tuple[str, str]:
    commands = (
        ("git", "init"),
        ("git", "config", "user.name", "Amaura Qualification"),
        ("git", "config", "user.email", "qualification@localhost"),
    )
    for command in commands:
        result = _run(*command, cwd=repository)
        if result.returncode != 0:
            raise RuntimeError(f"{' '.join(command)} failed: {(result.stderr or result.stdout)[-1000:]}")

    (repository / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    (repository / "math_utils.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    test_path = repository / "test_math.py"
    test_path.write_text(
        "import unittest\n\n"
        "from math_utils import add\n\n\n"
        "class TestAdd(unittest.TestCase):\n"
        "    def test_add(self):\n"
        "        self.assertEqual(add(2, 3), 5)\n\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n",
        encoding="utf-8",
    )
    for command in (("git", "add", "."), ("git", "commit", "-m", "Initial broken fixture")):
        result = _run(*command, cwd=repository)
        if result.returncode != 0:
            raise RuntimeError(f"{' '.join(command)} failed: {(result.stderr or result.stdout)[-1000:]}")
    return _sha256(repository / "math_utils.py"), _sha256(test_path)


def _safe_result_payload(run_result: Any) -> dict[str, Any]:
    result = dict(run_result.result or {})
    verification = dict(run_result.verification or {})
    return {
        "cli_version": str(run_result.cli_version or ""),
        "returncode": int(run_result.returncode),
        "changed_files": sorted(str(item) for item in result.get("changed_files", [])),
        "verification_commands": [str(item) for item in result.get("verification_commands", [])],
        "verification_ok": bool(verification.get("ok", verification.get("passed", False))),
        "receipt_status": str(getattr(run_result.receipt, "status", "")),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the live disposable Antigravity coding field qualification")
    parser.add_argument("--env-file", default=str(ROOT / ".env.amaura"))
    parser.add_argument("--evidence-dir", default="qualification_evidence")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args(argv)

    env_file = Path(args.env_file).expanduser().resolve()
    if not env_file.is_file():
        raise SystemExit(f"Environment file not found: {env_file}")
    load_amaura_env(env_file, override=True, require_private_permissions=True)

    candidate = _git_sha()
    evidence_base = Path(args.evidence_dir).expanduser()
    if not evidence_base.is_absolute():
        evidence_base = ROOT / evidence_base
    run_dir = evidence_base / f"{time.strftime('%Y%m%d_%H%M%S')}_CODING_FIELD"
    run_dir.mkdir(parents=True, exist_ok=False)
    if hasattr(run_dir, "chmod"):
        try:
            run_dir.chmod(0o700)
        except OSError:
            pass

    payload: dict[str, Any] = {
        "candidate_sha": candidate,
        "platform": platform.platform(),
        "status": "FAIL",
        "production_adapter": "AntigravityDeliveryAdapter",
        "disposable_repository": True,
        "checks": {},
    }

    try:
        with tempfile.TemporaryDirectory(prefix="amaura-antigravity-field-") as temporary:
            repository = Path(temporary).resolve()
            baseline_math_sha, baseline_test_sha = _init_fixture(repository)

            initial = _run(sys.executable, "-m", "unittest", "-q", "test_math.py", cwd=repository)
            payload["checks"]["fixture_initially_fails"] = initial.returncode != 0
            if initial.returncode == 0:
                raise RuntimeError("Coding fixture was not broken before Antigravity execution")

            adapter = AntigravityDeliveryAdapter()
            readiness = adapter.readiness(str(repository))
            payload["checks"]["antigravity_ready"] = readiness.get("ready") is True
            payload["antigravity_version"] = str(readiness.get("version") or adapter.version())
            if readiness.get("ready") is not True:
                raise RuntimeError(f"Antigravity production adapter is not ready: {readiness.get('blockers') or readiness}")

            run_result = adapter.run_with_result(
                repository_path=str(repository),
                objective="Fix math_utils.add so add(2, 3) returns 5. Do not modify test_math.py.",
                acceptance_criteria=[
                    "python -m unittest -q test_math.py exits with code 0",
                    "test_math.py is unchanged",
                ],
                idempotency_key=f"company-deployment-coding:{candidate}",
                timeout_seconds=max(60, args.timeout_seconds),
            )
            payload["adapter_result"] = _safe_result_payload(run_result)

            final = _run(sys.executable, "-m", "unittest", "-q", "test_math.py", cwd=repository)
            final_math_sha = _sha256(repository / "math_utils.py")
            final_test_sha = _sha256(repository / "test_math.py")
            changed = _run("git", "status", "--porcelain=v1", "--untracked-files=all", cwd=repository)
            changed_text = changed.stdout if changed.returncode == 0 else ""

            checks = {
                "fixture_initially_fails": True,
                "antigravity_ready": True,
                "adapter_returncode_zero": run_result.returncode == 0,
                "independent_verification_passed": final.returncode == 0,
                "implementation_changed": final_math_sha != baseline_math_sha,
                "test_unchanged": final_test_sha == baseline_test_sha,
                "expected_file_changed": "math_utils.py" in changed_text or "math_utils.py" in payload["adapter_result"]["changed_files"],
                "no_test_change_reported": "test_math.py" not in payload["adapter_result"]["changed_files"],
            }
            payload["checks"] = checks
            payload["status"] = "PASS" if all(checks.values()) else "FAIL"
    except Exception as exc:
        payload["error"] = {"type": type(exc).__name__, "message": str(exc)[:1200]}

    evidence_path = run_dir / "qualification.json"
    evidence_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        evidence_path.chmod(0o600)
    except OSError:
        pass
    print(json.dumps(payload, indent=2, sort_keys=True))
    print(f"Evidence: {evidence_path}")
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
