from __future__ import annotations

import json

import pytest

from jarvis.amaura.direct_action import DirectActionRouter
from jarvis.tools.security import tool_workspace


@pytest.mark.parametrize("path_word", ["add", "sum", "total", "times", "multiply", "divide", "difference"])
def test_arithmetic_words_inside_paths_cannot_change_json_extraction(tmp_path, path_word: str):
    input_path = tmp_path / f"device_{path_word}_source.txt"
    output_path = tmp_path / "device_result.json"
    input_path.write_text(
        "device: thermostat_alpha\nserial: SN-ABCDEF\nstatus: active\n",
        encoding="utf-8",
    )

    prompt = f"Read from '{input_path}', extract fields, and save output to '{output_path}'"
    with tool_workspace(tmp_path):
        result = DirectActionRouter.execute(prompt, workspace=str(tmp_path))

    assert result is not None
    assert result.success is True
    assert result.telemetry["requested_operation"] == "delimited_table_to_json"
    assert json.loads(output_path.read_text(encoding="utf-8")) == {
        "device": "thermostat_alpha",
        "serial": "SN-ABCDEF",
        "status": "active",
    }
