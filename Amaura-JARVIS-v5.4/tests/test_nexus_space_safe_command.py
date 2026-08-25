from __future__ import annotations

import sys
from pathlib import Path

from jarvis.amaura.nexus_bridge import NexusDeliveryAdapter


def test_legacy_nexus_command_supports_unquoted_executable_path_with_spaces(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime with spaces"
    runtime_dir.mkdir()
    executable = runtime_dir / "python"
    executable.symlink_to(Path(sys.executable))

    adapter = NexusDeliveryAdapter(command=f"{executable} --version")

    assert adapter.configured is True
    assert adapter._command_parts() == [str(executable), "--version"]
