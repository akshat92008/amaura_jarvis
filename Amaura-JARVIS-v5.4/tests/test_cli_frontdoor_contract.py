from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from jarvis import cli
from jarvis.agent import JarvisAgent


def _run_cli(prompt: str, working_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> str:
    """Helper to execute the public CLI main() function synchronously in a test workspace."""
    data_dir = working_dir.parent / f"{working_dir.name}_amaura_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AMAURA_DATA_DIR", str(data_dir))
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
