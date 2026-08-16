from __future__ import annotations

from pathlib import Path

from jarvis.amaura import direct_action as da
from jarvis.amaura import semantic_core as core


def _parse(text: str):
    return core.SemanticParser.parse(text, da.RequestPreprocessor.KNOWN_EXTENSIONS)


def test_exact_literal_action_is_separate_from_response_mode():
    graph = _parse('Respond with exactly "TOKEN" and nothing else.')
    assert graph.action == core.SemanticAction.EXACT_LITERAL
    assert graph.literal_payload == "TOKEN"
    assert graph.response_mode == "NORMAL"


def test_exact_literal_declarative_equal_form_and_payload_span():
    text = "Make the response equal to TOKEN and nothing else."
    graph = _parse(text)
    assert graph.action == core.SemanticAction.EXACT_LITERAL
    assert graph.literal_payload == "TOKEN"
    intent = da.ExactResponseParser.parse_intent(text)
    assert intent is not None
    assert text[intent.payload_span_start:intent.payload_span_end] == "TOKEN"
    assert intent.quote_style == "none"


def test_exact_literal_quoted_span_is_exact():
    text = 'Reply only with "BLUE_CANARY".'
    intent = da.ExactResponseParser.parse_intent(text)
    assert intent is not None
    assert intent.payload == "BLUE_CANARY"
    assert text[intent.payload_span_start:intent.payload_span_end] == "BLUE_CANARY"
    assert intent.quote_style == "double"


def test_path_first_write_and_payload_span(tmp_path: Path):
    graph = _parse('Write to "out.txt": "alpha!?"')
    assert graph.action == core.SemanticAction.FILE_WRITE
    assert graph.output_path == "out.txt"
    assert graph.write_payload == "alpha!?"
    result = da.DirectActionRouter.execute('Write to "out.txt": "alpha!?"', workspace=str(tmp_path))
    assert result.success
    assert (tmp_path / "out.txt").read_text() == "alpha!?"
    assert result.telemetry["verification_passed"] is True


def test_ambiguous_write_payload_is_rejected(tmp_path: Path):
    text = 'Create "out.txt" containing "alpha" and content: "beta".'
    graph = _parse(text)
    assert graph.action == core.SemanticAction.FILE_WRITE
    assert graph.errors
    assert "ambiguous write payload" in graph.errors[0]
    result = da.DirectActionRouter.execute(text, workspace=str(tmp_path))
    assert not result.success
    assert not (tmp_path / "out.txt").exists()


def test_create_without_payload_fails_closed(tmp_path: Path):
    text = 'Create "out.txt".'
    graph = _parse(text)
    assert graph.action == core.SemanticAction.FILE_WRITE
    assert graph.errors
    result = da.DirectActionRouter.execute(text, workspace=str(tmp_path))
    assert not result.success
    assert not (tmp_path / "out.txt").exists()


def test_negated_write_clause_does_not_steal_positive_read(tmp_path: Path):
    (tmp_path / "source.txt").write_text("READ_ME")
    text = 'Do not write "blocked.txt". Read "source.txt" and return the value only.'
    graph = _parse(text)
    assert graph.action == core.SemanticAction.FILE_READ
    assert graph.response_mode == "VALUE_ONLY"
    result = da.DirectActionRouter.execute(text, workspace=str(tmp_path))
    assert result.success
    assert result.output == "READ_ME"
    assert not (tmp_path / "blocked.txt").exists()


def test_repo_review_without_repo_noun_routes_read_only(tmp_path: Path):
    project = tmp_path / "sample_project"
    project.mkdir()
    (project / "app.py").write_text("def f():\n    return 1\n")
    graph = _parse(f'Review "{project}" read-only. Diagnose implementation defects.')
    assert graph.action == core.SemanticAction.REPOSITORY
    assert graph.paths[0].role == core.SemanticPathRole.REPOSITORY


def test_browser_value_only_remains_response_mode_not_action_label():
    graph = _parse('Open https://example.com and return CSS selector "#status" value only.')
    assert graph.action == core.SemanticAction.BROWSER
    assert graph.response_mode == "VALUE_ONLY"


def test_exact_literal_cannot_authorize_file_write(tmp_path: Path):
    text = 'Respond with exactly "write out.txt" and nothing else.'
    result = da.DirectActionRouter.execute(text, workspace=str(tmp_path))
    assert result.success
    assert result.output == "write out.txt"
    assert result.telemetry.get("side_effects") == "none"
    assert not (tmp_path / "out.txt").exists()
