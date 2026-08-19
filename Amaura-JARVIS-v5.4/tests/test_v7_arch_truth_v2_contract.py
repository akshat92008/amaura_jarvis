from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_arch_truth_v2_composite_contract() -> None:
    text = (ROOT / "scripts" / "arch_truth_benchmark_v2.py").read_text(encoding="utf-8")
    assert "arch_holdout_v9.py" in text
    assert 'int(counts.get("FAIL", 0)) == 0' in text
    assert 'int(counts.get("BLOCKED", 0)) == 0' in text
    assert "v9_pass_count == 26" in text
    assert "v2_cross_session_durable_memory" in text
    assert "recall.response_text.strip() == marker" in text
    assert "len({session_store, session_distractor, session_recall}) == 3" in text
    assert "_project_memory_source" in text
    assert "source_ref in [str(item) for item in context_sources]" in text
    assert "total_pass_count = v9_pass_count + (1 if supplement.status == PASS else 0)" in text
    assert '"score": f"{total_pass_count}/27"' in text
    assert "EVIDENCE_AUDIT_CHECKLIST.md" in text
    assert '"evidence_audit_status": "PENDING"' in text
    assert '"release_qualified": False' in text


def test_v7_arch_truth_wrapper_binds_v2_and_keeps_manual_audit_required() -> None:
    text = (ROOT / "scripts" / "run_v7_arch_truth.py").read_text(encoding="utf-8")
    assert "arch_truth_benchmark_v2.py" in text
    assert "TRUTH_V2_RESULTS.json" in text
    assert "benchmark_sha256_before" in text
    assert "benchmark_sha256_after" in text
    assert "benchmark_version_ok" in text
    assert "automated_gate_pass" in text
    assert '"release_qualified": False' in text
    assert "Raw ARCH Truth v2 evidence must be independently audited" in text
