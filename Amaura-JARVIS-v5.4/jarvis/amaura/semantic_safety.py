"""V9 semantic safety patch for Amaura JARVIS.

This module installs a narrow compatibility/safety layer around the Phase 8
DirectActionRouter.  It intentionally preserves the existing capability stack
while enforcing the invariants exposed by the independent V9 holdout:

* paths never become outputs merely because they are last in a sentence;
* response-only requests cannot silently invoke write_file;
* arithmetic operand roles are executed semantically, not positionally;
* browser_extract_content calls conform to the registered tool schema;
* VALUE_ONLY / NUMBER_ONLY are rendered after execution;
* repository-review requests do not require the literal word "repo".

The patch is designed to be removable once the legacy router is replaced by a
single SemanticRequestGraph implementation.
"""
from __future__ import annotations

import json
import re
from contextvars import ContextVar
from pathlib import Path
from typing import Any

_INSTALLED = False
_ALLOW_WRITE_FILE: ContextVar[bool] = ContextVar("amaura_allow_write_file", default=False)


def _strip_token(value: str) -> str:
    return value.strip().strip("'\"`").rstrip(".,:;!?)]}")


def _looks_like_path(value: str, known_extensions: tuple[str, ...]) -> bool:
    value = _strip_token(value)
    if not value or "\n" in value or " " in value:
        return False
    return (
        value.startswith(("/", "~/", "./", "../"))
        or "/" in value
        or "\\" in value
        or any(value.lower().endswith(ext) for ext in known_extensions)
    )


def _safe_paths(text: str, known_extensions: tuple[str, ...], stop_words: set[str]) -> list[str]:
    """Extract only syntactically path-like values.

    Generic prepositions (at/in/to/from/into) are deliberately NOT path
    introducers.  This prevents phrases such as "from the number in ..." from
    manufacturing paths like "the".
    """
    candidates: list[tuple[int, str]] = []

    # Explicit filesystem/repository nouns followed by a quoted value.
    for match in re.finditer(
        r"\b(?:file|path|directory|folder|repo|repository|codebase|location|dir|destination|source|target)\s+['\"`]([^'\"`\n]+)['\"`]",
        text,
        re.IGNORECASE,
    ):
        candidates.append((match.start(1), match.group(1)))

    # Any quoted value is accepted only when the value itself is path-like.
    for match in re.finditer(r"['\"`]([^'\"`\n]+)['\"`]", text):
        value = match.group(1)
        if _looks_like_path(value, known_extensions):
            candidates.append((match.start(1), value))

    # POSIX/home/relative paths.
    for match in re.finditer(r"(?<![\w])((?:~|\.\.?)?/[A-Za-z0-9_.\-~]+(?:/[A-Za-z0-9_.\-~]+)*)", text):
        candidates.append((match.start(1), match.group(1)))

    # Bare filenames with extensions.
    for match in re.finditer(r"\b[A-Za-z0-9_.\-/~]+\.[A-Za-z0-9_-]+\b", text):
        candidates.append((match.start(0), match.group(0)))

    candidates.sort(key=lambda item: item[0])
    result: list[str] = []
    seen: set[str] = set()
    for _, raw in candidates:
        value = _strip_token(raw)
        if not value or value.lower() in stop_words or not _looks_like_path(value, known_extensions):
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _explicit_output(text: str, paths: list[str]) -> str:
    """Return an output path only when language explicitly assigns that role."""
    if not paths:
        return ""
    lower = text.lower()
    output_markers = (
        "save", "write", "store", "put", "output", "export", "create", "dump", "record",
        "destination", "result to", "result in", "save as", "write to", "write into",
    )
    for path in paths:
        pos = lower.find(path.lower())
        if pos < 0:
            continue
        window = lower[max(0, pos - 90):pos]
        if any(marker in window for marker in output_markers):
            return path
    return ""


def _safe_structured_arguments(direct_action: Any, text: str, default_workspace: str = "") -> dict[str, Any]:
    paths = _safe_paths(text, direct_action.RequestPreprocessor.KNOWN_EXTENSIONS, direct_action.RequestPreprocessor.STOP_WORDS)
    args: dict[str, Any] = {}
    output_path = _explicit_output(text, paths)
    if output_path:
        args["output_path"] = output_path

    # Repo role is semantic: review/inspect/diagnose + a path is enough.
    lower = text.lower()
    inspection = any(word in lower for word in ("review", "inspect", "diagnose", "audit", "analyze", "analyse", "trace", "investigate"))
    if inspection and paths:
        args["repo_path"] = paths[0]

    inputs = [path for path in paths if path != output_path]
    if inputs:
        args["input_path"] = inputs[0]
    if len(inputs) >= 2:
        args["secondary_input_path"] = inputs[1]
    if len(paths) == 1 and not output_path and not inspection:
        args["path"] = paths[0]

    # Directory language assigns a directory role, but still never an output role.
    if paths and any(token in lower for token in ("directory", "folder", "list files", "list entries", "contents of", "children of")):
        args["directory"] = paths[0]
    return args


