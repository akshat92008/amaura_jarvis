from __future__ import annotations

import json

import pytest
import scripts.run_v7_arch_truth as wrapper


SHA = "a" * 40


def test_arch_truth_wrapper_accepts_only_exact_clean_candidate(monkeypatch):
    calls = []

    def fake_git(*args: str) -> str:
        calls.append(args)
        if args == ("rev-parse", "HEAD"):
            return SHA
        if args == ("status", "--porcelain", "--untracked-files=no"):
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(wrapper, "_git", fake_git)
    assert wrapper._assert_exact_candidate(SHA) == SHA
    assert ("status", "--porcelain", "--untracked-files=no") in calls


def test_arch_truth_wrapper_rejects_moved_or_dirty_candidate(monkeypatch):
    monkeypatch.setattr(wrapper, "_git", lambda *args: "b" * 40 if args[0] == "rev-parse" else "")
    with pytest.raises(RuntimeError, match="candidate mismatch"):
        wrapper._assert_exact_candidate(SHA)

    monkeypatch.setattr(wrapper, "_git", lambda *args: SHA if args[0] == "rev-parse" else " M jarvis/server.py")
    with pytest.raises(RuntimeError, match="clean tracked worktree"):
        wrapper._assert_exact_candidate(SHA)


def test_arch_truth_binding_records_exact_candidate(tmp_path):
    payload = {
        "expected_sha": SHA,
        "head_before": SHA,
        "head_after": SHA,
        "exact_candidate_unchanged": True,
        "benchmark_exit_code": 0,
    }
    path = wrapper._write_binding(tmp_path, payload)
    assert json.loads(path.read_text(encoding="utf-8")) == payload
