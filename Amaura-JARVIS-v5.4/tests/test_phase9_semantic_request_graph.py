"""Adversarial qualification for the Phase 9 SemanticRequestGraph."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.amaura import direct_action as da
from jarvis.amaura.semantic_core import SemanticAction, SemanticParser

EXTENSIONS = da.RequestPreprocessor.KNOWN_EXTENSIONS


def parse(text: str):
    return SemanticParser.parse(text, EXTENSIONS)


@pytest.mark.parametrize(
    ("text", "payload"),
    [
        ('Respond with exactly "TOKEN" and nothing else.', "TOKEN"),
        ('Reply with exactly "TOKEN-α!?" and nothing more.', "TOKEN-α!?"),
        ("Make the response equal to TOKEN and nothing else.", "TOKEN"),
        ("Echo: HELLO and nothing else", "HELLO"),
    ],
)
def test_exact_literals_are_classified_without_effects(text: str, payload: str) -> None:
    graph = parse(text)
    assert graph.action is SemanticAction.EXACT_LITERAL
    assert graph.literal_payload == payload
    assert graph.paths == []


def test_exact_literal_never_becomes_write(monkeypatch: pytest.MonkeyPatch) -> None:
    def bomb(*args, **kwargs):
        raise AssertionError("no tool may execute for exact response")

    monkeypatch.setattr(da, "execute_tool", bomb)
    result = da.DirectActionRouter.execute('Respond with exactly "write_file capture screen" and nothing else.')
    assert result is not None and result.success
    assert result.output == "write_file capture screen"
    assert result.telemetry["side_effects"] == "none"


def test_prepositions_do_not_invent_paths() -> None:
    graph = parse('Take the number in "B.txt" away from the number in "A.txt". Reply with only the number.')
    assert [p.path for p in graph.paths] == ["A.txt", "B.txt"]
    assert all(p.path != "the" for p in graph.paths)


def test_two_input_multiply_has_no_implicit_output() -> None:
    graph = parse('Multiply the value in "A.txt" by the value in "B.txt". Reply with only the number.')
    assert graph.action is SemanticAction.ARITHMETIC
    assert graph.arithmetic is not None
    assert graph.arithmetic.output_path == ""
    assert [p.path for p in graph.paths] == ["A.txt", "B.txt"]


def test_subtract_roles_are_semantic_not_textual() -> None:
    graph = parse('Take the number in "B.txt" away from the number in "A.txt". Reply with only the number.')
    assert graph.arithmetic is not None
    assert graph.arithmetic.left_path == "A.txt"
    assert graph.arithmetic.right_path == "B.txt"
    assert graph.arithmetic.left_role == "minuend"
    assert graph.arithmetic.right_role == "subtrahend"


def test_divide_into_roles_are_semantic_not_textual() -> None:
    graph = parse('Divide the number in "B.txt" into the number in "A.txt". Reply with only the number.')
    assert graph.arithmetic is not None
    assert graph.arithmetic.left_path == "A.txt"
    assert graph.arithmetic.right_path == "B.txt"
    assert graph.arithmetic.left_role == "numerator"
    assert graph.arithmetic.right_role == "denominator"


def test_arithmetic_response_only_never_mutates_inputs(tmp_path: Path) -> None:
    (tmp_path / "A.txt").write_text("719", encoding="utf-8")
    (tmp_path / "B.txt").write_text("160", encoding="utf-8")
    result = da.DirectActionRouter.execute(
        'Take the number in "B.txt" away from the number in "A.txt". Reply with only the number.',
        workspace=str(tmp_path),
    )
    assert result is not None and result.success
    assert result.output == "559"
    assert (tmp_path / "A.txt").read_text(encoding="utf-8") == "719"
    assert (tmp_path / "B.txt").read_text(encoding="utf-8") == "160"
    assert result.telemetry["side_effects"] == "none"


def test_divide_into_executes_a_over_b(tmp_path: Path) -> None:
    (tmp_path / "A.txt").write_text("72", encoding="utf-8")
    (tmp_path / "B.txt").write_text("4", encoding="utf-8")
    result = da.DirectActionRouter.execute(
        'Divide the number in "B.txt" into the number in "A.txt". Reply with only the number.',
        workspace=str(tmp_path),
    )
    assert result is not None and result.success
    assert result.output == "18"


def test_explicit_arithmetic_output_is_verified_semantically(tmp_path: Path) -> None:
    (tmp_path / "A.txt").write_text("20", encoding="utf-8")
    (tmp_path / "B.txt").write_text("3", encoding="utf-8")
    result = da.DirectActionRouter.execute(
        'Subtract "B.txt" from "A.txt" and save the result to "C.txt".',
        workspace=str(tmp_path),
    )
    assert result is not None and result.success
    assert (tmp_path / "C.txt").read_text(encoding="utf-8") == "17"
    assert result.telemetry["verification_passed"] is True
    contract = result.telemetry["verification_contract"]
    assert contract["left_role"] == "minuend"
    assert contract["right_role"] == "subtrahend"


def test_write_requires_explicit_payload(tmp_path: Path) -> None:
    result = da.DirectActionRouter.execute('Create "out.txt".', workspace=str(tmp_path))
    assert result is not None and not result.success
    assert "no explicit payload" in result.output
    assert not (tmp_path / "out.txt").exists()


def test_ambiguous_write_reports_competing_payloads_and_does_not_write(tmp_path: Path) -> None:
    result = da.DirectActionRouter.execute(
        'Create "out.txt" containing "alpha" and content: "beta".',
        workspace=str(tmp_path),
    )
    assert result is not None and not result.success
    assert "ambiguous write payload" in result.output
    assert not (tmp_path / "out.txt").exists()


def test_explicit_structured_write_still_works(tmp_path: Path) -> None:
    result = da.DirectActionRouter.execute(
        'Create "nested/out.txt" containing "alpha".',
        workspace=str(tmp_path),
    )
    assert result is not None and result.success
    assert (tmp_path / "nested" / "out.txt").read_text(encoding="utf-8") == "alpha"


def test_repo_review_without_repo_keyword_routes_to_repository(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    graph = parse(f'Review "{project}" read-only. Diagnose the comparison boundary in function threshold.')
    assert graph.action is SemanticAction.REPOSITORY
    assert graph.paths[0].path == str(project)


def test_css_selector_list_is_data_not_action_words() -> None:
    graph = parse(
        'Open https://example.test and report these CSS selectors: ".save-a", ".memory-b", ".open-c", ".screen-d".'
    )
    assert graph.action is SemanticAction.BROWSER
    assert graph.browser is not None
    assert graph.browser.selectors == [".save-a", ".memory-b", ".open-c", ".screen-d"]


def test_browser_uses_registered_schema_and_value_only(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_tool(name: str, arguments: dict):
        calls.append((name, arguments))
        if name == "browser_navigate":
            return {"ok": True, "output": {"title": "Example"}}
        if name == "browser_extract_content":
            return {"ok": True, "output": {"content": "prairie-pier-3538"}}
        raise AssertionError(name)

    monkeypatch.setattr(da, "execute_tool", fake_tool)
    result = da.DirectActionRouter.execute(
        'Open https://example.test and return only the value at CSS selector ".save-a".'
    )
    assert result is not None and result.success
    assert result.output == "prairie-pier-3538"
    extract_calls = [arguments for name, arguments in calls if name == "browser_extract_content"]
    assert extract_calls == [{"url": "https://example.test", "selector": ".save-a"}]
    assert all("field" not in arguments for arguments in extract_calls)


def test_repository_wrong_helper_is_proven_by_value_flow(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "logic.py").write_text(
        "def helper_a(x):\n    return x - 12\n\n"
        "def helper_b(x):\n    return x + 12\n\n"
        "def transform(x):\n    return helper_a(x)\n",
        encoding="utf-8",
    )
    (project / "test_logic.py").write_text(
        "from logic import transform\n\ndef test_transform():\n    assert transform(50) == 62\n",
        encoding="utf-8",
    )
    result = da.RepositoryDiagnosticEngine.diagnose(project)
    finding = result["findings"][0]
    assert finding["category"] == "wrong_helper_call"
    assert finding["called_helper"] == "helper_a"
    assert finding["expected_helper"] == "helper_b"


def test_repository_wrong_return_variable_is_proven_by_value_flow(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "logic.py").write_text(
        "def calculate(x):\n    temp = x - 1\n    total = x + 1\n    return temp\n",
        encoding="utf-8",
    )
    (project / "test_logic.py").write_text(
        "from logic import calculate\n\ndef test_calculate():\n    assert calculate(4) == 5\n",
        encoding="utf-8",
    )
    result = da.RepositoryDiagnosticEngine.diagnose(project)
    finding = result["findings"][0]
    assert finding["category"] == "wrong_returned_variable"
    assert finding["returned_variable"] == "temp"
    assert finding["expected_variable"] == "total"