def _first_number(text: str) -> int | float:
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        raise ValueError("no numeric operand found")
    token = match.group(0)
    return float(token) if "." in token else int(token)


def _semantic_arithmetic(direct_action: Any, text: str, workspace: str = "") -> Any | None:
    lower = text.lower()
    operation = ""
    if any(term in lower for term in ("subtract", "minus", "difference", "deduct", "away from")):
        operation = "subtract"
    elif any(term in lower for term in ("divide", "divided by", "quotient")):
        operation = "divide"
    elif any(term in lower for term in ("multiply", "product", " times ")):
        operation = "multiply"
    elif any(term in lower for term in (" add ", "sum", "total")):
        operation = "add"
    if not operation:
        return None

    paths = direct_action.PathExtractor.extract_all_paths(text)
    args = direct_action.PathExtractor.extract_structured_arguments(text, default_workspace=workspace)
    # This handler is specifically the response-only/no-output path. Explicit
    # output workflows remain on the existing workflow engine.
    if args.get("output_path") or len(paths) < 2:
        return None

    ws = Path(workspace if workspace else direct_action.workspace_root()).expanduser().resolve()
    try:
        with direct_action.tool_workspace(ws):
            resolved = [direct_action.resolve_workspace_path(path, must_exist=True) for path in paths[:2]]
        values = [_first_number(path.read_text(encoding="utf-8", errors="replace")) for path in resolved]

        if operation == "subtract":
            # "subtract/take/deduct B from A" and "take B away from A" => A-B.
            reverse = bool(re.search(r"\b(?:subtract|take|deduct)\b.+?\b(?:from|away\s+from)\b", lower))
            result = values[1] - values[0] if reverse else values[0] - values[1]
        elif operation == "divide":
            # "divide B into A" => A/B.  "divide A by B" => A/B.
            reverse = bool(re.search(r"\bdivide\b.+?\binto\b", lower))
            numerator, denominator = (values[1], values[0]) if reverse else (values[0], values[1])
            if denominator == 0:
                raise ZeroDivisionError("division by zero")
            result = numerator / denominator
        elif operation == "multiply":
            result = values[0] * values[1]
        else:
            result = values[0] + values[1]

        if isinstance(result, float) and result.is_integer():
            result = int(result)
        return direct_action.DirectActionResult(
            success=True,
            output=str(result),
            execution_type="semantic_workflow",
            tool_name="read_file",
            provider="local-filesystem",
            model="",
            policy_decision="allowed",
            telemetry={
                "requested_operation": operation,
                "input_paths": [str(path) for path in resolved],
                "input_values": values,
                "computed_result": result,
                "verification_passed": True,
                "verification": "semantic_relation",
                "side_effects": "none",
            },
        )
    except (FileNotFoundError, PermissionError, ValueError, ZeroDivisionError) as exc:
        return direct_action.DirectActionResult(
            success=False,
            output=f"Semantic arithmetic failed: {exc}",
            execution_type="semantic_workflow",
            tool_name="read_file",
            provider="local-filesystem",
            model="",
            policy_decision="refused" if isinstance(exc, PermissionError) else "allowed",
            telemetry={"reason": "semantic_arithmetic_failed", "error": str(exc), "side_effects": "none"},
        )


