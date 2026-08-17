from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from jarvis import cli
from jarvis.agent import JarvisAgent
from jarvis.amaura.mission_runner import MissionRunner


def _run_cli(prompt: str, working_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> str:
    """Helper to execute the public CLI main() function synchronously in a test workspace."""
    data_dir = working_dir.parent / f"{working_dir.name}_amaura_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AMAURA_DATA_DIR", str(data_dir))
    monkeypatch.setenv("AMAURA_AUDIT_CHECKPOINT_PATH", str(data_dir / "audit.checkpoint"))
    monkeypatch.setenv("AMAURA_PROVIDER_RECEIPT_KEY", "a" * 64)
    monkeypatch.setenv("AMAURA_REVIEW_ATTESTATION_KEY", "r" * 64)
    from jarvis.tools.amaura import reset_control_plane

    reset_control_plane()

    argv = ["jarvis", "--no-web", "--working-dir", str(working_dir), prompt]
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-key")
    cli.main()
    captured = capsys.readouterr()
    return captured.out + captured.err


def test_contract_a_oneshot_exact_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    """Contract A: 'Create exact.txt containing exactly HELLO' -> exact.txt bytes == b'HELLO'"""
    _run_cli("Create exact.txt containing exactly HELLO", tmp_path, monkeypatch, capsys)
    target = tmp_path / "exact.txt"
    assert target.exists(), "exact.txt was not created"
    assert target.read_bytes() == b"HELLO"


def test_contract_b_path_first_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    """Contract B: 'In nested/config.txt write exactly MODE=SAFE and nothing else.' -> exact file"""
    _run_cli("In nested/config.txt write exactly MODE=SAFE and nothing else.", tmp_path, monkeypatch, capsys)
    target = tmp_path / "nested" / "config.txt"
    assert target.exists(), "nested/config.txt was not created"
    assert target.read_bytes() == b"MODE=SAFE"


def test_contract_c_response_action_separation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    """Contract C: 'Create done.txt containing exactly READY, then respond with exactly DONE.' -> file READY and response DONE"""
    output = _run_cli("Create done.txt containing exactly READY, then respond with exactly DONE.", tmp_path, monkeypatch, capsys)
    target = tmp_path / "done.txt"
    assert target.exists(), "done.txt was not created"
    assert target.read_bytes() == b"READY"
    assert "DONE" in output


