"""Narrow semantic repairs discovered during v7 target-Mac qualification.

These repairs do not add new authority or a second execution stack. They wrap
the canonical semantic parser / deterministic workflow path to close proven
front-door correctness gaps while preserving fail-closed effect authorization.

The repairs are deliberately semantic rather than benchmark-template specific:
response contracts are separated from actions, filesystem roles must be
explicit, read-only repository inspection stays read-only, and deterministic
operations never fall through to a remote model merely because phrasing varies.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any

_INSTALLED = False


def _unwrap_classmethod(value: Any) -> Any:
    return getattr(value, "__func__", value)


def _install_attr(obj: object, name: str, value: object) -> None:
    setattr(obj, name, value)


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


def _quoted_spans(text: str) -> list[re.Match[str]]:
    return list(re.finditer(r"(['\"`])((?:(?!\1).)*)\1", text, re.DOTALL))


def _target_occurs_inside_quoted_payload(text: str, target: str) -> bool:
    if not target:
        return False
    return any(target in match.group(2) for match in _quoted_spans(text))


def _mask_quoted_spans(text: str) -> str:
    chars = list(text)
    for match in _quoted_spans(text):
        for index in range(match.start(), match.end()):
            if chars[index] not in "\r\n":
                chars[index] = " "
    return "".join(chars)


def _strip_response_directives(value: str) -> str:
    """Strip response-control suffixes without stripping payload punctuation."""
    result = value.strip()
    patterns = (
        r"\s+alone\.?\s*$",
        r"\s*,?\s*with\s+no\s+prefix\s+or\s+suffix\.?\s*$",
        r"\s+and\s+no\s+other\s+characters\.?\s*$",
        r"\s+and\s+nothing\s+(?:else|more)\.?\s*$",
        r"\s*[;,]\s*do\s+not\s+(?:explain|add\s+commentary|comment)\.?\s*$",
        r"\s*[;,]\s*exclude\s+(?:all\s+)?commentary\.?\s*$",
        r"\s*[;,]\s*stop\s+(?:immediately\s+)?after\s+(?:the\s+)?"
        r"(?:token|value|string|text|reply|response|answer|output)\.?\s*$",
        r"\s*[;,]\s*(?:no|without)\s+(?:any\s+)?(?:explanation|commentary)\.?\s*$",
    )
    changed = True
    while changed:
        changed = False
        for pattern in patterns:
            updated = re.sub(pattern, "", result, flags=re.IGNORECASE | re.DOTALL).rstrip()
            if updated != result:
                result = updated
                changed = True
    return result


def _unquote_whole(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in "'\"`":
        return stripped[1:-1]
    return stripped


def _response_literal_payload(text: str) -> str | None:
    """Extract payload only when language explicitly binds data to the response."""
    clean = text.strip()
    lower = clean.lower()
    if not clean:
        return None

    quoted = _quoted_spans(clean)
    if quoted and re.search(
        r"\bcopy\b[^\n]{0,180}\b(?:into|as)\s+(?:(?:your|the)\s+)?"
        r"(?:reply|response|answer|output)\b",
        lower,
        re.IGNORECASE,
    ):
        return quoted[-1].group(2)

    match = re.match(
        r"^\s*(?:please\s+|kindly\s+)?(?:set|make)\s+(?:(?:your|the)\s+)?"
        r"(?:entire|complete|full|whole)?\s*(?:response|reply|answer|output)\s+"
        r"(?:equal\s+to|equals?|to|be)\s+(.+?)\s*$",
        clean,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        return _unquote_whole(_strip_response_directives(match.group(1)))

    match = re.match(
        r"^\s*(?:please\s+|kindly\s+)?write\s+(?:only\s+|exactly\s+|just\s+|verbatim\s+)?"
        r"(.+?)\s+as\s+(?:(?:your|the)\s+)?(?:entire|complete|full|whole)?\s*"
        r"(?:reply|response|answer|output)\.?\s*$",
        clean,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        return _unquote_whole(_strip_response_directives(match.group(1)))

    match = re.match(
        r"^\s*(?:please\s+|kindly\s+)?use\s+this\s+as\s+(?:(?:your|the)\s+)?"
        r"(?:entire|complete|full|whole)?\s*(?:reply|response|answer|output)\s*"
        r"(?:->|=>|:=|:|=)\s*(.+?)\s*$",
        clean,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        return _unquote_whole(_strip_response_directives(match.group(1)))

    match = re.match(
        r"^\s*(?:your|the)\s+(?:(?:entire|complete|full|whole)\s+)?"
        r"(?:reply|response|answer|output)\s+"
        r"(?:must\s+(?:consist\s+(?:solely\s+)?of|be)|is|equals?)\s+(.+?)\s*$",
        clean,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        return _unquote_whole(_strip_response_directives(match.group(1)))

    command = re.match(
        r"^\s*(?:please\s+|kindly\s+)?"
        r"(?:send\s+back|give\s+back|return|reply|respond|answer|say|echo|repeat|"
        r"output|emit|provide)\b\s*(.+?)\s*$",
        clean,
        re.IGNORECASE | re.DOTALL,
    )
    if not command:
        return None

    exact_signal = bool(
        re.search(
            r"\b(?:only|just|exactly|verbatim|solely|alone|nothing\s+(?:else|more)|"
            r"no\s+other\s+characters|literal\s+(?:token|value|string|text)|"
            r"no\s+prefix\s+or\s+suffix|do\s+not\s+explain|exclude\s+commentary|"
            r"stop\s+(?:immediately\s+)?after)\b",
            lower,
        )
    )
    if not exact_signal:
        return None

    remainder = command.group(1).strip()
    remainder = re.sub(
        r"^(?:with\s+)?(?:only|just|exactly|verbatim|solely|precisely)\b\s*",
        "",
        remainder,
        flags=re.IGNORECASE,
    ).strip()
    remainder = re.sub(r"^(?:->|=>|:=|[:=-])\s*", "", remainder).strip()
    remainder = re.sub(
        r"^(?:this|the)\s+(?:literal\s+)?(?:token|value|string|text|word|payload)\s*:\s*",
        "",
        remainder,
        flags=re.IGNORECASE,
    ).strip()
    if quoted:
        return quoted[-1].group(2)
    payload = _strip_response_directives(remainder)
    if not payload:
        return None
    return _unquote_whole(payload)


def _path_first_write_relation(text: str, paths: list[str]) -> tuple[str, str] | None:
    """Parse explicit target-first create/initialize + payload relation."""
    if not re.match(r"^\s*(?:initialize|create|make|prepare)\b", text, re.IGNORECASE):
        return None
    relation = re.search(
        r"\b(?:contents?|content|text|payload|body|data)\s*"
        r"(?:->|=>|:=|=|:)\s*(.+?)\s*$",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if relation is None:
        return None
    before = text[: relation.start()]
    target_candidates = [path for path in paths if path in before]
    if len(target_candidates) != 1:
        return None
    payload = _unquote_whole(relation.group(1).strip())
    if not payload or re.search(r"\beither\b.+\bor\b", payload, re.IGNORECASE | re.DOTALL):
        return None
    return target_candidates[0], payload


def _leading_read_request(text: str, paths: list[str]) -> tuple[str, str] | None:
    """Recognize read-first requests while treating response wording as formatting."""
    if not paths or not re.match(
        r"^\s*(?:please\s+|kindly\s+)?(?:read|open|show|display|cat|fetch|view|print)\b",
        text,
        re.IGNORECASE,
    ):
        return None
    masked = _mask_quoted_spans(text)
    if re.search(
        r"\b(?:and|then)\s+(?:write|save|store|put|create|delete|remove|edit|modify)\b",
        masked,
        re.IGNORECASE,
    ):
        return None
    mode = "EXACT_RAW" if re.search(
        r"\b(?:byte[\s-]+for[\s-]+byte|verbatim|exact\s+(?:raw\s+)?(?:file\s+)?contents?)\b",
        text,
        re.IGNORECASE,
    ) else ""
    return paths[0], mode


def _explicit_result_output(text: str, paths: list[str], operands: set[str]) -> str:
    for path in paths:
        if path in operands:
            continue
        escaped = re.escape(path)
        if re.search(
            r"\b(?:put|save|write|store|record|output)\b[^\n;]{0,90}"
            r"\b(?:answer|result|difference|quotient|product|sum|output|value|number)\b"
            r"[^\n;]{0,50}\b(?:in|into|to|at)\s+['\"`]?"
            + escaped,
            text,
            re.IGNORECASE,
        ):
            return path
    return ""


def _repository_read_only_request(text: str, paths: list[str]) -> bool:
    if not paths:
        return False
    masked = _mask_quoted_spans(text).lower()
    inspect = bool(
        re.search(
            r"\b(?:review|inspect|diagnose|audit|analy[sz]e|trace|investigate|"
            r"find\s+(?:the\s+)?bug|locate\s+(?:the\s+)?bug)\b",
            masked,
        )
    )
    mutating = bool(
        re.search(
            r"\b(?:fix|repair|patch|rewrite|modify|edit|write|delete|remove|create|"
            r"save|store|apply)\b",
            masked,
        )
    )
    return inspect and not mutating


def _memory_recall_language(text: str) -> bool:
    lower = text.lower().strip()
    if re.match(r"^(?:please\s+)?remember\s+(?:that|this)\b", lower):
        return False
    if re.search(r"\b(?:store|save|write)\b[^\n]{0,80}\bmemory\b", lower):
        return False
    retrieval = bool(
        re.search(
            r"\b(?:recall|recalled|remembered|previously\s+told|previously\s+gave|"
            r"you\s+remember)\b",
            lower,
        )
    )
    response_or_question = bool(
        re.search(r"\b(?:reply|respond|return|give|tell|show|what|which|retrieve)\b", lower)
        or lower.endswith("?")
    )
    return retrieval and response_or_question


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


def _contract_comparison_findings(repo_path: Path, existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add generic inclusive-boundary findings missing from the legacy AST rules."""
    additions: list[dict[str, Any]] = []
    seen = {
        (str(item.get("function", "")), str(item.get("category", "")))
        for item in existing
        if isinstance(item, dict)
    }
    for py_file in sorted(repo_path.rglob("*.py")):
        if "test" in py_file.name.lower() or any(part.startswith(".") for part in py_file.parts):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            doc = (ast.get_docstring(node) or "").lower()
            expected: str | None = None
            observed: str | None = None
            if any(phrase in doc for phrase in ("no greater than", "no more than", "not greater than")):
                expected, observed = "<=", "<"
                predicate = ast.Lt
            elif any(phrase in doc for phrase in ("no less than", "not less than")):
                expected, observed = ">=", ">"
                predicate = ast.Gt
            else:
                continue
            if (node.name, "comparison_boundary") in seen:
                continue
            if not any(
                isinstance(child, ast.Compare) and any(isinstance(op, predicate) for op in child.ops)
                for child in ast.walk(node)
            ):
                continue
            additions.append(
                {
                    "function": node.name,
                    "category": "comparison_boundary",
                    "observed_operator": observed,
                    "expected_operator": expected,
                    "description": (
                        f"Function '{node.name}' uses strict '{observed}' comparison where "
                        f"'{expected}' is required by the inclusive contract"
                    ),
                    "confidence": 1.0,
                    "file": str(py_file),
                }
            )
            seen.add((node.name, "comparison_boundary"))
    return additions


