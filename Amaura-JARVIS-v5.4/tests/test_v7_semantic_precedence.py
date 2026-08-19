from __future__ import annotations

from pathlib import Path

from jarvis.amaura import semantic_core as core
from jarvis.amaura.direct_action import DirectActionRouter, RequestPreprocessor


def _parse(text: str):
    return core.SemanticParser.parse(text, RequestPreprocessor.KNOWN_EXTENSIONS)


def test_v7_precedence_preserves_browser_before_filesystem() -> None:
    graph = _parse("Open http://127.0.0.1:43210 and give me its title")
    assert graph.action == core.SemanticAction.BROWSER
    assert graph.browser is not None
    assert graph.browser.url == "http://127.0.0.1:43210"
    assert graph.browser.want_title is True


def test_v7_precedence_preserves_directory_contents_route(tmp_path: Path) -> None:
    folder = tmp_path / "my.dotted.folder"
    folder.mkdir()
    (folder / "child.txt").write_text("x", encoding="utf-8")

    graph = _parse(f"Show the contents of '{folder}'")
    assert graph.action == core.SemanticAction.DIRECTORY_LIST

    result = DirectActionRouter.execute(f"Show the contents of '{folder}'", workspace=str(tmp_path))
    assert result is not None
    assert result.success is True
    assert result.tool_name == "list_directory"
    assert "child.txt" in result.output


def test_v7_precedence_preserves_file_inspect_paraphrase(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_text("payload", encoding="utf-8")

    graph = _parse(f"Inspect the contents of '{source}'")
    assert graph.action == core.SemanticAction.FILE_READ

    result = DirectActionRouter.execute(f"Inspect the contents of '{source}'", workspace=str(tmp_path))
    assert result is not None
    assert result.success is True
    assert result.tool_name == "read_file"
    assert "payload" in result.output


def test_v7_precedence_preserves_table_transform(tmp_path: Path) -> None:
    source = tmp_path / "table.csv"
    output = tmp_path / "output.json"
    source.write_text("id,name\n1,Alice\n", encoding="utf-8")

    graph = _parse(f"read table from {source} and convert to json at {output}")
    assert graph.action == core.SemanticAction.FILE_WRITE
    assert graph.transform_plan is not None
    assert graph.output_path == str(output)


def test_v7_precedence_preserves_existing_exact_response_grammar() -> None:
    token = "TOKEN_V7_PRECEDENCE_123"
    graph = _parse(f"return only the token {token}")
    assert graph.action == core.SemanticAction.EXACT_LITERAL
    assert graph.literal_payload == token

    result = DirectActionRouter.execute(f"return only the token {token}")
    assert result is not None
    assert result.success is True
    assert result.output == token
    assert result.tool_name == "echo"


def test_v7_precedence_preserves_unquoted_subtract_from_roles(tmp_path: Path) -> None:
    minuend = tmp_path / "base.txt"
    subtrahend = tmp_path / "deduct.txt"
    output = tmp_path / "difference.txt"
    minuend.write_text("100", encoding="utf-8")
    subtrahend.write_text("35", encoding="utf-8")

    prompt = f"subtract {subtrahend} from {minuend} and save to {output}"
    graph = _parse(prompt)
    assert graph.action == core.SemanticAction.ARITHMETIC
    assert graph.arithmetic is not None
    assert graph.arithmetic.left_path == str(minuend)
    assert graph.arithmetic.right_path == str(subtrahend)
    assert graph.arithmetic.output_path == str(output)


def test_v7_precedence_preserves_ambiguous_write_fail_closed(tmp_path: Path) -> None:
    target = tmp_path / "ambiguous.txt"
    prompt = f"Write either 'ALPHA' or 'BETA' to '{target}'. If ambiguous, do not choose."
    graph = _parse(prompt)
    assert graph.action == core.SemanticAction.FILE_WRITE
    assert graph.errors

    result = DirectActionRouter.execute(prompt, workspace=str(tmp_path))
    assert result is not None
    assert result.success is False
    assert not target.exists()