def test_contract_d_readonly_repository_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    """Contract D: 'Inspect this repository and explain its architecture. Do not modify any file.' -> git status clean, no main.py"""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test User"], check=True)
    (tmp_path / "app.py").write_text("def main():\n    return 'OK'\n")
    (tmp_path / "service.py").write_text("def service():\n    return True\n")
    (tmp_path / "README.md").write_text("# Test Repo\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], check=True)

    _run_cli("Inspect this repository and explain its architecture. Do not modify any file.", tmp_path, monkeypatch, capsys)

    status = subprocess.run(
        ["git", "-C", str(tmp_path), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert status == "", f"Git repository status is not clean: {status}"
    assert not (tmp_path / "main.py").exists(), "main.py was unexpectedly created"


def test_contract_e_arithmetic_regression(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    """Contract E: 'Take 18 away from 50.' -> 32"""
    output = _run_cli("Take 18 away from 50. Return the numeric answer.", tmp_path, monkeypatch, capsys)
    assert "32" in output


def test_contract_f_ambiguous_write_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    """Contract F: 'Write either ALPHA or BETA to ambiguous.txt; choose neither unless payload is unambiguous.' -> no file"""
    _run_cli(
        "Write either ALPHA or BETA to ambiguous.txt; choose neither unless payload is unambiguous.",
        tmp_path,
        monkeypatch,
        capsys,
    )
    target = tmp_path / "ambiguous.txt"
    assert not target.exists(), "ambiguous.txt was created despite ambiguous payload"


def test_auto_fable_disabled_for_ordinary_prompts(tmp_path: Path):
    """Verify that _should_auto_fable does not auto-route keyword prompts into ungoverned Fable."""
    agent = JarvisAgent(api_key="test-key", model_key="default", working_dir=str(tmp_path))
    assert not agent._should_auto_fable("Inspect this repository and explain its architecture")
    assert not agent._should_auto_fable("Refactor the entire codebase and audit system design")
    assert not agent._should_auto_fable("Solve complex problem with python function database backend")


def test_auto_fable_explicit_optin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify that Fable remains accessible when explicitly requested via model key or env var."""
    fable_agent = JarvisAgent(api_key="test-key", model_key="fable-5-reasoning", working_dir=str(tmp_path))
    assert fable_agent._should_auto_fable("build app")

    monkeypatch.setenv("JARVIS_ENABLE_AUTO_FABLE", "1")
    default_agent = JarvisAgent(api_key="test-key", model_key="default", working_dir=str(tmp_path))
    assert default_agent._should_auto_fable("build app")


def _make_mock_agy(
    bin_dir: Path,
    *,
    modify_file: str = "math_utils.py",
    new_content: str = "def add(a: int, b: int) -> int:\n    return a + b\n",
    success: bool = True,
    remaining_failures: list[str] | None = None,
) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "mock_agy"
    rem_json = json.dumps(remaining_failures or [])
    new_content_json = json.dumps(new_content)
    modify_file_json = json.dumps(modify_file)
    script.write_text(
        f"""#!/usr/bin/env python3
import json, pathlib, sys
if "--version" in sys.argv or (len(sys.argv) > 1 and sys.argv[1] == "version"):
    print("Antigravity CLI v1.1.12")
    sys.exit(0)

repo = pathlib.Path.cwd()
if {success!r}:
    (repo / {modify_file_json}).write_text({new_content_json}, encoding="utf-8")
    result = {{
        "schema": "amaura.antigravity-result.v1",
        "success": True,
        "summary": "Fixed the math utility add function to correctly add numbers.",
        "changed_files": [{modify_file_json}],
        "verification_commands": ["python -m pytest -q"],
        "remaining_failures": {rem_json},
        "models_used": ["gemini-test"],
        "conversation_id": "test-conv-1",
    }}
else:
    result = {{
        "schema": "amaura.antigravity-result.v1",
        "success": False,
        "summary": "Failed to resolve issues.",
        "changed_files": [{modify_file_json}],
        "verification_commands": ["python -m pytest -q"],
        "remaining_failures": ["test_add failed"],
        "models_used": ["gemini-test"],
        "conversation_id": "test-conv-fail",
    }}
print(json.dumps({{"type": "assistant", "model": "gemini-test"}}), flush=True)
print(json.dumps({{"type": "result", "result": result}}), flush=True)
""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script


def test_regression_a_b_c_d_oneshot_engineering_execution_and_verify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Regression Tests A, B, C, D:
    A: One-shot engineering request creates mission AND executes it.
    B: Mission performs actual repository modification.
    C: Tests are run after modification.
    D: Successful mission returns completed.
    """
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)

    (repo / "math_utils.py").write_text("def add(a: int, b: int) -> int:\n    return a - b\n", encoding="utf-8")
    (repo / "test_math_utils.py").write_text(
        "from math_utils import add\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo, check=True)

    agy_script = _make_mock_agy(tmp_path / "bin")
    monkeypatch.setenv("AMAURA_ANTIGRAVITY_COMMAND", str(agy_script))
    monkeypatch.setenv("AMAURA_VERIFIER_MODE", "host")
    monkeypatch.setenv("AMAURA_ALLOW_HOST_VERIFICATION", "1")
    monkeypatch.setenv("AMAURA_ANTIGRAVITY_REQUIRE_AUTONOMY_SETTINGS", "0")
    monkeypatch.setenv("AMAURA_ANTIGRAVITY_REQUIRE_MODEL_PROVENANCE", "1")
    monkeypatch.setenv("AMAURA_PROVIDER_RECEIPT_KEY", "a" * 32)

    prompt = (
        "Fix the failing implementation in this repository with the smallest correct change. "
        "Preserve the public API and run the tests. Do not deploy or touch anything outside this repository."
    )
    output = _run_cli(prompt, repo, monkeypatch, capsys)
    # Test A & D: Successful mission execution and completed message returned
    assert "completed" in output.lower(), f"Expected completion message in output: {output}"
    assert "evidence/review pipeline" in output, f"Expected pipeline confirmation in output: {output}"

    # Test B: math_utils.py is actually modified on disk
    math_content = (repo / "math_utils.py").read_text(encoding="utf-8")
    assert "a + b" in math_content, f"math_utils.py was not updated with correct implementation: {math_content}"

    # Test C: tests pass on repository after modification
    cp = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=repo, capture_output=True, text=True)
    assert cp.returncode == 0, f"pytest failed after modification:\nstdout={cp.stdout}\nstderr={cp.stderr}"


def test_regression_e_approval_required_stops_without_protected_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Regression Test E: Approval-required mission stops without performing protected action."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "app.py").write_text("def health():\n    return {'ok': True}\n", encoding="utf-8")
    (repo / "README.md").write_text("# release fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo, check=True)

    # Request that hits governance boundary
    prompt = "Inspect this app and prepare a release-readiness assessment. Do not deploy, publish, push, or make any external change. Do not modify the repository."
    output = _run_cli(prompt, repo, monkeypatch, capsys)
    assert output, "CLI produced empty output"

    # Verify repository remains clean and uncompromised
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    assert status == "", f"Repository was modified unexpectedly: {status}"


def test_regression_f_failed_mission_reports_failure_truthfully(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Regression Test F: Failed mission reports failure truthfully without unhandled crash."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "math_utils.py").write_text("def add(a: int, b: int) -> int:\n    return a - b\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo, check=True)

    # Configure a mock agy that fails
    agy_script = _make_mock_agy(tmp_path / "bin", success=False)
    monkeypatch.setenv("AMAURA_ANTIGRAVITY_COMMAND", str(agy_script))
    monkeypatch.setenv("AMAURA_VERIFIER_MODE", "host")
    monkeypatch.setenv("AMAURA_ALLOW_HOST_VERIFICATION", "1")
    monkeypatch.setenv("AMAURA_ANTIGRAVITY_REQUIRE_AUTONOMY_SETTINGS", "0")
    monkeypatch.setenv("AMAURA_ANTIGRAVITY_REQUIRE_MODEL_PROVENANCE", "1")
    monkeypatch.setenv("AMAURA_PROVIDER_RECEIPT_KEY", "a" * 32)

    prompt = "Fix the failing implementation in this repository with the smallest correct change."
    output = _run_cli(prompt, repo, monkeypatch, capsys)
    assert ("not complete" in output.lower() or "failed" in output.lower() or "escalation" in output.lower()), f"Expected failure message in output: {output}"


def test_regression_g_no_duplicate_execution_when_leader_lease_held(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Regression Test G: No duplicate execution when mission runner leader lock is held."""
    from jarvis.tools.amaura import get_control_plane

    data_dir = tmp_path / "amaura_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AMAURA_DATA_DIR", str(data_dir))
    from jarvis.tools.amaura import reset_control_plane

    reset_control_plane()
    control = get_control_plane()

    runner = MissionRunner(control)
    # Simulate holding the leader lease in another process
    with runner._leader_lock() as leader_1:
        assert leader_1 is True, "First leader lock should succeed"
        # Second attempt must return False without executing duplicate work
        with runner._leader_lock() as leader_2:
            assert leader_2 is False, "Concurrent leader lock should fail-closed and return False"
