"""Unified semantic language front-end for ARCH.

This is the only active compatibility-aware parser above ``semantic_core``.
It turns natural language into one ``SemanticRequestGraph`` and owns the
parse -> authorize -> execute -> observe -> verify -> render lifecycle.

Important invariants:
- response-only requests never receive mutation authority;
- filesystem outputs must be role-bound by explicit grammar;
- successful mutating requests must have an observable verified postcondition;
- no positional "last path = output" fallback exists;
- browser partial results are structured and never reported as full success.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any

_INSTALLED = False


def _install_attr(obj: object, name: str, value: object) -> None:
    setattr(obj, name, value)


_SCOPE_NOUNS = r"(?:response|answer|reply|output|string|token|value|text|word|payload)"
_EXCLUSIVE = r"(?:only|solely|just|exactly|strictly|verbatim|precisely)"
_COMMAND = r"(?:write\s+back|send\s+back|give\s+back|respond\s+with|reply\s+with|give\s+me|reply|respond|return|say|echo|repeat|print|output|produce|send|type)"
_TRAILING_EXACT = re.compile(
    r"\s*(?:(?:and\s+nothing\s+(?:else|more)|with\s+nothing\s+(?:else|more)|"
    r"and\s+no\s+other\s+text|without\s+(?:any\s+)?(?:explanation|commentary)|"
    r"with\s+no\s+(?:other|extra)\s+(?:text|words|commentary)|"
    r"(?:and\s+)?no\s+(?:explanation|commentary)|alone|"
    r"verbatim|strictly|precisely)|[;,]\s*(?:add\s+nothing|no\s+(?:explanation|commentary))|only)\.?\s*$",
    re.IGNORECASE,
)


def _strip_token(value: str) -> str:
    return value.strip().strip("'\"`").rstrip(".,;!?)]}")


def _mask_literals(text: str) -> str:
    return re.sub(r"(['\"`]).*?\1", " <LITERAL> ", text, flags=re.DOTALL)


def _execution_dependency(text: str, paths: list[str]) -> bool:
    """Return True when the requested response depends on executing another action.

    Exact-literal routing is intentionally conservative: response formatting words
    such as "only" or "exactly" can never turn a lookup, calculation, file read,
    browser extraction, or repository inspection into an echo.  Quoted paths are
    data dependencies, not candidate literal payloads.
    """
    lower = text.lower()
    masked = _mask_literals(text).lower()
    if "://" in text:
        return True

    if paths and (
        any(
            phrase in lower
            for phrase in (
                "from the file",
                "in the file",
                "value in",
                "number in",
                "text in",
                "file contents",
                "contents of",
                "content of",
                "raw file",
                "file text",
                "read ",
                "open ",
                "load ",
                "fetch ",
                "repository",
                "repo",
                "codebase",
            )
        )
        or any(
            marker in lower
            for marker in (
                "verbatim",
                "exact contents",
                "only the contents",
                "raw content",
                "raw contents",
                "without line numbers",
                "just the contents",
                "exact raw",
                "byte-for-byte",
            )
        )
    ):
        return True

    # Explicit filesystem role grammar outranks response verbs such as
    # "print" and "output", even for extensionless relative targets.
    if paths and (
        re.search(
            r"\b(?:write|save|store|put|dump|record|output|create|make)\b[^\n]{0,140}\b(?:to|into|at|in|containing|with\s+(?:content|text|body|payload))\b",
            masked,
            re.IGNORECASE,
        )
        or re.search(
            r"\b(?:read|open|show|display|cat|fetch|load|print)\b[^\n]{0,100}\b(?:content|contents|file|path)\b",
            masked,
            re.IGNORECASE,
        )
    ):
        return True
    if re.search(
        r"^\s*(?:(?:please|kindly|can\s+you)\s+)?(?:list|enumerate|show|display|print|get|give\s+me)\b[^\n]{0,80}\b(?:files|entries|children|items|filenames|inventory|directory|folder|path|location|contents)\b",
        masked,
        re.IGNORECASE,
    ):
        return True

    # Calculations are primary actions even when the request ends in
    # "return/reply only the number".  Mask quoted data first so action-like
    # words inside literal payloads cannot trigger this guard.
    calculation_text = re.sub(r"[;,]\s*add\s+nothing\.?\s*$", "", masked, flags=re.IGNORECASE)
    if re.search(
        r"\b(?:compute|calculate|add|sum|subtract|deduct|multiply|divide|quotient|difference|product|power)\b|"
        r"\btake\b[^\n]{0,80}\baway\s+from\b|\bdivided\s+by\b|\braised\s+to\b",
        calculation_text,
        re.IGNORECASE,
    ):
        return True

    return any(
        phrase in masked
        for phrase in (
            "from memory",
            "stored in memory",
            "remembered value",
            "memory value",
            "what was stored",
            "stored value",
            "deployment marker for",
            "marker for",
            "codename for",
            "api key for",
            "retrieve ",
            "recall ",
            "from the browser",
            "from the page",
            "css selector",
            "calendar",
            "schedule",
        )
    )


def _positive_routing_text(text: str) -> str:
    """Mask explicitly negated mutating clauses while preserving offsets."""
    chars = list(text)
    negated = re.compile(
        r"\b(?:do\s+not|don't|dont|never|must\s+not|should\s+not)\s+"
        r"(?:write|save|create|store|put|dump|record|delete|remove|wipe|destroy|modify|edit)\b",
        re.IGNORECASE,
    )
    positive = r"(?:read|open|show|display|cat|fetch|load|get|retrieve|inspect|examine|list|review|analy[sz]e|diagnose|navigate|return|reply)"
    for match in negated.finditer(text):
        tail = text[match.end() :]
        # A clause boundary is punctuation/conjunction that actually introduces
        # a positive action. Bare dots are common inside paths (v5.4, .txt) and
        # must never terminate the negation mask.
        boundary = re.search(
            rf"(?:[.;]\s+|,\s*|\b(?:and|but|then)\s+)(?={positive}\b)|\n\s*(?={positive}\b)",
            tail,
            re.IGNORECASE,
        )
        end = match.end() + (boundary.start() if boundary else len(tail))
        for i in range(match.start(), end):
            if chars[i] not in "\r\n":
                chars[i] = " "
    return "".join(chars)


def _strip_exact_prefix(value: str) -> str:
    value = value.strip()
    # Declarative response contracts.
    value = re.sub(
        rf"^(?:(?:your|the)\s+)?(?:entire|whole|complete|full)?\s*{_SCOPE_NOUNS}\s+"
        rf"(?:must|should|shall|needs?\s+to)\s+(?:{_EXCLUSIVE}\s+)?(?:be|contain|consist\s+(?:solely\s+)?of)\s+",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    # Imperative contracts. Exclusivity is accepted before or after command.
    value = re.sub(r"^(?:please|kindly)\s+", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(rf"^{_EXCLUSIVE}\s+", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(rf"^{_COMMAND}\b\s*", "", value, flags=re.IGNORECASE).strip()
    # Control words may appear in either order ("reply only with X",
    # "respond with only X"). Normalize the short prefix iteratively rather
    # than assuming one template order.
    for _ in range(3):
        before = value
        value = re.sub(rf"^{_EXCLUSIVE}\b\s*", "", value, flags=re.IGNORECASE).strip()
        value = re.sub(r"^with\b\s*:?[ \t]*", "", value, flags=re.IGNORECASE).strip()
        if value == before:
            break
    value = re.sub(
        rf"^(?:the\s+|this\s+)?(?:entire\s+|whole\s+|complete\s+)?{_SCOPE_NOUNS}\b\s*",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    # Common semantic introducers are control language, not payload. "as" is
    # only an introducer when followed by whitespace/colon; a payload such as
    # "as-is" begins with real data and must be preserved byte-for-byte.
    value = re.sub(
        r"^(?:is(?=\s|:)|as(?=\s|:)|with\s*:|with\s+the\s+(?:value|token)|with\s+this\s+value|"
        r"this\s+value|the\s+token|following\s+token\s*:?)\s*",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    return value


def _parse_exact_literal(text: str, paths: list[str]) -> str | None:
    """Parse deterministic response contracts by payload span, not templates."""
    clean = text.strip()
    if not clean or _execution_dependency(clean, paths):
        return None
    masked = _mask_literals(clean)
    # Once execution dependencies are excluded, a leading response verb is a
    # deterministic response contract.  Keep multiword verbs atomic so
    # "send back" cannot be truncated to "send" and leak "back" into payload.
    signal = bool(re.match(rf"^\s*(?:please\s+|kindly\s+)?(?:{_EXCLUSIVE}\s+)?{_COMMAND}\b", masked, re.IGNORECASE))
    signal = signal or bool(
        re.match(
            rf"^\s*(?:(?:your|the)\s+)?(?:entire|whole|complete|full)?\s*{_SCOPE_NOUNS}\s+"
            rf"(?:must|should|shall)\s+(?:{_EXCLUSIVE}\s+)?(?:be|contain|consist)",
            masked,
            re.IGNORECASE,
        )
    )
    signal = signal or bool(
        re.search(
            rf"\b(?:make|set)\s+(?:the\s+)?{_SCOPE_NOUNS}\s+(?:equal\s+to|equals?|to|be)\b",
            masked,
            re.IGNORECASE,
        )
    )
    signal = signal or bool(re.match(r"^\s*(?:please\s+|kindly\s+)?(?:echo|repeat)\b", clean, re.IGNORECASE))
    signal = signal or bool(
        re.match(
            r"^\s*(?:and\s+nothing\s+(?:more|else)|(?:the\s+)?following\s+(?:string|token|value|word|payload|text|literal))\s*[:\-]",
            clean,
            re.IGNORECASE,
        )
    )
    if not signal:
        return None

    # A quoted literal is an explicit payload span.  Use the last one so a
    # quoted control noun earlier in an instruction cannot steal the payload.
    quoted = list(re.finditer(r"(['\"`])([^'\"`\n]*)\1", clean))
    if quoted:
        return quoted[-1].group(2)

    work = _TRAILING_EXACT.sub("", clean).strip()
    # Single colons delimit control language; double-colons are payload bytes.
    single_colons = list(re.finditer(r"(?<!:):(?!:)", work))
    if single_colons:
        tail = work[single_colons[-1].end() :].strip()
        if tail:
            return _strip_token(tail)
    eq = re.search(r"(?:=|\bequal\s+to\b|\bequals?\b)\s*(.+)$", work, re.IGNORECASE)
    if eq:
        return _strip_token(eq.group(1))

    payload = _strip_exact_prefix(work)
    payload = _TRAILING_EXACT.sub("", payload).strip()
    payload = re.sub(rf"^{_EXCLUSIVE}\s+", "", payload, flags=re.IGNORECASE).strip()
    if not payload or payload.lower() in {"with", "this value", "the token", "value", "token", "text"}:
        return None
    return _strip_token(payload)


def _normalized_paths(base_extract: Any, text: str, extensions: tuple[str, ...]) -> list[str]:
    """Drop shadow relative paths created by re-matching an absolute path."""
    raw = list(base_extract(text, extensions))
    result: list[str] = []
    for candidate in raw:
        if candidate in result:
            continue
        if not candidate.startswith("/"):
            shadowed = False
            for absolute in raw:
                if not absolute.startswith("/") or not absolute.endswith("/" + candidate):
                    continue
                occurrences = [m.start() for m in re.finditer(re.escape(candidate), text)]
                if occurrences and all(pos > 0 and text[pos - 1] == "/" for pos in occurrences):
                    shadowed = True
                    break
            if shadowed:
                continue
        result.append(candidate)
    return result


def _explicit_output(text: str, paths: list[str]) -> str:
    """Bind output only from an explicit mutation/destination clause."""
    lower = text.lower()
    for path in paths:
        escaped = re.escape(path.lower())
        patterns = (
            rf"\b(?:save|write|store|export|dump|record|output)\b[^\n;]{{0,90}}\b(?:to|into|in|at)\s+['\"`]?{escaped}",
            rf"\b(?:destination|output|target)\s+(?:file\s+)?(?:is|to|in|at)?\s*['\"`]?{escaped}",
            rf"\b(?:create|make)\s+(?:an?\s+)?(?:empty\s+)?(?:(?:json|csv|tsv|text)\s+)?(?:file\s+)?(?:at\s+)?['\"`]?{escaped}",
            rf"\bthe\s+file\s+['\"`]?{escaped}\b[^\n]{{0,50}}\b(?:contain|hold|have)\b",
            # Transform destinations must be introduced as a destination, not
            # merely appear after "in" (which commonly introduces the source).
            rf"\bto\s+(?:an?\s+)?json(?:\s+(?:array|object|file))?\s+(?:to|into|in|at)\s+['\"`]?{escaped}",
            rf"\bconvert\b[^\n;]{{0,140}}\b(?:to|into)\s+['\"`]?{escaped}",
        )
        if any(re.search(pattern, lower, re.IGNORECASE) for pattern in patterns):
            return path
    return ""


def _directory_target(text: str, paths: list[str]) -> str:
    lower = text.lower()
    strong = bool(
        re.search(
            r"\b(?:list|show|display|enumerate|get|print|give\s+me|what\s+is|what\s+files\s+are)\b"
            r"[^\n]{0,60}\b(?:files|entries|children|direct\s+children|items|filenames|inventory|directory|folder|path|location|contents)\b",
            lower,
        )
        or re.search(
            r"\b(?:inventory\s+of|what\s+is\s+inside|what\s+files\s+are\s+(?:in|under)|what\s+files\s+exist|what\s+entries\s+are|files\s+exist\s+(?:under|in)|give\s+filenames\s+from|print\s+location)\b",
            lower,
        )
    )
    if not strong:
        return ""
    if paths:
        return paths[0]
    patterns = (
        r"\b(?:files|entries|children|direct\s+children|items|filenames|inventory|contents)\s+(?:of|under|in|inside)\s+['\"`]?([~/A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)",
        r"\b(?:directory|folder|location|path)\s+['\"`]?([~/A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)",
        r"\bwhat\s+is\s+inside\s+['\"`]?([~/A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)",
        r"\bwhat\s+files\s+are\s+in\s+['\"`]?([~/A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = _strip_token(match.group(1))
            if value.lower() not in {"the", "a", "an", "this", "that", "box"}:
                return value
    return ""


def _file_read_target(text: str, paths: list[str]) -> str:
    if paths:
        return paths[0]
    patterns = (
        r"\b(?:contents?|content|text)\s+(?:of|from|inside)\s+[\x27\x22`]?([~/A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)",
        r"\b(?:stored|written)\s+in\s+[\x27\x22`]?([~/A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)",
        r"\bwhat\s+does\s+[\x27\x22`]?([~/A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)[\x27\x22`]?\s+contain\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _strip_token(match.group(1))
    return ""


def _browser_plan(core: Any, text: str) -> Any | None:
    url_match = re.search(r"([A-Za-z][A-Za-z0-9+.-]*://[^\s'\"),]+)", text)
    if not url_match:
        return None
    url = url_match.group(1).rstrip(".,;!")
    lower = text.lower()
    selectors: list[str] = []
    for match in re.finditer(r"(?:css\s+selector|selector|element)\s+['\"`]([^'\"`]+)['\"`]", text, re.IGNORECASE):
        selector = match.group(1)
        if selector not in selectors:
            selectors.append(selector)
    list_match = re.search(r"\bcss\s+selectors?\s*:\s*(.+)$", text, re.IGNORECASE | re.DOTALL)
    if list_match:
        for selector in re.findall(r"['\"`]([^'\"`]+)['\"`]", list_match.group(1)):
            if selector not in selectors:
                selectors.append(selector)
    scrubbed = text.replace(url, " ")
    if re.search(r"\b(?:extract|get|read|return|show|report)\b", lower):
        for match in re.finditer(r"(?<![A-Za-z0-9_/])([#.][A-Za-z_][A-Za-z0-9_-]*)", scrubbed):
            selector = match.group(1)
            if selector not in selectors:
                selectors.append(selector)
    return core.BrowserPlan(
        url=url,
        selectors=selectors,
        want_title="title" in lower,
        want_text=(
            any(term in lower for term in ("body text", "page text", "page content"))
            or bool(re.search(r"\b(?:extract|get|read|return|show|report)\b[^\n]{0,50}\bcontent\b", lower))
        )
        and not selectors,
        want_links=bool(re.search(r"\b(?:links|hrefs?)\b", lower)),
    )


def _arithmetic_graph(core: Any, text: str, paths: list[str], mode: str) -> Any | None:
    lower = text.lower()
    operation = ""
    if re.search(r"\b(?:subtract|minus|difference|deduct)\b|away\s+from", lower):
        operation = "subtract"
    elif re.search(r"\b(?:divide|quotient|divided\s+by)\b", lower):
        operation = "divide"
    elif re.search(r"\b(?:multiply|product|times)\b", lower):
        operation = "multiply"
    elif re.search(r"\b(?:add|sum|total)\b", lower):
        operation = "add"
    if not operation:
        return None
    output = _explicit_output(text, paths)
    inputs = [path for path in paths if path != output]
    if len(inputs) != 2:
        return None
    left, right = inputs[0], inputs[1]
    left_role, right_role = "left", "right"
    provenance = "explicit_operands"
    if operation == "subtract" and re.search(
        r"\b(?:subtract|take|deduct)\b.+?\b(?:from|away\s+from)\b", lower, re.DOTALL
    ):
        left, right = right, left
        left_role, right_role = "minuend", "subtrahend"
        provenance = "subtract_from"
    elif operation == "divide" and re.search(r"\bdivide\b.+?\binto\b", lower, re.DOTALL):
        left, right = right, left
        left_role, right_role = "numerator", "denominator"
        provenance = "divide_into"
    elif operation == "divide":
        left_role, right_role = "numerator", "denominator"
        provenance = "divide_by"
    plan = core.ArithmeticPlan(operation, left, right, left_role, right_role, output, provenance)
    bindings = [
        core.PathBinding(left, core.SemanticPathRole.INPUT, left_role),
        core.PathBinding(right, core.SemanticPathRole.SECONDARY_INPUT, right_role),
    ]
    if output:
        bindings.append(core.PathBinding(output, core.SemanticPathRole.OUTPUT, "explicit_result_destination"))
    return core.SemanticRequestGraph(
        text, core.SemanticAction.ARITHMETIC, mode, bindings, arithmetic=plan, evidence=[provenance]
    )


def _table_transform(text: str, paths: list[str]) -> dict[str, Any] | None:
    lower = text.lower()
    if re.search(r"\b(?:key[- /]?value|kv|config|env)\b", lower):
        return None
    if not ("json" in lower and re.search(r"\b(?:table|csv|tsv|semicolon|delimited|transform|convert)\b", lower)):
        return None
    output = _explicit_output(text, paths)
    if not output:
        # "convert to JSON at X" is semantically an explicit destination even
        # though the mutation verb appears before the format noun.
        for path in paths:
            escaped = re.escape(path)
            if re.search(
                rf"\bconvert\s+to\s+json\s+(?:at|to|into|in)\s+['\"`]?{escaped}", text, re.IGNORECASE
            ) or re.search(rf"\bconvert\b[^\n;]{{0,80}}\bto\s+['\"`]?{escaped}", text, re.IGNORECASE):
                output = path
                break
    inputs = [path for path in paths if path != output]
    if not output or len(inputs) != 1:
        return None
    return {"kind": "table_json", "input": inputs[0], "output": output}


def _legacy_transform(text: str, paths: list[str], da: Any) -> dict[str, Any] | None:
    output = _explicit_output(text, paths)
    inputs = [path for path in paths if path != output]
    if not output or not inputs:
        return None
    lower = text.lower()
    if re.search(r"\b(?:add|sum|total|subtract|minus|difference|deduct|multiply|product|divide|quotient)\b", lower):
        return None
    if not da.DirectActionRouter._is_workflow_request(text):
        return None
    return {"kind": "legacy_verified", "inputs": inputs, "output": output}


def _infer_scalar(value: str) -> Any:
    token = value.strip()
    lower = token.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower in {"null", "none"}:
        return None
    if re.fullmatch(r"[-+]?\d+", token):
        try:
            return int(token)
        except ValueError:
            pass
    if re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+)", token):
        try:
            return float(token)
        except ValueError:
            pass
    return token


def _parse_table(raw: str, source: Path, prompt: str) -> list[dict[str, Any]]:
    lines = [line for line in raw.splitlines() if line.strip()]
    if not lines:
        return []
    lower = prompt.lower()
    if "semicolon" in lower:
        delimiter = ";"
    elif source.suffix.lower() == ".tsv" or "tsv" in lower:
        delimiter = "\t"
    elif "|" in lines[0]:
        delimiter = "|"
    else:
        delimiter = ","
    reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    rows = [[cell.strip() for cell in row] for row in reader]
    if delimiter == "|":
        rows = [[cell for cell in row if cell != ""] for row in rows]
    if not rows:
        return []
    header = rows[0]
    data_rows = rows[1:]
    if data_rows and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in data_rows[0]):
        data_rows = data_rows[1:]
    result: list[dict[str, Any]] = []
    for row in data_rows:
        if not row:
            continue
        padded = row + [""] * max(0, len(header) - len(row))
        result.append({key: _infer_scalar(value) for key, value in zip(header, padded, strict=False)})
    return result


def _is_raw_read(text: str) -> bool:
    lower = text.lower()
    return any(
        phrase in lower
        for phrase in (
            "verbatim",
            "exact contents",
            "only the contents",
            "raw content",
            "raw contents",
            "without explanation",
            "without line numbers",
            "just the contents",
            "exact raw",
            "byte-for-byte",
        )
    )


def install_semantic_frontend() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from jarvis.amaura import direct_action as da
    from jarvis.amaura import semantic_core as core

    base_extract = core.extract_paths

    def unified_extract(text: str, known_extensions: tuple[str, ...]) -> list[str]:
        return _normalized_paths(base_extract, text, known_extensions)

    # Make every legacy helper that consults semantic_core.extract_paths observe
    # the same normalized entities.  This is normalization, not another parser.
    core.extract_paths = unified_extract

    def parse(cls: Any, text: str, known_extensions: tuple[str, ...]) -> Any:
        clean = text.strip()
        mode = core._response_mode(clean)
        if not clean:
            return core.SemanticRequestGraph(clean, core.SemanticAction.UNKNOWN, response_mode=mode)
        routing = _positive_routing_text(clean)
        paths = unified_extract(routing, known_extensions)

        literal = _parse_exact_literal(clean, paths)
        if literal is not None:
            return core.SemanticRequestGraph(
                clean,
                core.SemanticAction.EXACT_LITERAL,
                response_mode=mode,
                literal_payload=literal,
                evidence=["formal_exact_response_contract"],
            )

        lower = routing.lower()
        masked = _mask_literals(routing).lower()
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
            return core.SemanticRequestGraph(
                clean, core.SemanticAction.POLICY_REFUSAL, mode, evidence=["destructive_bypass_request"]
            )

        if re.search(r"https?://169\.254\.169\.254(?:/|$)", routing, re.IGNORECASE):
            return core.SemanticRequestGraph(
                clean, core.SemanticAction.POLICY_REFUSAL, mode, evidence=["cloud_metadata_endpoint_blocked"]
            )

        browser = _browser_plan(core, routing)
        if browser is not None:
            return core.SemanticRequestGraph(
                clean, core.SemanticAction.BROWSER, mode, browser=browser, evidence=["url_browser_contract"]
            )

        arithmetic = _arithmetic_graph(core, routing, paths, mode)
        if arithmetic is not None:
            arithmetic.original_text = clean
            return arithmetic

        table = _table_transform(routing, paths)
        if table is not None:
            graph = core.SemanticRequestGraph(
                clean,
                core.SemanticAction.FILE_WRITE,
                mode,
                [
                    core.PathBinding(table["input"], core.SemanticPathRole.INPUT, "table_source"),
                    core.PathBinding(table["output"], core.SemanticPathRole.OUTPUT, "explicit_transform_destination"),
                ],
                evidence=["typed_table_json_transform"],
            )
            graph.transform_plan = table
            return graph

        legacy = _legacy_transform(routing, paths, da)
        if legacy is not None:
            graph = core.SemanticRequestGraph(
                clean,
                core.SemanticAction.FILE_WRITE,
                mode,
                [
                    *[
                        core.PathBinding(path, core.SemanticPathRole.INPUT, "workflow_source")
                        for path in legacy["inputs"]
                    ],
                    core.PathBinding(legacy["output"], core.SemanticPathRole.OUTPUT, "explicit_transform_destination"),
                ],
                evidence=["verified_legacy_transform"],
            )
            graph.transform_plan = legacy
            return graph

        repo_noun = bool(re.search(r"\b(?:repo|repository|codebase|project(?:\s+repository)?|code)\b", lower))
        inspect = bool(
            re.search(
                r"\b(?:check|examine|review|inspect|diagnose|audit|analy[sz]e|trace|investigate|find\s+(?:the\s+)?bug|locate\s+(?:the\s+)?bug)\b",
                masked,
            )
        )
        mutating = bool(re.search(r"\b(?:write|edit|modify|delete|remove|create|save|store)\b", masked))
        if inspect and paths and not mutating and (repo_noun or "read-only" in lower or "read only" in lower):
            return core.SemanticRequestGraph(
                clean,
                core.SemanticAction.REPOSITORY,
                mode,
                [core.PathBinding(paths[0], core.SemanticPathRole.REPOSITORY, "repository_inspection_target")],
                evidence=["inspection_verb_plus_repository_entity"],
            )

        # Fail closed when the same write clause supplies multiple competing
        # explicit payloads.  Do this before subordinate extraction so a parser
        # fallback cannot silently choose one candidate and mutate the target.
        if re.search(r"\b(?:create|write|save|store|put|dump|record)\b", masked):
            quoted_payloads = []
            for match in re.finditer(r"(['\"`])([^'\"`\n]*)\1", clean):
                candidate = match.group(2)
                if candidate in paths:
                    continue
                if candidate not in quoted_payloads:
                    quoted_payloads.append(candidate)
            if len(quoted_payloads) > 1 and re.search(
                r"\b(?:contain(?:ing|s)?|content\s*:|payload\s*:|text\s*:|body\s*:)\b",
                clean,
                re.IGNORECASE,
            ):
                graph = core.SemanticRequestGraph(
                    clean,
                    core.SemanticAction.FILE_WRITE,
                    mode,
                    evidence=["ambiguous_write_payload_preflight"],
                )
                output = _explicit_output(clean, paths) or (paths[0] if len(paths) == 1 else "")
                if output:
                    graph.paths.append(
                        core.PathBinding(output, core.SemanticPathRole.OUTPUT, "grammar_proven_write_target")
                    )
                graph.errors.append("ambiguous write payload: multiple competing explicit payloads")
                return graph

        # Reuse the mature clause/reference parser as a subordinate role parser;
        # it no longer competes with other top-level actions.
        write_action = da.WriteActionParser.parse(routing)
        if write_action is not None:
            graph = core.SemanticRequestGraph(
                clean, core.SemanticAction.FILE_WRITE, mode, evidence=["write_clause_role_parser"]
            )
            target = str(write_action.target_path or "")
            if target:
                graph.paths.append(
                    core.PathBinding(target, core.SemanticPathRole.OUTPUT, "grammar_proven_write_target")
                )
            if write_action.is_invalid:
                graph.errors.append(write_action.invalid_reason or "write precondition failed")
                return graph
            if not target:
                graph.errors.append("write request has no unambiguous explicit output path")
                return graph
            if not write_action.has_explicit_content and not write_action.is_empty_requested:
                graph.errors.append("write request has no explicit payload")
                return graph
            graph.write_payload = write_action.content
            return graph

        # Screenshot routing comes after the write role parser. A strong write
        # grammar owns its payload span, so words such as "save screenshot"
        # inside unquoted file content cannot escape and become tool intent.
        if re.search(r"\b(?:capture|take|save)\b.*\b(?:screenshot|screen\s*shot)\b|\bscreenshot\b", masked):
            output = next((path for path in paths if path.lower().endswith(".png")), "screenshot.png")
            return core.SemanticRequestGraph(
                clean,
                core.SemanticAction.SCREENSHOT,
                mode,
                [
                    core.PathBinding(
                        output, core.SemanticPathRole.OUTPUT, "screenshot_destination", explicit=bool(paths)
                    )
                ],
                evidence=["screenshot_command"],
            )

        directory = _directory_target(routing, paths)
        if directory:
            return core.SemanticRequestGraph(
                clean,
                core.SemanticAction.DIRECTORY_LIST,
                mode,
                [core.PathBinding(directory, core.SemanticPathRole.TARGET, "grammar_proven_filesystem_target")],
                evidence=["directory_entity_role"],
            )

        read_target = _file_read_target(routing, paths)
        if read_target and re.search(
            r"\b(?:read|open|show|display|cat|fetch|view|print|load|get|retrieve|examine|inspect)\b|"
            r"\b(?:contents?|content|text)\s+(?:of|from|inside)\b|\bwhat\s+does\b[^\n]{0,120}\bcontain\b|\bwhat\s+is\s+inside\b",
            lower,
        ):
            return core.SemanticRequestGraph(
                clean,
                core.SemanticAction.FILE_READ,
                mode,
                [core.PathBinding(read_target, core.SemanticPathRole.INPUT, "file_read_target")],
                evidence=["file_read_grammar"],
            )

        if any(
            term in lower
            for term in (
                "from memory",
                "remembered",
                "recall",
                "stored in memory",
                "memory value",
                "remember for",
                "remember about",
                "deployment marker",
                "release marker",
                "codename for",
                "api key for",
                "stored value",
                "saved value",
            )
        ):
            return core.SemanticRequestGraph(
                clean, core.SemanticAction.MEMORY_RECALL, mode, evidence=["memory_recall_grammar"]
            )
        if any(
            term in lower
            for term in ("schedule", "calendar", "book an appointment", "add to calendar", "book a meeting")
        ):
            return core.SemanticRequestGraph(clean, core.SemanticAction.CALENDAR, mode, evidence=["calendar_grammar"])
        return core.SemanticRequestGraph(clean, core.SemanticAction.UNKNOWN, response_mode=mode)

    _install_attr(core.SemanticParser, "parse", classmethod(parse))

    def _result_failure(message: str, *, tool: str, provider: str, reason: str, policy: str = "allowed") -> Any:
        return da.DirectActionResult(
            False,
            message,
            execution_type="policy_enforcement" if policy == "refused" else "semantic_graph",
            tool_name=tool,
            provider=provider,
            policy_decision=policy,
            telemetry={"reason": reason, "verification_passed": False},
        )

    def _resolve(path_text: str, workspace: str, *, must_exist: bool) -> tuple[Path, Path]:
        ws = Path(workspace if workspace else da.workspace_root()).expanduser().resolve()
        with da.tool_workspace(ws):
            path = da.resolve_workspace_path(path_text, must_exist=must_exist)
        return ws, path

    def _write_exact(graph: Any, workspace: str) -> Any:
        payload = graph.write_payload if graph.write_payload is not None else ""
        try:
            ws, path = _resolve(graph.output_path, workspace, must_exist=False)
            with da.tool_workspace(ws):
                tool_res = da.parse_tool_result(da.execute_tool("write_file", {"path": str(path), "content": payload}))
            if not tool_res.ok:
                return _result_failure(
                    f"File write failed: {tool_res.error or 'write tool failed'}",
                    tool="write_file",
                    provider="local-filesystem",
                    reason="tool_failed",
                )
            if not path.exists():
                return da.DirectActionResult(
                    False,
                    "File write verification failed: output missing after write.",
                    execution_type="tool",
                    tool_name="write_file",
                    provider="local-filesystem",
                    telemetry={"reason": "missing_after_write", "verification_passed": False},
                )
            observed = path.read_text(encoding="utf-8", errors="replace")
            expected_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            actual_hash = hashlib.sha256(observed.encode("utf-8")).hexdigest()
            if observed != payload:
                return da.DirectActionResult(
                    False,
                    "File write verification failed: content mismatch; persisted bytes do not match the requested payload.",
                    execution_type="tool",
                    tool_name="write_file",
                    provider="local-filesystem",
                    telemetry={
                        "reason": "content_mismatch",
                        "expected_size": len(payload),
                        "actual_size": len(observed),
                        "expected_sha256": expected_hash,
                        "actual_sha256": actual_hash,
                        "content_match": False,
                        "verification_passed": False,
                    },
                )
            return da.DirectActionResult(
                True,
                f"Successfully wrote and independently verified {path}.",
                execution_type="tool",
                tool_name="write_file",
                provider="local-filesystem",
                telemetry={
                    "path": str(path),
                    "output_path": str(path),
                    "payload": payload,
                    "expected_size": len(payload),
                    "actual_size": len(observed),
                    "expected_sha256": expected_hash,
                    "actual_sha256": actual_hash,
                    "content_match": True,
                    "verification_passed": True,
                    "semantic_action": graph.action.value,
                    "status": "completed",
                },
            )
        except PermissionError as exc:
            return _result_failure(
                f"Cannot write to path outside workspace: {exc}",
                tool="effect_authorizer",
                provider="security-policy",
                reason="workspace_escape",
                policy="refused",
            )
        except Exception as exc:
            text = str(exc)
            if "workspace" in text.lower() or "outside" in text.lower() or "sensitive" in text.lower():
                return _result_failure(
                    f"Cannot write to path outside workspace: {text}",
                    tool="effect_authorizer",
                    provider="security-policy",
                    reason="workspace_escape",
                    policy="refused",
                )
            return _result_failure(
                f"File write failed: {text}", tool="write_file", provider="local-filesystem", reason="write_failed"
            )

    def _read_file(graph: Any, workspace: str) -> Any:
        try:
            _, path = _resolve(graph.paths[0].path, workspace, must_exist=True)
            if not path.is_file():
                return _result_failure(
                    f"File not found or not a regular file: {path}",
                    tool="read_file",
                    provider="local-filesystem",
                    reason="not_found",
                )
            with da.tool_workspace(Path(workspace if workspace else da.workspace_root()).expanduser().resolve()):
                receipt = da.parse_tool_result(da.execute_tool("read_file", {"path": str(path)}))
            if not receipt.ok:
                return _result_failure(
                    f"File read failed: {receipt.error or 'read tool failed'}",
                    tool="read_file",
                    provider="local-filesystem",
                    reason="tool_failed",
                )
            raw = path.read_text(encoding="utf-8", errors="replace")
            return da.DirectActionResult(
                True,
                raw,
                execution_type="tool",
                tool_name="read_file",
                provider="local-filesystem",
                telemetry={
                    "path": str(path),
                    "value": raw,
                    "read_mode": "raw" if _is_raw_read(graph.original_text) else "display",
                    "verification_passed": True,
                    "semantic_action": graph.action.value,
                    "status": "completed",
                },
            )
        except FileNotFoundError as exc:
            return _result_failure(
                f"File not found: {exc}", tool="read_file", provider="local-filesystem", reason="not_found"
            )
        except PermissionError as exc:
            return _result_failure(
                f"File read refused by workspace policy: {exc}",
                tool="read_file",
                provider="security-policy",
                reason="workspace_escape",
                policy="refused",
            )

    def _filesystem_contents(graph: Any, workspace: str) -> Any:
        try:
            _, path = _resolve(graph.paths[0].path, workspace, must_exist=True)
            if path.is_file():
                raw = path.read_text(encoding="utf-8", errors="replace")
                return da.DirectActionResult(
                    True,
                    raw,
                    execution_type="tool",
                    tool_name="read_file",
                    provider="local-filesystem",
                    telemetry={
                        "path": str(path),
                        "value": raw,
                        "read_mode": "display",
                        "verification_passed": True,
                        "semantic_action": "file_read",
                        "status": "completed",
                    },
                )
            if not path.is_dir():
                return _result_failure(
                    f"Directory not found: {path}",
                    tool="list_directory",
                    provider="local-filesystem",
                    reason="directory_not_found",
                )
            with da.tool_workspace(Path(workspace if workspace else da.workspace_root()).expanduser().resolve()):
                receipt = da.parse_tool_result(da.execute_tool("list_directory", {"path": str(path)}))
            if not receipt.ok:
                return _result_failure(
                    f"Directory listing failed: {receipt.error or 'list tool failed'}",
                    tool="list_directory",
                    provider="local-filesystem",
                    reason="tool_failed",
                )
            entries = sorted(child.name for child in path.iterdir())
            return da.DirectActionResult(
                True,
                "\n".join(entries),
                execution_type="tool",
                tool_name="list_directory",
                provider="local-filesystem",
                telemetry={
                    "path": str(path),
                    "value": entries,
                    "verification_passed": True,
                    "semantic_action": graph.action.value,
                    "status": "completed",
                },
            )
        except FileNotFoundError as exc:
            return _result_failure(
                f"Directory not found: {exc}",
                tool="list_directory",
                provider="local-filesystem",
                reason="directory_not_found",
            )
        except PermissionError as exc:
            return _result_failure(
                f"Directory access refused by workspace policy: {exc}",
                tool="list_directory",
                provider="security-policy",
                reason="workspace_escape",
                policy="refused",
            )

    def _numbers(raw: str) -> list[float]:
        return [float(token) for token in re.findall(r"[-+]?\d+(?:\.\d+)?", raw)]

    def _number_text(value: float) -> str:
        return str(int(value)) if value.is_integer() else str(value)

    def _compute(plan: Any, left_values: list[float], right_values: list[float], aggregate: bool) -> float:
        if not left_values or not right_values:
            raise ValueError("arithmetic inputs contain no numeric values")
        if plan.operation == "add":
            return sum(left_values) + sum(right_values) if aggregate else left_values[0] + right_values[0]
        left, right = left_values[0], right_values[0]
        if plan.operation == "subtract":
            return left - right
        if plan.operation == "multiply":
            return left * right
        if plan.operation == "divide":
            if right == 0:
                raise ZeroDivisionError("division by zero")
            return left / right
        raise ValueError(f"unsupported arithmetic operation: {plan.operation}")

    def _execute_arithmetic(graph: Any, workspace: str) -> Any:
        plan = graph.arithmetic
        assert plan is not None
        try:
            ws, left_path = _resolve(plan.left_path, workspace, must_exist=True)
            _, right_path = _resolve(plan.right_path, workspace, must_exist=True)
            aggregate = plan.operation == "add" and bool(
                re.search(r"\bsum\s+(?:all\s+)?(?:the\s+)?numbers\b", graph.original_text, re.IGNORECASE)
            )
            left_values = _numbers(left_path.read_text(encoding="utf-8", errors="replace"))
            right_values = _numbers(right_path.read_text(encoding="utf-8", errors="replace"))
            result = _compute(plan, left_values, right_values, aggregate)
            payload = _number_text(result)
            output_path = ""
            expected_hash = ""
            actual_hash = ""
            if plan.output_path:
                with da.tool_workspace(ws):
                    output = da.resolve_workspace_path(plan.output_path, must_exist=False)
                    write_res = da.parse_tool_result(
                        da.execute_tool("write_file", {"path": str(output), "content": payload})
                    )
                if not write_res.ok:
                    return _result_failure(
                        f"Arithmetic workflow write failed: {write_res.error or 'write tool failed'}",
                        tool="multi_step_workflow",
                        provider="local-filesystem",
                        reason="tool_failed",
                    )
                # Fresh source observation and recomputation is independent of the
                # first calculation and of the write-tool receipt.
                fresh_left = _numbers(left_path.read_text(encoding="utf-8", errors="replace"))
                fresh_right = _numbers(right_path.read_text(encoding="utf-8", errors="replace"))
                expected = _number_text(_compute(plan, fresh_left, fresh_right, aggregate))
                observed = output.read_text(encoding="utf-8", errors="replace")
                expected_hash = hashlib.sha256(expected.encode()).hexdigest()
                actual_hash = hashlib.sha256(observed.encode()).hexdigest()
                if observed.strip() != expected:
                    return _result_failure(
                        "Arithmetic postcondition failed: persisted result differs from fresh semantic recomputation.",
                        tool="multi_step_workflow",
                        provider="local-filesystem",
                        reason="content_mismatch",
                    )
                output_path = str(output)
            normalized: int | float = int(result) if result.is_integer() else result
            return da.DirectActionResult(
                True,
                payload
                if not output_path
                else f"Computed and independently verified {plan.operation} result {payload} at {output_path}.",
                execution_type="workflow" if output_path else "semantic_graph",
                tool_name="multi_step_workflow" if output_path else "semantic_arithmetic",
                provider="local-filesystem",
                telemetry={
                    "computed_result": normalized,
                    "verification_passed": True,
                    "verification_contract": {
                        "operation": plan.operation,
                        "left_role": plan.left_role,
                        "right_role": plan.right_role,
                        "left_path": plan.left_path,
                        "right_path": plan.right_path,
                        "output_path": plan.output_path,
                        "provenance": plan.provenance,
                    },
                    "input_paths": [str(left_path), str(right_path)],
                    "output_path": output_path,
                    "operation": plan.operation,
                    "expected_output_hash": expected_hash,
                    "actual_output_hash": actual_hash,
                    "side_effects": "write_explicit_output" if output_path else "none",
                    "semantic_action": graph.action.value,
                    "status": "completed",
                },
            )
        except PermissionError as exc:
            return _result_failure(
                f"Arithmetic workflow refused by workspace policy: {exc}",
                tool="effect_authorizer",
                provider="security-policy",
                reason="workspace_escape",
                policy="refused",
            )
        except FileNotFoundError as exc:
            return _result_failure(
                f"Arithmetic workflow input not found: {exc}",
                tool="multi_step_workflow",
                provider="local-filesystem",
                reason="input_file_not_found",
            )
        except Exception as exc:
            return _result_failure(
                f"Arithmetic workflow failed: {exc}",
                tool="multi_step_workflow",
                provider="local-filesystem",
                reason="arithmetic_failed",
            )

    def _execute_table_transform(graph: Any, plan: dict[str, Any], workspace: str) -> Any:
        try:
            ws, source = _resolve(plan["input"], workspace, must_exist=True)
            with da.tool_workspace(ws):
                output = da.resolve_workspace_path(plan["output"], must_exist=False)
            if not source.is_file():
                return _result_failure(
                    f"Transform input not found: {source}",
                    tool="multi_step_workflow",
                    provider="local-filesystem",
                    reason="input_file_not_found",
                )
            expected = _parse_table(source.read_text(encoding="utf-8", errors="replace"), source, graph.original_text)
            payload = json.dumps(expected, ensure_ascii=False, indent=2)
            with da.tool_workspace(ws):
                write_res = da.parse_tool_result(
                    da.execute_tool("write_file", {"path": str(output), "content": payload})
                )
            if not write_res.ok:
                return _result_failure(
                    f"Table transform write failed: {write_res.error or 'write tool failed'}",
                    tool="multi_step_workflow",
                    provider="local-filesystem",
                    reason="tool_failed",
                )
            if not output.exists():
                return _result_failure(
                    "Table transform verification failed: output artifact was not created.",
                    tool="multi_step_workflow",
                    provider="local-filesystem",
                    reason="missing_output_artifact",
                )
            observed = json.loads(output.read_text(encoding="utf-8", errors="replace"))
            if observed != expected:
                return _result_failure(
                    "Table transform verification failed: persisted JSON differs from independently parsed source data.",
                    tool="multi_step_workflow",
                    provider="local-filesystem",
                    reason="content_mismatch",
                )
            return da.DirectActionResult(
                True,
                f"Transformed table to JSON and independently verified {output}.",
                execution_type="workflow",
                tool_name="multi_step_workflow",
                provider="local-filesystem",
                telemetry={
                    "input_path": str(source),
                    "output_path": str(output),
                    "verification_passed": True,
                    "expected_output_hash": hashlib.sha256(payload.encode()).hexdigest(),
                    "actual_output_hash": hashlib.sha256(output.read_bytes()).hexdigest(),
                    "semantic_verifier": "fresh_table_parse_equals_persisted_json",
                    "status": "completed",
                },
            )
        except PermissionError as exc:
            return _result_failure(
                f"Table transform refused by workspace policy: {exc}",
                tool="effect_authorizer",
                provider="security-policy",
                reason="workspace_escape",
                policy="refused",
            )
        except FileNotFoundError as exc:
            return _result_failure(
                f"Transform input not found: {exc}",
                tool="multi_step_workflow",
                provider="local-filesystem",
                reason="input_file_not_found",
            )
        except Exception as exc:
            return _result_failure(
                f"Table transform failed: {exc}",
                tool="multi_step_workflow",
                provider="local-filesystem",
                reason="transform_failed",
            )

    def _execute_legacy_transform(graph: Any, plan: dict[str, Any], workspace: str) -> Any:
        output_text = plan["output"]
        result = da.DirectActionRouter._try_multi_step_workflow(graph.original_text, workspace=workspace)
        if result is None:
            return _result_failure(
                "Workflow failed: no executable transform matched the typed request.",
                tool="multi_step_workflow",
                provider="local-filesystem",
                reason="no_transform",
            )
        if not result.success:
            return result
        try:
            _, output = _resolve(output_text, workspace, must_exist=True)
        except Exception as exc:
            return _result_failure(
                f"Workflow verification failed: expected output artifact was not created: {exc}",
                tool="multi_step_workflow",
                provider="local-filesystem",
                reason="missing_output_artifact",
            )
        if not output.is_file():
            return _result_failure(
                "Workflow verification failed: expected output artifact is not a regular file.",
                tool="multi_step_workflow",
                provider="local-filesystem",
                reason="missing_output_artifact",
            )
        raw = output.read_text(encoding="utf-8", errors="replace")
        if "json" in graph.original_text.lower():
            try:
                json.loads(raw)
            except Exception as exc:
                return _result_failure(
                    f"Workflow verification failed: output is not valid JSON: {exc}",
                    tool="multi_step_workflow",
                    provider="local-filesystem",
                    reason="invalid_output",
                )
        result.execution_type = "workflow"
        result.tool_name = "multi_step_workflow"
        result.provider = "local-filesystem"
        result.telemetry = dict(result.telemetry or {})
        result.telemetry.update(
            {
                "output_path": str(output),
                "verification_passed": True,
                "actual_output_hash": hashlib.sha256(raw.encode()).hexdigest(),
                "semantic_verifier": "artifact_observed_after_execution",
                "status": "completed",
            }
        )
        return result

    def _browser_scalar(value: Any) -> Any:
        """Normalize browser tool presentation wrappers into semantic values."""
        if isinstance(value, dict):
            for key in ("content", "text", "title", "value", "output"):
                if key in value and len(value) == 1:
                    return _browser_scalar(value[key])
            return {key: _browser_scalar(item) for key, item in value.items()}
        if not isinstance(value, str):
            return value
        text = value.strip()
        # browser_extract_content may return a human presentation wrapper. The
        # semantic layer stores the extracted value, not that UI prose.
        match = re.match(
            r"^\s*🌐?\s*\*\*Extracted\s+\d+\s+element\(s\)\s+matching\s+.+?:\*\*\s*(?:\r?\n)+(.+)$",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        return match.group(1).strip() if match else text

    def _execute_browser(graph: Any) -> Any:
        plan = graph.browser
        assert plan is not None
        successful: dict[str, Any] = {}
        failed: list[dict[str, str]] = []

        def _field(primary_tool: str, selector: str | None, field: str) -> None:
            primary = da.parse_tool_result(da.execute_tool(primary_tool, {"url": plan.url}))
            if primary.ok:
                successful[field] = _browser_scalar(core._tool_output(primary))
                return
            fallback = (
                da.parse_tool_result(
                    da.execute_tool("browser_extract_content", {"url": plan.url, "selector": selector})
                )
                if selector
                else None
            )
            if fallback is not None and fallback.ok:
                value = core._tool_output(fallback)
                if isinstance(value, dict):
                    value = value.get("content", value.get("text", value))
                if not (isinstance(value, str) and "no elements matched" in value.lower()):
                    successful[field] = _browser_scalar(value)
                    return
            error = (fallback.error if fallback is not None else None) or primary.error or "extraction failed"
            failed.append({"field": field, "selector": selector or "", "error": error})

        nav = da.parse_tool_result(da.execute_tool("browser_navigate", {"url": plan.url}))
        if not nav.ok:
            return da.DirectActionResult(
                False,
                f"Browser execution failed: {nav.error or 'navigation failed'}",
                execution_type="semantic_graph",
                tool_name="browser_extract_content",
                provider="browser",
                telemetry={
                    "status": "total_failure",
                    "successful_fields": {},
                    "failed_fields": [{"field": "navigation", "error": nav.error or "navigation failed"}],
                    "verification_passed": False,
                    "reason": "browser_failed",
                },
            )
        nav_value = core._tool_output(nav)
        if plan.want_title:
            if isinstance(nav_value, dict) and nav_value.get("title") is not None:
                successful["title"] = _browser_scalar(nav_value["title"])
            else:
                _field("browser_get_title", "title", "title")
        for selector in plan.selectors:
            selected = da.parse_tool_result(
                da.execute_tool("browser_extract_content", {"url": plan.url, "selector": selector})
            )
            value = core._tool_output(selected) if selected.ok else None
            if isinstance(value, dict):
                value = value.get("content", value.get("text", value))
            no_match = isinstance(value, str) and "no elements matched" in value.lower()
            if not selected.ok or no_match:
                failed.append(
                    {
                        "field": selector,
                        "selector": selector,
                        "error": selected.error or str(value or "selector not found"),
                    }
                )
            else:
                successful[selector] = _browser_scalar(value)
        if plan.want_text:
            _field("browser_get_text", "body", "content")
        if plan.want_links:
            _field("browser_get_links", "a", "links")
        if not successful and not failed:
            successful["page"] = _browser_scalar(nav_value)
        if failed and successful:
            return da.DirectActionResult(
                False,
                f"Browser request partially completed. Successful fields: {json.dumps(successful, ensure_ascii=False, default=str)}. Failed fields: {json.dumps(failed, ensure_ascii=False)}",
                execution_type="semantic_graph",
                tool_name="browser_extract_content",
                provider="browser",
                telemetry={
                    "status": "partial_failure",
                    "successful_fields": successful,
                    "failed_fields": failed,
                    "structured_result": successful,
                    "verification_passed": False,
                    "reason": "partial_browser_failure",
                },
            )
        if failed:
            return da.DirectActionResult(
                False,
                f"Browser extraction failed: {json.dumps(failed, ensure_ascii=False)}",
                execution_type="semantic_graph",
                tool_name="browser_extract_content",
                provider="browser",
                telemetry={
                    "status": "total_failure",
                    "successful_fields": {},
                    "failed_fields": failed,
                    "verification_passed": False,
                    "reason": "browser_failed",
                },
            )
        browser_value: Any = next(iter(successful.values())) if len(successful) == 1 else successful
        return da.DirectActionResult(
            True,
            json.dumps(successful, ensure_ascii=False, default=str),
            execution_type="semantic_graph",
            tool_name="browser_extract_content",
            provider="browser",
            telemetry={
                "status": "completed",
                "successful_fields": successful,
                "failed_fields": [],
                "structured_result": successful,
                "value": browser_value,
                "selectors": plan.selectors,
                "verification_passed": True,
                "semantic_action": graph.action.value,
            },
        )

    def _authorize(graph: Any) -> tuple[bool, frozenset[str], frozenset[str], str]:
        if graph.errors:
            return False, frozenset(), frozenset(), graph.errors[0]
        transform = getattr(graph, "transform_plan", None)
        if transform is not None:
            return True, frozenset({"write_file"}), frozenset({transform["output"]}), "explicit_transform_output"
        return core.EffectAuthorizer.authorize(graph)

    def _public_exact(graph: Any) -> Any:
        return da.DirectActionResult(
            True,
            graph.literal_payload,
            execution_type="exact_response",
            tool_name="echo",
            provider="system",
            telemetry={
                "semantic_action": graph.action.value,
                "side_effects": "none",
                "verification_passed": True,
                "status": "completed",
            },
        )

    def can_handle(cls: Any, text: str) -> bool:
        return (
            core.SemanticParser.parse(text, da.RequestPreprocessor.KNOWN_EXTENSIONS).action
            != core.SemanticAction.UNKNOWN
        )

    def execute(cls: Any, text: str, *, context: str = "", control: Any = None, workspace: str = "") -> Any:
        graph = core.SemanticParser.parse(text, da.RequestPreprocessor.KNOWN_EXTENSIONS)
        if graph.action == core.SemanticAction.UNKNOWN:
            if control is not None:
                memory = cls._try_memory_recall(text, context=context, control=control)
                if memory is not None:
                    return core._render(da, graph, memory)
            return None
        allowed, effects, outputs, reason = _authorize(graph)
        if not allowed:
            return da.DirectActionResult(
                False,
                f"Request rejected before execution: {reason}",
                execution_type="policy_enforcement",
                tool_name="effect_authorizer",
                provider="semantic-core",
                policy_decision="refused",
                telemetry={"reason": reason, "semantic_action": graph.action.value, "verification_passed": False},
            )
        effect_token = core._EFFECT_SCOPE.set(effects)
        output_token = core._OUTPUT_SCOPE.set(outputs)
        try:
            if graph.action == core.SemanticAction.EXACT_LITERAL:
                result = _public_exact(graph)
            elif graph.action == core.SemanticAction.POLICY_REFUSAL:
                result = da.DirectActionResult(
                    False,
                    "Policy refusal: I cannot perform that destructive action while bypassing approval or policy.",
                    execution_type="policy_enforcement",
                    tool_name="policy",
                    provider="semantic-core",
                    policy_decision="refused",
                    telemetry={"reason": "destructive_action_unauthorized", "verification_passed": False},
                )
            elif graph.action == core.SemanticAction.FILE_READ:
                result = _read_file(graph, workspace)
            elif graph.action == core.SemanticAction.DIRECTORY_LIST:
                result = _filesystem_contents(graph, workspace)
            elif graph.action == core.SemanticAction.ARITHMETIC:
                result = _execute_arithmetic(graph, workspace)
            elif graph.action == core.SemanticAction.BROWSER:
                result = _execute_browser(graph)
            elif graph.action == core.SemanticAction.FILE_WRITE:
                transform = getattr(graph, "transform_plan", None)
                if transform and transform["kind"] == "table_json":
                    result = _execute_table_transform(graph, transform, workspace)
                elif transform:
                    result = _execute_legacy_transform(graph, transform, workspace)
                else:
                    result = _write_exact(graph, workspace)
            elif graph.action == core.SemanticAction.REPOSITORY:
                result = cls._try_repository_inspection(text, workspace=workspace)
            elif graph.action == core.SemanticAction.SCREENSHOT:
                result = cls._try_screenshot(text, workspace=workspace)
            elif graph.action == core.SemanticAction.MEMORY_RECALL:
                result = cls._try_memory_recall(text, context=context, control=control)
            elif graph.action == core.SemanticAction.CALENDAR:
                result = cls._try_calendar_event(text, context=context)
            else:
                result = None
        finally:
            core._OUTPUT_SCOPE.reset(output_token)
            core._EFFECT_SCOPE.reset(effect_token)
        return core._render(da, graph, result)

    def exact_parse(cls: Any, text: str, workspace: str = "") -> Any:
        graph = core.SemanticParser.parse(text, da.RequestPreprocessor.KNOWN_EXTENSIONS)
        if graph.action != core.SemanticAction.EXACT_LITERAL:
            return None
        result = _public_exact(graph)
        result.execution_type = "semantic_graph"
        return result

    def exact_parse_intent(cls: Any, text: str) -> Any:
        graph = core.SemanticParser.parse(text, da.RequestPreprocessor.KNOWN_EXTENSIONS)
        if graph.action != core.SemanticAction.EXACT_LITERAL or graph.literal_payload is None:
            return None
        payload = graph.literal_payload
        candidates = list(re.finditer(re.escape(payload), text))
        if not candidates:
            return None
        match = candidates[-1]
        start, end = match.start(), match.end()
        quote_style = "none"
        if start > 0 and end < len(text) and text[start - 1] == text[end] and text[start - 1] in "'\"`":
            quote_style = {"'": "single", '"': "double", "`": "backtick"}[text[start - 1]]
        return da.ExactLiteralIntent(
            payload=payload,
            payload_span_start=start,
            payload_span_end=end,
            quote_style=quote_style,
            prefix_constraint=text[:start],
            suffix_constraint=text[end:],
            confidence=1.0,
        )

    _install_attr(da.DirectActionRouter, "can_handle", classmethod(can_handle))
    _install_attr(da.DirectActionRouter, "execute", classmethod(execute))
    _install_attr(da.ExactResponseParser, "parse", classmethod(exact_parse))
    _install_attr(da.ExactResponseParser, "parse_intent", classmethod(exact_parse_intent))
    _INSTALLED = True
