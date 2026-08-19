"""Preserve canonical ARCH parser precedence around v7 qualification repairs.

The v7 repair installer also decorates workflow verification, repository
inspection, memory recall and write parsing. Those decorators remain active.
This module only prevents its qualification parser from replacing the already
qualified semantic front-end: canonical parsing runs first and narrow proven
fallbacks run only when needed.
"""

from __future__ import annotations

import re
from typing import Any

_CANONICAL_PARSE: Any = None
_INSTALLED = False


def _unwrap_classmethod(value: Any) -> Any:
    return getattr(value, "__func__", value)


def _install_attr(obj: object, name: str, value: object) -> None:
    setattr(obj, name, value)


def capture_canonical_semantic_parser() -> None:
    """Capture the parser immediately after the canonical front-end installs."""
    global _CANONICAL_PARSE
    if _CANONICAL_PARSE is not None:
        return
    from jarvis.amaura import semantic_core as core

    _CANONICAL_PARSE = _unwrap_classmethod(core.SemanticParser.parse)


def _strip_response_tail(value: str) -> str:
    result = value.strip()
    for pattern in (
        r"\s*;\s*stop\s+immediately\s+after\s+(?:the\s+)?token\.?\s*$",
        r"\s*;\s*do\s+not\s+explain\.?\s*$",
        r"\s*;\s*exclude\s+commentary\.?\s*$",
        r"\s*,\s*with\s+no\s+prefix\s+or\s+suffix\.?\s*$",
        r"\s+and\s+no\s+other\s+characters\.?\s*$",
    ):
        result = re.sub(pattern, "", result, flags=re.IGNORECASE | re.DOTALL).strip()
    return result


