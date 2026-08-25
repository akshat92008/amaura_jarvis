from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from jarvis.amaura import deployment_gate
from scripts import audit_arch_company_blockers


def test_company_deployment_stage_contract(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.amaura"
    stages = deployment_gate.build_stages(
        env_file=env_file,
        run_dir=tmp_path / "evidence",
        candidate_sha="abc123",
    )

    assert [stage.name for stage in stages] == [
        "authoritative_runtime",
        "canonical_arch_service",
        "deployed_arch_front_door",
        "live_coding_delivery",
        "live_semantic_company_task",
        "live_company_store_health",
        "unattended_resource_soak",
    ]
    assert "--recertify" in stages[0].command
    assert "install_arch_launchd.py" in " ".join(stages[1].command)
    assert "--install" in stages[1].command
    assert "--use-running" in stages[2].command
    assert "qual_coding_field_live.py" in " ".join(stages[3].command)
    assert "qual_semantic_root_live.py" in " ".join(stages[4].command)
    assert "--fail-on-degraded" in stages[5].command
    assert stages[6].command[stages[6].command.index("--expected-sha") + 1] == "abc123"
    assert stages[6].command[stages[6].command.index("--hours") + 1] == str(deployment_gate.SOAK_HOURS)


def test_run_stage_records_private_evidence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    stage = deployment_gate.DeploymentStage(
        name="probe",
        command=("python", "probe.py"),
        timeout_seconds=10,
        description="probe",
    )
    monkeypatch.setattr(
        deployment_gate.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="ok\n", stderr=""),
    )

    result = deployment_gate._run_stage(stage, tmp_path)

    assert result["status"] == "PASS"
    assert result["returncode"] == 0
    assert (tmp_path / "probe.stdout.log").read_text(encoding="utf-8") == "ok\n"
    assert result["stdout_sha256"]


def test_run_stage_timeout_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    stage = deployment_gate.DeploymentStage(
        name="probe",
        command=("python", "probe.py"),
        timeout_seconds=1,
        description="probe",
    )

    def expire(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=1)

    monkeypatch.setattr(deployment_gate.subprocess, "run", expire)
    result = deployment_gate._run_stage(stage, tmp_path)

    assert result["status"] == "FAIL"
    assert result["returncode"] == 124


def test_failed_authoritative_runtime_blocks_field_stages(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env.amaura"
    env_file.write_text("TEST=1\n", encoding="utf-8")
    monkeypatch.setattr(deployment_gate.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(deployment_gate, "load_amaura_env", lambda *args, **kwargs: {})
    monkeypatch.setattr(deployment_gate, "_git_sha", lambda: "candidate")

    calls: list[str] = []

    def fake_stage(stage: deployment_gate.DeploymentStage, log_dir: Path):
        calls.append(stage.name)
        return {
            "name": stage.name,
            "description": stage.description,
            "status": "FAIL",
            "returncode": 1,
            "duration_seconds": 0.1,
            "stdout_sha256": "",
            "stderr_sha256": "",
            "stdout_log": "",
            "stderr_log": "",
            "error": "qualification failed",
        }

    monkeypatch.setattr(deployment_gate, "_run_stage", fake_stage)
    report, report_path = deployment_gate.run_deployment_gate(env_file=env_file, evidence_base=tmp_path / "evidence")

    assert calls == ["authoritative_runtime"]
    assert report["ready"] is False
    assert report["verdict"] == "NOT_READY_FOR_COMPANY_DEPLOYMENT"
    assert all(stage["status"] == "BLOCKED" for stage in report["stages"][1:])
    assert report_path.is_file()


def test_blocker_audit_fail_on_degraded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env.amaura"
    env_file.write_text("TEST=1\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "amaura.db").touch()

    monkeypatch.setenv("AMAURA_DATA_DIR", str(data_dir))
    monkeypatch.setattr(audit_arch_company_blockers, "load_amaura_env", lambda *args, **kwargs: {})
    monkeypatch.setattr(audit_arch_company_blockers, "tracked_dirty", lambda: False)
    monkeypatch.setattr(audit_arch_company_blockers, "git_sha", lambda: "candidate")
    monkeypatch.setattr(
        audit_arch_company_blockers,
        "_read_live_state",
        lambda path: ([{"id": "task_1", "state": "failed", "metadata": "{}", "dependencies": "[]"}], []),
    )

    result = audit_arch_company_blockers.main(
        [
            "--env-file",
            str(env_file),
            "--evidence-dir",
            str(tmp_path / "audit"),
            "--fail-on-degraded",
        ]
    )
    assert result == 1


def test_blocker_audit_healthy_is_zero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env.amaura"
    env_file.write_text("TEST=1\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "amaura.db").touch()

    monkeypatch.setenv("AMAURA_DATA_DIR", str(data_dir))
    monkeypatch.setattr(audit_arch_company_blockers, "load_amaura_env", lambda *args, **kwargs: {})
    monkeypatch.setattr(audit_arch_company_blockers, "tracked_dirty", lambda: False)
    monkeypatch.setattr(audit_arch_company_blockers, "git_sha", lambda: "candidate")
    monkeypatch.setattr(audit_arch_company_blockers, "_read_live_state", lambda path: ([], []))

    result = audit_arch_company_blockers.main(
        [
            "--env-file",
            str(env_file),
            "--evidence-dir",
            str(tmp_path / "audit"),
            "--fail-on-degraded",
        ]
    )
    assert result == 0
