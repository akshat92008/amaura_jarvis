"""Compatibility tests proving legacy healthy paths cannot bypass Phase 9 safety."""
from pathlib import Path

from jarvis.amaura import direct_action as da
from jarvis.amaura.semantic_core import SemanticAction, SemanticParser


EXTENSIONS = da.RequestPreprocessor.KNOWN_EXTENSIONS


def test_direct_exact_parser_is_same_semantic_graph() -> None:
    result = da.ExactResponseParser.parse('Respond with exactly "TOKEN" and nothing else.')
    assert result is not None and result.success
    assert result.output == "TOKEN"
    assert result.execution_type == "semantic_graph"
    assert result.telemetry["side_effects"] == "none"


def test_unquoted_absolute_subtract_from_preserves_roles(tmp_path: Path) -> None:
    a = tmp_path / "base.txt"
    b = tmp_path / "deduct.txt"
    out = tmp_path / "difference.txt"
    graph = SemanticParser.parse(f"subtract {b} from {a} and save to {out}", EXTENSIONS)
    assert graph.action is SemanticAction.ARITHMETIC
    assert graph.arithmetic is not None
    assert graph.arithmetic.left_path == str(a)
    assert graph.arithmetic.right_path == str(b)
    assert graph.arithmetic.output_path == str(out)
    assert graph.arithmetic.left_role == "minuend"
    assert graph.arithmetic.right_role == "subtrahend"


def test_unquoted_absolute_subtract_executes_phase8_api_shape(tmp_path: Path) -> None:
    a = tmp_path / "base.txt"
    b = tmp_path / "deduct.txt"
    out = tmp_path / "difference.txt"
    a.write_text("100", encoding="utf-8")
    b.write_text("35", encoding="utf-8")
    result = da.DirectActionRouter.execute(
        f"subtract {b} from {a} and save to {out}",
        workspace=str(tmp_path),
    )
    assert result is not None and result.success
    assert out.read_text(encoding="utf-8") == "65"


def test_unquoted_absolute_divide_by_executes_phase8_api_shape(tmp_path: Path) -> None:
    numerator = tmp_path / "num.txt"
    denominator = tmp_path / "den.txt"
    out = tmp_path / "quotient.txt"
    numerator.write_text("200", encoding="utf-8")
    denominator.write_text("8", encoding="utf-8")
    result = da.DirectActionRouter.execute(
        f"divide {numerator} by {denominator} and save to {out}",
        workspace=str(tmp_path),
    )
    assert result is not None and result.success
    assert out.read_text(encoding="utf-8") == "25"


def test_legacy_transform_without_explicit_output_is_not_authorized(tmp_path: Path) -> None:
    source = tmp_path / "values.csv"
    source.write_text("name,value\na,1\n", encoding="utf-8")
    prompt = f"Convert {source} to JSON"
    assert da.DirectActionRouter.can_handle(prompt) is False
    assert da.DirectActionRouter.execute(prompt, workspace=str(tmp_path)) is None


def test_legacy_transform_with_explicit_output_remains_available(tmp_path: Path) -> None:
    source = tmp_path / "values.csv"
    output = tmp_path / "values.json"
    source.write_text("name,value\na,1\n", encoding="utf-8")
    prompt = f"Convert {source} to JSON and save the result to {output}"
    assert da.DirectActionRouter.can_handle(prompt) is True
