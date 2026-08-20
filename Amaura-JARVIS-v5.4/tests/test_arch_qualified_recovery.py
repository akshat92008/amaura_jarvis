from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from jarvis.amaura.models import GovernanceError, TaskState
from jarvis.amaura.qualified_recovery import (
    apply_qualified_recovery,
    build_recovery_plan,
    validate_qualification,
)
from jarvis.amaura.store import CompanyStore


TREE = "tree-sha-123"


def _qualification(**overrides):
    result = {
        "task_id": "root-1",
        "title": "Root task",
        "status": "PASS",
        "returncode": 0,
        "final_state": "completed",
        "reviewer_distinct_from_worker": True,
        "criteria_all_passed": True,
        "evidence": "/tmp/root/e2e-summary.json",
    }
    report = {
        "qualification": "ARCH_COMPANY_ROOT_E2E",
        "status": "PASS",
        "candidate_tree_sha": TREE,
        "source_writable_connection_opened": False,
        "root_blocker_count": 1,
        "passed_root_count": 1,
        "unsafe_or_manual_roots": [],
        "results": [result],
    }
    report.update(overrides)
    return report


def _minimal_live_db(path: Path, *, root_action: str = "internal_work", dependency_state: str = "completed") -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE work_items (
                id TEXT PRIMARY KEY,
                item_type TEXT NOT NULL,
                title TEXT NOT NULL,
                state TEXT NOT NULL,
                action_type TEXT NOT NULL,
                dependencies TEXT NOT NULL,
                evidence TEXT NOT NULL,
                summary TEXT NOT NULL,
                metadata TEXT NOT NULL
            );
            CREATE TABLE execution_runs (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                state TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO work_items VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "dep-1",
                "task",
                "Dependency",
                dependency_state,
                "internal_work",
                "[]",
                "[]",
                "",
                "{}",
            ),
        )
        connection.execute(
            "INSERT INTO work_items VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "root-1",
                "task",
                "Root task",
                "failed",
                root_action,
                json.dumps(["dep-1"]),
                json.dumps([{"type": "tool_result", "reference": "evidence://old", "success": False}]),
                "old failure",
                "{}",
            ),
        )
        connection.commit()
    finally:
        connection.close()


def test_validate_qualification_requires_full_pass_and_same_tree():
    qualified = validate_qualification(_qualification(), candidate_tree_sha=TREE)
    assert [item["task_id"] for item in qualified] == ["root-1"]

    with pytest.raises(GovernanceError, match="source tree"):
        validate_qualification(_qualification(), candidate_tree_sha="different-tree")

    with pytest.raises(GovernanceError, match="did not PASS"):
        validate_qualification(_qualification(status="FAIL"), candidate_tree_sha=TREE)


def test_build_recovery_plan_accepts_only_failed_internal_dependency_ready_root(tmp_path: Path):
    db = tmp_path / "amaura.db"
    _minimal_live_db(db)
    results = validate_qualification(_qualification(), candidate_tree_sha=TREE)

    plan = build_recovery_plan(db, results)

    assert len(plan) == 1
    assert plan[0]["task_id"] == "root-1"
    assert plan[0]["current_state"] == "failed"
    assert plan[0]["previous_evidence"][0]["reference"] == "evidence://old"


def test_build_recovery_plan_refuses_consequential_or_blocked_root(tmp_path: Path):
    consequential = tmp_path / "consequential.db"
    _minimal_live_db(consequential, root_action="send_email")
    results = validate_qualification(_qualification(), candidate_tree_sha=TREE)
    with pytest.raises(GovernanceError, match="consequential"):
        build_recovery_plan(consequential, results)

    blocked = tmp_path / "blocked.db"
    _minimal_live_db(blocked, dependency_state="failed")
    with pytest.raises(GovernanceError, match="not dependency-ready"):
        build_recovery_plan(blocked, results)


def test_build_recovery_plan_refuses_active_execution(tmp_path: Path):
    db = tmp_path / "amaura.db"
    _minimal_live_db(db)
    connection = sqlite3.connect(db)
    try:
        connection.execute("INSERT INTO execution_runs VALUES('run-1','root-1','running')")
        connection.commit()
    finally:
        connection.close()
    results = validate_qualification(_qualification(), candidate_tree_sha=TREE)

    with pytest.raises(GovernanceError, match="active execution lease"):
        build_recovery_plan(db, results)


def test_apply_recovery_requeues_only_root_and_preserves_old_evidence_in_history(tmp_path: Path):
    store = CompanyStore(tmp_path / "company.db")
    try:
        store.insert_work_item(
            {
                "id": "root-1",
                "item_type": "task",
                "title": "Root task",
                "owner_id": "worker",
                "reviewer_id": "reviewer",
                "state": TaskState.FAILED.value,
                "action_type": "internal_work",
                "acceptance_criteria": ["verified"],
                "dependencies": [],
                "evidence": [
                    {
                        "type": "tool_result",
                        "reference": "evidence://old",
                        "sha256": "abc",
                        "success": False,
                    }
                ],
                "summary": "old failure",
            }
        )
        store.insert_work_item(
            {
                "id": "child-1",
                "item_type": "task",
                "title": "Blocked child",
                "owner_id": "worker",
                "reviewer_id": "reviewer",
                "state": TaskState.BLOCKED.value,
                "action_type": "internal_work",
                "acceptance_criteria": ["verified"],
                "dependencies": ["root-1"],
            }
        )
        plan = [
            {
                "task_id": "root-1",
                "title": "Root task",
                "current_state": "failed",
                "action_type": "internal_work",
                "dependencies": [],
                "previous_summary": "old failure",
                "previous_evidence": [{"type": "tool_result", "reference": "evidence://old"}],
                "qualification_evidence": "/tmp/e2e-summary.json",
            }
        ]

        result = apply_qualified_recovery(
            store,
            plan,
            qualification_path="/tmp/company-summary.json",
            candidate_tree_sha=TREE,
            reason="qualified repair",
            actor="founder",
        )

        root = store.get_work_item("root-1")
        child = store.get_work_item("child-1")
        assert result["status"] == "PASS"
        assert root["state"] == TaskState.ASSIGNED.value
        assert root["evidence"] == []
        assert "QUALIFIED REPAIR RETRY" in root["summary"]
        history = root["metadata"]["qualified_repair_retries"]
        assert history[-1]["previous_evidence"][0]["reference"] == "evidence://old"
        assert child["state"] == TaskState.BLOCKED.value
        assert any(event["event_type"] == "task.qualified_retry" for event in store.list_events(limit=20))
        assert any(item["action"] == "qualified_retry" for item in store.list_audit(limit=20))
    finally:
        store.close()
