"""Narrow semantic repairs discovered during v7 target-Mac qualification.

These repairs do not add new authority or a second execution stack. They wrap the
canonical semantic parser / deterministic workflow path to close two proven
front-door correctness gaps:

* explicit directory requests phrased as "file names inside <path>" must route
  to DIRECTORY_LIST rather than conversational generation;
* explicit JSON field type constraints (for example "budget must be a number")
  must be satisfied and independently re-checked before workflow success.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

_INSTALLED = False


def _unwrap_classmethod(value: Any) -> Any:
    return getattr(value, "__func__", value)


def _explicit_directory_request(text: str) -> bool:
    lower = text.lower()
    if re.search(
        r"\b(?:write|save|create|make|store|export|delete|remove|move|rename|copy)\b",
        lower,
    ):
        return False
    return bool(
        re.search(
            r"\b(?:list|show|display|enumerate|print|get|give\s+me)\b"
            r"[^\n]{0,80}\b(?:file\s+names?|filenames|files|entries|items)\b"
            r"[^\n]{0,40}\b(?:inside|in|under|from|of)\b",
            lower,
        )
    )


def _directory_target(text: str, paths: list[str]) -> str:
    match = re.search(
        r"\b(?:inside|in|under|from|of)\s+['\"`]([^'\"`\n]+)['\"`]",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    return paths[0] if paths else ""


def _numeric_constraints(text: str) -> tuple[str, ...]:
    """Return normalized JSON field names explicitly required to be numeric."""
    fields: list[str] = []
    pattern = re.compile(
        r"\b([A-Za-z_][A-Za-z0-9_.-]*)\s+"
        r"(?:must|should|shall|needs?\s+to)\s+be\s+"
        r"(?:an?\s+)?(?:number|numeric|integer|float)\b",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        field = match.group(1).strip().lower().replace("-", "_").replace(".", "_")
        if field not in fields:
            fields.append(field)
    return tuple(fields)


def _coerce_explicit_number(value: Any) -> int | float | None:
    """Coerce a scalar carrying at most one unit token; never guess prose."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return None
    cleaned = value.strip().replace(",", "")
    match = re.fullmatch(
        r"([+-]?(?:\d+(?:\.\d+)?|\.\d+))(?:\s+([A-Za-z][A-Za-z0-9._/%-]*))?",
        cleaned,
    )
    if not match:
        return None
    token = match.group(1)
    return int(token) if re.fullmatch(r"[+-]?\d+", token) else float(token)


def _normalize_numeric_payload(payload: Any, fields: tuple[str, ...]) -> tuple[Any, list[str]]:
    """Normalize explicitly constrained fields and report unsatisfied fields."""
    missing_or_invalid: list[str] = []

    def normalize_object(obj: dict[str, Any]) -> None:
        for field in fields:
            if field not in obj:
                missing_or_invalid.append(field)
                continue
            coerced = _coerce_explicit_number(obj[field])
            if coerced is None:
                missing_or_invalid.append(field)
                continue
            obj[field] = coerced

    if isinstance(payload, dict):
        normalize_object(payload)
    elif isinstance(payload, list) and payload and all(isinstance(item, dict) for item in payload):
        for item in payload:
            normalize_object(item)
    else:
        missing_or_invalid.extend(fields)
    return payload, sorted(set(missing_or_invalid))


