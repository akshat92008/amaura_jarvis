"""Phase 9 semantic hardening for the single ARCH request graph.

This module is intentionally small and boundary-focused.  It does not add a
second routing stack: it hardens the installed semantic front-end with
span-aware exact literals, clause-scoped negation, path-first writes,
repository admission, response-mode normalization, and a fail-closed
postcondition gate for mutating actions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_INSTALLED = False


@dataclass(frozen=True)
class _PayloadSpan:
    payload: str
    start: int
    end: int
    quote_style: str = "none"
    prefix: str = ""
    suffix: str = ""


_EXACT_SUFFIX = re.compile(
    r"\s*(?:and\s+nothing\s+(?:else|more)|with\s+nothing\s+(?:else|more)|"
    r"and\s+no\s+other\s+text|without\s+(?:any\s+)?(?:explanation|commentary)|"
    r"with\s+no\s+(?:other|extra)\s+(?:text|words|commentary))\.?\s*$",
    re.IGNORECASE,
)
_EXACT_COMMAND = r"(?:reply|respond|return|say|echo|repeat|print|output|answer|give\s+me|send|type|write\s+back)"
_SCOPE = r"(?:response|answer|reply|output|string|token|value|text|word|payload)"
_EXCLUSIVE = r"(?:only|solely|just|exactly|strictly|verbatim|precisely)"


def _quote_style(ch: str) -> str:
    return {"'": "single", '"': "double", "`": "backtick"}.get(ch, "none")


def _split_clauses(text: str) -> list[tuple[int, int, str]]:
    """Split top-level clauses while preserving quoted payloads and offsets."""
    result: list[tuple[int, int, str]] = []
    quote = ""
    start = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote and (i == 0 or text[i - 1] != "\\"):
                quote = ""
        elif ch in "'\"`":
            quote = ch
        elif ch in ";\n" or ch in ".!?" and (i + 1 == len(text) or text[i + 1].isspace()):
            raw = text[start:i].strip()
            if raw:
                left = start
                while left < i and text[left].isspace():
                    left += 1
                result.append((left, i, text[left:i].strip()))
            start = i + 1
        i += 1
    raw = text[start:].strip()
    if raw:
        left = start
        while left < len(text) and text[left].isspace():
            left += 1
        result.append((left, len(text), text[left:].strip()))
    return result


def _clause_negates_action(clause: str) -> bool:
    masked = re.sub(r"(['\"`]).*?\1", " <DATA> ", clause, flags=re.DOTALL)
    return bool(
        re.search(
            r"\b(?:do\s+not|don't|dont|never|must\s+not|should\s+not|without)\b"
            r"[^;\n]{0,50}\b(?:write|create|save|store|modify|edit|delete|remove|overwrite|transform|convert)\b",
            masked,
            re.IGNORECASE,
        )
        or re.search(
            r"\b(?:rather\s+than|instead\s+of)\s+(?:writing|creating|saving|storing|modifying|editing|deleting|removing)\b",
            masked,
            re.IGNORECASE,
        )
    )


def _positive_view(text: str) -> str:
    clauses = _split_clauses(text)
    positive = [raw for _, _, raw in clauses if not _clause_negates_action(raw)]
    return ". ".join(positive) if positive else text


def _exact_span(text: str, paths: list[str]) -> _PayloadSpan | None:
    clean = text.strip()
    if not clean:
        return None
    lower = clean.lower()
    if "://" in clean:
        return None
    if paths and any(
        phrase in lower
        for phrase in (
            "from the file", "in the file", "file contents", "contents of", "raw file",
            "read ", "open ", "load ", "fetch ", "repository", "repo", "codebase",
        )
    ):
        return None
    if any(phrase in lower for phrase in ("from memory", "stored in memory", "from the browser", "from the page", "css selector", "calendar")):
        return None

    masked = re.sub(r"(['\"`]).*?\1", " <DATA> ", clean, flags=re.DOTALL)
    command_signal = bool(
        re.search(rf"\b{_EXACT_COMMAND}\b", masked, re.IGNORECASE)
        and (
            re.search(rf"\b{_EXCLUSIVE}\b", masked, re.IGNORECASE)
            or ":" in clean
            or re.search(r"\bnothing\s+(?:else|more)\b|\bno\s+other\s+text\b", masked, re.IGNORECASE)
        )
    )
    declarative_signal = bool(
        re.search(
            rf"\b(?:make|set)\s+(?:the\s+|your\s+)?{_SCOPE}\s+(?:equal\s+to|equals?|be)\b",
            masked,
            re.IGNORECASE,
        )
        or re.search(
            rf"\b(?:your\s+)?(?:entire|whole|complete|full)?\s*{_SCOPE}\s+"
            r"(?:must|should|shall|needs?\s+to)\s+(?:be|contain|consist)",
            masked,
            re.IGNORECASE,
        )
    )
    echo_signal = bool(re.match(r"^\s*(?:please\s+|kindly\s+)?(?:echo|repeat)\s*[:\-]", clean, re.IGNORECASE))
    if not (command_signal or declarative_signal or echo_signal):
        return None

    quoted = list(re.finditer(r"(['\"`])([^'\"`\n]*)\1", clean))
    if quoted:
        match = quoted[-1]
        return _PayloadSpan(
            match.group(2),
            match.start(2),
            match.end(2),
            _quote_style(match.group(1)),
            clean[: match.start(1)].strip(),
            clean[match.end(0) :].strip(),
        )

    work_match = _EXACT_SUFFIX.search(clean)
    work_end = work_match.start() if work_match else len(clean)
    work = clean[:work_end].rstrip()
    suffix = clean[work_end:].strip()

    boundary = re.search(r"(?:=|\bequals?\b|\bequal\s+to\b)\s*(.+)$", work, re.IGNORECASE)
    if boundary:
        raw = boundary.group(1).strip().rstrip(".")
        start = clean.find(raw, boundary.start(1))
        return _PayloadSpan(raw, start, start + len(raw), "none", clean[:start].strip(), suffix)

    if ":" in work:
        raw = work.rsplit(":", 1)[1].strip().rstrip(".")
        if raw:
            start = clean.rfind(raw, 0, work_end)
            return _PayloadSpan(raw, start, start + len(raw), "none", clean[:start].strip(), suffix)

    prefix = re.compile(
        rf"^\s*(?:(?:please|kindly)\s+)?(?:{_EXCLUSIVE}\s+)?{_EXACT_COMMAND}"
        rf"(?:\s+with)?\s*(?:{_EXCLUSIVE}\s+)?(?:the\s+|this\s+)?(?:entire\s+|whole\s+|complete\s+)?(?:{_SCOPE})?\s*",
        re.IGNORECASE,
    )
    candidate = prefix.sub("", work).strip()
    candidate = re.sub(rf"^(?:is|as|be|{_EXCLUSIVE})\s+", "", candidate, flags=re.IGNORECASE).strip()
    if not candidate or candidate.lower() in {"value", "token", "text", "response", "answer", "reply", "output"}:
        return None
    candidate = candidate.rstrip(".")
    start = clean.find(candidate)
    if start < 0:
        return None
    return _PayloadSpan(candidate, start, start + len(candidate), "none", clean[:start].strip(), suffix)


def _write_intent(da: Any, core: Any, text: str, known_extensions: tuple[str, ...]) -> Any | None:
    positive = _positive_view(text)
    masked = re.sub(r"(['\"`]).*?\1", " <DATA> ", positive, flags=re.DOTALL)
    if not re.search(r"\b(?:write|create|make|save|store|put|record)\b", masked, re.IGNORECASE):
        return None

    paths = list(core.extract_paths(positive, known_extensions))
    if not paths:
        return None

    target = ""
    for path in paths:
        p = re.escape(path)
        patterns = (
            rf"\b(?:write|save|store|put|record)\s+(?:to|into|in|at)\s+['\"`]?{p}",
            rf"\b(?:create|make)\s+(?:an?\s+)?(?:empty\s+)?(?:file\s+)?(?:at\s+)?['\"`]?{p}",
            rf"\b(?:write|save|store|put|record)\s+['\"`][^'\"`]*['\"`]\s+(?:to|into)\s+['\"`]?{p}",
            rf"\b(?:file|target|destination|output)\s+['\"`]?{p}\b",
        )
        if any(re.search(pattern, positive, re.IGNORECASE) for pattern in patterns):
            target = path
            break
    if not target:
        return None

    candidates: list[tuple[str, int, int]] = []

    def add_match(match: re.Match[str]) -> None:
        value = match.group("payload")
        start, end = match.span("payload")
        key = (value, start, end)
        if key not in candidates:
            candidates.append(key)

    target_re = re.escape(target)
    payload_patterns = (
        rf"\b(?:write|save|store|put|record)\s+(?:to|into|in|at)\s+['\"`]?{target_re}['\"`]?\s*(?:with\s+(?:content|text|payload|data)|containing|contains?|:|=)\s*['\"`]?(?P<payload>[^'\"`\n;]+)['\"`]?",
        rf"\b(?:create|make)\s+(?:an?\s+)?(?:file\s+)?(?:at\s+)?['\"`]?{target_re}['\"`]?\s*(?:with\s+(?:content|text|payload|data)|containing|contains?|:|=)\s*['\"`]?(?P<payload>[^'\"`\n;]+)['\"`]?",
        rf"\b(?:write|save|store|put|record)\s+['\"`](?P<payload>[^'\"`\n]*)['\"`]\s+(?:to|into)\s+['\"`]?{target_re}",
    )
    for pattern in payload_patterns:
        for match in re.finditer(pattern, positive, re.IGNORECASE):
            add_match(match)

    # Quoted payload following explicit content markers; this catches punctuation
    # and empty strings without allowing the quoted path itself to become data.
    for match in re.finditer(
        r"\b(?:containing|contains?|content\s*(?:is|=|:)|payload\s*(?:is|=|:)|text\s*(?:is|=|:)|with\s+(?:the\s+)?(?:content|text|payload|data))\s*['\"`](?P<payload>[^'\"`\n]*)['\"`]",
        positive,
        re.IGNORECASE,
    ):
        add_match(match)

    # Normalize raw candidates and reject contradictory payload authorities.
    normalized: list[tuple[str, int, int]] = []
    for value, start, end in candidates:
        value = value.strip()
        while value and value[-1] in ".,;":
            value = value[:-1].rstrip()
            end -= 1
        item = (value, start, end)
        if item not in normalized:
            normalized.append(item)
    unique_values = {value for value, _, _ in normalized}

    empty_requested = bool(re.search(r"\b(?:empty|blank)\s+(?:file|content)\b", positive, re.IGNORECASE))
    if len(unique_values) > 1:
        return da.WriteAction(target_path=target, is_invalid=True, invalid_reason="ambiguous write payload", confidence=1.0)
    if not normalized and not empty_requested:
        return da.WriteAction(target_path=target, is_invalid=True, invalid_reason="write request has no explicit payload", confidence=1.0)

    payload, start, end = normalized[0] if normalized else ("", -1, -1)
    return da.WriteAction(
        target_path=target,
        content=payload,
        payload=payload,
        payload_span_start=start,
        payload_span_end=end,
        content_source_span=positive[start:end] if start >= 0 else "",
        exactness=True,
        exact_content_requested=True,
        has_explicit_content=bool(normalized) or empty_requested,
        explicit_empty=empty_requested,
        is_empty_requested=empty_requested,
        confidence=1.0,
    )


def install_semantic_phase9() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from jarvis.amaura import direct_action as da
    from jarvis.amaura import semantic_core as core

    base_parse = core.SemanticParser.parse.__func__
    base_write_parse = da.WriteActionParser.parse.__func__
    base_execute = da.DirectActionRouter.execute.__func__

    def write_parse(cls: Any, text: str) -> Any:
        parsed = _write_intent(da, core, text, da.RequestPreprocessor.KNOWN_EXTENSIONS)
        return parsed if parsed is not None else base_write_parse(cls, text)

    da.WriteActionParser.parse = classmethod(write_parse)

    def parse(cls: Any, text: str, known_extensions: tuple[str, ...]) -> Any:
        clean = text.strip()
        mode = core._response_mode(clean)
        paths = list(core.extract_paths(clean, known_extensions))
        exact = _exact_span(clean, paths)
        if exact is not None:
            return core.SemanticRequestGraph(
                clean,
                core.SemanticAction.EXACT_LITERAL,
                response_mode=mode,
                literal_payload=exact.payload,
                evidence=["phase9_exact_payload_span"],
            )

        positive = _positive_view(clean)
        positive_paths = list(core.extract_paths(positive, known_extensions))
        masked = re.sub(r"(['\"`]).*?\1", " <DATA> ", positive, flags=re.DOTALL)
        inspect = bool(re.search(r"\b(?:check|examine|review|inspect|diagnose|audit|analy[sz]e|trace|investigate|debug|find\s+(?:the\s+)?bug|locate\s+(?:the\s+)?bug)\b", masked, re.IGNORECASE))
        repo_semantics = bool(re.search(r"\b(?:repo|repository|codebase|project|source|tests?|bugs?|defects?|implementation)\b", masked, re.IGNORECASE))
        positive_mutation = bool(re.search(r"\b(?:write|edit|modify|delete|remove|create|save|store|overwrite)\b", masked, re.IGNORECASE))
        if inspect and positive_paths and not positive_mutation:
            candidate = positive_paths[0]
            path_like_repo = not Path(candidate).suffix
            if repo_semantics or path_like_repo or "read-only" in positive.lower() or "read only" in positive.lower():
                return core.SemanticRequestGraph(
                    clean,
                    core.SemanticAction.REPOSITORY,
                    mode,
                    [core.PathBinding(candidate, core.SemanticPathRole.REPOSITORY, "phase9_repository_inspection_target")],
                    evidence=["phase9_clause_scoped_repository_routing"],
                )

        parsed_write = _write_intent(da, core, positive, known_extensions)
        if parsed_write is not None:
            graph = core.SemanticRequestGraph(clean, core.SemanticAction.FILE_WRITE, mode, evidence=["phase9_path_first_write_grammar"])
            if parsed_write.target_path:
                graph.paths.append(core.PathBinding(parsed_write.target_path, core.SemanticPathRole.OUTPUT, "phase9_grammar_proven_write_target"))
            if parsed_write.is_invalid:
                graph.errors.append(parsed_write.invalid_reason or "write precondition failed")
                return graph
            graph.write_payload = parsed_write.content
            return graph

        graph = base_parse(cls, positive, known_extensions)
        graph.original_text = clean
        # Action and formatting are orthogonal.  Never leak action labels into
        # ResponseMode, even when delegated legacy code does so.
        graph.response_mode = mode
        return graph

    core.SemanticParser.parse = classmethod(parse)

    def exact_intent(cls: Any, text: str) -> Any | None:
        paths = list(core.extract_paths(text, da.RequestPreprocessor.KNOWN_EXTENSIONS))
        span = _exact_span(text, paths)
        if span is None:
            return None
        return da.ExactLiteralIntent(
            payload=span.payload,
            payload_span_start=span.start,
            payload_span_end=span.end,
            quote_style=span.quote_style,
            prefix_constraint=span.prefix,
            suffix_constraint=span.suffix,
            confidence=1.0,
        )

    # Phase-8/9 public structured API.  Keep parse() installed by the unified
    # frontend so its DirectActionResult compatibility remains unchanged.
    da.ExactResponseParser.parse_intent = classmethod(exact_intent)

    def execute(cls: Any, text: str, *, context: str = "", control: Any = None, workspace: str = "") -> Any:
        graph = core.SemanticParser.parse(text, da.RequestPreprocessor.KNOWN_EXTENSIONS)
        result = base_execute(cls, text, context=context, control=control, workspace=workspace)
        if result is None or not getattr(result, "success", False):
            return result

        mutation_requires_proof = graph.action in {core.SemanticAction.FILE_WRITE, core.SemanticAction.SCREENSHOT}
        mutation_requires_proof = mutation_requires_proof or (
            graph.action == core.SemanticAction.ARITHMETIC and bool(graph.output_path)
        )
        telemetry = getattr(result, "telemetry", {}) or {}
        if mutation_requires_proof and telemetry.get("verification_passed") is not True:
            result.success = False
            result.output = "Postcondition verification failed: mutation completed without independent success evidence."
            telemetry["verification_passed"] = False
            telemetry["reason"] = "missing_postcondition_evidence"
            result.telemetry = telemetry
        return result

    da.DirectActionRouter.execute = classmethod(execute)
    _INSTALLED = True
