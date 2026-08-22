from pathlib import Path

from jarvis.tools.coding import tool_edit_file, tool_list_directory, tool_run_command, tool_write_file
from jarvis.tools.security import tool_workspace


def test_mutating_coding_helpers_reject_workspace_escape_before_side_effect(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    with tool_workspace(tmp_path):
        assert "Path escapes approved workspace" in tool_write_file("../outside.txt", "blocked")
        assert "Path escapes approved workspace" in tool_edit_file("../outside.txt", "", "blocked")
        assert "Path escapes approved workspace" in tool_list_directory("..")
        assert "Path escapes approved workspace" in tool_run_command("pwd", cwd="..")
    assert not outside.exists()


def test_mutating_coding_helpers_allow_scoped_file_work(tmp_path: Path) -> None:
    with tool_workspace(tmp_path):
        assert tool_write_file("nested/value.txt", "first").startswith("✅")
        assert tool_edit_file("nested/value.txt", "first", "second") == "✅ Edited value.txt"
        assert "second" in (tmp_path / "nested" / "value.txt").read_text(encoding="utf-8")
        assert tool_run_command("pwd", cwd="nested").strip() == str(tmp_path / "nested")