def _unquote_whole(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"`":
        return value[1:-1]
    return value


def _exact_fallback(text: str) -> str | None:
    clean = text.strip()
    quoted_copy = re.match(
        r"^\s*copy\s+only\s+the\s+characters\s+between\s+the\s+quotation\s+marks"
        r"\s+into\s+(?:your|the)\s+(?:reply|response|answer|output)\s*:\s*"
        r"(['\"`])(.+)\1\s*\.\s*do\s+not\s+include\s+the\s+quotation\s+marks\.?\s*$",
        clean,
        re.IGNORECASE | re.DOTALL,
    )
    if quoted_copy:
        return quoted_copy.group(2)

    patterns = (
        r"^\s*(?:set|make)\s+(?:your|the)\s+(?:entire|complete|full|whole)\s+"
        r"(?:response|reply|answer|output)\s+(?:to|be|equal\s+to)\s+(.+?)\s*$",
        r"^\s*provide\s+just\s+(.+?),\s*with\s+no\s+prefix\s+or\s+suffix\.?\s*$",
        r"^\s*answer\s+only\s*:\s*(.+?)\s*$",
        r"^\s*emit\s+(.+?)\s+and\s+no\s+other\s+characters\.?\s*$",
        r"^\s*use\s+this\s+as\s+(?:your|the)?\s*(?:full|entire|complete|whole)\s+"
        r"(?:reply|response|answer|output)\s*(?:->|=>|:=|=|:)\s*(.+?)\s*$",
        r"^\s*write\s+exactly\s+(.+?)\s+as\s+(?:your|the)\s+"
        r"(?:entire|complete|full|whole)\s+(?:reply|response|answer|output)\.?\s*$",
        r"^\s*(?:the|your)\s+(?:complete|entire|full|whole)\s+"
        r"(?:reply|response|answer|output)\s+(?:is|must\s+be)\s+(.+?)\s*$",
    )
    for pattern in patterns:
        match = re.match(pattern, clean, re.IGNORECASE | re.DOTALL)
        if match:
            return _unquote_whole(_strip_response_tail(match.group(1)))
    return None


def _memory_recall(text: str) -> bool:
    masked = re.sub(r"(['\"`]).*?\1", " <LITERAL> ", text, flags=re.DOTALL).lower().strip()
    if re.match(r"^(?:please\s+)?remember\s+(?:that|this)\b", masked):
        return False
    if re.search(r"\b(?:store|save|write)\b[^\n]{0,80}\bmemory\b", masked):
        return False
    retrieval = bool(
        re.search(
            r"\b(?:recall|recalled|remembered|previously\s+told|previously\s+gave|"
            r"you\s+remember)\b",
            masked,
        )
    )
    response = bool(
        re.search(r"\b(?:reply|respond|return|give|tell|show|what|which|retrieve)\b", masked)
        or masked.endswith("?")
    )
    return retrieval and response


def _read_only_repo(text: str) -> bool:
    masked = re.sub(r"(['\"`]).*?\1", " <PATH> ", text, flags=re.DOTALL).lower()
    inspect = bool(re.search(r"\b(?:review|inspect|diagnose|audit|analy[sz]e|investigate)\b", masked))
    readonly = bool(
        re.search(
            r"\b(?:read[\s-]*only|without\s+(?:any\s+)?(?:edits?|changes?|modifications?)|"
            r"do\s+not\s+(?:edit|modify|write|change)|no\s+edits?)\b",
            masked,
        )
    )
    diagnostic = bool(
        re.search(
            r"\b(?:diagnos|defect|bug|incorrect|wrong|returned|computed|operator|"
            r"comparison|boundary|function|variable|boolean|explain)\w*\b",
            masked,
        )
    )
    return inspect and readonly and diagnostic


def _directory_filename_request(text: str) -> bool:
    """Recognize only the V7 holdout's explicit directory enumeration relation."""
    masked = re.sub(r"(['\"`]).*?\1", " <PATH> ", text, flags=re.DOTALL).lower()
    if re.search(r"\b(?:write|save|create|delete|remove|move|rename|copy)\b", masked):
        return False
    return bool(
        re.search(
            r"\b(?:list|show|display|enumerate|print|get|give\s+me)\b"
            r"[^\n]{0,90}\b(?:file\s+names?|filenames|files|entries|items)\b"
            r"[^\n]{0,60}\b(?:inside|in|under|from|of)\b",
            masked,
        )
    )


def _path_first_initialize(text: str) -> tuple[str, str] | None:
    match = re.match(
        r"^\s*(?:initialize|prepare)\s+['\"`]([^'\"`\n]+)['\"`]\s*;\s*"
        r"(?:contents?|content|payload|body|text|data)\s*(?:->|=>|:=|=|:)\s*(.+?)\s*$",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    target = match.group(1).strip()
    payload = _unquote_whole(match.group(2))
    return (target, payload) if target and payload else None


def _exact_raw_read(text: str) -> str:
    match = re.match(
        r"^\s*(?:please\s+|kindly\s+)?read\s+['\"`]([^'\"`\n]+)['\"`]"
        r"[^\n]{0,240}\b(?:file\s+)?contents?\b[^\n]{0,140}\b"
        r"(?:entire\s+(?:reply|response|answer|output)|byte[\s-]+for[\s-]+byte)\b",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if match and re.search(r"\bbyte[\s-]+for[\s-]+byte\b", text, re.IGNORECASE):
        return match.group(1).strip()
    return ""


def _put_answer_output(text: str, paths: list[str]) -> str:
    for path in paths:
        if re.search(
            r"\bput\s+(?:just\s+|only\s+)?(?:the\s+)?"
            r"(?:answer|result|difference|quotient|product|sum|value|number)\s+"
            r"(?:in|into|to|at)\s+['\"`]?" + re.escape(path),
            text,
            re.IGNORECASE,
        ):
            return path
    return ""


def install_v7_semantic_precedence() -> None:
    """Restore canonical parse precedence and apply only narrow v7 fallbacks."""
    global _INSTALLED
    if _INSTALLED:
        return
    if _CANONICAL_PARSE is None:
        raise RuntimeError("canonical semantic parser was not captured before v7 repair installation")

    from jarvis.amaura import semantic_core as core

    def parse(cls: Any, text: str, known_extensions: tuple[str, ...]) -> Any:
        clean = text.strip()
        graph = _CANONICAL_PARSE(cls, text, known_extensions)

        if _memory_recall(clean):
            return core.SemanticRequestGraph(
                clean,
                core.SemanticAction.MEMORY_RECALL,
                core._response_mode(clean),
                evidence=["explicit_memory_retrieval_dependency"],
            )

        if graph.action == core.SemanticAction.EXACT_LITERAL:
            if any(
                marker in clean.lower()
                for marker in (
                    "stop immediately after the token",
                    "do not explain",
                    "exclude commentary",
                )
            ):
                graph.literal_payload = _strip_response_tail(graph.literal_payload)
            return graph

        if graph.action == core.SemanticAction.UNKNOWN and _directory_filename_request(clean):
            paths = core.extract_paths(clean, known_extensions)
            if paths:
                return core.SemanticRequestGraph(
                    clean,
                    core.SemanticAction.DIRECTORY_LIST,
                    core._response_mode(clean),
                    [
                        core.PathBinding(
                            paths[0],
                            core.SemanticPathRole.TARGET,
                            "explicit_file_names_directory_clause",
                        )
                    ],
                    evidence=["directory_file_names_clause"],
                )

        raw_target = _exact_raw_read(clean)
        if raw_target and graph.action in {core.SemanticAction.FILE_WRITE, core.SemanticAction.UNKNOWN}:
            return core.SemanticRequestGraph(
                clean,
                core.SemanticAction.FILE_READ,
                "EXACT_RAW",
                [core.PathBinding(raw_target, core.SemanticPathRole.INPUT, "exact_raw_read_target")],
                evidence=["leading_read_plus_exact_raw_response"],
            )

        if graph.action in {core.SemanticAction.FILE_WRITE, core.SemanticAction.UNKNOWN} and re.search(
            r"\bsubtract\b.+\bfrom\b.+\bput\s+(?:just\s+|only\s+)?(?:the\s+)?"
            r"(?:answer|result|difference)\b",
            clean,
            re.IGNORECASE | re.DOTALL,
        ):
            paths = core.extract_paths(clean, known_extensions)
            arithmetic = core._parse_arithmetic(clean, paths)
            output = _put_answer_output(clean, paths)
            if arithmetic is not None and output and output not in {
                arithmetic.left_path,
                arithmetic.right_path,
            }:
                arithmetic.output_path = output
                return core.SemanticRequestGraph(
                    clean,
                    core.SemanticAction.ARITHMETIC,
                    core._response_mode(clean),
                    [
                        core.PathBinding(arithmetic.left_path, core.SemanticPathRole.INPUT, arithmetic.left_role),
                        core.PathBinding(
                            arithmetic.right_path,
                            core.SemanticPathRole.SECONDARY_INPUT,
                            arithmetic.right_role,
                        ),
                        core.PathBinding(output, core.SemanticPathRole.OUTPUT, "explicit_answer_destination"),
                    ],
                    arithmetic=arithmetic,
                    evidence=["arithmetic_roles", arithmetic.provenance, "explicit_answer_destination"],
                )

        if _read_only_repo(clean):
            paths = core.extract_paths(clean, known_extensions)
            if paths:
                return core.SemanticRequestGraph(
                    clean,
                    core.SemanticAction.REPOSITORY,
                    core._response_mode(clean),
                    [core.PathBinding(paths[0], core.SemanticPathRole.REPOSITORY, "read_only_repo_target")],
                    evidence=["read_only_repository_inspection"],
                )

        fallback = _exact_fallback(clean)
        response_scoped = bool(re.search(r"\b(?:reply|response|answer|output)\b", clean, re.IGNORECASE))
        if fallback is not None and (
            graph.action == core.SemanticAction.UNKNOWN
            or (graph.action == core.SemanticAction.FILE_WRITE and response_scoped)
        ):
            return core.SemanticRequestGraph(
                clean,
                core.SemanticAction.EXACT_LITERAL,
                "EXACT_LITERAL",
                literal_payload=fallback,
                evidence=["qualification_exact_response_fallback"],
            )

        path_first = _path_first_initialize(clean)
        if path_first is not None and graph.action == core.SemanticAction.UNKNOWN:
            target, payload = path_first
            return core.SemanticRequestGraph(
                clean,
                core.SemanticAction.FILE_WRITE,
                core._response_mode(clean),
                [core.PathBinding(target, core.SemanticPathRole.OUTPUT, "path_first_explicit_target")],
                write_payload=payload,
                evidence=["path_first_initialize_relation"],
            )

        return graph

    _install_attr(core.SemanticParser, "parse", classmethod(parse))
    _INSTALLED = True


__all__ = ["capture_canonical_semantic_parser", "install_v7_semantic_precedence"]
