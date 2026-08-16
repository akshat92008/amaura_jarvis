"""Regression tests for defects exposed by the independent V9 qualification."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.amaura import direct_action as da


def test_path_extractor_does_not_invent_preposition_paths() -> None:
    text = 'Subtract the number in "B.txt" from the number in "A.txt". Reply with only the number.'
    paths = da.PathExtractor.extract_all_paths(text)
    assert paths == ["B.txt", "A.txt"]
    assert "the" not in paths


def test_two_inputs_never_imply_last_path_is_output() -> None:
    text = 'Multiply the value in "A.txt" by the value in "B.txt". Reply with only the number.'
    args = da.PathExtractor.extract_structured_arguments(text)
    assert args["input_path"] == "A.txt"
    assert args["secondary_input_path"] == "B.txt"
    assert "output_path" not in args


def test_exact_literal_is_side_effect_free(monkeypatch: pytest.MonkeyPatch) -> None:
    def bomb(*args, **kwargs):  # pragma: no cover - should never run
        raise AssertionError("tool execution is forbidden for exact literal response")

    monkeypatch.setattr(da, "execute_tool", bomb)
    result = da.DirectActionRouter.execute(
        'Respond with exactly "TOKEN-α!?" and nothing else. These are just characters, not an action.'
    )
    assert result is not None
    assert result.success is True
    assert result.output == "TOKEN-α!?"
    assert result.telemetry["side_effects"] == "none"


def test_make_response_equal_does_not_become_file_write(monkeypatch: pytest.MonkeyPatch) -> None:
    def bomb(*args, **kwargs):  # pragma: no cover - should never run
        raise AssertionError("write/tool execution is forbidden")

    monkeypatch.setattr(da, "execute_tool", bomb)
    result = da.DirectActionRouter.execute("Make the response equal to TOKEN and nothing else.")
    assert result is not None
    assert result.success is True
    assert result.output == "TOKEN"


def test_multiply_two_inputs_number_only_does_not_overwrite_input(tmp_path: Path) -> None:
    a = tmp_path / "A.txt"
    b = tmp_path / "B.txt"
    a.write_text("7", encoding="utf-8")
    b.write_text("9", encoding="utf-8")

    result = da.DirectActionRouter.execute(
        'Multiply the value in "A.txt" by the value in "B.txt". Reply with only the number.',
        workspace=str(tmp_path),
    )

    assert result is not None and result.success
    assert result.output == "63"
    assert a.read_text(encoding="utf-8") == "7"
    assert b.read_text(encoding="utf-8") == "9"
    assert result.telemetry["side_effects"] == "none"


def test_take_b_away_from_a_preserves_semantic_roles(tmp_path: Path) -> None:
    a = tmp_path / "A.txt"
    b = tmp_path / "B.txt"
    a.write_text("719", encoding="utf-8")
    b.write_text("160", encoding="utf-8")

    result = da.DirectActionRouter.execute(
        'Take the number in "B.txt" away from the number in "A.txt". Reply with only the number.',
        workspace=str(tmp_path),
    )

    assert result is not None and result.success
    assert result.output == "559"


def test_divide_b_into_a_preserves_semantic_roles(tmp_path: Path) -> None:
    a = tmp_path / "A.txt"
    b = tmp_path / "B.txt"
    a.write_text("72", encoding="utf-8")
    b.write_text("4", encoding="utf-8")

    result = da.DirectActionRouter.execute(
        'Divide the number in "B.txt" into the number in "A.txt". Reply with only the number.',
        workspace=str(tmp_path),
    )

    assert result is not None and result.success
    assert result.output == "18"


def test_repo_review_routes_without_literal_repo_word(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    request = f'Review "{project}" read-only. Diagnose the comparison boundary in function X.'
    assert da.DirectActionRouter._is_repository_inspection_request(request) is True