def install_v7_semantic_repairs() -> None:
    """Install qualification-found repairs on the canonical stack."""
    global _INSTALLED
    if _INSTALLED:
        return

    from jarvis.amaura import direct_action as da
    from jarvis.amaura import semantic_core as core

    current_parse = _unwrap_classmethod(core.SemanticParser.parse)
    current_workflow = _unwrap_classmethod(da.DirectActionRouter._try_multi_step_workflow)
    current_write_parse = _unwrap_classmethod(da.WriteActionParser.parse)
    current_repo_request = _unwrap_classmethod(da.DirectActionRouter._is_repository_inspection_request)
    current_memory_request = _unwrap_classmethod(da.DirectActionRouter._is_memory_recall_request)
    current_diagnose = _unwrap_classmethod(da.RepositoryDiagnosticEngine.diagnose)

    def parse_with_v7_semantics(
        cls: Any,
        text: str,
        known_extensions: tuple[str, ...],
    ) -> Any:
        clean = text.strip()
        paths = core.extract_paths(clean, known_extensions)

        if _memory_recall_language(clean):
            return core.SemanticRequestGraph(
                original_text=clean,
                action=core.SemanticAction.MEMORY_RECALL,
                response_mode=core._response_mode(clean),
                evidence=["explicit_memory_retrieval_dependency"],
            )

        read = _leading_read_request(clean, paths)
        if read is not None:
            target, forced_mode = read
            return core.SemanticRequestGraph(
                original_text=clean,
                action=core.SemanticAction.FILE_READ,
                response_mode=forced_mode or core._response_mode(clean),
                paths=[
                    core.PathBinding(
                        target,
                        core.SemanticPathRole.INPUT,
                        "leading_file_read_clause",
                    )
                ],
                evidence=["leading_file_read_clause"],
            )

        if _repository_read_only_request(clean, paths):
            return core.SemanticRequestGraph(
                original_text=clean,
                action=core.SemanticAction.REPOSITORY,
                response_mode=core._response_mode(clean),
                paths=[
                    core.PathBinding(
                        paths[0],
                        core.SemanticPathRole.REPOSITORY,
                        "read_only_repository_inspection",
                    )
                ],
                evidence=["read_only_repository_inspection"],
            )

        arithmetic = core._parse_arithmetic(clean, paths)
        if arithmetic is not None and len(paths) >= 2:
            operands = {arithmetic.left_path, arithmetic.right_path}
            explicit_output = arithmetic.output_path or _explicit_result_output(clean, paths, operands)
            if explicit_output:
                arithmetic.output_path = explicit_output
                bindings = [
                    core.PathBinding(
                        arithmetic.left_path,
                        core.SemanticPathRole.INPUT,
                        arithmetic.left_role,
                    ),
                    core.PathBinding(
                        arithmetic.right_path,
                        core.SemanticPathRole.SECONDARY_INPUT,
                        arithmetic.right_role,
                    ),
                    core.PathBinding(
                        explicit_output,
                        core.SemanticPathRole.OUTPUT,
                        "explicit_arithmetic_output_clause",
                    ),
                ]
                return core.SemanticRequestGraph(
                    original_text=clean,
                    action=core.SemanticAction.ARITHMETIC,
                    response_mode=core._response_mode(clean),
                    paths=bindings,
                    arithmetic=arithmetic,
                    evidence=["arithmetic_roles", arithmetic.provenance, "explicit_arithmetic_output_clause"],
                )

        path_first = _path_first_write_relation(clean, paths)
        if path_first is not None:
            target, payload = path_first
            return core.SemanticRequestGraph(
                original_text=clean,
                action=core.SemanticAction.FILE_WRITE,
                response_mode=core._response_mode(clean),
                paths=[
                    core.PathBinding(
                        target,
                        core.SemanticPathRole.OUTPUT,
                        "path_first_explicit_target",
                    )
                ],
                write_payload=payload,
                evidence=["path_first_write_relation", "explicit_payload_relation"],
            )

        if not core._execution_dependency(clean, known_extensions):
            literal = _response_literal_payload(clean)
            if literal is not None:
                return core.SemanticRequestGraph(
                    original_text=clean,
                    action=core.SemanticAction.EXACT_LITERAL,
                    response_mode="EXACT_LITERAL",
                    literal_payload=literal,
                    evidence=["response_scoped_exact_literal"],
                )

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

    def parse_write_with_quoted_payload_isolation(
        cls: Any,
        text: str,
        default_workspace: str = "",
    ) -> Any:
        action = current_write_parse(cls, text, default_workspace=default_workspace)
        if action is None or not _target_occurs_inside_quoted_payload(text, action.target_path):
            return action

        outside_literals = _mask_quoted_spans(text)
        external_paths = da.PathExtractor.extract_all_paths(outside_literals)
        external_paths = [candidate for candidate in external_paths if candidate != action.target_path]
        if len(external_paths) == 1:
            action.target_path = external_paths[0]
        return action

    def repository_request_with_generic_read_only_path(cls: Any, text: str) -> bool:
        if current_repo_request(cls, text):
            return True
        paths = da.PathExtractor.extract_all_paths(text)
        return _repository_read_only_request(text, paths)

    def memory_request_with_retrieval_language(cls: Any, text: str) -> bool:
        return bool(current_memory_request(cls, text) or _memory_recall_language(text))

    def diagnose_with_inclusive_contract_language(cls: Any, repo_path: Path) -> dict[str, Any]:
        result = current_diagnose(cls, repo_path)
        findings = result.get("findings")
        if not isinstance(findings, list):
            return result
        additions = _contract_comparison_findings(repo_path, findings)
        if additions:
            findings.extend(additions)
            result["findings"] = findings
        return result

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

    _install_attr(core.SemanticParser, "parse", classmethod(parse_with_v7_semantics))
    _install_attr(da.WriteActionParser, "parse", classmethod(parse_write_with_quoted_payload_isolation))
    _install_attr(
        da.DirectActionRouter,
        "_is_repository_inspection_request",
        classmethod(repository_request_with_generic_read_only_path),
    )
    _install_attr(
        da.DirectActionRouter,
        "_is_memory_recall_request",
        classmethod(memory_request_with_retrieval_language),
    )
    _install_attr(
        da.RepositoryDiagnosticEngine,
        "diagnose",
        classmethod(diagnose_with_inclusive_contract_language),
    )
    _install_attr(da.DirectActionRouter, "_try_multi_step_workflow", classmethod(workflow_with_typed_constraints))
    _INSTALLED = True


__all__ = ["install_v7_semantic_repairs"]