def _safe_exact_literal(text: str) -> str | None:
    """Parse response-only literal requests without consulting filesystem logic."""
    clean = text.strip()
    lower = clean.lower()
    if not clean:
        return None
    if "://" in clean or any(term in lower for term in (
        "from the file", "file contents", "stored in memory", "from memory",
        "from the page", "css selector", "from the browser", "from url",
    )):
        return None

    exact_signal = bool(re.search(
        r"\b(?:return|reply|respond|say|echo|repeat|print|answer)\b.*\b(?:only|exactly|verbatim|nothing\s+else|nothing\s+more)\b",
        lower,
    )) or bool(re.search(r"\b(?:make|set)\s+(?:the\s+)?response\s+(?:equal\s+to|to|be)\b", lower))
    if not exact_signal:
        return None

    # Quoted literals are strongest and preserve punctuation/unicode exactly.
    quoted = re.search(r"[\"'`«]([^\"'`»\n]+)[\"'`»]", clean)
    if quoted:
        return quoted.group(1)

    match = re.search(
        r"(?:make|set)\s+(?:the\s+)?response\s+(?:equal\s+to|to|be)\s+([^\s.,;]+)",
        clean,
        re.IGNORECASE,
    )
    if match:
        return match.group(1)

    match = re.search(
        r"(?:return|reply|respond|say|echo|repeat|print|answer)(?:\s+with)?\s+(?:only\s+|exactly\s+|verbatim\s+)*(.*)",
        clean,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    payload = match.group(1).strip()
    payload = re.split(
        r"\s+(?:and\s+nothing\s+(?:else|more)|with\s+no\s+(?:extra\s+)?(?:text|commentary|explanation)|nothing\s+(?:else|more))\b",
        payload,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    return payload.rstrip(".") if payload else None


def _explicit_write_authorized(direct_action: Any, text: str) -> bool:
    paths = direct_action.PathExtractor.extract_all_paths(text)
    output_path = _explicit_output(text, paths)
    if not output_path:
        return False
    lower = text.lower()
    return any(re.search(rf"\b{verb}\b", lower) for verb in ("write", "save", "store", "put", "create", "export", "dump", "record"))


def _flatten_single_value(value: Any) -> Any:
    if isinstance(value, dict):
        if len(value) == 1:
            return _flatten_single_value(next(iter(value.values())))
        for key in ("value", "text", "content", "result", "computed_result"):
            if key in value:
                return _flatten_single_value(value[key])
    if isinstance(value, list) and len(value) == 1:
        return _flatten_single_value(value[0])
    return value


def _render_response(direct_action: Any, text: str, result: Any) -> Any:
    if result is None or not getattr(result, "success", False):
        return result
    mode = direct_action.RequestPreprocessor.process(text).response_mode
    telemetry = getattr(result, "telemetry", {}) or {}

    if mode == direct_action.ResponseMode.NUMBER_ONLY:
        value = telemetry.get("computed_result")
        if value is None:
            matches = re.findall(r"-?\d+(?:\.\d+)?", str(result.output))
            value = matches[-1] if matches else result.output
        result.output = str(value)
        return result

    if mode == direct_action.ResponseMode.VALUE_ONLY:
        value: Any = telemetry.get("computed_result")
        if value is None:
            try:
                value = json.loads(str(result.output))
            except Exception:
                value = result.output
        value = _flatten_single_value(value)
        if isinstance(value, (dict, list)):
            result.output = json.dumps(value, ensure_ascii=False)
        else:
            result.output = str(value)
        return result

    if mode == direct_action.ResponseMode.PATH_ONLY:
        for key in ("output_path", "path"):
            if key in telemetry:
                result.output = str(telemetry[key])
                break
    return result


def install_semantic_safety_patch() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from jarvis.amaura import direct_action as da

    # Preserve original entry points once.
    original_execute = da.DirectActionRouter.execute.__func__
    original_repo_check = da.DirectActionRouter._is_repository_inspection_request.__func__
    original_execute_tool = da.execute_tool

    def safe_extract_all_paths(cls: Any, text: str) -> list[str]:
        return _safe_paths(text, cls.KNOWN_EXTENSIONS, cls.STOP_WORDS)

    def safe_extract_structured_arguments(cls: Any, text: str, *, default_workspace: str = "") -> dict[str, Any]:
        return _safe_structured_arguments(da, text, default_workspace)

    da.PathExtractor.extract_all_paths = classmethod(safe_extract_all_paths)
    da.PathExtractor.extract_structured_arguments = classmethod(safe_extract_structured_arguments)

    def safe_repo_check(cls: Any, text: str) -> bool:
        if original_repo_check(cls, text):
            return True
        lower = text.lower()
        inspection = any(word in lower for word in ("review", "inspect", "diagnose", "audit", "analyze", "analyse", "trace", "investigate"))
        mutating = any(word in lower for word in ("write", "edit", "modify", "delete", "remove", "create"))
        return inspection and not mutating and bool(da.PathExtractor.extract_all_paths(text))

    da.DirectActionRouter._is_repository_inspection_request = classmethod(safe_repo_check)

    def guarded_execute_tool(name: str, arguments: dict[str, Any] | None = None, *args: Any, **kwargs: Any) -> Any:
        arguments = dict(arguments or {})
        if name == "write_file" and not _ALLOW_WRITE_FILE.get():
            raise da.GovernanceError("semantic side-effect firewall blocked write_file: no explicit output role")
        if name == "browser_extract_content" and "field" in arguments:
            field = str(arguments.pop("field", "")).lower()
            if field == "links" and not arguments.get("selector"):
                arguments["selector"] = "a"
            # text/content need no synthetic field; registered schema defaults to body.
        return original_execute_tool(name, arguments, *args, **kwargs)

    da.execute_tool = guarded_execute_tool

    def safe_execute(cls: Any, text: str, *, context: str = "", control: Any = None, workspace: str = "") -> Any:
        clean = text.strip()
        if not clean:
            return None

        literal = _safe_exact_literal(clean)
        if literal is not None:
            return da.DirectActionResult(
                success=True,
                output=literal,
                execution_type="deterministic",
                tool_name="exact_response",
                provider="local-parser",
                model="",
                policy_decision="allowed",
                telemetry={"response_mode": "EXACT_LITERAL", "side_effects": "none", "verification_passed": True},
            )

        arithmetic = _semantic_arithmetic(da, clean, workspace=workspace)
        if arithmetic is not None:
            return _render_response(da, clean, arithmetic)

        allow_write = _explicit_write_authorized(da, clean)
        token = _ALLOW_WRITE_FILE.set(allow_write)
        try:
            result = original_execute(cls, clean, context=context, control=control, workspace=workspace)
        finally:
            _ALLOW_WRITE_FILE.reset(token)
        return _render_response(da, clean, result)

    da.DirectActionRouter.execute = classmethod(safe_execute)
    _INSTALLED = True
