"""ARCH semantic request graph and deterministic execution boundary.

This module replaces the legacy "first parser that wins" direct-action front door
with one parse -> authorize -> execute -> verify -> render pipeline.

The capability implementations remain reusable adapters, but they no longer
compete to reinterpret the same user sentence.  Filesystem mutations are denied
unless the graph proves an explicit mutation action, output role and payload.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import operator
import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from pathlib import Path
from typing import Any


class SemanticAction(StrEnum):
    UNKNOWN = "unknown"
    EXACT_LITERAL = "exact_literal"
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    DIRECTORY_LIST = "directory_list"
    ARITHMETIC = "arithmetic"
    BROWSER = "browser"
    REPOSITORY = "repository"
    SCREENSHOT = "screenshot"
    MEMORY_RECALL = "memory_recall"
    CALENDAR = "calendar"
    POLICY_REFUSAL = "policy_refusal"


class SemanticPathRole(StrEnum):
    INPUT = "input"
    SECONDARY_INPUT = "secondary_input"
    OUTPUT = "output"
    TARGET = "target"
    REPOSITORY = "repository"
    WORKSPACE = "workspace"


@dataclass(frozen=True)
class PathBinding:
    path: str
    role: SemanticPathRole
    provenance: str
    explicit: bool = True


@dataclass
class ArithmeticPlan:
    operation: str
    left_path: str
    right_path: str
    left_role: str
    right_role: str
    output_path: str = ""
    provenance: str = ""


@dataclass
class BrowserPlan:
    url: str
    selectors: list[str] = field(default_factory=list)
    want_title: bool = False
    want_text: bool = False
    want_links: bool = False


@dataclass
class SemanticRequestGraph:
    original_text: str
    action: SemanticAction
    response_mode: str = "NORMAL"
    paths: list[PathBinding] = field(default_factory=list)
    literal_payload: str = ""
    write_payload: str | None = None
    arithmetic: ArithmeticPlan | None = None
    browser: BrowserPlan | None = None
    transform_plan: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    @property
    def output_path(self) -> str:
        for binding in self.paths:
            if binding.role in {SemanticPathRole.OUTPUT, SemanticPathRole.TARGET}:
                return binding.path
        return ""


# Direct-action tool calls are guarded by a graph-scoped authorization token.
_EFFECT_SCOPE: ContextVar[frozenset[str]] = ContextVar("amaura_semantic_effect_scope", default=frozenset())
_OUTPUT_SCOPE: ContextVar[frozenset[str]] = ContextVar("amaura_semantic_output_scope", default=frozenset())
_INSTALLED = False


def _unwrap_classmethod(value: Any) -> Any:
    return getattr(value, "__func__", value)


def _install_attr(obj: object, name: str, value: object) -> None:
    setattr(obj, name, value)


_MUTATING_TOOLS = {
    "write_file",
    "delete_file",
    "take_screenshot",
    "browser_click",
    "browser_type",
    "browser_upload_file",
    "browser_download_file",
}

_STOP_WORDS = {
    "the",
    "a",
    "an",
    "this",
    "that",
    "it",
    "its",
    "to",
    "in",
    "into",
    "at",
    "from",
    "for",
    "with",
    "by",
    "of",
    "as",
    "is",
    "be",
    "are",
    "was",
    "were",
    "and",
    "or",
    "but",
    "so",
    "if",
    "only",
    "exactly",
    "verbatim",
}


def _strip_path(value: str) -> str:
    return value.strip().strip("'\"`").rstrip(".,:;!?)]}")


def _looks_like_path(value: str, known_extensions: tuple[str, ...]) -> bool:
    value = _strip_path(value)
    if not value or "\n" in value or " " in value:
        return False
    return (
        value.startswith(("/", "~/", "./", "../"))
        or "/" in value
        or "\\" in value
        or any(value.lower().endswith(ext) for ext in known_extensions)
    )


def extract_paths(text: str, known_extensions: tuple[str, ...]) -> list[str]:
    """Extract syntactically real paths only; generic prepositions are not introducers."""
    candidates: list[tuple[int, str]] = []
    for match in re.finditer(r"['\"`]([^'\"`\n]+)['\"`]", text):
        value = match.group(1)
        if _looks_like_path(value, known_extensions):
            candidates.append((match.start(1), value))
    for match in re.finditer(r"(?<![\w])((?:~|\.\.?)?/[A-Za-z0-9_.\-~]+(?:/[A-Za-z0-9_.\-~]+)*)", text):
        candidates.append((match.start(1), match.group(1)))
    for match in re.finditer(r"\b[A-Za-z0-9_.\-/~]+\.[A-Za-z0-9_-]+\b", text):
        candidates.append((match.start(), match.group(0)))
    candidates.sort(key=lambda item: item[0])
    result: list[str] = []
    seen: set[str] = set()
    for _, raw in candidates:
        value = _strip_path(raw)
        if not value or value.lower() in _STOP_WORDS or not _looks_like_path(value, known_extensions) or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _mask_quoted(text: str) -> str:
    return re.sub(r"(['\"`]).*?\1", " <LITERAL> ", text, flags=re.DOTALL)


def _response_mode(text: str) -> str:
    lower = text.lower()
    # Raw-file contracts outrank generic scalar wording such as "only the contents".
    if "exact raw" in lower or "byte-for-byte" in lower or "exact file contents" in lower:
        return "EXACT_RAW"
    if (
        "raw file" in lower
        or "raw contents" in lower
        or "without line numbers" in lower
        or "just the contents" in lower
    ):
        return "RAW"
    if (
        re.search(r"\b(?:reply|respond|return|output|answer|give)\b.*\bonly\b.*\bnumber\b", lower)
        or "number only" in lower
    ):
        return "NUMBER_ONLY"
    if (
        re.search(
            r"\b(?:reply|respond|return|output|answer|give)\b.*\b(?:only|just)\b.*\b(?:value|text|title|content|token|marker|code)\b",
            lower,
        )
        or re.search(
            r"\b(?:reply|respond|return|output|answer|give)\b\s+(?:with\s+)?(?:only|just)\s+(?:the\s+)?(?:value|text|title|content|token|marker|code)\b",
            lower,
        )
        or any(phrase in lower for phrase in ("value only", "title only", "text only", "content only"))
    ):
        return "VALUE_ONLY"
    if "json only" in lower or "only json" in lower:
        return "JSON_ONLY"
    if "path only" in lower or "only the path" in lower:
        return "PATH_ONLY"
    if "no output" in lower or "silent" in lower:
        return "SILENT"
    return "NORMAL"


def _execution_dependency(text: str, known_extensions: tuple[str, ...]) -> bool:
    lower = text.lower()
    if "://" in text:
        return True
    paths = extract_paths(text, known_extensions)
    if paths and any(
        phrase in lower
        for phrase in (
            "from the file",
            "in the file",
            "file contents",
            "contents of",
            "raw file",
            "text stored in",
            "value in",
            "number in",
            "read ",
            "open ",
            "load ",
            "repository",
            "repo",
            "codebase",
        )
    ):
        return True
    return any(
        phrase in lower
        for phrase in (
            "from memory",
            "stored in memory",
            "remembered",
            "recalled",
            "from the browser",
            "from the page",
            "css selector",
        )
    )


def _parse_exact_literal(text: str, known_extensions: tuple[str, ...]) -> str | None:
    """Strict exact-response grammar. Payload is explicit data and can never authorize effects."""
    clean = text.strip()
    if not clean or _execution_dependency(clean, known_extensions):
        return None
    masked = _mask_quoted(clean).lower()
    exact_signal = bool(
        re.search(
            r"\b(?:reply|respond|return|say|echo|repeat|print|output|answer)\b[^\n]{0,60}\b(?:only|exactly|verbatim|nothing\s+(?:else|more))\b",
            masked,
        )
    ) or bool(
        re.search(
            r"\b(?:make|set)\s+(?:the\s+)?(?:response|reply|output|answer)\s+(?:equal\s+to|equals?|to|be)\b", masked
        )
    )
    exact_signal = exact_signal or bool(re.match(r"^\s*(?:echo|repeat)\s*[:\-]", clean, re.IGNORECASE))
    if not exact_signal:
        return None

    # Prefer the first explicit quoted literal after the command prefix.
    quoted = re.search(r"[\"'`«]([^\"'`»\n]*)[\"'`»]", clean)
    if quoted:
        return quoted.group(1)

    m_equal = re.search(
        r"(?:make|set)\s+(?:the\s+)?(?:response|reply|output|answer)\s+(?:equal\s+to|equals?|to|be)\s+([^\s,;.!?]+)",
        clean,
        re.IGNORECASE,
    )
    if m_equal:
        return m_equal.group(1).strip()

    remaining = re.sub(
        r"^\s*(?:(?:please|kindly)\s+)?(?:reply|respond|return|say|echo|repeat|print|output|answer)(?:\s+with)?\s*",
        "",
        clean,
        flags=re.IGNORECASE,
    ).strip()
    remaining = re.sub(r"^(?:only|exactly|verbatim|strictly|precisely)\s*[:\-]?\s*", "", remaining, flags=re.IGNORECASE)
    remaining = re.split(
        r"\s+(?:and\s+nothing\s+(?:else|more)|nothing\s+(?:else|more)|without\s+(?:any\s+)?(?:commentary|explanation)|with\s+no\s+(?:extra\s+)?(?:text|words|commentary))\b",
        remaining,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    if not remaining:
        return None
    return remaining[:-1] if remaining.endswith(".") else remaining


def _explicit_output(text: str, paths: list[str]) -> str:
    lower = text.lower()
    patterns = (
        r"(?:save|write|store|put|export|dump|record)\s+(?:the\s+)?(?:result|output|data|value)?\s*(?:to|into|in|at)\s+['\"`]?{p}",
        r"(?:output|destination|target)\s+(?:file\s+)?(?:is|to|at|in)?\s*['\"`]?{p}",
        r"(?:create|make)\s+(?:the\s+)?(?:file\s+)?['\"`]?{p}",
        r"(?:write|save|store)\s+['\"`]?{p}",
    )
    for path in paths:
        escaped = re.escape(path.lower())
        if any(re.search(pattern.format(p=escaped), lower, re.IGNORECASE) for pattern in patterns):
            return path
    return ""


def _write_payload_candidates(text: str, target: str) -> list[str]:
    candidates: list[str] = []
    patterns = (
        r"\b(?:containing|contains?|with\s+(?:the\s+)?(?:content|text|payload|body)|content\s*(?:is|=|:)|payload\s*(?:is|=|:)|text\s*(?:is|=|:))\s*['\"`]([^'\"`\n]*)['\"`]",
        r"\b(?:containing|contains?|with\s+(?:the\s+)?(?:content|text|payload|body)|content\s*(?:is|=|:)|payload\s*(?:is|=|:))\s*:\s*([^\n]+)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            candidates.append(match.group(1).strip())

    # "write <literal> to <path>" form.
    m = re.search(
        r"\bwrite\s+['\"`]([^'\"`\n]*)['\"`]\s+(?:to|into)\s+['\"`]?" + re.escape(target), text, re.IGNORECASE
    )
    if m:
        candidates.append(m.group(1))

    unique: list[str] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def _parse_browser(text: str) -> BrowserPlan | None:
    m_url = re.search(r"([A-Za-z][A-Za-z0-9+.-]*://[^\s'\"),]+)", text)
    if not m_url:
        return None
    url = m_url.group(1).rstrip(".,;!")
    lower = text.lower()
    selectors: list[str] = []

    # Explicit per-selector grammar.
    for match in re.finditer(r"(?:css\s+selector|selector|element)\s+['\"`]([^'\"`]+)['\"`]", text, re.IGNORECASE):
        selector = match.group(1)
        if selector not in selectors:
            selectors.append(selector)

    # Natural list grammar: CSS selectors: ".a", ".b", "#c".
    list_match = re.search(r"\bcss\s+selectors?\s*:\s*(.+)$", text, re.IGNORECASE | re.DOTALL)
    if list_match:
        for selector in re.findall(r"['\"`]([^'\"`]+)['\"`]", list_match.group(1)):
            if selector not in selectors:
                selectors.append(selector)

    return BrowserPlan(
        url=url,
        selectors=selectors,
        want_title="title" in lower,
        want_text=any(term in lower for term in ("body", "text", "content")) and not selectors,
        want_links=any(term in lower for term in ("links", "href")),
    )


def _parse_arithmetic(text: str, paths: list[str]) -> ArithmeticPlan | None:
    if len(paths) < 2:
        return None
    lower = text.lower()
    operation = ""
    if any(term in lower for term in ("subtract", "minus", "difference", "deduct", "away from")):
        operation = "subtract"
    elif any(term in lower for term in ("divide", "divided by", "quotient")):
        operation = "divide"
    elif any(term in lower for term in ("multiply", "product", " times ")):
        operation = "multiply"
    elif re.search(r"\b(?:add|sum|total)\b", lower):
        operation = "add"
    if not operation:
        return None

    left, right = paths[0], paths[1]
    left_role, right_role = "left", "right"
    provenance = "positional"

    if operation == "subtract":
        m = re.search(
            r"(?:subtract|take|deduct)\b.*?['\"`]([^'\"`]+)['\"`].*?(?:away\s+from|from).*?['\"`]([^'\"`]+)['\"`]",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            subtrahend, minuend = _strip_path(m.group(1)), _strip_path(m.group(2))
            if subtrahend in paths and minuend in paths:
                left, right = minuend, subtrahend
                left_role, right_role = "minuend", "subtrahend"
                provenance = "subtract_from"
    elif operation == "divide":
        m_into = re.search(
            r"divide\b.*?['\"`]([^'\"`]+)['\"`].*?\binto\b.*?['\"`]([^'\"`]+)['\"`]",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        m_by = re.search(
            r"divide\b.*?['\"`]([^'\"`]+)['\"`].*?\bby\b.*?['\"`]([^'\"`]+)['\"`]",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if m_into:
            denominator, numerator = _strip_path(m_into.group(1)), _strip_path(m_into.group(2))
            if denominator in paths and numerator in paths:
                left, right = numerator, denominator
                left_role, right_role = "numerator", "denominator"
                provenance = "divide_into"
        elif m_by:
            numerator, denominator = _strip_path(m_by.group(1)), _strip_path(m_by.group(2))
            if numerator in paths and denominator in paths:
                left, right = numerator, denominator
                left_role, right_role = "numerator", "denominator"
                provenance = "divide_by"

    output = _explicit_output(text, paths)
    if output in {left, right}:
        output = ""
    return ArithmeticPlan(operation, left, right, left_role, right_role, output, provenance)


class SemanticParser:
    @classmethod
    def parse(cls, text: str, known_extensions: tuple[str, ...]) -> SemanticRequestGraph:
        clean = text.strip()
        mode = _response_mode(clean)
        if not clean:
            return SemanticRequestGraph(clean, SemanticAction.UNKNOWN, response_mode=mode)

        literal = _parse_exact_literal(clean, known_extensions)
        if literal is not None:
            return SemanticRequestGraph(
                clean,
                SemanticAction.EXACT_LITERAL,
                response_mode="EXACT_LITERAL",
                literal_payload=literal,
                evidence=["explicit_exact_literal"],
            )

        lower = clean.lower()
        masked = _mask_quoted(clean).lower()
        paths = extract_paths(clean, known_extensions)

        if any(v in lower for v in ("delete", "remove", "wipe", "destroy", "purge")) and any(
            term in lower
            for term in (
                "without asking",
                "bypass",
                "force",
                "protected",
                "silently",
                "override policy",
                "no confirmation",
            )
        ):
            return SemanticRequestGraph(
                clean, SemanticAction.POLICY_REFUSAL, response_mode=mode, evidence=["destructive_bypass_request"]
            )

        browser = _parse_browser(clean)
        if browser is not None:
            return SemanticRequestGraph(
                clean, SemanticAction.BROWSER, response_mode=mode, browser=browser, evidence=["explicit_url"]
            )

        arithmetic = _parse_arithmetic(clean, paths)
        if arithmetic is not None:
            bindings = [
                PathBinding(arithmetic.left_path, SemanticPathRole.INPUT, arithmetic.left_role),
                PathBinding(arithmetic.right_path, SemanticPathRole.SECONDARY_INPUT, arithmetic.right_role),
            ]
            if arithmetic.output_path:
                bindings.append(
                    PathBinding(arithmetic.output_path, SemanticPathRole.OUTPUT, "explicit_result_destination")
                )
            return SemanticRequestGraph(
                clean,
                SemanticAction.ARITHMETIC,
                mode,
                bindings,
                arithmetic=arithmetic,
                evidence=[arithmetic.provenance],
            )

        inspect = bool(
            re.search(
                r"\b(?:review|inspect|diagnose|audit|analy[sz]e|trace|investigate|find\s+(?:the\s+)?bug|locate\s+(?:the\s+)?bug)\b",
                masked,
            )
        )
        mutating = bool(re.search(r"\b(?:write|edit|modify|delete|remove|create|save|store)\b", masked))
        if inspect and paths and not mutating:
            return SemanticRequestGraph(
                clean,
                SemanticAction.REPOSITORY,
                mode,
                [PathBinding(paths[0], SemanticPathRole.REPOSITORY, "inspection_target")],
                evidence=["inspection_verb_plus_path"],
            )

        if re.search(r"\b(?:capture|take|save)\b.*\b(?:screenshot|screen\s*shot)\b|\bscreenshot\b", masked):
            output = next((p for p in paths if p.lower().endswith(".png")), "screenshot.png")
            return SemanticRequestGraph(
                clean,
                SemanticAction.SCREENSHOT,
                mode,
                [PathBinding(output, SemanticPathRole.OUTPUT, "screenshot_destination", explicit=bool(paths))],
                evidence=["screenshot_command"],
            )

        write_verb = bool(re.search(r"\b(?:write|save|store|put|create|make|dump|record|export)\b", masked))
        if write_verb and paths:
            target = _explicit_output(clean, paths)
            graph = SemanticRequestGraph(clean, SemanticAction.FILE_WRITE, mode, evidence=["write_verb"])
            if not target:
                graph.errors.append("write request has no unambiguous explicit output path")
                return graph
            payloads = _write_payload_candidates(clean, target)
            explicit_empty = bool(
                re.search(r"\b(?:empty|zero[- ]byte|blank)\s+file\b|\bfile\s+(?:empty|blank)\b", lower)
            )
            if len(payloads) > 1:
                graph.paths.append(PathBinding(target, SemanticPathRole.OUTPUT, "explicit_write_target"))
                graph.errors.append("ambiguous write payload: multiple distinct payloads were provided")
                return graph
            if not payloads and not explicit_empty:
                graph.paths.append(PathBinding(target, SemanticPathRole.OUTPUT, "explicit_write_target"))
                graph.errors.append("write request has no explicit payload")
                return graph
            graph.paths.append(PathBinding(target, SemanticPathRole.OUTPUT, "explicit_write_target"))
            graph.write_payload = payloads[0] if payloads else ""
            return graph

        if paths and re.search(
            r"\b(?:list|enumerate)\b|\b(?:directory|folder)\s+(?:contents|entries|children)\b|\bwhat\s+(?:files|entries|children)\b",
            masked,
        ):
            return SemanticRequestGraph(
                clean,
                SemanticAction.DIRECTORY_LIST,
                mode,
                [PathBinding(paths[0], SemanticPathRole.TARGET, "directory_target")],
                evidence=["directory_list_grammar"],
            )

        if paths and re.search(
            r"\b(?:read|open|show|display|cat|fetch|view|print)\b|\b(?:contents?|text)\s+of\b", masked
        ):
            return SemanticRequestGraph(
                clean,
                SemanticAction.FILE_READ,
                mode,
                [PathBinding(paths[0], SemanticPathRole.INPUT, "file_read_target")],
                evidence=["file_read_grammar"],
            )

        if any(term in lower for term in ("from memory", "remembered", "recall", "stored in memory", "memory value")):
            return SemanticRequestGraph(clean, SemanticAction.MEMORY_RECALL, mode, evidence=["memory_recall_grammar"])

        if any(
            term in lower
            for term in ("schedule", "calendar", "book an appointment", "add to calendar", "book a meeting")
        ):
            return SemanticRequestGraph(clean, SemanticAction.CALENDAR, mode, evidence=["calendar_grammar"])

        return SemanticRequestGraph(clean, SemanticAction.UNKNOWN, response_mode=mode)


class EffectAuthorizer:
    @classmethod
    def authorize(cls, graph: SemanticRequestGraph) -> tuple[bool, frozenset[str], frozenset[str], str]:
        if graph.errors:
            return False, frozenset(), frozenset(), graph.errors[0]
        if graph.action == SemanticAction.FILE_WRITE:
            if not graph.output_path or graph.write_payload is None:
                return False, frozenset(), frozenset(), "file mutation requires explicit output path and payload"
            return True, frozenset({"write_file"}), frozenset({graph.output_path}), "explicit_write"
        if graph.action == SemanticAction.ARITHMETIC and graph.arithmetic and graph.arithmetic.output_path:
            return (
                True,
                frozenset({"write_file"}),
                frozenset({graph.arithmetic.output_path}),
                "explicit_arithmetic_output",
            )
        if graph.action == SemanticAction.SCREENSHOT:
            return True, frozenset({"take_screenshot"}), frozenset({graph.output_path}), "explicit_screenshot"
        if graph.action == SemanticAction.CALENDAR:
            return True, frozenset(), frozenset(), "calendar_adapter_policy"
        return True, frozenset(), frozenset(), "read_only_or_response_only"


def _number_from_text(text: str) -> int | float:
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        raise ValueError("no numeric operand found")
    token = match.group(0)
    return float(token) if "." in token else int(token)


def _normalize_number(value: int | float) -> int | float:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _render(da: Any, graph: SemanticRequestGraph, result: Any) -> Any:
    if result is None or not getattr(result, "success", False):
        return result
    mode = graph.response_mode
    telemetry = getattr(result, "telemetry", {}) or {}
    if mode == "SILENT":
        result.output = ""
    elif mode == "NUMBER_ONLY":
        result.output = str(telemetry.get("computed_result", result.output))
    elif mode == "VALUE_ONLY":
        value = telemetry.get("value", telemetry.get("computed_result", result.output))
        if isinstance(value, (dict, list)):
            if isinstance(value, dict) and len(value) == 1:
                value = next(iter(value.values()))
        result.output = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    elif mode == "JSON_ONLY":
        value = telemetry.get("value", telemetry.get("structured_result", result.output))
        result.output = json.dumps(value, ensure_ascii=False)
    elif mode == "PATH_ONLY":
        result.output = graph.output_path or next((p.path for p in graph.paths), result.output)
    return result


def _tool_output(tool_res: Any) -> Any:
    data = tool_res.data if isinstance(tool_res.data, dict) else tool_res.data
    if isinstance(data, dict) and "output" in data:
        return data["output"]
    return data


def _execute_file_read(da: Any, graph: SemanticRequestGraph, workspace: str) -> Any:
    path_str = graph.paths[0].path
    ws = Path(workspace if workspace else da.workspace_root()).expanduser().resolve()
    try:
        with da.tool_workspace(ws):
            path = da.resolve_workspace_path(path_str, must_exist=True)
        if not path.is_file():
            raise FileNotFoundError(f"not a regular file: {path_str}")
        raw = path.read_text(encoding="utf-8", errors="replace")
        return da.DirectActionResult(
            success=True,
            output=raw,
            execution_type="semantic_graph",
            tool_name="read_file",
            provider="local-filesystem",
            telemetry={
                "path": str(path),
                "value": raw,
                "verification_passed": True,
                "semantic_action": graph.action.value,
            },
        )
    except (PermissionError, FileNotFoundError) as exc:
        return da.DirectActionResult(
            False,
            f"File read failed: {exc}",
            execution_type="semantic_graph",
            tool_name="read_file",
            provider="local-filesystem",
            telemetry={"reason": "read_failed", "error": str(exc)},
        )


def _execute_file_write(da: Any, graph: SemanticRequestGraph, workspace: str) -> Any:
    path_str = graph.output_path
    payload = graph.write_payload if graph.write_payload is not None else ""
    ws = Path(workspace if workspace else da.workspace_root()).expanduser().resolve()
    try:
        with da.tool_workspace(ws):
            path = da.resolve_workspace_path(path_str, must_exist=False)
            raw_result = da.execute_tool("write_file", {"path": str(path), "content": payload})
        tool_res = da.parse_tool_result(raw_result)
        if not tool_res.ok:
            raise RuntimeError(tool_res.error or "write tool failed")
        actual = path.read_text(encoding="utf-8", errors="replace")
        if actual != payload:
            raise RuntimeError("independent write verification failed: content mismatch")
        return da.DirectActionResult(
            True,
            f"Successfully wrote file at {path} ({len(payload)} chars).",
            execution_type="semantic_graph",
            tool_name="write_file",
            provider="local-filesystem",
            telemetry={
                "path": str(path),
                "output_path": str(path),
                "payload": payload,
                "content_match": True,
                "verification_passed": True,
                "semantic_action": graph.action.value,
            },
        )
    except Exception as exc:
        return da.DirectActionResult(
            False,
            f"File write failed: {exc}",
            execution_type="semantic_graph",
            tool_name="write_file",
            provider="local-filesystem",
            telemetry={"reason": "write_failed", "error": str(exc), "verification_passed": False},
        )


def _execute_directory_list(da: Any, graph: SemanticRequestGraph, workspace: str) -> Any:
    path_str = graph.paths[0].path
    ws = Path(workspace if workspace else da.workspace_root()).expanduser().resolve()
    try:
        with da.tool_workspace(ws):
            path = da.resolve_workspace_path(path_str, must_exist=True)
        if not path.is_dir():
            raise FileNotFoundError(f"not a directory: {path_str}")
        entries = sorted(child.name for child in path.iterdir())
        return da.DirectActionResult(
            True,
            "\n".join(entries),
            execution_type="semantic_graph",
            tool_name="list_directory",
            provider="local-filesystem",
            telemetry={
                "path": str(path),
                "value": entries,
                "verification_passed": True,
                "semantic_action": graph.action.value,
            },
        )
    except (PermissionError, FileNotFoundError) as exc:
        return da.DirectActionResult(
            False,
            f"Directory list failed: {exc}",
            execution_type="semantic_graph",
            tool_name="list_directory",
            provider="local-filesystem",
            telemetry={"reason": "list_failed", "error": str(exc)},
        )


def _execute_arithmetic(da: Any, graph: SemanticRequestGraph, workspace: str) -> Any:
    assert graph.arithmetic is not None
    plan = graph.arithmetic
    ws = Path(workspace if workspace else da.workspace_root()).expanduser().resolve()
    try:
        with da.tool_workspace(ws):
            left_path = da.resolve_workspace_path(plan.left_path, must_exist=True)
            right_path = da.resolve_workspace_path(plan.right_path, must_exist=True)
        left = _number_from_text(left_path.read_text(encoding="utf-8", errors="replace"))
        right = _number_from_text(right_path.read_text(encoding="utf-8", errors="replace"))
        if plan.operation == "add":
            result = left + right
        elif plan.operation == "subtract":
            result = left - right
        elif plan.operation == "multiply":
            result = left * right
        elif plan.operation == "divide":
            if right == 0:
                raise ZeroDivisionError("division by zero")
            result = left / right
        else:
            raise ValueError(f"unsupported arithmetic operation: {plan.operation}")
        result = _normalize_number(result)
        rendered = str(result)

        verification = {
            "operation": plan.operation,
            "left_role": plan.left_role,
            "right_role": plan.right_role,
            "left_value": left,
            "right_value": right,
            "required_postcondition": f"{plan.left_role} {plan.operation} {plan.right_role}",
        }

        if plan.output_path:
            with da.tool_workspace(ws):
                output = da.resolve_workspace_path(plan.output_path, must_exist=False)
                tool_res = da.parse_tool_result(
                    da.execute_tool("write_file", {"path": str(output), "content": rendered})
                )
            if not tool_res.ok:
                raise RuntimeError(tool_res.error or "write tool failed")
            observed = output.read_text(encoding="utf-8", errors="replace")
            # Independent semantic verification: recompute from role-bound operands,
            # then compare that postcondition to the persisted value.
            expected = str(
                _normalize_number(
                    left + right
                    if plan.operation == "add"
                    else left - right
                    if plan.operation == "subtract"
                    else left * right
                    if plan.operation == "multiply"
                    else left / right
                )
            )
            if observed != expected:
                raise RuntimeError(f"semantic postcondition failed: expected {expected}, observed {observed}")
            output_msg = f"Successfully executed {plan.operation} and verified {output}."
            output_path = str(output)
        else:
            output_msg = rendered
            output_path = ""

        return da.DirectActionResult(
            True,
            output_msg,
            execution_type="semantic_graph",
            tool_name="semantic_arithmetic",
            provider="local-filesystem",
            telemetry={
                "computed_result": result,
                "input_values": [left, right],
                "input_paths": [str(left_path), str(right_path)],
                "output_path": output_path,
                "verification_contract": verification,
                "verification_passed": True,
                "side_effects": "write_explicit_output" if output_path else "none",
                "semantic_action": graph.action.value,
            },
        )
    except Exception as exc:
        return da.DirectActionResult(
            False,
            f"Arithmetic execution failed: {exc}",
            execution_type="semantic_graph",
            tool_name="semantic_arithmetic",
            provider="local-filesystem",
            telemetry={"reason": "arithmetic_failed", "error": str(exc), "verification_passed": False},
        )


def _execute_browser(da: Any, graph: SemanticRequestGraph) -> Any:
    assert graph.browser is not None
    plan = graph.browser
    try:
        nav = da.parse_tool_result(da.execute_tool("browser_navigate", {"url": plan.url}))
        if not nav.ok:
            raise RuntimeError(nav.error or "navigation failed")
        nav_value = _tool_output(nav)
        fields: dict[str, Any] = {}
        if plan.want_title:
            if isinstance(nav_value, dict) and nav_value.get("title") is not None:
                fields["title"] = nav_value.get("title")
            else:
                title_res = da.parse_tool_result(
                    da.execute_tool("browser_extract_content", {"url": plan.url, "selector": "title"})
                )
                if title_res.ok:
                    fields["title"] = _tool_output(title_res)
        for selector in plan.selectors:
            selected = da.parse_tool_result(
                da.execute_tool("browser_extract_content", {"url": plan.url, "selector": selector})
            )
            if not selected.ok:
                raise RuntimeError(f"selector {selector!r} failed: {selected.error or 'unknown error'}")
            value = _tool_output(selected)
            if isinstance(value, dict):
                value = value.get("content", value.get("text", value))
            fields[selector] = value
        if plan.want_text:
            body = da.parse_tool_result(
                da.execute_tool("browser_extract_content", {"url": plan.url, "selector": "body"})
            )
            if not body.ok:
                raise RuntimeError(body.error or "body extraction failed")
            fields["content"] = _tool_output(body)
        if plan.want_links:
            links = da.parse_tool_result(da.execute_tool("browser_extract_content", {"url": plan.url, "selector": "a"}))
            if not links.ok:
                raise RuntimeError(links.error or "link extraction failed")
            fields["links"] = _tool_output(links)
        if not fields:
            fields["page"] = nav_value
        browser_value: Any = next(iter(fields.values())) if len(fields) == 1 else fields
        return da.DirectActionResult(
            True,
            json.dumps(fields, ensure_ascii=False, default=str),
            execution_type="semantic_graph",
            tool_name="browser_extract_content",
            provider="browser-automation",
            telemetry={
                "url": plan.url,
                "value": browser_value,
                "structured_result": fields,
                "selectors": plan.selectors,
                "verification_passed": True,
                "semantic_action": graph.action.value,
            },
        )
    except Exception as exc:
        return da.DirectActionResult(
            False,
            f"Browser execution failed: {exc}",
            execution_type="semantic_graph",
            tool_name="browser_extract_content",
            provider="browser-automation",
            telemetry={"reason": "browser_failed", "error": str(exc)},
        )


_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_CMPOPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


def _eval_expr(
    node: ast.AST, env: dict[str, Any], functions: dict[str, ast.FunctionDef], overrides: dict[str, str], depth: int
) -> Any:
    if depth > 12:
        raise ValueError("semantic evaluation depth exceeded")
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return env[node.id]
    if isinstance(node, ast.UnaryOp):
        value = _eval_expr(node.operand, env, functions, overrides, depth + 1)
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return +value
        if isinstance(node.op, ast.Not):
            return not value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](
            _eval_expr(node.left, env, functions, overrides, depth + 1),
            _eval_expr(node.right, env, functions, overrides, depth + 1),
        )
    if isinstance(node, ast.BoolOp):
        values = [_eval_expr(v, env, functions, overrides, depth + 1) for v in node.values]
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.Compare):
        left = _eval_expr(node.left, env, functions, overrides, depth + 1)
        for op_node, comparator in zip(node.ops, node.comparators, strict=False):
            right = _eval_expr(comparator, env, functions, overrides, depth + 1)
            if type(op_node) not in _CMPOPS or not _CMPOPS[type(op_node)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        branch = node.body if _eval_expr(node.test, env, functions, overrides, depth + 1) else node.orelse
        return _eval_expr(branch, env, functions, overrides, depth + 1)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        name = overrides.get(node.func.id, node.func.id)
        if name in functions:
            args = [_eval_expr(arg, env, functions, overrides, depth + 1) for arg in node.args]
            value, _ = _eval_function(name, args, functions, overrides, depth + 1)
            return value
    raise ValueError(f"unsupported AST expression: {type(node).__name__}")


def _eval_function(
    name: str, args: list[Any], functions: dict[str, ast.FunctionDef], overrides: dict[str, str], depth: int = 0
) -> tuple[Any, dict[str, Any]]:
    fn = functions[name]
    if len(args) != len(fn.args.args):
        raise ValueError("arity mismatch")
    env = {arg.arg: value for arg, value in zip(fn.args.args, args, strict=False)}
    for stmt in fn.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            env[stmt.targets[0].id] = _eval_expr(stmt.value, env, functions, overrides, depth + 1)
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
            env[stmt.target.id] = _eval_expr(stmt.value, env, functions, overrides, depth + 1)
        elif isinstance(stmt, ast.If):
            branch = stmt.body if _eval_expr(stmt.test, env, functions, overrides, depth + 1) else stmt.orelse
            for child in branch:
                if isinstance(child, ast.Return):
                    return (
                        _eval_expr(child.value, env, functions, overrides, depth + 1)
                        if child.value is not None
                        else None
                    ), env
        elif isinstance(stmt, ast.Return):
            return (
                _eval_expr(stmt.value, env, functions, overrides, depth + 1) if stmt.value is not None else None
            ), env
    raise ValueError("no evaluable return")


def _value_flow_findings(repo_path: Path, base_result: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    assertions: list[dict[str, Any]] = []
    functions: dict[str, ast.FunctionDef] = {}
    function_file: dict[str, str] = {}

    for py_file in sorted(repo_path.rglob("*.py")):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if "test" in py_file.name.lower():
            # Parse simple assert target(args) == expected contracts.
            for node in ast.walk(tree):
                if isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare) and node.test.comparators:
                    call = node.test.left
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                        try:
                            args = [ast.literal_eval(arg) for arg in call.args]
                            expected = ast.literal_eval(node.test.comparators[0])
                        except Exception:
                            continue
                        assertions.append(
                            {"function": call.func.id, "args": args, "expected": expected, "file": str(py_file)}
                        )
        else:
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    functions[node.name] = node
                    function_file[node.name] = str(py_file)

    for contract in assertions:
        fn_name = contract["function"]
        if fn_name not in functions:
            continue
        try:
            actual, env = _eval_function(fn_name, contract["args"], functions, {})
        except Exception:
            continue
        expected = contract["expected"]
        if actual == expected:
            continue
        fn = functions[fn_name]
        local_calls = [
            node.func.id
            for node in ast.walk(fn)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in functions
        ]

        # Wrong helper: prove a sibling substitution satisfies the test contract.
        for called in local_calls:
            for sibling, sibling_fn in functions.items():
                if sibling in {called, fn_name} or len(sibling_fn.args.args) != len(functions[called].args.args):
                    continue
                try:
                    candidate, _ = _eval_function(fn_name, contract["args"], functions, {called: sibling})
                except Exception:
                    continue
                if candidate == expected:
                    findings.append(
                        {
                            "function": fn_name,
                            "category": "wrong_helper_call",
                            "called_helper": called,
                            "expected_helper": sibling,
                            "description": f"Function '{fn_name}' calls '{called}', but substituting '{sibling}' satisfies the observed test contract ({expected!r}).",
                            "reason": "symbolic value-flow substitution reproduces expected assertion",
                            "confidence": 1.0,
                            "file": function_file.get(fn_name, ""),
                        }
                    )
                    break
            if findings and findings[-1].get("function") == fn_name:
                break

        if findings and findings[-1].get("function") == fn_name:
            continue

        # Wrong return variable: an already-computed local equals the contract.
        returned_names = [
            node.value.id for node in ast.walk(fn) if isinstance(node, ast.Return) and isinstance(node.value, ast.Name)
        ]
        for returned in returned_names:
            matching = [name for name, value in env.items() if name != returned and value == expected]
            if matching:
                findings.append(
                    {
                        "function": fn_name,
                        "category": "wrong_returned_variable",
                        "returned_variable": returned,
                        "expected_variable": matching[0],
                        "description": f"Function '{fn_name}' returns '{returned}' ({actual!r}) although computed local '{matching[0]}' equals the required result ({expected!r}).",
                        "reason": "symbolic local-value flow matches failing assertion",
                        "confidence": 1.0,
                        "file": function_file.get(fn_name, ""),
                    }
                )

    return findings


def install_semantic_core() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from jarvis.amaura import direct_action as da
    from jarvis.amaura.models import GovernanceError

    original_execute_tool = da.execute_tool
    original_diagnose: Any = getattr(
        da.RepositoryDiagnosticEngine.diagnose, "__func__", da.RepositoryDiagnosticEngine.diagnose
    )

    def guarded_execute_tool(name: str, arguments: dict[str, Any] | None = None, *args: Any, **kwargs: Any) -> Any:
        arguments = dict(arguments or {})
        if name in _MUTATING_TOOLS and name not in _EFFECT_SCOPE.get():
            raise GovernanceError(
                f"semantic effect firewall blocked {name}: action was not authorized by request graph"
            )
        if name == "write_file":
            requested = str(arguments.get("path", ""))
            allowed = _OUTPUT_SCOPE.get()
            if allowed and requested:
                requested_path = Path(requested).expanduser()
                if not any(
                    requested_path == Path(candidate).expanduser() or requested_path.name == Path(candidate).name
                    for candidate in allowed
                ):
                    raise GovernanceError(
                        f"semantic effect firewall blocked write_file target {requested!r}: not an authorized output role"
                    )
        return original_execute_tool(name, arguments, *args, **kwargs)

    da.execute_tool = guarded_execute_tool

    def safe_extract_all_paths(cls: Any, text: str) -> list[str]:
        return extract_paths(text, cls.KNOWN_EXTENSIONS)

    def safe_extract_structured_arguments(cls: Any, text: str, *, default_workspace: str = "") -> dict[str, Any]:
        paths = extract_paths(text, cls.KNOWN_EXTENSIONS)
        output = _explicit_output(text, paths)
        args: dict[str, Any] = {}
        if output:
            args["output_path"] = output
        remaining = [path for path in paths if path != output]
        if remaining:
            args["input_path"] = remaining[0]
        if len(remaining) > 1:
            args["secondary_input_path"] = remaining[1]
        lower = text.lower()
        if paths and re.search(r"\b(?:review|inspect|diagnose|audit|analy[sz]e|trace|investigate)\b", lower):
            args["repo_path"] = paths[0]
        if paths and any(
            term in lower for term in ("directory", "folder", "list files", "list entries", "contents of")
        ):
            args["directory"] = paths[0]
        if len(paths) == 1 and not output:
            args["path"] = paths[0]
        return args

    _install_attr(da.PathExtractor, "extract_all_paths", classmethod(safe_extract_all_paths))
    _install_attr(da.PathExtractor, "extract_structured_arguments", classmethod(safe_extract_structured_arguments))

    def enhanced_diagnose(cls: Any, repo_path: Path) -> dict[str, Any]:
        result = original_diagnose(cls, repo_path)
        flow = _value_flow_findings(repo_path, result)
        if flow:
            existing = [f for f in result.get("findings", []) if f.get("category") != "unresolved_semantic_defect"]
            seen = {(f.get("function"), f.get("category"), f.get("description")) for f in flow}
            existing = [f for f in existing if (f.get("function"), f.get("category"), f.get("description")) not in seen]
            result["findings"] = flow + existing
        return result

    _install_attr(da.RepositoryDiagnosticEngine, "diagnose", classmethod(enhanced_diagnose))

    def can_handle(cls: Any, text: str) -> bool:
        graph = SemanticParser.parse(text, da.RequestPreprocessor.KNOWN_EXTENSIONS)
        return graph.action != SemanticAction.UNKNOWN

    def execute(cls: Any, text: str, *, context: str = "", control: Any = None, workspace: str = "") -> Any:
        graph = SemanticParser.parse(text, da.RequestPreprocessor.KNOWN_EXTENSIONS)
        if graph.action == SemanticAction.UNKNOWN:
            return None
        allowed, effects, outputs, reason = EffectAuthorizer.authorize(graph)
        if not allowed:
            return da.DirectActionResult(
                False,
                f"Request rejected before execution: {reason}",
                execution_type="semantic_graph",
                tool_name="effect_authorizer",
                provider="semantic-core",
                policy_decision="refused",
                telemetry={"reason": reason, "semantic_action": graph.action.value, "verification_passed": False},
            )

        token_effect = _EFFECT_SCOPE.set(effects)
        token_output = _OUTPUT_SCOPE.set(outputs)
        try:
            if graph.action == SemanticAction.EXACT_LITERAL:
                result = da.DirectActionResult(
                    True,
                    graph.literal_payload,
                    execution_type="semantic_graph",
                    tool_name="exact_response",
                    provider="semantic-core",
                    telemetry={
                        "side_effects": "none",
                        "verification_passed": True,
                        "semantic_action": graph.action.value,
                    },
                )
            elif graph.action == SemanticAction.POLICY_REFUSAL:
                result = da.DirectActionResult(
                    False,
                    "I cannot perform that destructive action while bypassing approval or policy.",
                    execution_type="semantic_graph",
                    tool_name="policy",
                    provider="semantic-core",
                    policy_decision="refused",
                    telemetry={"reason": "destructive_action_unauthorized", "semantic_action": graph.action.value},
                )
            elif graph.action == SemanticAction.FILE_READ:
                result = _execute_file_read(da, graph, workspace)
            elif graph.action == SemanticAction.FILE_WRITE:
                result = _execute_file_write(da, graph, workspace)
            elif graph.action == SemanticAction.DIRECTORY_LIST:
                result = _execute_directory_list(da, graph, workspace)
            elif graph.action == SemanticAction.ARITHMETIC:
                result = _execute_arithmetic(da, graph, workspace)
            elif graph.action == SemanticAction.BROWSER:
                result = _execute_browser(da, graph)
            elif graph.action == SemanticAction.REPOSITORY:
                result = cls._try_repository_inspection(text, workspace=workspace)
            elif graph.action == SemanticAction.SCREENSHOT:
                result = cls._try_screenshot(text, workspace=workspace)
            elif graph.action == SemanticAction.MEMORY_RECALL:
                result = cls._try_memory_recall(text, context=context, control=control)
            elif graph.action == SemanticAction.CALENDAR:
                result = cls._try_calendar_event(text, context=context)
            else:
                result = None
        finally:
            _OUTPUT_SCOPE.reset(token_output)
            _EFFECT_SCOPE.reset(token_effect)
        return _render(da, graph, result)

    _install_attr(da.DirectActionRouter, "can_handle", classmethod(can_handle))
    _install_attr(da.DirectActionRouter, "execute", classmethod(execute))
    _INSTALLED = True
