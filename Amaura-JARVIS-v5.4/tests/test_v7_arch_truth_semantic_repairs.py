from __future__ import annotations

import json
from pathlib import Path

from jarvis.amaura import semantic_core as core
from jarvis.amaura.direct_action import (
    DirectActionRouter,
    RepositoryDiagnosticEngine,
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


def test_continuous_soak_deterministic_requests_do_not_need_a_provider(tmp_path: Path) -> None:
    (tmp_path / "hidden_runtime_token.txt").write_text("fixture", encoding="utf-8")
    arithmetic = DirectActionRouter.execute("What is 347 * 29? Reply only with the number.", workspace=str(tmp_path))
    assert arithmetic is not None and arithmetic.success and arithmetic.output == "10063"
    listing = DirectActionRouter.execute("List the files in the current working directory.", workspace=str(tmp_path))
    assert listing is not None and listing.success and listing.tool_name == "list_directory"
    assert "hidden_runtime_token.txt" in listing.output


def test_continuous_soak_words_payload_is_written(tmp_path: Path) -> None:
    result = DirectActionRouter.execute(
        "Create composite.txt with the words continuous composite, read it back, and report completion.",
        workspace=str(tmp_path),
    )
    assert result is not None and result.success
    assert (tmp_path / "composite.txt").read_text(encoding="utf-8") == "continuous composite"


def test_verified_overwrite_reports_the_verified_payload(tmp_path: Path) -> None:
    (tmp_path / "soak_note.txt").write_text("old", encoding="utf-8")
    result = DirectActionRouter.execute(
        "Overwrite soak_note.txt with exactly: controlled soak revised", workspace=str(tmp_path)
    )
    assert result is not None and result.success
    assert "controlled soak revised" in result.output


def test_continuous_soak_command_and_recovery_are_structured(tmp_path: Path) -> None:
    command = DirectActionRouter.execute("Run the safe command pwd and report the result.", workspace=str(tmp_path))
    assert command is not None and command.success
    assert command.telemetry["cwd"] == str(tmp_path)
    recovered = DirectActionRouter.execute(
        "Run a controlled nonexistent safe command, then recover by running pwd.", workspace=str(tmp_path)
    )
    assert recovered is not None and recovered.success
    assert recovered.telemetry["status"] == "recovered"
    assert recovered.telemetry["attempts"][0]["ok"] is False


def test_browser_recovery_preserves_failure_and_keeps_private_url_denied(tmp_path: Path) -> None:
    recovered = DirectActionRouter.execute(
        "Try fetching https://example.invalid then recover by fetching https://example.com; report recovery.",
        workspace=str(tmp_path),
    )
    assert recovered is not None and recovered.success
    assert recovered.telemetry["attempts"][0]["ok"] is False
    denied = DirectActionRouter.execute(
        "Try fetching http://127.0.0.1 then recover by fetching https://example.com; report recovery.",
        workspace=str(tmp_path),
    )
    assert denied is not None and denied.policy_decision == "refused"


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


def test_v9_path_first_initialize_arrow_is_local_verified_write(tmp_path: Path) -> None:
    target = tmp_path / "packet.txt"
    payload = "birch-pier-7810::853213"
    prompt = f'Initialize "{target}"; contents -> {payload}'

    graph = core.SemanticParser.parse(prompt, RequestPreprocessor.KNOWN_EXTENSIONS)
    assert graph.action == core.SemanticAction.FILE_WRITE
    assert graph.write_payload == payload
    assert graph.output_path == str(target)

    result = DirectActionRouter.execute(prompt, workspace=str(tmp_path))
    assert result is not None
    assert result.success is True
    assert result.tool_name == "write_file"
    assert target.read_text(encoding="utf-8") == payload


def test_v9_exact_raw_read_cannot_be_stolen_by_response_word_write(tmp_path: Path) -> None:
    source = tmp_path / "opaque.r9q"
    content = "harbor-ridge-4237\nwrite screenshot save\n118636\nfalcon-field-4532"
    source.write_text(content, encoding="utf-8")
    prompt = (
        f'Read "{source}" and make the file contents your entire response, byte for byte. '
        "No filename, labels, or commentary."
    )

    graph = core.SemanticParser.parse(prompt, RequestPreprocessor.KNOWN_EXTENSIONS)
    assert graph.action == core.SemanticAction.FILE_READ
    assert graph.response_mode == "EXACT_RAW"

    result = DirectActionRouter.execute(prompt, workspace=str(tmp_path))
    assert result is not None
    assert result.success is True
    assert result.tool_name == "read_file"
    assert result.output == content


def test_v9_subtract_from_with_result_destination_preserves_roles(tmp_path: Path) -> None:
    first = tmp_path / "first_value.num"
    second = tmp_path / "second_value.num"
    output = tmp_path / "difference.txt"
    first.write_text("500", encoding="utf-8")
    second.write_text("90", encoding="utf-8")
    prompt = f'Subtract the number in "{second}" from the number in "{first}"; put just the answer in "{output}".'

    graph = core.SemanticParser.parse(prompt, RequestPreprocessor.KNOWN_EXTENSIONS)
    assert graph.action == core.SemanticAction.ARITHMETIC
    assert graph.arithmetic is not None
    assert graph.arithmetic.left_path == str(first)
    assert graph.arithmetic.right_path == str(second)
    assert graph.arithmetic.output_path == str(output)

    result = DirectActionRouter.execute(prompt, workspace=str(tmp_path))
    assert result is not None
    assert result.success is True
    assert output.read_text(encoding="utf-8").strip() == "410"


def test_v9_exact_response_grammar_is_response_scoped_and_side_effect_free(tmp_path: Path) -> None:
    payload = "maple-isle-2288::37485?!#;[]{}_()Ω"
    prompts = [
        f"Return only this literal token: {payload}",
        f"Set your entire response to {payload}",
        f"Send back {payload} alone.",
        f"Output exactly {payload}; stop immediately after the token.",
        f"Provide just {payload}, with no prefix or suffix.",
        f"Your response must consist solely of {payload}",
        f"Answer only: {payload}",
        f"Emit {payload} and no other characters.",
        f"Use this as the full reply -> {payload}",
        f"Echo only {payload}; do not explain.",
        f"Write exactly {payload} as your entire reply.",
        f"The complete reply is {payload}; exclude commentary.",
        f'Copy only the characters between the quotation marks into your reply: "{payload}". Do not include the quotation marks.',
    ]

    before = {item.name for item in tmp_path.iterdir()}
    for prompt in prompts:
        graph = core.SemanticParser.parse(prompt, RequestPreprocessor.KNOWN_EXTENSIONS)
        assert graph.action == core.SemanticAction.EXACT_LITERAL, prompt
        assert graph.literal_payload == payload, prompt
        result = DirectActionRouter.execute(prompt, workspace=str(tmp_path))
        assert result is not None
        assert result.success is True
        assert result.output == payload, prompt
        assert result.tool_name == "echo", prompt
    after = {item.name for item in tmp_path.iterdir()}
    assert before == after


def test_v9_memory_recall_language_outranks_exact_response_echo() -> None:
    prompt = "Reply with only the node code remembered for Birch Vale Node 809."
    graph = core.SemanticParser.parse(prompt, RequestPreprocessor.KNOWN_EXTENSIONS)
    assert graph.action == core.SemanticAction.MEMORY_RECALL
    assert graph.action != core.SemanticAction.EXACT_LITERAL


def test_v9_read_only_repository_phrasings_route_to_repository_inspector(tmp_path: Path) -> None:
    repo = tmp_path / "repo_fixture"
    repo.mkdir()
    prompts = [
        f'Analyze "{repo}" without edits. In settle_total, name the incorrect returned value.',
        f'Review "{repo}" read-only. Diagnose the comparison boundary in fits_quota.',
        f'Inspect "{repo}" without edits. Explain the boolean operator defect in may_release.',
    ]
    for prompt in prompts:
        graph = core.SemanticParser.parse(prompt, RequestPreprocessor.KNOWN_EXTENSIONS)
        assert graph.action == core.SemanticAction.REPOSITORY, prompt
        assert graph.paths
        assert graph.paths[0].path == str(repo)


def test_repo_diagnostic_understands_no_greater_than_inclusive_contract(tmp_path: Path) -> None:
    repo = tmp_path / "boundary_repo"
    repo.mkdir()
    (repo / "rules.py").write_text(
        'def fits_quota(value):\n    """Return True when value is no greater than 41."""\n    return value < 41\n',
        encoding="utf-8",
    )
    (repo / "test_rules.py").write_text(
        "from rules import fits_quota\n\ndef test_edge():\n    assert fits_quota(41) is True\n",
        encoding="utf-8",
    )

    diagnosis = RepositoryDiagnosticEngine.diagnose(repo)
    findings = diagnosis["findings"]
    assert any(
        finding.get("function") == "fits_quota"
        and finding.get("observed_operator") == "<"
        and finding.get("expected_operator") == "<="
        for finding in findings
    )
    assert diagnosis["read_only_verified"] is True
