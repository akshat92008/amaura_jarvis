"""Final release contracts for the Phase 9 semantic execution boundary.

This module does not add a competing natural-language router. It enforces two
narrow, typed public contracts after the central SemanticRequestGraph exists:

* explicit read -> extract/convert -> explicit JSON output executes as one
  verified transformation contract; and
* exact-response provenance retains the historical ``tool_name='echo'`` value.

Transformation writes remain guarded by the semantic effect scope. An output is
accepted only when mutation language explicitly binds that exact path; path
position never authorizes a side effect.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

_INSTALLED = False


def _install_attr(obj: object, name: str, value: object) -> None:
    setattr(obj, name, value)


def install_semantic_release_contracts() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from jarvis.amaura import direct_action as da
    from jarvis.amaura import semantic_core as core

    current_parse = getattr(core.SemanticParser.parse, "__func__", core.SemanticParser.parse)

    def _explicit_transform_output(text: str, paths: list[str]) -> str:
        lower = text.lower()
        for path in paths:
            escaped = re.escape(path.lower())
            patterns = (
                rf"\b(?:create|make)\s+(?:a\s+)?(?:json\s+|text\s+|output\s+)?file\s+(?:at|to|in)\s+['\"`]?{escaped}",
                rf"\b(?:save|write|store|export)\s+(?:the\s+)?(?:output|result|data|json)?\s*(?:to|at|in|into)\s+['\"`]?{escaped}",
            )
            if any(re.search(pattern, lower, re.IGNORECASE) for pattern in patterns):
                return path
        return ""

    def _transform_contract(text: str, known_extensions: tuple[str, ...]) -> tuple[str, str] | None:
        paths = core.extract_paths(text, known_extensions)
        output = _explicit_transform_output(text, paths)
        has_transform = bool(
            re.search(
                r"\b(?:read|load|fetch)\b.*\b(?:extract|convert|transform)\b|"
                r"\b(?:extract|convert|transform)\b.*\b(?:save|write|create|export)\b",
                text,
                re.IGNORECASE | re.DOTALL,
            )
        )
        inputs = [path for path in paths if path != output]
        if not has_transform or not output or len(inputs) != 1:
            return None
        return inputs[0], output

    def parse_with_workflow_precedence(
        cls: Any,
        text: str,
        known_extensions: tuple[str, ...],
    ) -> Any:
        graph = current_parse(cls, text, known_extensions)
        if _transform_contract(text, known_extensions) is not None:
            return core.SemanticRequestGraph(
                original_text=text,
                action=core.SemanticAction.UNKNOWN,
                response_mode=core._response_mode(text),
                evidence=["explicit_transform_workflow_precedence"],
            )
        return graph

    _install_attr(core.SemanticParser, "parse", classmethod(parse_with_workflow_precedence))

    def _parse_scalar(value: str) -> Any:
        stripped = value.strip()
        if re.fullmatch(r"[-+]?\d+", stripped):
            return int(stripped)
        if re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+)", stripped):
            return float(stripped)
        if stripped.lower() == "true":
            return True
        if stripped.lower() == "false":
            return False
        if stripped.lower() in {"null", "none"}:
            return None
        return stripped

    def _execute_verified_json_transform(text: str, workspace: str) -> Any | None:
        contract = _transform_contract(text, da.RequestPreprocessor.KNOWN_EXTENSIONS)
        if contract is None:
            return None
        input_path, output_path = contract
        if not output_path.lower().endswith(".json"):
            return None
        if not re.search(r"\b(?:extract\s+(?:data|fields)|convert\b|json\b)\b", text, re.IGNORECASE):
            return None

        ws = Path(workspace if workspace else da.workspace_root()).expanduser().resolve()
        effect_token = core._EFFECT_SCOPE.set(frozenset({"write_file"}))
        output_token = core._OUTPUT_SCOPE.set(frozenset({output_path}))
        try:
            with da.tool_workspace(ws):
                resolved_input = da.resolve_workspace_path(input_path, must_exist=True)
                resolved_output = da.resolve_workspace_path(output_path, must_exist=False)

            # Read the authorized input directly from the resolved path. The
            # read_file tool intentionally returns a human-oriented presentation
            # with headers/line numbers; semantic transformation must operate on
            # raw source bytes, and direct reading also keeps verification
            # independent from tool presentation formatting.
            if not resolved_input.is_file():
                raise FileNotFoundError(f"not a regular file: {resolved_input}")
            raw = resolved_input.read_text(encoding="utf-8", errors="replace")

            parsed: dict[str, Any] = {}
            for line in raw.splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                key = key.strip()
                if key:
                    parsed[key] = _parse_scalar(value)
            if not parsed:
                return da.DirectActionResult(
                    False,
                    "Workflow source contained no key:value fields.",
                    execution_type="workflow",
                    tool_name="multi_step_workflow",
                    provider="local-filesystem",
                    telemetry={"reason": "transform_failed", "verification_passed": False},
                )

            payload = json.dumps(parsed, ensure_ascii=False, indent=2)
            expected_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            with da.tool_workspace(ws):
                write_result = da.parse_tool_result(
                    da.execute_tool("write_file", {"path": str(resolved_output), "content": payload})
                )
            if not write_result.ok:
                return da.DirectActionResult(
                    False,
                    f"Workflow write failed: {write_result.error or 'write tool failed'}",
                    execution_type="workflow",
                    tool_name="multi_step_workflow",
                    provider="local-filesystem",
                    telemetry={
                        "reason": "tool_failed",
                        "verification_passed": False,
                        "expected_output_hash": expected_hash,
                        "actual_output_hash": "",
                    },
                )

            try:
                observed_text = resolved_output.read_text(encoding="utf-8")
            except Exception as exc:
                return da.DirectActionResult(
                    False,
                    f"Workflow verification failed: {exc}",
                    execution_type="workflow",
                    tool_name="multi_step_workflow",
                    provider="local-filesystem",
                    telemetry={
                        "reason": "content_mismatch",
                        "verification_passed": False,
                        "expected_output_hash": expected_hash,
                        "actual_output_hash": "",
                    },
                )
            actual_hash = hashlib.sha256(observed_text.encode("utf-8")).hexdigest()
            try:
                observed = json.loads(observed_text)
            except Exception:
                observed = None
            verification_passed = observed == parsed
            if not verification_passed:
                return da.DirectActionResult(
                    False,
                    "Workflow verification failed: persisted JSON does not match the semantic transformation.",
                    execution_type="workflow",
                    tool_name="multi_step_workflow",
                    provider="local-filesystem",
                    telemetry={
                        "reason": "content_mismatch",
                        "verification_passed": False,
                        "expected_output_hash": expected_hash,
                        "actual_output_hash": actual_hash,
                        "expected": parsed,
                        "observed": observed,
                    },
                )

            return da.DirectActionResult(
                True,
                f"Successfully transformed {resolved_input} to {resolved_output} and independently verified the result.",
                execution_type="workflow",
                tool_name="multi_step_workflow",
                provider="local-filesystem",
                telemetry={
                    "verification_passed": True,
                    "expected_output_hash": expected_hash,
                    "actual_output_hash": actual_hash,
                    "input_path": str(resolved_input),
                    "output_path": str(resolved_output),
                    "value": parsed,
                    "semantic_verifier": "raw_source_transform_equals_persisted_json",
                },
            )
        except PermissionError as exc:
            return da.DirectActionResult(
                False,
                f"Workflow path rejected: {exc}",
                execution_type="workflow",
                tool_name="multi_step_workflow",
                provider="security-policy",
                policy_decision="refused",
                telemetry={"reason": "path_rejected", "error": str(exc), "verification_passed": False},
            )
        except FileNotFoundError as exc:
            return da.DirectActionResult(
                False,
                f"Workflow input file not found: {exc}",
                execution_type="workflow",
                tool_name="multi_step_workflow",
                provider="local-filesystem",
                telemetry={"reason": "input_file_not_found", "error": str(exc), "verification_passed": False},
            )
        except Exception as exc:
            return da.DirectActionResult(
                False,
                f"Workflow failed: {exc}",
                execution_type="workflow",
                tool_name="multi_step_workflow",
                provider="local-filesystem",
                telemetry={"reason": "workflow_failed", "error": str(exc), "verification_passed": False},
            )
        finally:
            core._OUTPUT_SCOPE.reset(output_token)
            core._EFFECT_SCOPE.reset(effect_token)

    current_router_execute = getattr(da.DirectActionRouter.execute, "__func__", da.DirectActionRouter.execute)

    def execute_with_release_contracts(
        cls: Any,
        text: str,
        *,
        context: str = "",
        control: Any = None,
        workspace: str = "",
    ) -> Any:
        transformed = _execute_verified_json_transform(text, workspace)
        if transformed is not None:
            return core._render(
                da,
                core.SemanticRequestGraph(
                    original_text=text,
                    action=core.SemanticAction.UNKNOWN,
                    response_mode=core._response_mode(text),
                ),
                transformed,
            )
        result = current_router_execute(
            cls,
            text,
            context=context,
            control=control,
            workspace=workspace,
        )
        if result is not None and getattr(result, "execution_type", "") == "exact_response":
            result.tool_name = "echo"
        return result

    _install_attr(da.DirectActionRouter, "execute", classmethod(execute_with_release_contracts))
    current_exact_parse = getattr(da.ExactResponseParser.parse, "__func__", da.ExactResponseParser.parse)

    def exact_with_public_provenance(cls: Any, text: str, workspace: str = "") -> Any:
        result = current_exact_parse(cls, text, workspace=workspace)
        if result is not None:
            result.tool_name = "echo"
        return result

    _install_attr(da.ExactResponseParser, "parse", classmethod(exact_with_public_provenance))
    _INSTALLED = True
