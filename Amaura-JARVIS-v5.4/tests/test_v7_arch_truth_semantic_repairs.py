from __future__ import annotations

import json
from pathlib import Path

from jarvis.amaura import semantic_core as core
from jarvis.amaura.direct_action import (
    DirectActionRouter,
    RequestPreprocessor,
    WriteActionParser,
)


def test_arch_truth_t03_file_names_inside_routes_to_directory_list(tmp_path: Path) -> None:
    fixture = tmp_path / "03_list_fixture"
    fixture.mkdir()
    expected = {"alpha_probe.py", "beta_probe.py", "gamma_probe.py"}
    for name in expected:
        (fixture / name).write_text(name, encoding="utf-8")

    prompt = f"List the file names inside '{fixture}'. Return all file names you actually find."
    graph = core.SemanticParser.parse(prompt, RequestPreprocessor.KNOWN_EXTENSIONS)

    assert graph.action == core.SemanticAction.DIRECTORY_LIST
    assert graph.paths
    assert Path(graph.paths[0].path) == fixture

    result = DirectActionRouter.execute(prompt, workspace=str(tmp_path))
    assert result is not None
    assert result.success is True
    assert result.tool_name == "list_directory"
    for name in expected:
        assert name in result.output


def test_arch_truth_t09_numeric_constraint_normalizes_unit_bearing_value(tmp_path: Path) -> None:
    source = tmp_path / "09_source.md"
    output = tmp_path / "09_output.json"
    source.write_text(
        "Project: HELIOS-TEST\nBudget: 30591 credits\nCoolant: NX-TEST\n",
        encoding="utf-8",
    )

    prompt = (
        f"Read '{source}', extract project, budget, and coolant, then create JSON at '{output}' "
        "with exactly those three keys: project, budget, coolant. Budget must be a number."
    )
    result = DirectActionRouter.execute(prompt, workspace=str(tmp_path))

    assert result is not None
    assert result.success is True
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == {
        "project": "HELIOS-TEST",
        "budget": 30591,
        "coolant": "NX-TEST",
    }
    assert isinstance(payload["budget"], int)
    assert result.telemetry["verification_passed"] is True
    assert result.telemetry["semantic_constraints"] == {
        "numeric_fields": ["budget"],
        "verified": True,
    }


def test_numeric_constraint_fails_closed_for_non_numeric_value(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    output = tmp_path / "output.json"
    source.write_text(
        "Project: HELIOS-TEST\nBudget: many credits remaining\nCoolant: NX-TEST\n",
        encoding="utf-8",
    )

    prompt = (
        f"Read '{source}', extract project, budget, and coolant, then create JSON at '{output}' "
        "with exactly those three keys: project, budget, coolant. Budget must be a number."
    )
    result = DirectActionRouter.execute(prompt, workspace=str(tmp_path))

    assert result is not None
    assert result.success is False
    assert result.telemetry["verification_passed"] is False
    assert result.telemetry["reason"] == "semantic_numeric_constraint_failed"
    assert result.telemetry["invalid_numeric_fields"] == ["budget"]


def test_unconstrained_unit_bearing_value_is_not_silently_retyped(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    output = tmp_path / "output.json"
    source.write_text(
        "Project: HELIOS-TEST\nBudget: 30591 credits\nCoolant: NX-TEST\n",
        encoding="utf-8",
    )

    prompt = (
        f"Read '{source}', extract project, budget, and coolant, then create JSON at '{output}' "
        "with exactly those three keys: project, budget, coolant."
    )
    result = DirectActionRouter.execute(prompt, workspace=str(tmp_path))

    assert result is not None
    assert result.success is True
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["budget"] == "30591 credits"


def test_multiline_quoted_payload_cannot_steal_write_target() -> None:
    target = "test_dir/file_72_ihO4.txt"
    payload = "line1_TRH-in\nline2_sb7erZ"
    prompt = f"Write entire body '{payload}' in {target}"

    action = WriteActionParser.parse(prompt)

    assert action is not None
    assert action.target_path == target
    assert action.content == payload