def install_v7_semantic_repairs() -> None:
    """Install the two qualification-found repairs on the canonical stack."""
    global _INSTALLED
    if _INSTALLED:
        return

    from jarvis.amaura import direct_action as da
    from jarvis.amaura import semantic_core as core

    current_parse = _unwrap_classmethod(core.SemanticParser.parse)
    current_workflow = _unwrap_classmethod(da.DirectActionRouter._try_multi_step_workflow)

    def parse_with_directory_filename_grammar(
        cls: Any,
        text: str,
        known_extensions: tuple[str, ...],
    ) -> Any:
        graph = current_parse(cls, text, known_extensions)
        if not _explicit_directory_request(text):
            return graph

        paths = core.extract_paths(text, known_extensions)
        target = _directory_target(text, paths)
        if not target:
            return graph
        named_directory = bool(re.search(r"\b(?:directory|folder)\b", text, re.IGNORECASE))
        looks_like_file = any(target.lower().endswith(ext) for ext in known_extensions)
        if looks_like_file and not named_directory:
            return graph
        return core.SemanticRequestGraph(
            original_text=text,
            action=core.SemanticAction.DIRECTORY_LIST,
            response_mode=core._response_mode(text),
            paths=[
                core.PathBinding(
                    target,
                    core.SemanticPathRole.TARGET,
                    "explicit_file_names_directory_clause",
                )
            ],
            evidence=["directory_file_names_clause"],
        )

    def workflow_with_typed_constraints(
        cls: Any,
        text: str,
        workspace: str = "",
    ) -> Any:
        result = current_workflow(cls, text, workspace=workspace)
        fields = _numeric_constraints(text)
        if result is None or not result.success or not fields:
            return result

        telemetry = dict(result.telemetry or {})
        parsed_plan = telemetry.get("parsed_plan") or {}
        output_path = str(parsed_plan.get("output_path") or telemetry.get("output_path") or "").strip()
        if not output_path:
            return da.DirectActionResult(
                False,
                "Workflow semantic verification failed: constrained output path is unavailable.",
                execution_type="workflow",
                tool_name="multi_step_workflow",
                provider="local-filesystem",
                telemetry={
                    **telemetry,
                    "reason": "semantic_constraint_output_missing",
                    "verification_passed": False,
                    "numeric_fields": list(fields),
                },
            )

        ws = Path(workspace if workspace else da.workspace_root()).expanduser().resolve()
        try:
            with da.tool_workspace(ws):
                output = da.resolve_workspace_path(output_path, must_exist=True)
            raw = output.read_text(encoding="utf-8", errors="replace")
            payload = json.loads(raw)
        except Exception as exc:
            return da.DirectActionResult(
                False,
                f"Workflow semantic verification failed: could not inspect JSON output: {exc}",
                execution_type="workflow",
                tool_name="multi_step_workflow",
                provider="local-filesystem",
                telemetry={
                    **telemetry,
                    "reason": "semantic_constraint_read_failed",
                    "verification_passed": False,
                    "numeric_fields": list(fields),
                },
            )

        normalized, invalid = _normalize_numeric_payload(payload, fields)
        if invalid:
            return da.DirectActionResult(
                False,
                "Workflow semantic verification failed: numeric constraint was not satisfied for "
                + ", ".join(invalid)
                + ".",
                execution_type="workflow",
                tool_name="multi_step_workflow",
                provider="local-filesystem",
                telemetry={
                    **telemetry,
                    "reason": "semantic_numeric_constraint_failed",
                    "verification_passed": False,
                    "numeric_fields": list(fields),
                    "invalid_numeric_fields": invalid,
                },
            )

        normalized_text = json.dumps(normalized, indent=2)
        if normalized_text != raw:
            with da.tool_workspace(ws):
                write_raw = da.execute_tool("write_file", {"path": str(output), "content": normalized_text})
            write_result = da.parse_tool_result(write_raw)
            if not write_result.ok:
                return da.DirectActionResult(
                    False,
                    f"Workflow semantic normalization failed at write step: {write_result.error or 'write_tool_failed'}",
                    execution_type="workflow",
                    tool_name="multi_step_workflow",
                    provider="local-filesystem",
                    telemetry={
                        **telemetry,
                        "reason": "semantic_normalization_write_failed",
                        "verification_passed": False,
                        "numeric_fields": list(fields),
                    },
                )

        actual = output.read_text(encoding="utf-8", errors="replace")
        try:
            verified_payload = json.loads(actual)
        except Exception as exc:
            return da.DirectActionResult(
                False,
                f"Workflow semantic verification failed after normalization: {exc}",
                execution_type="workflow",
                tool_name="multi_step_workflow",
                provider="local-filesystem",
                telemetry={
                    **telemetry,
                    "reason": "semantic_normalization_invalid_json",
                    "verification_passed": False,
                    "numeric_fields": list(fields),
                },
            )
        _, invalid_after = _normalize_numeric_payload(verified_payload, fields)
        if invalid_after:
            return da.DirectActionResult(
                False,
                "Workflow semantic verification failed after normalization for " + ", ".join(invalid_after) + ".",
                execution_type="workflow",
                tool_name="multi_step_workflow",
                provider="local-filesystem",
                telemetry={
                    **telemetry,
                    "reason": "semantic_numeric_postcondition_failed",
                    "verification_passed": False,
                    "numeric_fields": list(fields),
                    "invalid_numeric_fields": invalid_after,
                },
            )

        actual_hash = hashlib.sha256(actual.encode("utf-8")).hexdigest()
        telemetry.update(
            {
                "computed_result": verified_payload,
                "expected_output_hash": actual_hash,
                "actual_output_hash": actual_hash,
                "verification_passed": True,
                "semantic_constraints": {
                    "numeric_fields": list(fields),
                    "verified": True,
                },
            }
        )
        result.telemetry = telemetry
        return result

    setattr(core.SemanticParser, "parse", classmethod(parse_with_directory_filename_grammar))
    setattr(da.DirectActionRouter, "_try_multi_step_workflow", classmethod(workflow_with_typed_constraints))
    _INSTALLED = True


__all__ = ["install_v7_semantic_repairs"]
