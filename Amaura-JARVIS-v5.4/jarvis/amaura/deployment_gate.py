"""Authoritative target-Mac company deployment qualification for Amaura JARVIS.

This gate composes the existing release, black-box, semantic, coding, live-state,
and soak qualifications into one exact-SHA verdict. It intentionally performs
no public publishing, outbound messaging, spending, account mutation, or
external production deployment.
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jarvis.amaura.runtime import load_amaura_env

ROOT = Path(__file__).resolve().parents[2]
SOAK_HOURS = 2.0


@dataclass(frozen=True, slots=True)
class DeploymentStage:
    name: str
    command: tuple[str, ...]
    timeout_seconds: int
    description: str


def _canonical_env_file() -> Path:
    return (ROOT / ".env.amaura").resolve()


def _git_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "git rev-parse failed").strip())
    return completed.stdout.strip()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=False)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def _private_write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _default_evidence_base() -> Path:
    configured = os.environ.get("AMAURA_DATA_DIR", "").strip()
    if configured:
        base = Path(configured).expanduser()
        if not base.is_absolute():
            base = ROOT / base
        return base.resolve() / "deployment_qualification"
    return (ROOT / ".amaura-data" / "deployment_qualification").resolve()


def build_stages(*, env_file: Path, run_dir: Path, candidate_sha: str) -> tuple[DeploymentStage, ...]:
    python = sys.executable
    scripts = ROOT / "scripts"
    return (
        DeploymentStage(
            name="authoritative_runtime",
            command=(
                python,
                "-m",
                "jarvis.amaura.ready_cli",
                "--env-file",
                str(env_file),
                "--check-only",
                "--recertify",
                "--full-report",
            ),
            timeout_seconds=1800,
            description="Exact-main provenance, live production doctor, security/model gates, and real PTY continuity.",
        ),
        DeploymentStage(
            name="canonical_arch_service",
            command=(
                python,
                str(scripts / "install_arch_launchd.py"),
                "--install",
                "--repo-root",
                str(ROOT),
            ),
            timeout_seconds=180,
            description="Install/restart the rollback-safe canonical launchd service from this certified checkout.",
        ),
        DeploymentStage(
            name="deployed_arch_front_door",
            command=(
                python,
                str(scripts / "run_arch_target_acceptance.py"),
                "--env-file",
                str(env_file),
                "--use-running",
                "--evidence-dir",
                str(run_dir / "front_door"),
            ),
            timeout_seconds=600,
            description="Black-box test of the freshly deployed ARCH service, founder auth, grounding, runner, and macOS control.",
        ),
        DeploymentStage(
            name="live_coding_delivery",
            command=(
                python,
                str(scripts / "qual_coding_field_live.py"),
                "--env-file",
                str(env_file),
                "--evidence-dir",
                str(run_dir / "coding"),
            ),
            timeout_seconds=1200,
            description="Production Antigravity adapter fixes a real defect in a disposable Git repo and passes independent verification.",
        ),
        DeploymentStage(
            name="live_semantic_company_task",
            command=(
                python,
                str(scripts / "qual_semantic_root_live.py"),
                "--reset",
                "--state-root",
                str(run_dir / "semantic_root"),
                "--max-iterations",
                "12",
                "--worker-deadline-seconds",
                "300",
            ),
            timeout_seconds=1500,
            description="Live public research, evidence, structured completion, Amaura synthesis, originality, and independent review.",
        ),
        DeploymentStage(
            name="live_company_store_health",
            command=(
                python,
                str(scripts / "audit_arch_company_blockers.py"),
                "--env-file",
                str(env_file),
                "--evidence-dir",
                str(run_dir / "company_store"),
                "--fail-on-degraded",
            ),
            timeout_seconds=120,
            description="Read-only live CompanyStore audit; any failed/blocked task or open alert fails deployment.",
        ),
        DeploymentStage(
            name="unattended_resource_soak",
            command=(
                python,
                str(scripts / "run_arch_soak.py"),
                "--hours",
                str(SOAK_HOURS),
                "--expected-sha",
                candidate_sha,
                "--evidence-dir",
                str(run_dir / "soak"),
            ),
            timeout_seconds=int(SOAK_HOURS * 3600) + 300,
            description="Two-hour exact-SHA launchd soak: singleton runtime, health, RSS, swap growth, and child-process bounds.",
        ),
    )


def _run_stage(stage: DeploymentStage, log_dir: Path) -> dict[str, Any]:
    started = time.time()
    try:
        completed = subprocess.run(
            list(stage.command),
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=stage.timeout_seconds,
            check=False,
            env=os.environ.copy(),
        )
        returncode = completed.returncode
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        error = ""
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        stdout = str(exc.stdout or "")
        stderr = str(exc.stderr or "")
        error = f"stage exceeded {stage.timeout_seconds} second deadline"
    except Exception as exc:
        returncode = 125
        stdout = ""
        stderr = ""
        error = f"{type(exc).__name__}: {exc}"

    stdout_path = log_dir / f"{stage.name}.stdout.log"
    stderr_path = log_dir / f"{stage.name}.stderr.log"
    _private_write(stdout_path, stdout)
    _private_write(stderr_path, stderr)
    ended = time.time()
    return {
        "name": stage.name,
        "description": stage.description,
        "status": "PASS" if returncode == 0 else "FAIL",
        "returncode": returncode,
        "duration_seconds": round(ended - started, 2),
        "stdout_sha256": _sha256_text(stdout),
        "stderr_sha256": _sha256_text(stderr),
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
        "error": error,
    }


def _blocked_stage(stage: DeploymentStage, reason: str) -> dict[str, Any]:
    return {
        "name": stage.name,
        "description": stage.description,
        "status": "BLOCKED",
        "returncode": None,
        "duration_seconds": 0.0,
        "stdout_sha256": "",
        "stderr_sha256": "",
        "stdout_log": "",
        "stderr_log": "",
        "error": reason,
    }


def run_deployment_gate(*, env_file: Path, evidence_base: Path | None = None) -> tuple[dict[str, Any], Path]:
    if platform.system() != "Darwin":
        raise RuntimeError("Company deployment qualification must run on the target macOS machine")
    env_file = env_file.expanduser().resolve()
    canonical_env = _canonical_env_file()
    if env_file != canonical_env:
        raise RuntimeError(
            f"Company deployment qualification must use the canonical launchd environment file: {canonical_env}"
        )
    if not env_file.is_file():
        raise RuntimeError(f"Private environment file not found: {env_file}")

    load_amaura_env(env_file, override=True, require_private_permissions=True)
    candidate = _git_sha()
    base = (evidence_base or _default_evidence_base()).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    run_dir = base / f"{stamp}_COMPANY_DEPLOYMENT"
    _private_dir(run_dir)
    log_dir = run_dir / "logs"
    _private_dir(log_dir)

    stages = build_stages(env_file=env_file, run_dir=run_dir, candidate_sha=candidate)
    results: list[dict[str, Any]] = []

    certification = _run_stage(stages[0], log_dir)
    results.append(certification)
    if certification["status"] != "PASS":
        for stage in stages[1:]:
            results.append(_blocked_stage(stage, "authoritative_runtime prerequisite failed"))
    else:
        for stage in stages[1:]:
            results.append(_run_stage(stage, log_dir))

    ready = all(item["status"] == "PASS" for item in results)
    report: dict[str, Any] = {
        "schema": "amaura.company-deployment-qualification.v1",
        "candidate_sha": candidate,
        "platform": platform.platform(),
        "soak_hours": SOAK_HOURS,
        "verdict": "READY_FOR_COMPANY_DEPLOYMENT" if ready else "NOT_READY_FOR_COMPANY_DEPLOYMENT",
        "ready": ready,
        "safety_scope": {
            "external_outreach": False,
            "public_publish": False,
            "spend": False,
            "account_mutation": False,
            "external_production_deploy": False,
            "local_arch_service_install": True,
            "coding_repository": "disposable",
            "company_store_audit": "read_only",
        },
        "stages": results,
    }
    report_path = run_dir / "deployment_qualification.json"
    _private_write(report_path, json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report, report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the authoritative Amaura JARVIS company deployment gate")
    parser.add_argument("--env-file", default=str(_canonical_env_file()))
    parser.add_argument(
        "--evidence-dir",
        default="",
        help="Optional private evidence base. Defaults under AMAURA_DATA_DIR, outside the source tree.",
    )
    parser.add_argument("--show-stage-commands", action="store_true", help="Print stage names/commands without executing them")
    args = parser.parse_args(argv)

    env_file = Path(args.env_file).expanduser().resolve()
    if args.show_stage_commands:
        candidate = _git_sha()
        placeholder = Path("<private-evidence-dir>")
        for stage in build_stages(env_file=env_file, run_dir=placeholder, candidate_sha=candidate):
            print(f"{stage.name}: {' '.join(stage.command)}")
        return 0

    evidence_base = Path(args.evidence_dir).expanduser().resolve() if args.evidence_dir else None
    try:
        report, report_path = run_deployment_gate(env_file=env_file, evidence_base=evidence_base)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ready": False,
                    "verdict": "NOT_READY_FOR_COMPANY_DEPLOYMENT",
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1

    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"Evidence: {report_path}")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
