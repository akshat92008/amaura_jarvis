from jarvis.amaura.evidence import EvidenceVault, deterministic_evidence_review


def _evidence_item(record, *, item_type: str, success: bool, tool: str = ""):
    return {
        "type": item_type,
        "reference": record.reference,
        "sha256": record.sha256,
        "byte_length": record.byte_length,
        "success": success,
        "tool": tool,
    }


def test_recovered_failed_tool_attempt_is_audit_evidence_not_a_fatal_completion_failure(tmp_path):
    vault = EvidenceVault(tmp_path / "evidence")
    failed = vault.put_text('{"ok": false, "error": "unresolvable source"}', source="failed-web-fetch")
    successful = vault.put_text('{"ok": true, "data": {"output": "credible source"}}', source="successful-web-search")

    task = {
        "id": "task-recovered",
        "summary": "Completed from successful evidence.",
        "acceptance_criteria": ["Source register complete"],
        "evidence": [
            _evidence_item(failed, item_type="tool_result", success=False, tool="web_fetch"),
            _evidence_item(successful, item_type="tool_result", success=True, tool="web_search"),
        ],
    }

    result = deterministic_evidence_review(task, vault)

    assert result["approve"] is True
    assert result["findings"] == []
    assert result["failed_attempts"] == [
        {
            "evidence_index": 1,
            "tool": "web_fetch",
            "reference": failed.reference,
        }
    ]


def test_all_failed_tool_attempts_still_fail_deterministic_review(tmp_path):
    vault = EvidenceVault(tmp_path / "evidence")
    failed = vault.put_text('{"ok": false, "error": "unresolvable source"}', source="failed-web-fetch")

    task = {
        "id": "task-failed",
        "summary": "Claimed completion without successful evidence.",
        "acceptance_criteria": ["Source register complete"],
        "evidence": [
            _evidence_item(failed, item_type="tool_result", success=False, tool="web_fetch"),
        ],
    }

    result = deterministic_evidence_review(task, vault)

    assert result["approve"] is False
    assert any("records a failed operation" in finding for finding in result["findings"])
    assert result["failed_attempts"] == []


def test_failed_completion_artifact_remains_fatal_after_other_success(tmp_path):
    vault = EvidenceVault(tmp_path / "evidence")
    failed_test = vault.put_text('{"passed": false}', source="failed-independent-test")
    successful = vault.put_text('{"ok": true, "data": {"output": "evidence"}}', source="successful-web-search")

    task = {
        "id": "task-bad-completion",
        "summary": "Completion with a failed verification artifact.",
        "acceptance_criteria": ["Verified outcome"],
        "evidence": [
            _evidence_item(successful, item_type="tool_result", success=True, tool="web_search"),
            _evidence_item(failed_test, item_type="independent_test", success=False),
        ],
    }

    result = deterministic_evidence_review(task, vault)

    assert result["approve"] is False
    assert any("records a failed operation" in finding for finding in result["findings"])
