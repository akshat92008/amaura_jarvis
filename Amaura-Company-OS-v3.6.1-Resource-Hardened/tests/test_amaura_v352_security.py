from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from jarvis.amaura.tool_governance import READ_ONLY_TOOLS, legacy_tool_allowed
from jarvis.tools.registry import execute_tool
from jarvis.tools.result import parse_tool_result
from jarvis.tools.security import tool_workspace


def test_read_only_mode_excludes_git_history_and_diff():
    assert "git_diff" not in READ_ONLY_TOOLS
    assert "git_log" not in READ_ONLY_TOOLS
    with patch.dict(os.environ, {"JARVIS_LEGACY_TOOL_MODE": "read_only"}, clear=False):
        assert not legacy_tool_allowed("git_diff")
        assert not legacy_tool_allowed("git_log")
        assert legacy_tool_allowed("git_status")


def test_tool_registry_rejects_wrong_types_and_extra_properties():
    wrong_type = parse_tool_result(execute_tool("git_log", {"count": "10"}))
    assert not wrong_type.ok
    assert wrong_type.code == "INVALID_TOOL_ARGUMENTS"

    smuggled = parse_tool_result(execute_tool("git_log", {"count": 10, "unexpected": "value"}))
    assert not smuggled.ok
    assert smuggled.code == "INVALID_TOOL_ARGUMENTS"


def test_git_argument_injection_is_not_executed(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    marker = tmp_path / "pwned"
    payload = f"HEAD; touch {marker}"
    with tool_workspace(repo):
        result = parse_tool_result(execute_tool("git_diff", {"target": payload, "cwd": str(repo)}))
    assert not marker.exists()
    assert not result.ok


def test_packaged_python_has_no_shell_true():
    root = Path(__file__).resolve().parents[1] / "jarvis"
    findings = []
    for path in root.rglob("*.py"):
        if "shell=True" in path.read_text(encoding="utf-8", errors="ignore"):
            findings.append(str(path.relative_to(root.parent)))
    assert findings == []


def test_startup_copy_does_not_claim_uncertified_autonomy():
    root = Path(__file__).resolve().parents[1] / "jarvis"
    text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in root.rglob("*")
        if path.is_file() and path.suffix in {".py", ".js", ".html"}
    )
    assert "All systems operational" not in text
    assert "J.A.R.V.I.S. is fully autonomous" not in text


def test_installation_resources_are_embedded_and_version_aligned():
    from jarvis.amaura import cli

    package_resources = Path(cli.__file__).resolve().parent / "resources"
    template = package_resources / "env.amaura.example"
    dockerfile = package_resources / "amaura-sandbox.Dockerfile"
    assert template.is_file()
    assert dockerfile.is_file()
    text = dockerfile.read_text(encoding="utf-8")
    assert "mypy==1.20.2" in text
    assert "pytest==9.1.1" in text
    assert "ruff==0.16.0" in text


def test_static_doctor_does_not_require_runtime_initialisation(monkeypatch):
    from jarvis.amaura import cli

    monkeypatch.setattr(cli, "command_doctor", lambda args: 0)
    parser = cli.build_parser()
    args = parser.parse_args(["doctor", "--static"])
    assert args.command == "doctor"
    assert args.static is True


def test_environment_bootstrap_generates_distinct_non_placeholder_authorities(monkeypatch, tmp_path):
    from jarvis.amaura import cli

    monkeypatch.setattr(cli, "REPOSITORY_ROOT", tmp_path)
    rendered = cli._render_env_template()
    values = {}
    for line in rendered.splitlines():
        if "=" in line and not line.startswith("#"):
            name, value = line.split("=", 1)
            values[name] = value
    authority_names = sorted(cli._SECRET_NAMES)
    authority_values = [values[name] for name in authority_names]
    assert all(authority_values)
    assert len(set(authority_values)) == len(authority_values)
    assert values["AMAURA_REVIEWER_KEYS"].startswith("qa-reviewer:")
    assert cli._SECRET_PLACEHOLDER not in rendered
