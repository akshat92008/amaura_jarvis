from __future__ import annotations

from importlib import util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_arch_company_blockers.py"
SPEC = util.spec_from_file_location("audit_arch_company_blockers", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
audit = util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def _task(task_id: str, state: str, *, deps: list[str] | None = None, title: str | None = None, priority: int = 3):
    return {
        "id": task_id,
        "parent_id": "mile",
        "workflow_id": "engineering",
        "title": title or task_id,
        "owner_id": "engineer",
        "state": state,
        "priority": priority,
        "dependencies": deps or [],
        "metadata": {},
        "summary": "",
        "updated_at": "2026-08-19T00:00:00+00:00",
    }


def test_audit_collapses_downstream_blocked_tasks_to_upstream_failure():
    tasks = [
        _task("root", "failed", title="Root provider failure", priority=1),
        _task("b1", "blocked", deps=["root"]),
        _task("b2", "blocked", deps=["b1"]),
        _task("b3", "blocked", deps=["b2"]),
        _task("healthy", "completed"),
    ]

    result = audit.analyze(tasks, [])

    assert result["status"] == "DEGRADED"
    assert result["counts"]["failed_tasks"] == 1
    assert result["counts"]["blocked_tasks"] == 3
    assert result["counts"]["root_blockers"] == 1
    assert result["root_blockers"][0]["id"] == "root"
    assert result["root_blockers"][0]["blocked_descendants"] == 3


def test_audit_surfaces_blocked_task_with_no_dependency_as_root_blocker():
    tasks = [
        _task("manual", "blocked", title="Policy/manual block", priority=2),
        _task("downstream", "blocked", deps=["manual"]),
    ]

    result = audit.analyze(tasks, [])

    assert result["counts"]["blocked_without_unresolved_dependencies"] == 1
    assert result["root_blockers"][0]["id"] == "manual"
    assert result["root_blockers"][0]["blocked_descendants"] == 1


def test_audit_does_not_treat_failed_task_with_failed_upstream_as_separate_root():
    tasks = [
        _task("upstream", "failed"),
        _task("downstream_failure", "failed", deps=["upstream"]),
        _task("blocked", "blocked", deps=["downstream_failure"]),
    ]

    result = audit.analyze(tasks, [])

    root_ids = [item["id"] for item in result["root_blockers"]]
    assert root_ids == ["upstream"]
    assert result["root_blockers"][0]["blocked_descendants"] == 1


def test_audit_counts_alert_codes_and_redacts_secret_like_summary():
    tasks = [_task("f1", "failed")]
    tasks[0]["summary"] = "provider token=super-secret-value timed out"
    alerts = [
        {"id": "a1", "status": "open", "severity": "high", "code": "provider", "message": "timeout"},
        {"id": "a2", "status": "open", "severity": "high", "code": "provider", "message": "timeout again"},
    ]

    result = audit.analyze(tasks, alerts)

    assert result["alert_code_counts"]["provider"] == 2
    assert "super-secret-value" not in result["failed_tasks"][0]["summary_excerpt"]
    assert "[REDACTED]" in result["failed_tasks"][0]["summary_excerpt"]
