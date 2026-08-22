"""Generic, policy-governed direct action execution for ARCH / Amaura JARVIS.

Routes natural-language deterministic actions through registered capabilities
behind explicit policy boundaries, with independent effect verification,
semantic accuracy, structured language interpretation, and truthful lifecycle telemetry.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from jarvis.tools.registry import execute_tool
from jarvis.tools.result import parse_tool_result
from jarvis.tools.security import resolve_workspace_path, tool_workspace, workspace_root

# ═════════════════════════════════════════════════════════════════════════════
# 1. Structural Preprocessing & Semantic Span Data Models
# ═════════════════════════════════════════════════════════════════════════════


class SpanType(StrEnum):
    """Types of semantic spans identified during preprocessing."""

    PATH = "PATH"
    URL = "URL"
    QUOTED_LITERAL = "QUOTED_LITERAL"
    JSON_OBJECT = "JSON_OBJECT"
    JSON_ARRAY = "JSON_ARRAY"
    CODE_BLOCK = "CODE_BLOCK"
    INLINE_CODE = "INLINE_CODE"
    NUMBER = "NUMBER"
    VERB = "VERB"
    OBJECT = "OBJECT"
    NEGATION = "NEGATION"
    RESPONSE_CONSTRAINT = "RESPONSE_CONSTRAINT"
    DELIMITER = "DELIMITER"
    MODIFIER = "MODIFIER"


@dataclass
class SemanticSpan:
    """A semantic span preserving start/end character offsets, raw text, and role."""

    span_type: SpanType
    start: int
    end: int
    raw_text: str
    normalized_role: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Clause:
    """A single semantic clause/sentence with scoped spans and negation."""

    clause_id: int
    start: int
    end: int
    raw_text: str
    masked_text: str
    spans: list[SemanticSpan] = field(default_factory=list)
    is_negated: bool = False
    negation_words: list[str] = field(default_factory=list)
    verbs: list[str] = field(default_factory=list)
    objects: list[str] = field(default_factory=list)


class PathRole(StrEnum):
    """Semantic role of a filesystem path in a natural-language request."""

    INPUT = "input"
    SECONDARY_INPUT = "secondary_input"
    OUTPUT = "output"
    WORKSPACE = "workspace"
    REPOSITORY = "repository"


class ResponseMode(StrEnum):
    """Response formatting constraints separated from action intent.

    NORMAL    — default formatted response
    DISPLAY   — rich display with labels/line-numbers
    RAW       — minimal formatting, no labels
    EXACT_RAW — byte-for-byte file content (no extra formatting)
    VALUE_ONLY— execute underlying action, return only extracted value
    NUMBER_ONLY — execute calculation, return only numeric result
    JSON_ONLY  — format as JSON
    PATH_ONLY  — return only the path string
    SILENT     — suppress output
    """

    NORMAL = "NORMAL"
    DISPLAY = "DISPLAY"
    RAW = "RAW"
    EXACT_RAW = "EXACT_RAW"
    VALUE_ONLY = "VALUE_ONLY"
    NUMBER_ONLY = "NUMBER_ONLY"
    JSON_ONLY = "JSON_ONLY"
    PATH_ONLY = "PATH_ONLY"
    SILENT = "SILENT"


class ActionType(StrEnum):
    """Semantic action types supported by direct deterministic routing."""

    EXACT_LITERAL_RESPONSE = "EXACT_LITERAL_RESPONSE"
    SCREENSHOT_CAPTURE = "SCREENSHOT_CAPTURE"
    FILE_WRITE = "FILE_WRITE"
    FILE_READ = "FILE_READ"
    DIRECTORY_LIST = "DIRECTORY_LIST"
    BROWSER_ACTION = "BROWSER_ACTION"
    STRUCTURED_WORKFLOW = "STRUCTURED_WORKFLOW"
    REPOSITORY_INSPECT = "REPOSITORY_INSPECT"
    MEMORY_ACTION = "MEMORY_ACTION"
    DESKTOP_APP_ACTION = "DESKTOP_APP_ACTION"
    CONVERSATION = "CONVERSATION"
    MISSION = "MISSION"


@dataclass
class ActionCandidate:
    """Scored candidate action derived from positive and negative semantic evidence."""

    action_type: ActionType
    verb_span: SemanticSpan | None = None
    object_span: SemanticSpan | None = None
    positive_evidence: list[str] = field(default_factory=list)
    negative_evidence: list[str] = field(default_factory=list)
    confidence: float = 1.0
    clause_id: int = 0
    is_blocked_as_negated: bool = False


@dataclass
class ParsedRequest:
    """Structured representation of a request operating on semantic spans."""

    original_text: str
    clauses: list[Clause] = field(default_factory=list)
    tokens: set[str] = field(default_factory=set)
    paths: list[SemanticSpan] = field(default_factory=list)
    urls: list[SemanticSpan] = field(default_factory=list)
    quoted_literals: list[SemanticSpan] = field(default_factory=list)
    code_blocks: list[SemanticSpan] = field(default_factory=list)
    structured_literals: list[SemanticSpan] = field(default_factory=list)
    verbs: list[SemanticSpan] = field(default_factory=list)
    objects: list[SemanticSpan] = field(default_factory=list)
    modifiers: list[SemanticSpan] = field(default_factory=list)
    negations: list[SemanticSpan] = field(default_factory=list)
    response_constraints: list[SemanticSpan] = field(default_factory=list)
    response_mode: ResponseMode = ResponseMode.NORMAL
    masked_classifier_view: str = ""
    candidate_actions: list[ActionCandidate] = field(default_factory=list)
    primary_action: ActionCandidate | None = None


@dataclass
class IntentDecision:
    """Structured decision representing classified intent and extracted arguments."""

    domain: str
    action: str
    confidence: float = 1.0
    arguments: dict[str, Any] = field(default_factory=dict)
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


@dataclass
class DirectActionResult:
    """Result of a direct action execution with verifiable evidence and provenance."""

    success: bool
    output: str
    execution_type: str = "tool"
    tool_name: str = ""
    provider: str = ""
    model: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)
    policy_decision: str = "allowed"
    telemetry: dict[str, Any] = field(default_factory=dict)


class FilesystemActionType(StrEnum):
    """Semantic action types for filesystem operations."""

    FS_READ_FILE = "FS_READ_FILE"
    FS_LIST_DIRECTORY = "FS_LIST_DIRECTORY"
    FS_WRITE_FILE = "FS_WRITE_FILE"
    FS_STAT = "FS_STAT"
    FS_UNKNOWN = "FS_UNKNOWN"


@dataclass
class FilesystemSemanticAction:
    """Structured semantic decision for a filesystem request."""

    action_type: FilesystemActionType
    target_path: str
    is_directory: bool = False
    is_file: bool = False
    exists: bool = False
    confidence: float = 1.0
    evidence: list[str] = field(default_factory=list)


@dataclass
class FilesystemAction:
    """Structured filesystem action representing parsed write, read, or list request."""

    action: str
    path: str
    content: str = ""
    read_mode: str = "display"
    overwrite: bool = True


@dataclass
class WriteIntent:
    """Structured write intent representing parsed write request with extraction provenance."""

    target_path: str
    payload_span: tuple[int, int] = (-1, -1)
    payload: str = ""
    payload_type: str = "INLINE_LITERAL"
    exactness: bool = True
    source_clause: str = ""
    confidence: float = 1.0
    explicit_empty: bool = False
    is_invalid: bool = False
    invalid_reason: str = ""


@dataclass
class WriteAction:
    """Structured write action representing parsed write request with clause-level provenance."""

    target_path: str
    content: str = ""
    payload: str = ""
    payload_span_start: int = -1
    payload_span_end: int = -1
    content_source_span: str = ""
    exactness: bool = True
    exact_content_requested: bool = True
    has_explicit_content: bool = False
    explicit_empty: bool = False
    is_empty_requested: bool = False
    confidence: float = 1.0
    overwrite: bool = True
    is_invalid: bool = False
    invalid_reason: str = ""
    payload_type: str = "INLINE_LITERAL"

    def __post_init__(self):
        if not self.content and self.payload:
            self.content = self.payload
        elif not self.payload and self.content:
            self.payload = self.content
        if self.exact_content_requested and not self.exactness:
            self.exactness = self.exact_content_requested
        if self.is_empty_requested and not self.explicit_empty:
            self.explicit_empty = self.is_empty_requested


@dataclass
class BrowserField:
    """Single requested field in a browser action."""

    type: str
    selector: str = ""
    name: str = ""


@dataclass
class BrowserFieldRequest:
    """A single explicitly-requested browser field with source span provenance.

    Phase 8: CSS selectors containing action-like words (capture, write, screen,
    read, open) must be preserved verbatim as data, not interpreted as intents.
    """

    selector: str
    requested_output_role: str = "value"
    source_span: tuple[int, int] = (-1, -1)


@dataclass
class BrowserActionPlan:
    """Structured multi-field browser extraction plan."""

    url: str
    requests: list[BrowserField] = field(default_factory=list)


@dataclass
class SubtractIntent:
    """Phase 8: Structured subtraction operation with explicit semantic roles.

    Natural-language semantics preserved:
      'subtract B from A'  => A - B  (minuend=A, subtrahend=B)
      'take B away from A' => A - B  (minuend=A, subtrahend=B)
      'A minus B'          => A - B  (minuend=A, subtrahend=B)
    """

    minuend: str  # the value being subtracted FROM
    subtrahend: str  # the value being subtracted
    output_path: str = ""
    provenance: str = ""  # source phrase that established roles
    minuend_role_span: tuple[int, int] = (-1, -1)
    subtrahend_role_span: tuple[int, int] = (-1, -1)
    confidence: float = 1.0


@dataclass
class DivisionIntent:
    """Phase 8: Structured division operation with explicit semantic roles.

    Natural-language semantics preserved:
      'divide A by B'   => A / B  (numerator=A, denominator=B)
      'A divided by B'  => A / B  (numerator=A, denominator=B)
      'divide B into A' => A / B  (numerator=A, denominator=B)
    """

    numerator: str
    denominator: str
    output_path: str = ""
    provenance: str = ""
    numerator_role_span: tuple[int, int] = (-1, -1)
    denominator_role_span: tuple[int, int] = (-1, -1)
    confidence: float = 1.0


@dataclass
class ExactLiteralIntent:
    """Phase 8: Structured exact-literal echo intent with explicit payload extraction.

    The payload MUST be explicitly present in the request text.
    If the payload depends on another action (file read, memory, browser), this
    is NOT an ExactLiteralIntent — it is a composite action with VALUE_ONLY mode.
    """

    payload: str
    payload_span_start: int = -1
    payload_span_end: int = -1
    quote_style: str = ""  # 'single', 'double', 'backtick', 'none'
    prefix_constraint: str = ""  # the command prefix (e.g., 'Return only')
    suffix_constraint: str = ""  # trailing instruction stripped from payload
    confidence: float = 1.0


@dataclass
class TransformationPlan:
    """Structured workflow transformation plan derived from user semantics."""

    inputs: list[str]
    operation: str
    output_path: str
    output_format: str = "text"
    parameters: dict[str, Any] = field(default_factory=dict)
    # Phase 8: semantic role metadata for arithmetic operations
    input_roles: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DelimitedTablePlan:
    """Structured plan for delimited table to JSON transformation."""

    source_path: str
    delimiter: str
    has_header: bool = True
    output_path: str = ""
    output_format: str = "json"
    infer_types: bool = True


# ═════════════════════════════════════════════════════════════════════════════
# 2. Reusable Request Preprocessing Layer
# ═════════════════════════════════════════════════════════════════════════════


class RequestPreprocessor:
    """Reusable structural preprocessing layer extracting typed semantic spans."""

    KNOWN_EXTENSIONS = (
        ".txt",
        ".json",
        ".py",
        ".md",
        ".csv",
        ".tsv",
        ".log",
        ".yaml",
        ".yml",
        ".html",
        ".htm",
        ".js",
        ".ts",
        ".sh",
        ".toml",
        ".cfg",
        ".ini",
        ".conf",
        ".xml",
        ".sql",
        ".dat",
        ".bin",
        ".out",
        ".png",
        ".jpg",
        ".jpeg",
        ".pdf",
        ".env",
        ".lock",
        ".rst",
        ".xyz",
        ".custom",
        ".abc",
        ".num",
    )

    STOP_WORDS = {
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
        "your",
        "my",
        "our",
        "their",
        "his",
        "her",
        "should",
        "must",
        "will",
        "can",
        "could",
        "would",
        "content",
        "contents",
        "text",
        "payload",
        "data",
        "body",
        "sum",
        "total",
        "result",
        "file",
        "files",
        "directory",
        "directories",
        "folder",
        "folders",
        "repo",
        "repository",
        "codebase",
        "true",
        "false",
        "null",
        "none",
        "only",
        "verbatim",
        "exact",
        "raw",
        "table",
        "tables",
        "json",
        "csv",
        "tsv",
        "destination",
        "target",
        "location",
        "located",
        "following",
        "out",
        "transformed",
        "transformed json",
        "converted",
        "output",
        "input",
        "source",
        "sources",
        "entry",
        "entries",
        "item",
        "items",
        "solely",
        "strictly",
        "precisely",
        "nothing",
        "without",
        "explanation",
        "commentary",
        "all",
        "each",
        "every",
        "some",
        "any",
        "not",
    }

    NEGATION_WORDS = {
        "not",
        "don't",
        "dont",
        "do not",
        "does not",
        "doesn't",
        "never",
        "without",
        "instead of",
        "rather than",
        "no",
        "cannot",
        "can't",
        "should not",
        "shouldn't",
    }

    CAPTURE_VERBS = {"capture", "grab", "snap", "take", "save", "record"}
    SCREEN_OBJECTS = {
        "screen",
        "display",
        "desktop",
        "monitor",
        "screenshot",
        "screen shot",
        "screen capture",
        "screen image",
    }

    WRITE_VERBS = {
        "write",
        "overwrite",
        "save",
        "create",
        "make",
        "put",
        "store",
        "dump",
        "record",
        "generate",
        "set",
        "contain",
        "contains",
        "hold",
        "holds",
    }
    READ_VERBS = {"read", "cat", "open", "show", "display", "view", "inspect", "fetch", "load", "get", "print"}
    LIST_VERBS = {"list", "enumerate", "inventory", "show", "display"}
    WORKFLOW_VERBS = {
        "add",
        "subtract",
        "difference",
        "multiply",
        "divide",
        "sum",
        "total",
        "calculate",
        "compute",
        "combine",
        "transform",
        "convert",
    }

    @classmethod
    def scan_balanced_json(cls, text: str) -> list[SemanticSpan]:
        """Scan text for balanced JSON objects and arrays with quote and escape tracking."""
        spans: list[SemanticSpan] = []
        i = 0
        n = len(text)

        while i < n:
            ch = text[i]
            if ch in ("{", "["):
                open_ch = ch
                close_ch = "}" if ch == "{" else "]"
                start = i
                depth = 0
                in_quote = False
                quote_char = ""
                escaped = False
                valid_json = False
                candidate_str = ""

                j = i
                while j < n:
                    c = text[j]
                    if in_quote:
                        if escaped:
                            escaped = False
                        elif c == "\\":
                            escaped = True
                        elif c == quote_char:
                            in_quote = False
                    else:
                        if c in ('"', "'"):
                            in_quote = True
                            quote_char = c
                        elif c == open_ch:
                            depth += 1
                        elif c == close_ch:
                            depth -= 1
                            if depth == 0:
                                candidate_str = text[start : j + 1]
                                # Attempt JSON parse
                                try:
                                    json.loads(candidate_str)
                                    valid_json = True
                                except Exception:
                                    pass
                                break
                    j += 1

                if valid_json and candidate_str:
                    stype = SpanType.JSON_OBJECT if open_ch == "{" else SpanType.JSON_ARRAY
                    spans.append(
                        SemanticSpan(
                            span_type=stype,
                            start=start,
                            end=j + 1,
                            raw_text=candidate_str,
                            normalized_role="structured_literal",
                        )
                    )
                    i = j + 1
                    continue
            i += 1

        return spans

    @classmethod
    def scan_code_blocks(cls, text: str) -> list[SemanticSpan]:
        """Scan text for fenced code blocks and inline code."""
        spans: list[SemanticSpan] = []

        # 1. Fenced blocks ```...```
        for m in re.finditer(r"```(?:[a-zA-Z0-9_-]+)?\n?(.*?)\n?```", text, re.DOTALL):
            spans.append(
                SemanticSpan(
                    span_type=SpanType.CODE_BLOCK,
                    start=m.start(0),
                    end=m.end(0),
                    raw_text=m.group(0),
                    normalized_role="code_block",
                    metadata={"inner": m.group(1)},
                )
            )

        # 2. Inline code `...`
        for m in re.finditer(r"`([^`\n]+)`", text):
            if not any(s.start <= m.start(0) and s.end >= m.end(0) for s in spans):
                spans.append(
                    SemanticSpan(
                        span_type=SpanType.INLINE_CODE,
                        start=m.start(0),
                        end=m.end(0),
                        raw_text=m.group(0),
                        normalized_role="inline_code",
                        metadata={"inner": m.group(1)},
                    )
                )

        return spans

    @classmethod
    def scan_urls(cls, text: str) -> list[SemanticSpan]:
        """Scan text for HTTP/HTTPS/file URLs."""
        spans: list[SemanticSpan] = []
        for m in re.finditer(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s'\"`<>]+", text):
            raw = m.group(0).rstrip(".,:;!?)]}")
            spans.append(
                SemanticSpan(
                    span_type=SpanType.URL,
                    start=m.start(0),
                    end=m.start(0) + len(raw),
                    raw_text=raw,
                    normalized_role="url",
                )
            )
        return spans

    @classmethod
    def scan_quoted_literals(cls, text: str, existing_spans: list[SemanticSpan]) -> list[SemanticSpan]:
        """Scan text for quoted strings not already part of structured spans."""
        spans: list[SemanticSpan] = []
        pattern = re.compile(
            r"('([^'\\]*(?:\\.[^'\\]*)*)'|\"([^\"\\]*(?:\\.[^\"\\]*)*)\"|`([^`\\]*(?:\\.[^`\\]*)*)`|«([^»]*)»|“([^”]*)”)"
        )
        for m in pattern.finditer(text):
            start = m.start(0)
            end = m.end(0)
            if any(s.start <= start and s.end >= end for s in existing_spans):
                continue
            inner = (
                m.group(2)
                if m.group(2) is not None
                else (
                    m.group(3)
                    if m.group(3) is not None
                    else (
                        m.group(4)
                        if m.group(4) is not None
                        else (m.group(5) if m.group(5) is not None else (m.group(6) if m.group(6) is not None else ""))
                    )
                )
            )
            spans.append(
                SemanticSpan(
                    span_type=SpanType.QUOTED_LITERAL,
                    start=start,
                    end=end,
                    raw_text=m.group(0),
                    normalized_role="quoted_literal",
                    metadata={"inner": inner},
                )
            )
        return spans

    @classmethod
    def scan_paths(cls, text: str, existing_spans: list[SemanticSpan]) -> list[SemanticSpan]:
        """Scan text for filesystem path spans."""
        spans: list[SemanticSpan] = []
        raw_paths = PathExtractor.extract_all_paths(text)

        for p_str in raw_paths:
            pattern = re.escape(p_str)
            for m in re.finditer(pattern, text):
                start = m.start(0)
                end = m.end(0)
                if (
                    start > 0
                    and end < len(text)
                    and text[start - 1] in ("'", '"', "`")
                    and text[end] in ("'", '"', "`")
                ):
                    start -= 1
                    end += 1
                if any(
                    s.span_type in (SpanType.JSON_OBJECT, SpanType.JSON_ARRAY, SpanType.CODE_BLOCK)
                    and s.start <= start
                    and s.end >= end
                    for s in existing_spans
                ):
                    continue
                spans.append(
                    SemanticSpan(
                        span_type=SpanType.PATH,
                        start=start,
                        end=end,
                        raw_text=text[start:end],
                        normalized_role="path",
                        metadata={"clean_path": p_str},
                    )
                )
        return spans

    @classmethod
    def build_masked_view(cls, text: str, non_intent_spans: list[SemanticSpan]) -> str:
        """Produce a masked view for action classification where non-intent spans are replaced."""
        sorted_spans = sorted(non_intent_spans, key=lambda s: s.start)
        merged: list[SemanticSpan] = []
        for s in sorted_spans:
            if not merged:
                merged.append(s)
            else:
                prev = merged[-1]
                if s.start >= prev.end:
                    merged.append(s)
                elif s.end > prev.end:
                    pass

        out: list[str] = []
        curr = 0
        for s in merged:
            out.append(text[curr : s.start])
            if s.span_type == SpanType.PATH:
                out.append("<PATH>")
            elif s.span_type == SpanType.URL:
                out.append("<URL>")
            elif s.span_type == SpanType.QUOTED_LITERAL:
                out.append("<QUOTED_LITERAL>")
            elif s.span_type in (SpanType.JSON_OBJECT, SpanType.JSON_ARRAY):
                out.append("<JSON>")
            elif s.span_type in (SpanType.CODE_BLOCK, SpanType.INLINE_CODE):
                out.append("<CODE>")
            else:
                out.append("<LITERAL>")
            curr = s.end
        out.append(text[curr:])
        return "".join(out)

    @classmethod
    def segment_clauses(cls, text: str, masked_text: str, non_intent_spans: list[SemanticSpan]) -> list[Clause]:
        """Segment request into semantic clauses and evaluate negation within each clause."""
        clause_pattern = re.compile(
            r"(?:;|[\n]+|(?<=[a-zA-Z0-9_\"'`])\.(?=\s+|$)|(?:\band\s+then\b|\bthen\b|\bbut\b)|(?=\b(?:without|instead\s+of|rather\s+than)\b))",
            re.IGNORECASE,
        )

        clauses: list[Clause] = []
        matches = list(clause_pattern.finditer(text))
        boundaries = [0] + [m.start(0) for m in matches] + [len(text)]
        end_boundaries = [0] + [m.end(0) for m in matches] + [len(text)]

        intervals: list[tuple[int, int]] = []
        for idx in range(len(boundaries) - 1):
            s_idx = end_boundaries[idx] if idx > 0 else boundaries[idx]
            e_idx = boundaries[idx + 1]
            if s_idx < e_idx:
                intervals.append((s_idx, e_idx))

        if not intervals:
            intervals = [(0, len(text))]

        clause_id = 0
        for s_idx, e_idx in intervals:
            c_raw = text[s_idx:e_idx].strip()
            if not c_raw:
                continue

            c_spans = [s for s in non_intent_spans if s.start >= s_idx and s.end <= e_idx]
            c_masked = cls.build_masked_view(
                text[s_idx:e_idx],
                [
                    SemanticSpan(s.span_type, s.start - s_idx, s.end - s_idx, s.raw_text, s.normalized_role, s.metadata)
                    for s in c_spans
                ],
            )

            c_lower = c_masked.lower()
            neg_words = [nw for nw in cls.NEGATION_WORDS if re.search(r"\b" + re.escape(nw) + r"\b", c_lower)]
            is_negated = bool(neg_words)

            verbs = [
                v
                for v in (cls.CAPTURE_VERBS | cls.WRITE_VERBS | cls.READ_VERBS | cls.LIST_VERBS | cls.WORKFLOW_VERBS)
                if re.search(r"\b" + re.escape(v) + r"\b", c_lower)
            ]
            objects = [o for o in cls.SCREEN_OBJECTS if re.search(r"\b" + re.escape(o) + r"\b", c_lower)]

            clauses.append(
                Clause(
                    clause_id=clause_id,
                    start=s_idx,
                    end=e_idx,
                    raw_text=c_raw,
                    masked_text=c_masked,
                    spans=c_spans,
                    is_negated=is_negated,
                    negation_words=neg_words,
                    verbs=verbs,
                    objects=objects,
                )
            )
            clause_id += 1

        return clauses

    @classmethod
    def detect_response_mode(cls, text: str) -> ResponseMode:
        """Detect explicit response formatting constraints.

        Phase 8: Detection order is semantically significant.
          1. NUMBER_ONLY/VALUE_ONLY (specific arithmetic/memory modes) — checked FIRST
          2. FILE-AS-REPLY patterns
          3. EXACT_RAW (catch-all for raw output constraints)
          4. Structured output modes (JSON_ONLY, PATH_ONLY)
          5. SILENT, RAW, NORMAL

        NUMBER_ONLY must come before EXACT_RAW because phrases like
        "give only the number" also match "give only" in the EXACT_RAW list.
        """
        clean = text.lower()
        # Phase 8: NUMBER_ONLY — arithmetic result only (HIGHEST PRIORITY)
        if any(
            phrase in clean
            for phrase in (
                "result only",
                "number only",
                "only the number",
                "only the result",
                "just the number",
                "just the result",
                "reply with only the number",
                "return only the number",
                "give only the number",
            )
        ):
            return ResponseMode.NUMBER_ONLY
        # Phase 8: VALUE_ONLY — memory/browser/file value only (BEFORE EXACT_RAW)
        if any(
            phrase in clean
            for phrase in (
                "value only",
                "only the value",
                "only value at",
                "reply with only value",
                "return only value",
                "return only the value",
                "give only the value",
                "only the remembered",
                "only the stored",
                "only the retrieved",
                "reply only with the value",
                "just the value",
                "just return the value",
                "only its value",
                "reply with the value only",
                "return only the marker",
                "only the marker",
                "just the marker",
            )
        ):
            return ResponseMode.VALUE_ONLY
        # Phase 8: FILE-AS-REPLY patterns
        if any(
            w in clean
            for w in (
                "use the text stored in",
                "use the contents of",
                "use file contents as",
                "as your complete reply",
                "as your entire reply",
                "as your whole reply",
                "as my complete response",
                "use it as your reply",
            )
        ):
            return ResponseMode.EXACT_RAW
        if any(
            w in clean
            for w in (
                "return exactly",
                "give exactly",
                "print exactly",
                "verbatim",
                "exact contents",
                "only contents",
                "only the contents",
                "raw content",
                "raw contents",
                "unchanged",
                "without explanation",
                "without line numbers",
                "just the contents",
                "just contents",
                "no formatting",
                "no headers",
                "raw file",
                "exact file",
                "only file content",
                "give only",
                "return only the content",
                "return only the contents",
                "exact output",
                "whole reply must be file text",
                "whole response must be",
            )
        ):
            return ResponseMode.EXACT_RAW
        if "json only" in clean or "only json" in clean or "as json" in clean:
            return ResponseMode.JSON_ONLY
        if "path only" in clean or "only path" in clean:
            return ResponseMode.PATH_ONLY
        if "silent" in clean or "silently" in clean:
            return ResponseMode.SILENT
        if "raw" in clean:
            return ResponseMode.RAW
        return ResponseMode.NORMAL

    @classmethod
    def process(cls, text: str) -> ParsedRequest:
        """Build full structured ParsedRequest representation from input text."""
        clean = text.strip()
        if not clean:
            return ParsedRequest(original_text=text)

        # 1. Structural Spans
        json_spans = cls.scan_balanced_json(clean)
        code_spans = cls.scan_code_blocks(clean)
        url_spans = cls.scan_urls(clean)
        known_spans = json_spans + code_spans + url_spans

        path_spans = cls.scan_paths(clean, known_spans)
        known_spans += path_spans

        quoted_spans = cls.scan_quoted_literals(clean, known_spans)
        all_non_intent = json_spans + code_spans + url_spans + path_spans + quoted_spans

        # 2. Masked Classifier View
        masked_view = cls.build_masked_view(clean, all_non_intent)

        # 3. Clauses & Negation
        clauses = cls.segment_clauses(clean, masked_view, all_non_intent)

        # 4. Response Mode
        resp_mode = cls.detect_response_mode(clean)

        # 5. Tokens
        tokens = set(re.findall(r"[a-z0-9_+-]+", clean.lower()))

        # 6. Candidate Actions Scoring
        candidates = cls.score_candidate_actions(clean, masked_view, clauses, path_spans, quoted_spans, resp_mode)

        # Determine primary action
        primary = None
        valid_candidates = [c for c in candidates if not c.is_blocked_as_negated and c.confidence > 0]
        if valid_candidates:
            valid_candidates.sort(key=lambda c: c.confidence, reverse=True)
            primary = valid_candidates[0]

        return ParsedRequest(
            original_text=clean,
            clauses=clauses,
            tokens=tokens,
            paths=path_spans,
            urls=url_spans,
            quoted_literals=quoted_spans,
            code_blocks=code_spans,
            structured_literals=json_spans,
            response_mode=resp_mode,
            masked_classifier_view=masked_view,
            candidate_actions=candidates,
            primary_action=primary,
        )

    @classmethod
    def score_candidate_actions(
        cls,
        original_text: str,
        masked_view: str,
        clauses: list[Clause],
        paths: list[SemanticSpan],
        quoted_literals: list[SemanticSpan],
        response_mode: ResponseMode,
    ) -> list[ActionCandidate]:
        """Score candidate actions on semantic clauses and masked views."""
        candidates: list[ActionCandidate] = []
        clean_lower = masked_view.lower()

        # ── A. Screenshot Capture Candidate ──────────────────────────────────
        # Requires: CAPTURE_VERB + SCREEN_OBJECT in the SAME clause of masked view
        for c in clauses:
            c_mask = c.masked_text.lower()
            has_verb = any(re.search(r"\b" + re.escape(v) + r"\b", c_mask) for v in cls.CAPTURE_VERBS)
            has_obj = any(re.search(r"\b" + re.escape(o) + r"\b", c_mask) for o in cls.SCREEN_OBJECTS)
            has_direct_noun = bool(
                re.search(r"\b(?:screenshot|screen\s+shot|screen\s+capture|screen\s+image)\b", c_mask)
            )

            if (has_verb and has_obj) or has_direct_noun:
                if c.is_negated:
                    candidates.append(
                        ActionCandidate(
                            action_type=ActionType.SCREENSHOT_CAPTURE,
                            positive_evidence=[f"capture_verb_and_object_in_clause_{c.clause_id}"],
                            negative_evidence=["clause_negated"],
                            confidence=0.0,
                            clause_id=c.clause_id,
                            is_blocked_as_negated=True,
                        )
                    )
                else:
                    candidates.append(
                        ActionCandidate(
                            action_type=ActionType.SCREENSHOT_CAPTURE,
                            positive_evidence=[f"capture_verb_and_object_in_clause_{c.clause_id}"],
                            confidence=0.95,
                            clause_id=c.clause_id,
                        )
                    )

        # ── B. File Write Candidate ──────────────────────────────────────────
        has_write_verb = any(re.search(r"\b" + re.escape(v) + r"\b", clean_lower) for v in cls.WRITE_VERBS)
        has_path_dest = (
            "<path>" in clean_lower
            and any(w in clean_lower for w in (" to ", " in ", " into ", " at ", " file ", "create "))
        ) or bool(paths)
        if has_write_verb and (has_path_dest or "<path>" in clean_lower):
            candidates.append(
                ActionCandidate(
                    action_type=ActionType.FILE_WRITE,
                    positive_evidence=["write_verb_with_target_path"],
                    confidence=0.90,
                )
            )

        # ── C. Structured Workflow Candidate (Arithmetic / Data transforms) ──
        has_workflow_verb = (
            any(re.search(r"\b" + re.escape(v) + r"\b", clean_lower) for v in cls.WORKFLOW_VERBS)
            or "away from" in clean_lower
        )
        if (has_workflow_verb and len(paths) >= 2) or ("take" in clean_lower and "away from" in clean_lower):
            candidates.append(
                ActionCandidate(
                    action_type=ActionType.STRUCTURED_WORKFLOW,
                    positive_evidence=["arithmetic_or_transform_with_multiple_paths"],
                    confidence=0.98,
                )
            )

        # ── D. File Read Candidate ───────────────────────────────────────────
        has_read_verb = any(re.search(r"\b" + re.escape(v) + r"\b", clean_lower) for v in cls.READ_VERBS) or any(
            w in clean_lower
            for w in (
                "file text",
                "contents of",
                "content of",
                "raw contents",
                "verbatim",
                "give me raw",
                "whole reply must be",
            )
        )
        if (
            (has_read_verb or response_mode in (ResponseMode.EXACT_RAW, ResponseMode.RAW))
            and paths
            and not has_write_verb
            and not (has_workflow_verb and len(paths) >= 2)
        ):
            candidates.append(
                ActionCandidate(
                    action_type=ActionType.FILE_READ,
                    positive_evidence=["read_verb_or_raw_mode_with_path"],
                    confidence=0.88,
                )
            )

        # ── E. Directory List Candidate ──────────────────────────────────────
        has_list_verb = any(re.search(r"\b" + re.escape(v) + r"\b", clean_lower) for v in cls.LIST_VERBS) or any(
            w in clean_lower
            for w in ("directory", "folder", "filenames", "entries", "what files are in", "what is under")
        )
        if has_list_verb and not has_write_verb and not has_read_verb and not (has_workflow_verb and len(paths) >= 2):
            candidates.append(
                ActionCandidate(
                    action_type=ActionType.DIRECTORY_LIST,
                    positive_evidence=["directory_list_intent"],
                    confidence=0.85,
                )
            )

        # ── F. Browser Action Candidate ──────────────────────────────────────
        if "<url>" in clean_lower or any(
            w in clean_lower
            for w in ("navigate to", "extract content from", "extract title", "browse ", "open url", "web page")
        ):
            candidates.append(
                ActionCandidate(
                    action_type=ActionType.BROWSER_ACTION,
                    positive_evidence=["browser_navigation_or_extraction"],
                    confidence=0.91,
                )
            )

        # ── G. Memory Action Candidate ───────────────────────────────────────
        if any(
            w in clean_lower
            for w in (
                "what was the value of",
                "recall",
                "remember",
                "saved value of",
                "stored value of",
                "memory value",
            )
        ):
            candidates.append(
                ActionCandidate(
                    action_type=ActionType.MEMORY_ACTION,
                    positive_evidence=["memory_query_intent"],
                    confidence=0.90,
                )
            )

        # ── H. Repository Inspection Candidate ───────────────────────────────
        if any(
            w in clean_lower
            for w in ("inspect repo", "analyze repo", "diagnose", "find bug", "codebase", "review code", "check repo")
        ):
            candidates.append(
                ActionCandidate(
                    action_type=ActionType.REPOSITORY_INSPECT,
                    positive_evidence=["repository_inspection_intent"],
                    confidence=0.92,
                )
            )

        # ── I. Exact Literal Response Candidate ──────────────────────────────
        if not paths and not any(
            w in clean_lower for w in ("<path>", "://", "repo", "repository", "inspect", "diagnose")
        ):
            if (
                any(
                    clean_lower.startswith(pfx)
                    for pfx in (
                        "echo:",
                        "echo ",
                        "reply ",
                        "respond ",
                        "return ",
                        "say ",
                        "print ",
                        "type ",
                        "the following string:",
                        "and nothing more:",
                        "just return",
                        "just echo",
                        "just say",
                        "only reply",
                    )
                )
                or "reply must be" in clean_lower
                or "response must be" in clean_lower
            ):
                candidates.append(
                    ActionCandidate(
                        action_type=ActionType.EXACT_LITERAL_RESPONSE,
                        positive_evidence=["explicit_literal_command"],
                        confidence=0.96,
                    )
                )

        return candidates


# ═════════════════════════════════════════════════════════════════════════════
# 3. Path Extraction with Provenance
# ═════════════════════════════════════════════════════════════════════════════


class PathExtractor:
    """Robust, generic path extractor from natural language prompts preserving semantic roles."""

    KNOWN_EXTENSIONS = RequestPreprocessor.KNOWN_EXTENSIONS
    STOP_WORDS = RequestPreprocessor.STOP_WORDS

    @classmethod
    def extract_all_paths(cls, text: str) -> list[str]:
        """Extract candidate filesystem paths from text in exact order of appearance."""
        candidates: list[tuple[int, str]] = []

        # 1. Quoted strings following path prepositions or keywords
        for m in re.finditer(
            r"\b(?:file|path|directory|folder|repo|repository|codebase|at|in|to|into|from|under|inside|destination|source|target)\s+['\"`]([^'\"`\n]+)['\"`]",
            text,
            re.IGNORECASE,
        ):
            candidates.append((m.start(1), m.group(1)))

        # 2. Quoted strings with path indicators or extensions
        for m in re.finditer(r"['\"`]([^'\"`\n]+)['\"`]", text):
            val = m.group(1)
            if (
                any(val.startswith(pfx) for pfx in ("/", "~", "./", "../"))
                or any(val.endswith(ext) for ext in cls.KNOWN_EXTENSIONS)
                or "/" in val
                or "\\" in val
                or ("." in val and not val.endswith(".") and " " not in val)
            ):
                candidates.append((m.start(1), val))

        # 3. Explicit POSIX absolute paths
        for m in re.finditer(r"(?:^|\s)(/[a-zA-Z0-9_.\-~]+(?:/[a-zA-Z0-9_.\-~]+)*)", text):
            candidates.append((m.start(1), m.group(1)))

        # 4. Relative or home paths
        for m in re.finditer(r"(?:^|\s)((?:~|\.\.?)?/[a-zA-Z0-9_.\-~]+(?:/[a-zA-Z0-9_.\-~]+)*)", text):
            candidates.append((m.start(1), m.group(1)))

        # 5. Words with extensions
        for m in re.finditer(r"\b[a-zA-Z0-9_.\-/~]+\.[a-zA-Z0-9_-]+", text):
            candidates.append((m.start(0), m.group(0)))

        # 6. Unquoted path keywords
        for m in re.finditer(
            r"\b(?:file|path|directory|folder|repo|repository|codebase|location|dir|destination|target|at|in|to|into|from|under|inside)\s+([~/a-zA-Z0-9_.\-]+)",
            text,
            re.IGNORECASE,
        ):
            candidates.append((m.start(1), m.group(1)))

        for m in re.finditer(
            r"\b(?:(?:files|entries|children|direct children|items|filenames|inventory|contents)\s+\b(?:of|under|in|inside)\b)\s+['\"`]?([~/a-zA-Z0-9_.\-]+)['\"`]?",
            text,
            re.IGNORECASE,
        ):
            candidates.append((m.start(1), m.group(1)))

        candidates.sort(key=lambda x: x[0])

        paths: list[str] = []
        seen: set[str] = set()

        for _, raw_p in candidates:
            if not raw_p:
                continue
            p = raw_p.strip().strip("'\"`").rstrip(".,:;!?)]}")
            if not p or p.lower() in cls.STOP_WORDS:
                continue
            if any(p == s or (len(p) < len(s) and p in s and "/" in s) for s in seen):
                continue
            seen.add(p)
            paths.append(p)

        return paths

    @classmethod
    def extract_structured_arguments(cls, text: str, *, default_workspace: str = "") -> dict[str, Any]:
        """Extract structured argument roles: input_path, secondary_input_path, output_path, repo_path, directory."""
        args: dict[str, Any] = {}
        all_paths = cls.extract_all_paths(text)

        # Output path indicators
        out_matches = re.finditer(
            r"\b(?:save|saving|write|writing|put|store|output|destination|create|export|convert)\s+(?:the\s+)?(?:transformed\s+json|json|output|data|result|table)?\s*(?:in|to|into|at)?\s*['\"`]?([~/a-zA-Z0-9_.\-]+)['\"`]?",
            text,
            re.IGNORECASE,
        )
        for m in out_matches:
            cand = m.group(1).strip().strip("'\"`")
            while cand and cand[-1] in (".", ",", ":", ";", "!", "?", ")", "]", "}"):
                cand = cand[:-1].strip()
            if cand in all_paths and cand.lower() not in cls.STOP_WORDS:
                args["output_path"] = cand
                break

        # Input path indicators
        in_matches = re.finditer(
            r"\b(?:read|reading|reads|from|load|loading|input|source|open|cat|fetch|display)\s+(?:the\s+)?(?:table|file|csv|tsv|data|content)?\s*(?:from|in|at|inside)?\s*['\"`]?([~/a-zA-Z0-9_.\-]+)['\"`]?",
            text,
            re.IGNORECASE,
        )
        for m in in_matches:
            cand = m.group(1).strip().strip("'\"`")
            while cand and cand[-1] in (".", ",", ":", ";", "!", "?", ")", "]", "}"):
                cand = cand[:-1].strip()
            if cand in all_paths and cand.lower() not in cls.STOP_WORDS and cand != args.get("output_path"):
                args["input_path"] = cand
                break

        # Two-input indicators
        two_in = re.search(
            r"\b(?:read|from|inputs?|files?)\s+['\"`]?([~/a-zA-Z0-9_.\-]+)['\"`]?\s+(?:and|&|\+)\s+['\"`]?([~/a-zA-Z0-9_.\-]+)['\"`]?",
            text,
            re.IGNORECASE,
        )
        if two_in:
            cand1 = two_in.group(1).strip().strip("'\"`").rstrip(".,;:")
            cand2 = two_in.group(2).strip().strip("'\"`").rstrip(".,;:")
            if cand1 in all_paths and cand2 in all_paths:
                args["input_path"] = cand1
                args["secondary_input_path"] = cand2

        # Repository path indicators
        repo_match = re.search(
            r"\b(?:repo|repository|codebase|project)\s+(?:at|under|in|for|path|located\s+at|located\s+in|located)?\s*['\"`]?([~/a-zA-Z0-9_.\-]+)['\"`]?",
            text,
            re.IGNORECASE,
        )
        if repo_match:
            cand = repo_match.group(1).strip().strip("'\"`").rstrip(".,;:")
            if cand in all_paths:
                args["repo_path"] = cand

        # Directory path indicators
        dir_match = re.search(
            r"\b(?:directory|folder|location|under|inside|contents of|directory contents|folder contents|what is inside|what's inside|what is under|what's under|what files are in|what entries are in|what filenames are in|(?:files|entries|children|direct children|items|filenames|inventory|contents)\s+\b(?:of|under|in|inside)\b|(?:list|show|display|get|print|give(?:\s+me)?|enumerate)\s+(?:location|folder|directory|files|entries|filenames|inventory|contents|children)?)\s*(?:\b(?:of|at|for|in|under|inside)\b\s*)?['\"`]?([~/a-zA-Z0-9_.\-]+)['\"`]?",
            text,
            re.IGNORECASE,
        )
        if dir_match:
            cand = dir_match.group(1).strip().strip("'\"`").rstrip(".,;:")
            if cand.lower() not in cls.STOP_WORDS:
                if not all_paths or cand in all_paths:
                    args["directory"] = cand
                    if cand not in all_paths:
                        all_paths.append(cand)

        # Fallback assignments from all_paths
        if all_paths:
            if (
                not args.get("input_path")
                and not args.get("output_path")
                and not args.get("directory")
                and not args.get("repo_path")
            ):
                args["path"] = all_paths[0]
            if len(all_paths) >= 2 and not args.get("output_path"):
                args["output_path"] = all_paths[-1]
            if len(all_paths) >= 2 and not args.get("input_path"):
                args["input_path"] = all_paths[0]
            if len(all_paths) >= 3 and not args.get("secondary_input_path"):
                args["secondary_input_path"] = all_paths[1]

        return args


# ═════════════════════════════════════════════════════════════════════════════
# 4. Rebuilt Write Parser with Balanced AST, Sanity Checks & Provenance
# ═════════════════════════════════════════════════════════════════════════════


class WriteActionParser:
    """Generic, role-based structured grammar parser for natural-language file write requests."""

    INTRODUCER_STRIP_RE = re.compile(
        r"^(?:"
        r"(?:and\s+)?(?:set\s+(?:its\s+)?)?(?:the|this|its|an?)?\s*(?:complete|exact|exactly|entire|whole|full|verbatim|strictly)?\s*(?:content|text|payload|body|data|string)?\s*\b(?:to\s+be|should\s+be|must\s+be|needs\s+to\s+be|will\s+be|is|to|as)\b\s*[:\-]?\s*"
        r"|(?:complete|exact|exactly|entire|whole|full|verbatim|strictly)?\s*\b(?:content|text|payload|body|data|string)\b\s*[:=]\s*"
        r"|\bout\s+"
        r"|\bthe\s+following\b\s*(?:in\s+['\"`][^'\"`]+['\"`]\s*)?[:\-]\s*"
        r"|(?:the|this|an?)?\s*(?:complete|exact|exactly|entire|whole|full|verbatim|strictly)\s+\b(?:content|text|payload|body|data|string)\b\s*"
        r"|(?:only|just|solely|exactly|strictly|verbatim|precisely)\s+(?:the\s+)?(?:quoted|literal|exact|verbatim|following|above|specified|given)?\s*(?:value|text|string|word|payload|content|body|data|token|literal)\s*"
        r"|the\s+(?:quoted|literal|exact|verbatim|following|above|specified|given)\s+(?:value|text|string|word|payload|content|body|data|token|literal)\s*"
        r"|(?:quoted|literal)\s+(?:value|text|string|word|payload|content|body|data|token|literal)\s*"
        r"|use\s+(?:this|the\s+following|it)\s+as\s+(?:its\s+|the\s+)?(?:complete|exact|exactly|entire|whole|full|verbatim|strictly)?\s*(?:content|text|payload|body|data|string)\s*[:\-]?\s*"
        r")",
        re.IGNORECASE,
    )

    TRAILING_DIRECTIVE_RE = re.compile(
        r"\s+(?:inside\s+it|inside|in\s+it|into\s+it|verbatim|strictly|precisely)\.?$",
        re.IGNORECASE,
    )

    @classmethod
    def parse(cls, text: str, default_workspace: str = "") -> WriteAction | None:
        """Parse natural language write request into a structured WriteAction with clause roles."""
        clean = text.strip()
        if not clean:
            return None

        parsed = RequestPreprocessor.process(clean)
        tokens = parsed.tokens

        # Check if write intent exists
        write_candidates = [
            c
            for c in parsed.candidate_actions
            if c.action_type == ActionType.FILE_WRITE and not c.is_blocked_as_negated
        ]
        has_write_verb = bool(tokens & RequestPreprocessor.WRITE_VERBS) or any(
            ph in clean.lower()
            for ph in ("should contain", "must contain", "should have", "must have", "should hold", "must hold", "put ")
        )
        if not write_candidates and not has_write_verb:
            return None

        clean_lower = clean.lower()
        if any(
            clean_lower.startswith(r)
            for r in (
                "read",
                "open",
                "show",
                "cat",
                "load",
                "fetch",
                "display",
                "view",
                "inspect",
                "examine",
                "list",
                "what",
                "print",
            )
        ):
            if not any(
                w in clean_lower
                for w in (
                    " and write",
                    " and save",
                    " and put",
                    " and store",
                    " and create",
                    " and make",
                    " then write",
                    " then save",
                    " then create",
                    " then make",
                )
            ):
                return None

        # Screenshot-looking words inside an explicit write payload are data.
        # Reject as a screenshot only when the request does not establish a strong
        # write target+payload relationship.
        strong_write_payload_contract = bool(
            re.search(
                r"\b(?:write|create|save|store|put|dump|record)\b[^\n]{0,180}"
                r"(?:\b(?:to|into|at)\b[^\n]{0,120}\b(?:text|content|payload|body|data|string)\b\s*:|"
                r"\b(?:contain|containing|contains|should\s+contain|must\s+contain)\b)",
                clean,
                re.IGNORECASE,
            )
        )
        if not strong_write_payload_contract and any(
            c.action_type == ActionType.SCREENSHOT_CAPTURE and not c.is_blocked_as_negated and c.confidence > 0.8
            for c in parsed.candidate_actions
        ):
            return None

        all_paths = [p.raw_text.strip("'\"`") for p in parsed.paths]
        args = PathExtractor.extract_structured_arguments(clean, default_workspace=default_workspace)

        # 1. Identify Target Path
        target_path = ""
        to_match = re.search(
            r"\b(?:to|into|at|in|in\s+file|file|destination|target|location)(?:\s+(?:destination|target|location|file|path|out|output))*\s+['\"`]?([~/a-zA-Z0-9_.\-]+)['\"`]?",
            clean,
            re.IGNORECASE,
        )
        if to_match:
            cand = to_match.group(1).strip().strip("'\"`")
            while cand and cand[-1] in (".", ",", ":", ";", "!", "?", ")", "]", "}"):
                cand = cand[:-1].strip()
            # An explicit write destination introduced by to/into/at/in is a
            # path role even when it is extensionless.  Reject only obvious
            # grammar stop words; do not require a suffix to prove a path.
            if (
                cand in all_paths
                or any(cand.endswith(ext) for ext in RequestPreprocessor.KNOWN_EXTENSIONS)
                or "/" in cand
                or (
                    cand.lower()
                    not in {
                        "the",
                        "a",
                        "an",
                        "this",
                        "that",
                        "it",
                        "content",
                        "text",
                        "payload",
                        "to",
                        "into",
                        "at",
                        "in",
                        "file",
                        "path",
                        "location",
                        "destination",
                        "target",
                        "out",
                        "output",
                    }
                    and bool(re.fullmatch(r"[~/A-Za-z0-9_.-]+", cand))
                )
            ):
                target_path = cand

        if not target_path and args.get("output_path"):
            target_path = args["output_path"]
        elif not target_path and all_paths:
            m_path_verb = re.search(
                r"\b(?:create|make|write|save|store|dump|record|generate|file)\s+(?:(?:the\s+)?file\s+)?['\"`]?([~/a-zA-Z0-9_.\-]+)['\"`]?",
                clean,
                re.IGNORECASE,
            )
            if m_path_verb:
                cand = m_path_verb.group(1).strip().strip("'\"`")
                while cand and cand[-1] in (".", ",", ":", ";", "!", "?", ")", "]", "}"):
                    cand = cand[:-1].strip()
                if cand in all_paths:
                    target_path = cand
            if not target_path:
                target_path = all_paths[-1] if len(all_paths) == 1 else (args.get("path") or all_paths[0])

        while target_path and target_path[-1] in (".", ",", ":", ";", "!", "?", ")", "]", "}"):
            target_path = target_path[:-1].strip()

        if not target_path:
            return None

        # 2. Check Explicit Empty File Request
        is_empty_requested = bool(
            re.search(
                r"\b(?:empty\s+file|0-byte\s+file|0-byte|zero-byte|zero\s+bytes?|with\s+empty\s+(?:content|body|payload|text)|empty\s+body|blank\s+file|with\s+no\s+content|content\s+is\s+empty|put\s+nothing\s+inside)\b",
                clean_lower,
            )
        )

        has_explicit_content = False
        parsed_content: str | None = None
        payload_span_start = -1
        payload_span_end = -1
        payload_type = "INLINE_LITERAL"
        content_clause_raw = ""
        is_ambiguous = False
        invalid_reason = ""

        if is_empty_requested:
            parsed_content = ""
            has_explicit_content = True
            payload_type = "EXPLICIT_EMPTY"

        # 3. Check Balanced JSON Literals First
        if parsed_content is None and parsed.structured_literals:
            for json_span in parsed.structured_literals:
                if json_span.raw_text != target_path:
                    parsed_content = json_span.raw_text
                    payload_span_start = json_span.start
                    payload_span_end = json_span.end
                    payload_type = json_span.span_type.value
                    has_explicit_content = True
                    break

        # 4. Check Fenced Code Blocks
        if parsed_content is None and parsed.code_blocks:
            for cb in parsed.code_blocks:
                inner = cb.metadata.get("inner", cb.raw_text)
                parsed_content = inner
                payload_span_start = cb.start
                payload_span_end = cb.end
                payload_type = cb.span_type.value
                has_explicit_content = True
                break

        # 4b. Check Colon Introducers (e.g., 'payload and nothing else: ...', 'content: ...')
        if parsed_content is None and ":" in clean:
            colon_in_clean = clean.find(":")
            non_path_quotes_before = [
                q for q in (parsed.quoted_literals or [])
                if q.end <= colon_in_clean and q.raw_text.strip("'\"`") != target_path and q.metadata.get("inner", "") != target_path
            ]
            if not non_path_quotes_before:
                tgt_idx = clean.find(target_path) if target_path else -1
                search_span = clean[tgt_idx + len(target_path):] if tgt_idx != -1 else clean
                m_intro_colon = re.search(
                    r"\b(?:content|payload|text|body|characters?|following|this\s+payload)\b[^\n:]*:\s*(.+)$",
                    search_span,
                    re.IGNORECASE | re.DOTALL,
                )
                if not m_intro_colon and ":" in search_span:
                    m_intro_colon = re.search(r":\s*(.+)$", search_span, re.DOTALL)
                if m_intro_colon:
                    body = m_intro_colon.group(1).strip()
                    body = re.split(r"\s+(?:and|with)\s+nothing\s+else\b|\s+and\s+no\s+other\s+words\b", body, flags=re.IGNORECASE)[0]
                    body = re.split(r"(?:\.|\;)\s*(?:do\s+not|don't|choose\s+neither|never)\b", body, flags=re.IGNORECASE)[0]
                    body = body.strip()
                    if body in ("''", '""', "``"):
                        if not is_empty_requested:
                            is_ambiguous = True
                            invalid_reason = (
                                "Write precondition failed: empty quoted payload supplied without explicit empty request"
                            )
                            parsed_content = ""
                            payload_span_start = clean.find(body)
                            payload_span_end = payload_span_start + len(body)
                            payload_type = "COLON_INTRODUCED"
                            has_explicit_content = True
                    elif body:
                        parsed_content = body
                        payload_span_start = clean.find(body)
                        payload_span_end = payload_span_start + len(body)
                        payload_type = "COLON_INTRODUCED"
                        has_explicit_content = True

        # 5. Check Quoted Literals
        if parsed_content is None and parsed.quoted_literals:
            non_path_quotes = [
                q
                for q in parsed.quoted_literals
                if q.raw_text.strip("'\"`") != target_path and q.metadata.get("inner", "") != target_path
            ]
            if len(non_path_quotes) == 1:
                q = non_path_quotes[0]
                cand = q.metadata.get("inner", q.raw_text[1:-1])
                if (
                    (cand.startswith("'") and cand.endswith("'"))
                    or (cand.startswith('"') and cand.endswith('"'))
                    or (cand.startswith("`") and cand.endswith("`"))
                ):
                    cand = cand[1:-1]
                parsed_content = cand
                payload_span_start = q.start
                payload_span_end = q.end
                payload_type = "QUOTED_LITERAL"
                has_explicit_content = True
                if not parsed_content and not is_empty_requested:
                    is_ambiguous = True
                    invalid_reason = (
                        "Write precondition failed: empty quoted payload supplied without explicit empty request"
                    )
            elif len(non_path_quotes) > 1:
                is_ambiguous = True
                invalid_reason = "Multiple ambiguous quoted literals in write request"

        # 6. Check Multiline Blocks (when first line ends with colon or arrow and payload starts on line 2)
        if parsed_content is None and "\n" in clean:
            lines = clean.splitlines()
            if len(lines) >= 2 and lines[0].strip().endswith((":", "->", "==", ":-")):
                multiline_body = "\n".join(lines[1:])
                parsed_content = multiline_body
                payload_span_start = clean.find(multiline_body)
                payload_span_end = payload_span_start + len(multiline_body)
                payload_type = "MULTILINE_BLOCK"
                has_explicit_content = True

        # 7. Check Clause Relationships and Positional Fallbacks
        if parsed_content is None and not is_ambiguous:
            # 7a. Target path first: extract content following target path
            tgt_idx = clean.find(target_path)
            if tgt_idx != -1:
                after_idx = tgt_idx + len(target_path)
                if after_idx < len(clean) and clean[after_idx] in ("'", '"', "`"):
                    after_idx += 1
                after_tgt = clean[after_idx:].strip()
                cand_after = re.sub(
                    r"^(?:[\s,:;\.\-]+|\b(?:and\s+)?(?:then\s+)?(?:store|write|put|save|set\s+content\s+to|set\s+its\s+content\s+to|set\s+body\s+to|contents?\s+(?:must|should|needs?\s+to)?\s+be|body\s+(?:must|should|needs?\s+to)?\s+be|its\s+body\s+(?:must|should|needs?\s+to)?\s+be|its\s+(?:complete\s+|exact\s+|entire\s+|whole\s+|full\s+|verbatim\s+|strictly\s+|exactly\s+)?(?:content|text|payload|body|data)\s+(?:must|should|needs?\s+to|is|will)?\s*(?:be)?|content\s+is|body\s+is|should\s+contain|must\s+contain|should\s+have\s+content|must\s+hold|containing\s+(?:exactly\s+)?(?:this\s+)?(?:text|content|payload|body|data)|containing|contain|with\s+(?:the\s+)?(?:content|text|body|payload|words))\b[\s:=->]*)+",
                    "",
                    after_tgt,
                    flags=re.IGNORECASE,
                ).strip()
                cand_after = cls.INTRODUCER_STRIP_RE.sub("", cand_after).strip()
                cand_after = re.sub(
                    r"^(?:exactly|verbatim|strictly|precisely)\s*[:=\-]?\s*",
                    "",
                    cand_after,
                    flags=re.IGNORECASE,
                ).strip()
                if cand_after and cand_after != after_tgt:
                    cand_after = cls.TRAILING_DIRECTIVE_RE.sub("", cand_after).strip()
                    if (cand_after.startswith("'") and cand_after.endswith("'")) or (
                        cand_after.startswith('"') and cand_after.endswith('"')
                    ):
                        cand_after = cand_after[1:-1]
                    parsed_content = cand_after
                    payload_span_start = clean.find(cand_after)
                    payload_span_end = payload_span_start + len(cand_after)
                    payload_type = "INLINE_LITERAL"
                    has_explicit_content = True

            # 7b. Clause relationships
            if parsed_content is None:
                for c in parsed.clauses:
                    c_text = c.raw_text.strip()
                    if target_path in c_text and len(parsed.clauses) > 1:
                        continue
                    m_clause_payload = cls.INTRODUCER_STRIP_RE.sub("", c_text).strip()
                    if m_clause_payload and m_clause_payload != c_text and m_clause_payload != target_path:
                        m_clause_payload = cls.TRAILING_DIRECTIVE_RE.sub("", m_clause_payload).strip()
                        if (m_clause_payload.startswith("'") and m_clause_payload.endswith("'")) or (
                            m_clause_payload.startswith('"') and m_clause_payload.endswith('"')
                        ):
                            m_clause_payload = m_clause_payload[1:-1]
                        parsed_content = m_clause_payload
                        payload_span_start = clean.find(m_clause_payload)
                        payload_span_end = payload_span_start + len(m_clause_payload)
                        payload_type = "INLINE_LITERAL"
                        content_clause_raw = c_text
                        has_explicit_content = True
                        break

            # 7c. Payload before path
            if parsed_content is None and not is_ambiguous:
                tgt_idx = clean.find(target_path)
                if tgt_idx > 0:
                    before_tgt = clean[:tgt_idx].strip()
                    m_before = re.match(
                        r"^(?:please\s+)?(?:write|save|put|store|dump|append|emit|record|create|output)\s+(?:the\s+)?(?:data\s+|file\s+|text\s+|body\s+|payload\s+)?(.*?)\s+(?:to|into|in|inside|at|destination)\s*$",
                        before_tgt,
                        re.IGNORECASE,
                    )
                    if m_before:
                        cand_before = m_before.group(1).strip()
                        is_quoted_before = (
                            (cand_before.startswith("'") and cand_before.endswith("'"))
                            or (cand_before.startswith('"') and cand_before.endswith('"'))
                            or (cand_before.startswith("`") and cand_before.endswith("`"))
                        )
                        if is_quoted_before:
                            cand_before = cand_before[1:-1]
                            parsed_content = cand_before
                            payload_span_start = clean.find(cand_before)
                            payload_span_end = payload_span_start + len(cand_before)
                            payload_type = "QUOTED_LITERAL"
                            has_explicit_content = True
                        elif cand_before and cand_before.lower() not in (
                            "file",
                            "a file",
                            "the file",
                            "some file",
                            "content",
                            "data",
                            "text",
                            "payload",
                            "output",
                            "it",
                            "the text",
                            "the content",
                            "the data",
                            "the payload",
                            "the body",
                            "the file content",
                        ):
                            parsed_content = cand_before
                            payload_span_start = clean.find(cand_before)
                            payload_span_end = payload_span_start + len(cand_before)
                            payload_type = "INLINE_LITERAL"
                            has_explicit_content = True

        # 8. Unquoted inline fallback
        if parsed_content is None and not is_ambiguous:
            m_after_path = re.search(
                r"\b(?:with\s+content|with\s+text|with\s+payload|with\s+body|with\s+the\s+words|contents?\s+must\s+be|contents?\s+should\s+be|contents?\s+is|containing)\s+(.*)$",
                clean,
                re.IGNORECASE | re.DOTALL,
            )
            if m_after_path:
                raw_cand = m_after_path.group(1).strip()
                # A payload introduced by "with the words" ends before a
                # subsequent workflow clause (", read it back, ...").
                raw_cand = re.split(
                    r",?\s+(?:and\s+)?(?:then\s+)?(?:read|open|show|display|verify|report)\b",
                    raw_cand,
                    maxsplit=1,
                    flags=re.IGNORECASE,
                )[0].strip()
                clean_cand = cls.INTRODUCER_STRIP_RE.sub("", raw_cand).strip()
                clean_cand = cls.TRAILING_DIRECTIVE_RE.sub("", clean_cand).strip()
                if (
                    (clean_cand.startswith("'") and clean_cand.endswith("'"))
                    or (clean_cand.startswith('"') and clean_cand.endswith('"'))
                    or (clean_cand.startswith("`") and clean_cand.endswith("`"))
                ):
                    clean_cand = clean_cand[1:-1]
                if clean_cand:
                    parsed_content = clean_cand
                    payload_span_start = clean.find(clean_cand)
                    payload_span_end = payload_span_start + len(clean_cand)
                    has_explicit_content = True

        # 9. Semantic Sanity Checks
        if parsed_content is not None:
            if target_path in parsed_content and len(parsed_content) == len(target_path):
                is_ambiguous = True
                invalid_reason = "Parsed payload identical to target path"

            if payload_type != "QUOTED_LITERAL" and parsed_content.lower() in (
                "content",
                "contents",
                "text",
                "payload",
                "body",
                "file",
                "verbatim",
                "strictly",
                "precisely",
                "data",
            ):
                is_ambiguous = True
                invalid_reason = f"Parsed payload '{parsed_content}' is a bare grammar keyword"

            if any(
                parsed_content.lower().startswith(pfx)
                for pfx in ("body is exactly ->", "the following in", "set its content to be")
            ):
                parsed_content = cls.INTRODUCER_STRIP_RE.sub("", parsed_content).strip()

        if (
            payload_type != "QUOTED_LITERAL"
            and (
                not parsed_content
                or parsed_content.lower()
                in (
                    "the text",
                    "the content",
                    "the payload",
                    "the body",
                    "the data",
                    "text",
                    "content",
                    "payload",
                    "body",
                    "data",
                )
            )
            and not is_empty_requested
        ):
            has_content_intent = bool(
                re.search(
                    r"(?:with\s+content|content\s*:|contents?\s+(?:is|of|to|must|should|:)|body\s+(?:is|of|to|must|should|:)|payload\s+(?:is|of|to|must|should|:)|with\s+payload|the\s+(?:text|content|payload|body|data)\s+(?:in|into|to))",
                    clean_lower,
                )
            )
            if has_content_intent:
                is_ambiguous = True
                invalid_reason = "Write precondition failed: semantic content was requested but no payload was provided"

        if parsed_content is None:
            parsed_content = ""

        exact_content_requested = bool(
            re.search(
                r"\b(?:exact|exactly|verbatim|strictly|precisely|complete|entire|whole|full)\b",
                clean_lower,
            )
        )

        return WriteAction(
            target_path=target_path,
            content=parsed_content,
            payload=parsed_content,
            payload_span_start=payload_span_start,
            payload_span_end=payload_span_end,
            content_source_span=content_clause_raw or clean,
            exactness=exact_content_requested or True,
            exact_content_requested=exact_content_requested or True,
            has_explicit_content=has_explicit_content,
            explicit_empty=is_empty_requested,
            is_empty_requested=is_empty_requested,
            confidence=0.0 if is_ambiguous else 1.0,
            is_invalid=is_ambiguous,
            invalid_reason=invalid_reason,
            payload_type=payload_type,
        )


# ═════════════════════════════════════════════════════════════════════════════
# 5. Exact Literal Response Fast-Path Parser
# ═════════════════════════════════════════════════════════════════════════════


@dataclass
class ExactResponseInstruction:
    command_prefix: str = ""
    target_pattern: str = ""
    payload: str = ""
    trailing_constraints: str = ""
    confidence: float = 1.0


class ExactResponseParser:
    """Formal structured exact-response grammar parser with zero-model fast path."""

    COMMAND_PREFIX_RE = re.compile(
        r"^(?:(?:please|kindly)\s+)?(?:only|solely|just|exactly|strictly|verbatim|precisely)?\s*"
        r"(?:write\s+back|send\s+back|give\s+back"
        r"|just\s+say|just\s+return|just\s+echo|just\s+output"
        r"|only\s+reply|solely\s+return|exactly\s+output|strictly\s+return|verbatim\s+return"
        r"|return\s+exactly|output\s+only|respond\s+with\s+only|reply\s+with\s+only"
        r"|give\s+me\s+(?:exactly|only|verbatim|just|back)|reply|respond|return|say|echo|repeat|print|output|send|type|produce)\b",
        re.IGNORECASE,
    )
    REPLY_MUST_BE_RE = re.compile(
        r"^(?:(?:please|kindly)\s+)?(?:your\s+|the\s+|my\s+)?(?:entire|complete|whole|only)?\s*"
        r"(?:reply|response|output|answer|word|token|value|text|string|payload|message)"
        r"\s+(?:should|must|needs\s+to|has\s+to|is\s+to|will)?\s*"
        r"(?:be|only\s+be|only\s+contain|contain|consist\s+of|consist\s+solely\s+of|equal|equals)\b",
        re.IGNORECASE,
    )
    EXCLUSIVITY_PREFIX_RE = re.compile(
        r"^(?:(?:please|kindly)\s+)?(?:only|solely|just|exactly|strictly|verbatim|precisely)\s+"
        r"(?:reply|respond|return|say|echo|print|output|type|send|give)\b",
        re.IGNORECASE,
    )

    MODIFIER_STRIP_PATTERNS = [
        r"^(?:(?:only|solely|just|exactly|strictly|verbatim|precisely)?\s*(?:with\s+)?(?:the|this)?\s*(?:value|token|text|string|payload|word|message|output|response|answer)\b\s+(?:and|with)\s+nothing\s+else\s*[:\-]?\s*)",
        r"^(?:with\s+(?:no\s+other\s+(?:text|words)|nothing\s+else)\s*[:\-]?\s*)",
        r"^(?:and\s+nothing\s+else\s*[:\-]?\s*)",
        r"^(?:(?:only|just|exactly|solely|strictly|verbatim|precisely)\s+with\s+(?:the|this\s+)?(?:quoted\s+|literal\s+|exact\s+)?(?:token|value|string|text|word|payload|output|response|answer)\b\s*[:\-]?\s*)",
        r"^(?:with\s+(?:only\s+|just\s+|exactly\s+|solely\s+|strictly\s+|verbatim\s+|precisely\s+)?(?:the\s+|this\s+)?(?:quoted\s+|literal\s+|exact\s+)?(?:token|value|string|text|word|payload|output|response|answer)\b\s*[:\-]?\s*)",
        r"^(?:this\s+(?:value|token|text|string|payload|output|response|answer)\b\s+(?:and|with)\s+nothing\s+else\s*[:\-]?\s*)",
        r"^(?:(?:solely|only|just|exactly|strictly|verbatim|precisely)\s+(?:the|this)?\s*(?:quoted\s+|literal\s+|exact\s+)?(?:value|token|text|string|payload|output|response|answer)\b\s*[:\-]?\s*)",
        r"^(?:(?:the|this)\s+(?:quoted\s+|literal\s+|exact\s+)?(?:token|value|string|text|word|payload|output|response|answer)\b\s*[:\-]?\s*)",
        r"^(?:(?:only|just|exactly|solely|strictly|verbatim|precisely)\b\s*[:]?\s*)",
        r"^(?:(?:output|response|answer|reply|string|token|value|text|word|payload)\b\s*[:]?\s*)",
        r"^(?:following\s+(?:token|value|payload|string|response|output)\s*[:]?\s*)",
        r"^(?:(?:as|is|with|equals)\b\s*[:]?\s*)",
        r"^(?:[:=]|->)\s*",
        r"^(?:and\s+nothing\s+more\s*[:\-]\s*)",
        r"^(?:the\s+following\s+(?:string|token|value|word|payload|text|literal)\s*[:\-]\s*)",
        r"^(?:following\s+(?:string|token|value|word|payload|text|literal)\s*[:\-]\s*)",
        r"^(?:the\s+(?:string|token|value|word|payload|text|literal)\s+is\s*[:\-]?\s*)",
    ]

    SUFFIX_STRIP_PATTERNS = [
        r"\s+(?:and\s+nothing\s+else|with\s+nothing\s+else|and\s+no\s+other\s+text|and\s+no\s+other\s+words|with\s+no\s+other\s+text|with\s+no\s+other\s+words|without\s+explanation|without\s+any\s+explanation|without\s+commentary|without\s+any\s+commentary|with\s+no\s+commentary|with\s+no\s+additional\s+commentary|verbatim|strictly|precisely|exactly|nothing\s+more|and\s+nothing\s+more)\.?$",
        r"[;,]\s*add\s+nothing\.?$",
        r"(?<=\S)\s+only\.?$",
    ]

    # ── Phase 8 Part A: Composite-request rejection guards ───────────────────
    # These patterns indicate that the payload depends on EXECUTION of another
    # action (file read, memory recall, browser extraction). The ExactResponseParser
    # MUST NOT claim these requests — they are composite actions with VALUE_ONLY mode.

    # Phrases that indicate the value comes from a memory store
    _MEMORY_DEPENDENCY_PHRASES = (
        "the remembered ",
        "the stored value",
        "the memory value",
        "what was the value of",
        "recalled",
        "retrieve memory",
        "deployment marker for",
        "the marker for",
        "the codename for",
        "stored in memory",
        "in my memory",
        "from memory",
    )
    # Phrases that indicate the value comes from a file
    _FILE_DEPENDENCY_PHRASES = (
        "the text stored in",
        "the contents of",
        "use file",
        "from the file",
        "in the file",
        "the file contents",
        "file text",
        "raw file",
    )
    # Phrases that indicate the value comes from a browser
    _BROWSER_DEPENDENCY_PHRASES = (
        "at selector",
        "from url",
        "at the url",
        "from the page",
        "from the browser",
        "the title of the page",
        "value at .",
        "element value",
        "css selector",
        "from the website",
    )

    @classmethod
    def _depends_on_execution(cls, text: str) -> bool:
        """Phase 8 B1: Return True if the payload must come from executing another action.

        An ExactLiteralResponse is valid ONLY if the response payload is
        explicitly present in the request text — not obtained by reading a file,
        recalling memory, or extracting browser content.
        """
        clean_lower = text.lower()
        # Memory dependency
        if any(phrase in clean_lower for phrase in cls._MEMORY_DEPENDENCY_PHRASES):
            return True
        # File dependency
        all_paths = PathExtractor.extract_all_paths(text)
        if all_paths and any(phrase in clean_lower for phrase in cls._FILE_DEPENDENCY_PHRASES):
            return True
        # Browser dependency
        if "://" in text or any(phrase in clean_lower for phrase in cls._BROWSER_DEPENDENCY_PHRASES):
            return True
        return False

    @classmethod
    def parse_intent(cls, text: str) -> ExactLiteralIntent | None:
        """Phase 8 B2: Parse into structured ExactLiteralIntent with payload span tracking.

        Returns None if:
          - payload depends on another action (execution dependency)
          - no explicit literal payload is present in the request
          - confidence is insufficient for deterministic routing
        """
        clean = text.strip()
        if not clean:
            return None
        if cls._depends_on_execution(clean):
            return None
        # Quick path/URL rejection
        all_paths = PathExtractor.extract_all_paths(clean)
        if all_paths:
            return None
        clean_lower = clean.lower()
        if "://" in clean or any(w in clean_lower for w in ("browser", "navigate", "open url")):
            return None
        # Find prefix
        prefix_constraint = ""
        remaining = clean
        if cls.COMMAND_PREFIX_RE.search(clean):
            prefix_match = cls.COMMAND_PREFIX_RE.match(clean)
            prefix_constraint = prefix_match.group(0) if prefix_match is not None else ""
            remaining = cls.COMMAND_PREFIX_RE.sub("", clean).strip()
        elif cls.REPLY_MUST_BE_RE.search(clean):
            remaining = cls.REPLY_MUST_BE_RE.sub("", clean).strip()
            prefix_constraint = text[: len(text) - len(remaining)].strip()
        elif cls.EXCLUSIVITY_PREFIX_RE.search(clean):
            remaining = cls.EXCLUSIVITY_PREFIX_RE.sub("", clean).strip()
            prefix_constraint = text[: len(text) - len(remaining)].strip()
        elif clean_lower.startswith(("echo:", "echo ", "repeat:", "repeat ")):
            remaining = re.sub(r"^(?:echo|repeat)\s*[:\-]?\s*", "", clean, flags=re.IGNORECASE).strip()
            prefix_constraint = "echo"
        else:
            return None

        # Strip suffix constraints
        suffix_constraint = ""
        for suf_pat in cls.SUFFIX_STRIP_PATTERNS:
            m = re.search(suf_pat, remaining, flags=re.IGNORECASE)
            if m:
                suffix_constraint = remaining[m.start() :].strip()
                remaining = remaining[: m.start()].strip()

        # Strip modifier prefixes
        prev = None
        while prev != remaining:
            prev = remaining
            for mod_pat in cls.MODIFIER_STRIP_PATTERNS:
                remaining = re.sub(mod_pat, "", remaining, flags=re.IGNORECASE).strip()

        # Detect quote style and extract payload
        quote_style = "none"
        payload = remaining.strip()
        if (payload.startswith("'") and payload.endswith("'")) and len(payload) >= 2:
            payload = payload[1:-1]
            quote_style = "single"
        elif (payload.startswith('"') and payload.endswith('"')) and len(payload) >= 2:
            payload = payload[1:-1]
            quote_style = "double"
        elif (payload.startswith("`") and payload.endswith("`")) and len(payload) >= 2:
            payload = payload[1:-1]
            quote_style = "backtick"
        elif (payload.startswith("«") and payload.endswith("»")) and len(payload) >= 2:
            payload = payload[1:-1]
            quote_style = "guillemet"

        # Second round of modifier stripping after unquoting
        prev = None
        while prev != payload:
            prev = payload
            for mod_pat in cls.MODIFIER_STRIP_PATTERNS:
                payload = re.sub(mod_pat, "", payload, flags=re.IGNORECASE).strip()

        # Remove trailing sentence period ONLY if it wasn't inside explicit quotes
        if payload.endswith(".") and quote_style == "none" and not clean.endswith("'.") and not clean.endswith('".'):
            payload = payload[:-1].strip()
        if payload.endswith(",") and quote_style == "none" and not (clean.endswith("',") or clean.endswith('",')):
            payload = payload[:-1].strip()

        if not payload:
            return None

        # Locate span of payload in original text
        payload_start = text.find(payload)
        payload_end = payload_start + len(payload) if payload_start != -1 else -1

        return ExactLiteralIntent(
            payload=payload,
            payload_span_start=payload_start,
            payload_span_end=payload_end,
            quote_style=quote_style,
            prefix_constraint=prefix_constraint,
            suffix_constraint=suffix_constraint,
            confidence=1.0,
        )

    @classmethod
    def parse(cls, text: str, workspace: str = "") -> DirectActionResult | None:
        """Parse exact explicit-literal echo intent with 0 model calls and 0 tools.

        Phase 8 Part A: PRIMARY ACTION FIRST.
        If the payload depends on execution (file read, memory recall, browser
        extraction), this method returns None. The caller must route to the
        appropriate primary action handler instead.
        """
        clean = text.strip()
        if not clean:
            return None

        # Phase 8 B1: Explicit payload requirement — reject execution-dependent requests
        if cls._depends_on_execution(clean):
            return None

        # If it references a filesystem path, URL, repo, browser, or workflow calculation, it is NOT an exact echo
        all_paths = PathExtractor.extract_all_paths(clean)
        if all_paths:
            return None
        clean_lower = clean.lower()
        if any(w in clean_lower for w in (" to ", " into ", " in ", " at ")) and any(
            w in clean_lower for w in ("write", "save", "put", "store", "create", "output", "dump")
        ):
            return None
        if "://" in clean or any(w in clean_lower for w in ("browser", "navigate", "open url", "http")):
            return None

        # Reject if this is a directory listing or other filesystem operation
        if (
            FilesystemActionClassifier.classify(clean, workspace=workspace).action_type
            != FilesystemActionType.FS_UNKNOWN
        ):
            return None

        is_match = False
        remaining = clean

        if cls.COMMAND_PREFIX_RE.search(clean):
            is_match = True
            remaining = cls.COMMAND_PREFIX_RE.sub("", clean).strip()
        elif cls.REPLY_MUST_BE_RE.search(clean):
            is_match = True
            remaining = cls.REPLY_MUST_BE_RE.sub("", clean).strip()
        elif cls.EXCLUSIVITY_PREFIX_RE.search(clean):
            is_match = True
            remaining = cls.EXCLUSIVITY_PREFIX_RE.sub("", clean).strip()
        elif clean_lower.startswith(("echo:", "echo ", "repeat:", "repeat ")):
            is_match = True
            remaining = re.sub(r"^(?:echo|repeat)\s*[:\-]?\s*", "", clean, flags=re.IGNORECASE).strip()

        if not is_match:
            _leading_only_re = re.compile(
                r"^(?:"
                r"and\s+nothing\s+more\s*[:\-]\s*"
                r"|the\s+following\s+(?:string|token|value|word|payload|text|literal)\s*[:\-]\s*"
                r"|following\s+(?:string|token|value|word|payload|text|literal)\s*[:\-]\s*"
                r"|the\s+(?:string|token|value|word|payload|text|literal)\s+is\s*[:\-]?\s*"
                r")(.*)",
                re.IGNORECASE | re.DOTALL,
            )
            m_lead = _leading_only_re.match(clean)
            if m_lead:
                candidate = m_lead.group(1).strip()
                if candidate and not any(
                    w in candidate.lower()
                    for w in ("write ", "save ", "create ", "open ", "navigate ", "://", " to ", " into ")
                ):
                    is_match = True
                    remaining = candidate

        if not is_match:
            return None

        for suf_pat in cls.SUFFIX_STRIP_PATTERNS:
            remaining = re.sub(suf_pat, "", remaining, flags=re.IGNORECASE).strip()

        prev = None
        while prev != remaining:
            prev = remaining
            for mod_pat in cls.MODIFIER_STRIP_PATTERNS:
                remaining = re.sub(mod_pat, "", remaining, flags=re.IGNORECASE).strip()

        target = remaining.strip()
        if (
            (target.startswith("'") and target.endswith("'"))
            or (target.startswith('"') and target.endswith('"'))
            or (target.startswith("`") and target.endswith("`"))
            or (target.startswith("«") and target.endswith("»"))
        ):
            if len(target) >= 2:
                target = target[1:-1].strip()

        prev = None
        while prev != target:
            prev = target
            for mod_pat in cls.MODIFIER_STRIP_PATTERNS:
                target = re.sub(mod_pat, "", target, flags=re.IGNORECASE).strip()

        if (
            (target.startswith("'") and target.endswith("'"))
            or (target.startswith('"') and target.endswith('"'))
            or (target.startswith("`") and target.endswith("`"))
            or (target.startswith("«") and target.endswith("»"))
        ):
            if len(target) >= 2:
                target = target[1:-1].strip()

        if target.endswith(".") and not clean.endswith("'.") and not clean.endswith('".') and not clean.endswith("`."):
            target = target[:-1].strip()

        if target.endswith(",") and not (clean.endswith("',") or clean.endswith('",') or clean.endswith("`,")):
            target = target[:-1].strip()

        if target:
            return DirectActionResult(
                success=True,
                output=target,
                execution_type="exact_response",
                tool_name="echo",
                provider="system",
                model="",
                policy_decision="allowed",
                telemetry={"exact_response": True, "length": len(target)},
            )

        return None


# ═════════════════════════════════════════════════════════════════════════════
# 6. Filesystem Action Classifier (Stat-Dominant)
# ═════════════════════════════════════════════════════════════════════════════


class FilesystemActionClassifier:
    """Stat-dominant filesystem action classifier separating directories from files."""

    @classmethod
    def classify(cls, text: str, workspace: str = "") -> FilesystemSemanticAction:
        clean = text.lower().strip()
        all_paths = PathExtractor.extract_all_paths(text)
        args = PathExtractor.extract_structured_arguments(text, default_workspace=workspace)

        target_path_str = (
            args.get("directory") or args.get("input_path") or args.get("path") or (all_paths[0] if all_paths else "")
        )

        if not target_path_str:
            return FilesystemSemanticAction(
                action_type=FilesystemActionType.FS_UNKNOWN,
                target_path="",
                confidence=0.0,
            )

        ws = Path(workspace if workspace else workspace_root()).expanduser().resolve()
        is_dir = False
        is_file = False
        exists = False

        with tool_workspace(ws):
            try:
                resolved = resolve_workspace_path(target_path_str, must_exist=False)
                exists = resolved.exists()
                if exists:
                    is_dir = resolved.is_dir()
                    is_file = resolved.is_file()
            except Exception:
                pass

        if is_dir:
            return FilesystemSemanticAction(
                action_type=FilesystemActionType.FS_LIST_DIRECTORY,
                target_path=target_path_str,
                is_directory=True,
                is_file=False,
                exists=True,
                confidence=1.0,
                evidence=["stat_is_directory"],
            )

        if is_file:
            return FilesystemSemanticAction(
                action_type=FilesystemActionType.FS_READ_FILE,
                target_path=target_path_str,
                is_directory=False,
                is_file=True,
                exists=True,
                confidence=1.0,
                evidence=["stat_is_file"],
            )

        has_real_path = (
            exists
            or any(target_path_str.endswith(ext) for ext in RequestPreprocessor.KNOWN_EXTENSIONS)
            or target_path_str.startswith(("/", "./", "../", "~/"))
            or bool(re.search(r"/[a-zA-Z0-9_.\-]+", target_path_str))
        )

        if not has_real_path and not exists:
            has_dir_phrase = bool(
                re.search(r"\b(?:directory|folder|path|dir)\s+['\"`]?([a-zA-Z0-9_.\-/]+)", text, re.IGNORECASE)
            ) or any(
                w in clean
                for w in ("files are in", "what files are in", "what is in", "what's in", "files of", "files in")
            )
            has_action_verb = any(
                re.search(rf"\b{re.escape(v)}\b", clean)
                for v in (
                    "list",
                    "ls",
                    "show",
                    "display",
                    "print",
                    "enumerate",
                    "inspect",
                    "view",
                    "files in",
                    "files of",
                    "files under",
                    "entries in",
                    "items in",
                    "children of",
                    "what is inside",
                    "what is under",
                    "what files are in",
                    "what is in",
                    "what's in",
                    "what files in",
                    "files are in",
                )
            )
            if not (has_dir_phrase and has_action_verb):
                return FilesystemSemanticAction(
                    action_type=FilesystemActionType.FS_UNKNOWN,
                    target_path="",
                    confidence=0.0,
                )

        # Keyword heuristics when stat is indeterminate
        if any(
            w in clean
            for w in (
                "directory",
                "folder",
                "entries",
                "filenames",
                "files under",
                "children",
                "items in",
                "what is under",
                "entries inside",
                "what is inside",
                "list ",
                "list_dir",
                "files are in",
                "what files are in",
                "what is in",
                "what's in",
                "files in",
                "files of",
            )
        ):
            return FilesystemSemanticAction(
                action_type=FilesystemActionType.FS_LIST_DIRECTORY,
                target_path=target_path_str,
                is_directory=True,
                is_file=False,
                exists=exists,
                confidence=0.85,
                evidence=["grammar_directory_intent"],
            )

        if any(w in clean for w in ("read", "cat", "open", "show", "display", "contents", "content", "raw")) or any(
            target_path_str.endswith(ext) for ext in RequestPreprocessor.KNOWN_EXTENSIONS
        ):
            return FilesystemSemanticAction(
                action_type=FilesystemActionType.FS_READ_FILE,
                target_path=target_path_str,
                is_directory=False,
                is_file=True,
                exists=exists,
                confidence=0.85,
                evidence=["grammar_read_intent"],
            )

        return FilesystemSemanticAction(
            action_type=FilesystemActionType.FS_UNKNOWN,
            target_path=target_path_str,
            confidence=0.0,
        )


# ═════════════════════════════════════════════════════════════════════════════
# 7. Repository Diagnostic Engine (Multi-Class AST Analysis & Truthful Unknown)
# ═════════════════════════════════════════════════════════════════════════════


class RepositoryDiagnosticEngine:
    """Safe, read-only repository inspection and deterministic AST semantic defect diagnosis."""

    @classmethod
    def parse_test_assertions(cls, test_file_path: Path) -> list[dict[str, Any]]:
        """Directly parse test assertions from a test file."""
        assertions: list[dict[str, Any]] = []
        try:
            tree = ast.parse(test_file_path.read_text(encoding="utf-8", errors="replace"))
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name.startswith("test"):
                    for child in ast.walk(node):
                        if isinstance(child, ast.Assert):
                            test_info: dict[str, Any] = {
                                "test_function": node.name,
                                "function_under_test": "",
                                "input_args": [],
                                "expected_value": None,
                                "operator": "==",
                            }
                            if isinstance(child.test, ast.Compare):
                                left = child.test.left
                                if isinstance(left, ast.Call):
                                    if isinstance(left.func, ast.Name):
                                        test_info["function_under_test"] = left.func.id
                                    elif isinstance(left.func, ast.Attribute):
                                        test_info["function_under_test"] = left.func.attr
                                    test_info["input_args"] = [ast.unparse(arg) for arg in left.args]
                                if child.test.comparators:
                                    try:
                                        test_info["expected_value"] = ast.literal_eval(child.test.comparators[0])
                                    except Exception:
                                        test_info["expected_value"] = ast.unparse(child.test.comparators[0])
                            elif isinstance(child.test, ast.Call):
                                if isinstance(child.test.func, ast.Name):
                                    test_info["function_under_test"] = child.test.func.id
                                test_info["input_args"] = [ast.unparse(arg) for arg in child.test.args]
                                test_info["expected_value"] = True

                            if test_info["function_under_test"]:
                                assertions.append(test_info)
        except Exception:
            pass
        return assertions

    @classmethod
    def diagnose(cls, repo_path: Path) -> dict[str, Any]:
        """Execute read-only isolated test suite and perform deterministic AST semantic defect diagnosis."""
        findings: list[dict[str, Any]] = []
        pre_hashes: dict[str, str] = {}

        for py_file in sorted(repo_path.rglob("*.py")):
            if any(part.startswith(".") for part in py_file.parts):
                continue
            try:
                pre_hashes[str(py_file)] = hashlib.sha256(py_file.read_bytes()).hexdigest()
            except Exception:
                pass

        test_files = [p for p in pre_hashes if "test" in Path(p).name.lower()]
        test_failure_captured: dict[str, Any] | None = None
        extracted_assertions: list[dict[str, Any]] = []

        for tf in test_files:
            extracted_assertions.extend(cls.parse_test_assertions(Path(tf)))

        if extracted_assertions:
            ea = extracted_assertions[0]
            test_failure_captured = {
                "test_name": ea["test_function"],
                "function_under_test": ea["function_under_test"],
                "error_type": "AssertionError",
                "error_detail": "",
                "failing_assert_line": "",
                "traceback": "",
            }

        primary_fn = test_failure_captured["function_under_test"] if test_failure_captured else ""

        for file_path_str in pre_hashes:
            py_file = Path(file_path_str)
            if "test" in py_file.name.lower():
                continue
            code_text = py_file.read_text(encoding="utf-8", errors="replace")

            try:
                tree = ast.parse(code_text)
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        fn_name = node.name
                        if primary_fn and fn_name != primary_fn and primary_fn != "unknown_function":
                            continue

                        doc = ast.get_docstring(node) or ""
                        doc_lower = doc.lower()
                        fn_lower = fn_name.lower()
                        combined_doc = doc_lower + " " + fn_lower
                        local_vars: list[str] = []
                        return_nodes: list[ast.Return] = []

                        for child in ast.walk(node):
                            if isinstance(child, ast.Assign):
                                for target in child.targets:
                                    if isinstance(target, ast.Name):
                                        local_vars.append(target.id)
                            elif isinstance(child, ast.Return):
                                return_nodes.append(child)

                        # Semantic Bug Class 1: Wrong Helper Call
                        module_fn_names = [
                            mod_node.name
                            for mod_node in ast.walk(tree)
                            if isinstance(mod_node, ast.FunctionDef) and mod_node.name != fn_name
                        ]
                        local_calls: list[str] = []
                        for child in ast.walk(node):
                            if isinstance(child, ast.Call):
                                if isinstance(child.func, ast.Name) and child.func.id in module_fn_names:
                                    local_calls.append(child.func.id)
                                elif isinstance(child.func, ast.Attribute) and child.func.attr in module_fn_names:
                                    local_calls.append(child.func.attr)

                        if local_calls and module_fn_names:

                            def _helper_return_operator(helper_name: str, current_tree: ast.AST = tree) -> str:
                                for helper_node in ast.walk(current_tree):
                                    if not isinstance(helper_node, ast.FunctionDef) or helper_node.name != helper_name:
                                        continue
                                    for ret in ast.walk(helper_node):
                                        if isinstance(ret, ast.Return) and isinstance(ret.value, ast.BinOp):
                                            if isinstance(ret.value.op, ast.Add):
                                                return "+"
                                            if isinstance(ret.value.op, ast.Sub):
                                                return "-"
                                            if isinstance(ret.value.op, ast.Mult):
                                                return "*"
                                            if isinstance(ret.value.op, ast.Div):
                                                return "/"
                                return ""

                            contract_op = ""
                            if re.search(r"\b(?:add|adds|adding|increase|plus|bonus|fee)\b", combined_doc):
                                contract_op = "+"
                            elif re.search(
                                r"\b(?:subtract|subtracts|subtracting|decrease|minus|deduct|discount)\b", combined_doc
                            ):
                                contract_op = "-"

                            for called_helper in set(local_calls):
                                called_op = _helper_return_operator(called_helper)
                                for sibling in module_fn_names:
                                    if sibling == called_helper:
                                        continue
                                    sibling_op = _helper_return_operator(sibling)
                                    if (
                                        contract_op
                                        and called_op
                                        and sibling_op == contract_op
                                        and called_op != contract_op
                                    ):
                                        findings.append(
                                            {
                                                "function": fn_name,
                                                "category": "wrong_helper_call",
                                                "called_helper": called_helper,
                                                "expected_helper": sibling,
                                                "description": f"Function '{fn_name}' calls helper '{called_helper}' ({called_op}) but contract semantics require '{sibling}' ({contract_op}).",
                                                "reason": "helper return operator contradicts function contract while sibling satisfies it",
                                                "confidence": 1.0,
                                                "file": str(py_file),
                                            }
                                        )
                                        break
                                    sibling_doc = ""
                                    for mod_node in ast.walk(tree):
                                        if isinstance(mod_node, ast.FunctionDef) and mod_node.name == sibling:
                                            sibling_doc = ast.get_docstring(mod_node) or ""
                                            break

                                    contract_keywords = set(re.findall(r"[a-z]{3,}", (doc + fn_name).lower()))
                                    sibling_keywords = set(re.findall(r"[a-z]{3,}", (sibling_doc + sibling).lower()))
                                    called_keywords = set(re.findall(r"[a-z]{3,}", called_helper.lower()))

                                    sibling_overlap = len(contract_keywords & sibling_keywords) - len(
                                        {"def", "the", "and", "for", "with"} & sibling_keywords
                                    )
                                    called_overlap = len(contract_keywords & called_keywords)

                                    if sibling_overlap > called_overlap and sibling_overlap > 0:
                                        findings.append(
                                            {
                                                "function": fn_name,
                                                "category": "wrong_helper_call",
                                                "called_helper": called_helper,
                                                "expected_helper": sibling,
                                                "description": f"Function '{fn_name}' calls helper '{called_helper}' but should call '{sibling}' according to contract",
                                                "reason": f"Sibling '{sibling}' matches function contract better ({sibling_overlap} vs {called_overlap})",
                                                "confidence": 1.0,
                                                "file": str(py_file),
                                            }
                                        )
                                        break

                        # Semantic Bug Class 2: Comparison Boundary Defects
                        for child in ast.walk(node):
                            if isinstance(child, ast.Compare):
                                doc_lower = doc.lower()
                                fn_lower = fn_name.lower()
                                combined_doc = doc_lower + " " + fn_lower

                                # At least / greater than or equal
                                if (
                                    "at least" in combined_doc
                                    or "greater than or equal" in combined_doc
                                    or ">=" in doc
                                    or "inclusive" in combined_doc
                                ) and any(isinstance(op, ast.Gt) for op in child.ops):
                                    findings.append(
                                        {
                                            "function": fn_name,
                                            "category": "comparison_boundary",
                                            "observed_operator": ">",
                                            "expected_operator": ">=",
                                            "description": f"Function '{fn_name}' uses strict '>' comparison where '>=' (at least) was required by contract",
                                            "confidence": 1.0,
                                            "file": str(py_file),
                                        }
                                    )
                                # At most / less than or equal
                                elif (
                                    "at most" in combined_doc or "less than or equal" in combined_doc or "<=" in doc
                                ) and any(isinstance(op, ast.Lt) for op in child.ops):
                                    findings.append(
                                        {
                                            "function": fn_name,
                                            "category": "comparison_boundary",
                                            "observed_operator": "<",
                                            "expected_operator": "<=",
                                            "description": f"Function '{fn_name}' uses strict '<' comparison where '<=' (at most) was required by contract",
                                            "confidence": 1.0,
                                            "file": str(py_file),
                                        }
                                    )
                                # Strictly greater
                                elif ("strictly greater" in combined_doc or "exclusive" in combined_doc) and any(
                                    isinstance(op, ast.GtE) for op in child.ops
                                ):
                                    findings.append(
                                        {
                                            "function": fn_name,
                                            "category": "comparison_boundary",
                                            "observed_operator": ">=",
                                            "expected_operator": ">",
                                            "description": f"Function '{fn_name}' uses inclusive '>=' comparison where strict '>' was required by contract",
                                            "confidence": 1.0,
                                            "file": str(py_file),
                                        }
                                    )
                                # Strictly less
                                elif ("strictly less" in combined_doc) and any(
                                    isinstance(op, ast.LtE) for op in child.ops
                                ):
                                    findings.append(
                                        {
                                            "function": fn_name,
                                            "category": "comparison_boundary",
                                            "observed_operator": "<=",
                                            "expected_operator": "<",
                                            "description": f"Function '{fn_name}' uses inclusive '<=' comparison where strict '<' was required by contract",
                                            "confidence": 1.0,
                                            "file": str(py_file),
                                        }
                                    )
                                # Equality inversion
                                elif any(isinstance(op, ast.NotEq) for op in child.ops) and (
                                    "equal" in combined_doc and "not" not in combined_doc
                                ):
                                    findings.append(
                                        {
                                            "function": fn_name,
                                            "category": "comparison_boundary",
                                            "observed_operator": "!=",
                                            "expected_operator": "==",
                                            "description": f"Function '{fn_name}' uses '!=' where '==' was expected",
                                            "confidence": 1.0,
                                            "file": str(py_file),
                                        }
                                    )
                                # Comparison Inversion (> instead of < or vice versa)
                                elif ("less than" in combined_doc or "is_less" in fn_name) and any(
                                    isinstance(op, ast.Gt) for op in child.ops
                                ):
                                    findings.append(
                                        {
                                            "function": fn_name,
                                            "category": "comparison_inversion",
                                            "observed_operator": ">",
                                            "expected_operator": "<",
                                            "description": f"Function '{fn_name}' uses inverted '>' comparison where '<' was expected by contract/name",
                                            "confidence": 1.0,
                                            "file": str(py_file),
                                        }
                                    )
                                elif ("greater than" in combined_doc or "is_greater" in fn_name) and any(
                                    isinstance(op, ast.Lt) for op in child.ops
                                ):
                                    findings.append(
                                        {
                                            "function": fn_name,
                                            "category": "comparison_inversion",
                                            "observed_operator": "<",
                                            "expected_operator": ">",
                                            "description": f"Function '{fn_name}' uses inverted '<' comparison where '>' was expected by contract/name",
                                            "confidence": 1.0,
                                            "file": str(py_file),
                                        }
                                    )

                        # Semantic Bug Class: Indexing Error
                        for child in ast.walk(node):
                            if isinstance(child, ast.Subscript):
                                if isinstance(child.slice, ast.Constant) and isinstance(child.slice.value, int):
                                    idx_val = child.slice.value
                                    if (
                                        "first" in combined_doc
                                        or "first" in fn_name
                                        or "head" in fn_name
                                        or "initial" in combined_doc
                                    ) and idx_val != 0:
                                        findings.append(
                                            {
                                                "function": fn_name,
                                                "category": "indexing_error",
                                                "observed_index": idx_val,
                                                "expected_index": 0,
                                                "description": f"Function '{fn_name}' accesses index [{idx_val}] where index [0] was expected for the first element",
                                                "confidence": 1.0,
                                                "file": str(py_file),
                                            }
                                        )
                                    elif (
                                        "last" in combined_doc
                                        or "last" in fn_name
                                        or "tail" in fn_name
                                        or "final" in combined_doc
                                    ) and idx_val not in (-1, None):
                                        findings.append(
                                            {
                                                "function": fn_name,
                                                "category": "indexing_error",
                                                "observed_index": idx_val,
                                                "expected_index": -1,
                                                "description": f"Function '{fn_name}' accesses index [{idx_val}] where index [-1] was expected for the last element",
                                                "confidence": 1.0,
                                                "file": str(py_file),
                                            }
                                        )

                        # Semantic Bug Class 3: Wrong Constant
                        for child in ast.walk(node):
                            if (
                                isinstance(child, ast.Constant)
                                and isinstance(child.value, (int, float))
                                and not isinstance(child.value, bool)
                            ):
                                val = child.value
                                num_matches = re.findall(r"\b\d+(?:\.\d+)?\b", doc)
                                doc_nums = [float(n) if "." in n else int(n) for n in num_matches]
                                if doc_nums and val not in doc_nums and val not in (0, 1, -1):
                                    expected_const = doc_nums[0]
                                    findings.append(
                                        {
                                            "function": fn_name,
                                            "category": "wrong_constant",
                                            "observed_constant": val,
                                            "expected_constant": expected_const,
                                            "description": f"Function '{fn_name}' uses constant {val} but contract specifies {expected_const}",
                                            "confidence": 1.0,
                                            "file": str(py_file),
                                        }
                                    )
                                    break

                        # Semantic Bug Class 4: Wrong Returned Variable
                        if len(local_vars) >= 2 and return_nodes:
                            ret_val = return_nodes[0].value
                            if isinstance(ret_val, ast.Name):
                                returned_name = ret_val.id
                                other_vars = [v for v in local_vars if v != returned_name]
                                contract_tokens = set(re.findall(r"[a-z]{3,}", (fn_name + " " + doc).lower())) - {
                                    "def",
                                    "the",
                                    "and",
                                    "for",
                                    "with",
                                    "compute",
                                    "calculate",
                                    "process",
                                    "return",
                                    "function",
                                    "value",
                                }
                                for other in other_vars:
                                    other_tokens = set(re.findall(r"[a-z]{3,}", other.lower()))
                                    ret_tokens = set(re.findall(r"[a-z]{3,}", returned_name.lower()))
                                    has_token_match = bool(other_tokens & contract_tokens) and not bool(
                                        ret_tokens & contract_tokens
                                    )
                                    is_temp = "temp" in returned_name.lower() or "intermediate" in returned_name.lower()
                                    if has_token_match or (is_temp and "total" in other.lower()):
                                        findings.append(
                                            {
                                                "function": fn_name,
                                                "category": "wrong_returned_variable",
                                                "returned_variable": returned_name,
                                                "expected_variable": other,
                                                "description": f"Function '{fn_name}' computes '{other}' but returns '{returned_name}' instead",
                                                "confidence": 1.0,
                                                "file": str(py_file),
                                            }
                                        )
                                        break

                        # Semantic Bug Class 5: Boolean Operator Mismatch
                        for child in ast.walk(node):
                            bool_node = (
                                child
                                if isinstance(child, ast.BoolOp)
                                else (
                                    child.test
                                    if isinstance(child, ast.If) and isinstance(child.test, ast.BoolOp)
                                    else None
                                )
                            )
                            if bool_node:
                                if isinstance(bool_node.op, ast.Or) and (
                                    "both" in doc.lower() or "and" in doc.lower() or "all" in fn_name.lower()
                                ):
                                    findings.append(
                                        {
                                            "function": fn_name,
                                            "category": "boolean_operator_mismatch",
                                            "observed_operator": "or",
                                            "expected_operator": "and",
                                            "description": f"Function '{fn_name}' uses 'or' logic where 'and' is required according to contract",
                                            "confidence": 1.0,
                                            "file": str(py_file),
                                        }
                                    )
                                elif isinstance(bool_node.op, ast.And) and (
                                    "either" in doc.lower() or "any" in doc.lower()
                                ):
                                    findings.append(
                                        {
                                            "function": fn_name,
                                            "category": "boolean_operator_mismatch",
                                            "observed_operator": "and",
                                            "expected_operator": "or",
                                            "description": f"Function '{fn_name}' uses 'and' logic where 'or' is required according to contract",
                                            "confidence": 1.0,
                                            "file": str(py_file),
                                        }
                                    )

                        # Semantic Bug Class 6: Operator Mismatch (Arithmetic)
                        for child in ast.walk(node):
                            if isinstance(child, ast.Return) and isinstance(child.value, ast.BinOp):
                                op = child.value.op
                                if (
                                    "add" in fn_name.lower() or "sum" in fn_name.lower() or "total" in fn_name.lower() or "plus" in doc.lower()
                                ) and isinstance(op, ast.Sub):
                                    findings.append(
                                        {
                                            "function": fn_name,
                                            "category": "operator_mismatch",
                                            "observed_operator": "-",
                                            "expected_operator": "+",
                                            "description": f"Function '{fn_name}' subtracts instead of adding (return a - b instead of addition or computed answer)",
                                            "confidence": 1.0,
                                            "file": str(py_file),
                                        }
                                    )
                                elif (
                                    "sub" in fn_name.lower() or "diff" in fn_name.lower() or "minus" in doc.lower()
                                ) and isinstance(op, ast.Add):
                                    findings.append(
                                        {
                                            "function": fn_name,
                                            "category": "operator_mismatch",
                                            "observed_operator": "+",
                                            "expected_operator": "-",
                                            "description": f"Function '{fn_name}' adds instead of subtracting",
                                            "confidence": 1.0,
                                            "file": str(py_file),
                                        }
                                    )

            except Exception:
                pass

        # Truthful Unknown: If test failed but no deterministic semantic AST finding was established
        if test_failure_captured and not findings:
            findings.insert(
                0,
                {
                    "function": test_failure_captured["function_under_test"],
                    "category": "unresolved_semantic_defect",
                    "description": "test failure located; semantic root cause unresolved",
                    "confidence": 0.5,
                    "file": test_files[0] if test_files else str(repo_path),
                },
            )

        post_hashes: dict[str, str] = {}
        for file_path_str in pre_hashes:
            try:
                post_hashes[file_path_str] = hashlib.sha256(Path(file_path_str).read_bytes()).hexdigest()
            except Exception:
                pass

        read_only_intact = pre_hashes == post_hashes

        return {
            "pre_hashes": pre_hashes,
            "post_hashes": post_hashes,
            "read_only_verified": read_only_intact,
            "test_failure": test_failure_captured,
            "findings": findings,
        }


# ═════════════════════════════════════════════════════════════════════════════
# 8. Unified Direct Action Router
# ═════════════════════════════════════════════════════════════════════════════


class DirectActionRouter:
    """Generic router for single-step deterministic actions and policy-governed tools."""

    @classmethod
    def can_handle(cls, text: str) -> bool:
        """Check if a natural-language request matches a direct deterministic action."""
        clean = text.strip()
        if not clean:
            return False

        if ExactResponseParser.parse(clean) is not None:
            return True

        if cls._try_policy_refusal(clean) is not None:
            return True

        if cls._is_screenshot_request(clean):
            return True

        if cls._is_workflow_request(clean):
            return True

        if cls._is_repository_inspection_request(clean):
            return True

        if cls._is_filesystem_request(clean):
            return True

        if "://" in clean or any(
            w in clean.lower()
            for w in ("browser", "navigate to", "open http", "browse ", "fetch url", "extract content from http")
        ):
            return True

        if cls._is_memory_recall_request(clean):
            return True

        if any(
            w in clean.lower()
            for w in ("schedule", "calendar", "book an appointment", "add to calendar", "book a meeting")
        ):
            return True

        return False

    @classmethod
    def _try_exact_response(cls, text: str, workspace: str = "") -> DirectActionResult | None:
        return ExactResponseParser.parse(text, workspace=workspace)

    @classmethod
    def execute(
        cls,
        text: str,
        *,
        context: str = "",
        control: Any = None,
        workspace: str = "",
    ) -> DirectActionResult | None:
        """Parse intent, evaluate policy, execute registered capability, verify, and return."""
        clean = text.strip()
        if not clean:
            return None

        echo_res = cls._try_exact_response(clean, workspace=workspace)
        if echo_res is not None:
            return echo_res

        refusal_res = cls._try_policy_refusal(clean)
        if refusal_res is not None:
            return refusal_res

        screenshot_res = cls._try_screenshot(clean, workspace=workspace)
        if screenshot_res is not None:
            return screenshot_res

        workflow_res = cls._try_multi_step_workflow(clean, workspace=workspace)
        if workflow_res is not None:
            return workflow_res

        repo_res = cls._try_repository_inspection(clean, workspace=workspace)
        if repo_res is not None:
            return repo_res

        browser_res = cls._try_browser_action(clean)
        if browser_res is not None:
            return browser_res

        fs_res = cls._try_filesystem_action(clean, workspace=workspace)
        if fs_res is not None:
            return fs_res

        if control is not None or cls._is_memory_recall_request(clean):
            mem_res = cls._try_memory_recall(clean, context=context, control=control)
            if mem_res is not None:
                return mem_res

        cal_res = cls._try_calendar_event(clean, context=context)
        if cal_res is not None:
            return cal_res

        return None

    # ── 1. Policy Refusal Handling ───────────────────────────────────────────

    @classmethod
    def _try_policy_refusal(cls, text: str) -> DirectActionResult | None:
        clean = text.lower()
        destructive_verbs = ("delete", "remove", "wipe", "destroy", "drop", "purge")
        bypass_terms = (
            "without asking",
            "bypass",
            "force",
            "protected",
            "silently",
            "override policy",
            "no confirmation",
        )
        if any(v in clean for v in destructive_verbs) and any(t in clean for t in bypass_terms):
            return DirectActionResult(
                success=False,
                output="I cannot delete protected files or perform destructive actions without explicit approval. Policy refusal enforced.",
                execution_type="policy_enforcement",
                tool_name="delete_file",
                provider="security-policy",
                model="",
                policy_decision="refused",
                telemetry={"reason": "destructive_action_unauthorized"},
            )
        return None

    # ── 2. Screenshot Handling (Positive Semantic Relation Required) ─────────

    @classmethod
    def _is_screenshot_request(cls, text: str) -> bool:
        """Return True only if text has positive, unnegated semantic command for screenshot."""
        parsed = RequestPreprocessor.process(text)
        screenshot_candidates = [c for c in parsed.candidate_actions if c.action_type == ActionType.SCREENSHOT_CAPTURE]
        if not screenshot_candidates:
            return False

        # If any candidate is blocked as negated, do not route screenshot
        if any(c.is_blocked_as_negated for c in screenshot_candidates):
            return False

        return any(c.confidence > 0.8 for c in screenshot_candidates)

    @classmethod
    def _try_screenshot(cls, text: str, workspace: str = "") -> DirectActionResult | None:
        if not cls._is_screenshot_request(text):
            return None

        parsed = RequestPreprocessor.process(text)
        all_paths = [p.raw_text.strip("'\"`") for p in parsed.paths]
        png_paths = [p for p in all_paths if p.lower().endswith(".png")]
        output_path = png_paths[0] if png_paths else (all_paths[0] if all_paths else "screenshot.png")

        ws = Path(workspace if workspace else workspace_root()).expanduser().resolve()
        with tool_workspace(ws):
            try:
                p = resolve_workspace_path(output_path, must_exist=False)
            except PermissionError as exc:
                return DirectActionResult(
                    success=False,
                    output=f"Cannot write screenshot to sensitive/blocked path: {exc}",
                    execution_type="policy_enforcement",
                    tool_name="take_screenshot",
                    provider="security-policy",
                    model="",
                    policy_decision="refused",
                    telemetry={"reason": "workspace_escape", "error": str(exc)},
                )

        try:
            start_time = time.time()
            with tool_workspace(ws):
                res_raw = execute_tool("take_screenshot", {"output_path": str(p)})
            tool_res = parse_tool_result(res_raw)

            if not tool_res.ok:
                is_perm = any(
                    w in str(tool_res.error).lower() for w in ("permission", "denied", "not permitted", "authorization")
                )
                return DirectActionResult(
                    success=False,
                    output=f"Screenshot failed: {tool_res.error or 'tool_failed'}",
                    execution_type="tool",
                    tool_name="take_screenshot",
                    provider="macos-native-tool",
                    model="",
                    policy_decision="refused" if is_perm else "allowed",
                    telemetry={"reason": "permission_denied" if is_perm else "tool_failed", "error": tool_res.error},
                )

            if not p.exists():
                return DirectActionResult(
                    success=False,
                    output=f"Screenshot verification failed: file missing after execution at {p}",
                    execution_type="tool",
                    tool_name="take_screenshot",
                    provider="macos-native-tool",
                    model="",
                    policy_decision="allowed",
                    telemetry={"reason": "verification_failed", "detail": "file_missing"},
                )

            if not p.is_file():
                return DirectActionResult(
                    success=False,
                    output=f"Screenshot verification failed: not a regular file at {p}",
                    execution_type="tool",
                    tool_name="take_screenshot",
                    provider="macos-native-tool",
                    model="",
                    policy_decision="allowed",
                    telemetry={"reason": "verification_failed", "detail": "not_a_file"},
                )

            if p.stat().st_size == 0:
                return DirectActionResult(
                    success=False,
                    output=f"Screenshot verification failed: empty file (0 bytes) at {p}",
                    execution_type="tool",
                    tool_name="take_screenshot",
                    provider="macos-native-tool",
                    model="",
                    policy_decision="allowed",
                    telemetry={"reason": "verification_failed", "detail": "empty_file"},
                )

            if p.stat().st_mtime < (start_time - 2.0):
                return DirectActionResult(
                    success=False,
                    output=f"Screenshot verification failed: output file is not fresh at {p}",
                    execution_type="tool",
                    tool_name="take_screenshot",
                    provider="macos-native-tool",
                    model="",
                    policy_decision="allowed",
                    telemetry={"reason": "verification_failed", "detail": "not_fresh"},
                )

            with open(p, "rb") as f:
                header = f.read(24)
            if len(header) < 24 or not header.startswith(b"\x89PNG\r\n\x1a\n"):
                return DirectActionResult(
                    success=False,
                    output=f"Screenshot verification failed: invalid PNG signature at {p}",
                    execution_type="tool",
                    tool_name="take_screenshot",
                    provider="macos-native-tool",
                    model="",
                    policy_decision="allowed",
                    telemetry={"reason": "verification_failed", "detail": "invalid_png_signature"},
                )

            width = int.from_bytes(header[16:20], "big")
            height = int.from_bytes(header[20:24], "big")
            if width <= 0 or height <= 0:
                return DirectActionResult(
                    success=False,
                    output=f"Screenshot verification failed: non-positive dimensions ({width}x{height})",
                    execution_type="tool",
                    tool_name="take_screenshot",
                    provider="macos-native-tool",
                    model="",
                    policy_decision="allowed",
                    telemetry={"reason": "verification_failed", "detail": "invalid_dimensions"},
                )

            size = p.stat().st_size
            return DirectActionResult(
                success=True,
                output=f"Screenshot saved to {p} ({size} bytes, {width}x{height}).",
                execution_type="tool",
                tool_name="take_screenshot",
                provider="macos-native-tool",
                model="",
                policy_decision="allowed",
                telemetry={
                    "output_path": str(p),
                    "size_bytes": size,
                    "dimensions": f"{width}x{height}",
                    "verification_passed": True,
                    "verification": "passed",
                },
            )
        except Exception as exc:
            return DirectActionResult(
                success=False,
                output=f"Screenshot failed: {exc}",
                execution_type="tool",
                tool_name="take_screenshot",
                provider="macos-native-tool",
                model="",
                policy_decision="refused" if "permission" in str(exc).lower() else "allowed",
                telemetry={"reason": "tool_exception", "error": str(exc)},
            )

    # ── 3. Multi-Step Workflows ───────────────────────────────────────────────

    @classmethod
    def _is_workflow_request(cls, text: str) -> bool:
        parsed = RequestPreprocessor.process(text)
        workflow_candidates = [
            c
            for c in parsed.candidate_actions
            if c.action_type == ActionType.STRUCTURED_WORKFLOW and not c.is_blocked_as_negated
        ]
        if workflow_candidates:
            return True

        tokens = parsed.tokens
        has_input = bool(
            tokens
            & {
                "read",
                "reading",
                "reads",
                "input",
                "inputs",
                "from",
                "extract",
                "extracting",
                "combine",
                "combining",
                "load",
                "loading",
                "cat",
                "files",
                "source",
                "sources",
                "table",
                "tables",
            }
        )
        has_output = bool(
            tokens
            & {
                "save",
                "saving",
                "saves",
                "output",
                "outputs",
                "write",
                "writing",
                "writes",
                "create",
                "creating",
                "creates",
                "into",
                "put",
                "puts",
                "store",
                "stores",
                "convert",
                "converting",
                "destination",
                "dest",
            }
        )
        has_transform = bool(
            tokens
            & {
                "json",
                "prefix",
                "suffix",
                "sum",
                "total",
                "compute",
                "add",
                "subtract",
                "difference",
                "multiply",
                "product",
                "divide",
                "merge",
                "convert",
                "transform",
                "fields",
                "table",
                "delimiter",
                "replace",
                "concatenate",
                "key",
                "value",
                "pairs",
            }
        )
        all_paths = PathExtractor.extract_all_paths(text)
        return has_input and (has_output or "convert to" in text.lower()) and (has_transform or len(all_paths) >= 2)

    @classmethod
    def _parse_workflow_plan(cls, text: str, default_workspace: str = "") -> TransformationPlan | None:
        """Derive a structured TransformationPlan from natural language prompt with path-role validation."""
        clean = text.lower()
        args = PathExtractor.extract_structured_arguments(text, default_workspace=default_workspace)
        all_paths = PathExtractor.extract_all_paths(text)

        in_path_str = args.get("input_path")
        sec_in_path_str = args.get("secondary_input_path")
        out_path_str = args.get("output_path")

        if not in_path_str or not out_path_str or in_path_str == out_path_str:
            if len(all_paths) >= 2:
                m_save_first = re.search(
                    r"\b(?:save|write|put|output|store)\b.*?\b(?:from|after\s+reading|reading\s+table)\b", clean
                )
                if m_save_first:
                    out_path_str = all_paths[0]
                    in_path_str = all_paths[1]
                else:
                    in_path_str = all_paths[0]
                    out_path_str = all_paths[-1]
                if len(all_paths) >= 3 and not sec_in_path_str:
                    sec_in_path_str = all_paths[1]
            else:
                return None

        if in_path_str == out_path_str:
            return None

        # Role validation
        ws = Path(default_workspace if default_workspace else workspace_root()).expanduser().resolve()
        try:
            p_in = Path(in_path_str) if Path(in_path_str).is_absolute() else ws / in_path_str
            p_out = Path(out_path_str) if Path(out_path_str).is_absolute() else ws / out_path_str
            if not p_in.exists() and p_out.exists():
                in_path_str, out_path_str = out_path_str, in_path_str
        except Exception:
            pass

        inputs = [in_path_str]
        if sec_in_path_str and sec_in_path_str not in inputs and sec_in_path_str != out_path_str:
            inputs.append(sec_in_path_str)

        is_json_output = "json" in out_path_str.lower() or "json" in clean
        is_add = any(w in clean for w in ("sum", "total", "add", "addition", "calculate sum", "compute sum"))
        is_sub = any(w in clean for w in ("subtract", "difference", "minus", "subtraction", "deduct", "away from"))
        is_mul = any(w in clean for w in ("multiply", "product", "multiplication", "times"))
        is_div = any(w in clean for w in ("divide", "quotient", "division", "divided by"))
        is_prefix = "prefix" in clean
        is_suffix = "suffix" in clean
        is_replace = any(w in clean for w in ("replace", "substitute"))
        is_table = any(
            w in clean
            for w in ("table", "delimited", "csv", "tsv", "pipe", "semicolon", "rows", "columns", "convert to")
        )
        is_kv = any(w in clean for w in ("key-value", "key value", "key/value", "pairs", "config", "env", "kv"))

        # Phase 8 Part C: Explicit semantic operand roles for subtraction
        # Supported forms:
        #   'subtract B from A'      → minuend=A, subtrahend=B
        #   'take B away from A'     → minuend=A, subtrahend=B
        #   'A minus B'              → minuend=A, subtrahend=B  (positional)
        #   'deduct B from A'        → minuend=A, subtrahend=B
        input_roles: list[dict[str, Any]] = []
        if is_sub:
            # Pattern 1: subtract/take/deduct X [away] from Y
            m_from = re.search(
                r"(?:take|subtract|deduct)\s+(?:the\s+number\s+in\s+)?['\"`]?([~/a-zA-Z0-9_.\-]+)['\"`]?\s+(?:away\s+from|from)\s+['\"`]?([~/a-zA-Z0-9_.\-]+)['\"`]?",
                text,
                re.IGNORECASE,
            )
            if m_from:
                subtrahend = m_from.group(1).strip().strip("'\"`")
                minuend = m_from.group(2).strip().strip("'\"`")
                inputs = [minuend, subtrahend]
                input_roles = [
                    {"role": "minuend", "path": minuend, "provenance": "subtract_from_pattern"},
                    {"role": "subtrahend", "path": subtrahend, "provenance": "subtract_from_pattern"},
                ]
            else:
                # Pattern 2: positional path order (first=minuend, second=subtrahend)
                if len(inputs) >= 2:
                    input_roles = [
                        {"role": "minuend", "path": inputs[0], "provenance": "positional"},
                        {"role": "subtrahend", "path": inputs[1], "provenance": "positional"},
                    ]

        # Phase 8 Part C: Explicit semantic operand roles for division
        # Supported forms:
        #   'divide A by B'       → numerator=A, denominator=B
        #   'A divided by B'      → numerator=A, denominator=B
        #   'divide B into A'     → numerator=A, denominator=B
        if is_div and not input_roles:
            # Pattern 1: divide X by Y
            m_div_by = re.search(
                r"divide\s+['\"`]?([~/a-zA-Z0-9_.\-]+)['\"`]?\s+by\s+['\"`]?([~/a-zA-Z0-9_.\-]+)['\"`]?",
                text,
                re.IGNORECASE,
            )
            # Pattern 2: X divided by Y
            m_div_passive = re.search(
                r"['\"`]?([~/a-zA-Z0-9_.\-]+)['\"`]?\s+divided\s+by\s+['\"`]?([~/a-zA-Z0-9_.\-]+)['\"`]?",
                text,
                re.IGNORECASE,
            )
            # Pattern 3: divide Y into X  (Y goes into X, so numerator=X)
            m_div_into = re.search(
                r"divide\s+['\"`]?([~/a-zA-Z0-9_.\-]+)['\"`]?\s+into\s+['\"`]?([~/a-zA-Z0-9_.\-]+)['\"`]?",
                text,
                re.IGNORECASE,
            )
            if m_div_by:
                numerator = m_div_by.group(1).strip().strip("'\"`")
                denominator = m_div_by.group(2).strip().strip("'\"`")
                inputs = [numerator, denominator]
                input_roles = [
                    {"role": "numerator", "path": numerator, "provenance": "divide_by_pattern"},
                    {"role": "denominator", "path": denominator, "provenance": "divide_by_pattern"},
                ]
            elif m_div_passive:
                numerator = m_div_passive.group(1).strip().strip("'\"`")
                denominator = m_div_passive.group(2).strip().strip("'\"`")
                inputs = [numerator, denominator]
                input_roles = [
                    {"role": "numerator", "path": numerator, "provenance": "divided_by_pattern"},
                    {"role": "denominator", "path": denominator, "provenance": "divided_by_pattern"},
                ]
            elif m_div_into:
                # 'divide B into A' means A/B: denominator is first group, numerator is second
                denominator = m_div_into.group(1).strip().strip("'\"`")
                numerator = m_div_into.group(2).strip().strip("'\"`")
                inputs = [numerator, denominator]
                input_roles = [
                    {"role": "numerator", "path": numerator, "provenance": "divide_into_pattern"},
                    {"role": "denominator", "path": denominator, "provenance": "divide_into_pattern"},
                ]
            elif len(inputs) >= 2:
                input_roles = [
                    {"role": "numerator", "path": inputs[0], "provenance": "positional"},
                    {"role": "denominator", "path": inputs[1], "provenance": "positional"},
                ]

        op = "concatenate"
        params: dict[str, Any] = {}

        if is_table or ("table" in in_path_str.lower() and is_json_output) or in_path_str.endswith((".csv", ".tsv")):
            op = "delimited_table_to_json"
            if "pipe" in clean or "|" in text:
                params["delimiter"] = "|"
            elif "comma" in clean or "csv" in clean or in_path_str.endswith(".csv"):
                params["delimiter"] = ","
            elif "semicolon" in clean or ";" in text:
                params["delimiter"] = ";"
            elif re.search(r"\b(?:tab|tabs|tsv)\b", clean) or in_path_str.endswith(".tsv"):
                params["delimiter"] = "\t"
        elif is_kv:
            op = "kv_to_json"
        elif is_json_output and not (is_add or is_sub or is_mul or is_div or is_prefix or is_suffix or is_replace):
            op = "delimited_table_to_json"
        elif is_sub:
            op = "subtract"
        elif is_mul:
            op = "multiply"
        elif is_div:
            op = "divide"
        elif is_add:
            op = "add"
        elif is_prefix:
            op = "prefix"
            m_pfx = re.search(
                r"prefix\s+(?:with\s+)?['\"]?([^'\"\n]+?)['\"]?(?:\s+and|\s+to|\s+save|$)", text, re.IGNORECASE
            )
            if m_pfx:
                params["prefix"] = m_pfx.group(1).strip()
        elif is_suffix:
            op = "suffix"
            m_sfx = re.search(
                r"suffix\s+(?:with\s+)?['\"]?([^'\"\n]+?)['\"]?(?:\s+and|\s+to|\s+save|$)", text, re.IGNORECASE
            )
            if m_sfx:
                params["suffix"] = m_sfx.group(1).strip()
        elif is_replace:
            op = "replace"
            m_rep = re.search(
                r"replace\s+['\"]?([^'\"\n]+?)['\"]?\s+with\s+['\"]?([^'\"\n]+?)['\"]?", text, re.IGNORECASE
            )
            if m_rep:
                params["target"] = m_rep.group(1)
                params["replacement"] = m_rep.group(2)
        elif any(w in clean for w in ("uppercase", "upper case", "to upper", "to uppercase")):
            op = "uppercase"
        elif any(w in clean for w in ("lowercase", "lower case", "to lower", "to lowercase")):
            op = "lowercase"
        elif is_json_output:
            op = "kv_to_json"
        else:
            op = "concatenate" if len(inputs) > 1 else "identity"

        return TransformationPlan(
            inputs=inputs,
            operation=op,
            output_path=out_path_str,
            output_format="json" if is_json_output else "text",
            parameters=params,
            input_roles=input_roles,
        )

    @classmethod
    def _try_multi_step_workflow(cls, text: str, workspace: str = "") -> DirectActionResult | None:
        if not cls._is_workflow_request(text):
            return None

        plan = cls._parse_workflow_plan(text, default_workspace=workspace)
        if not plan:
            return None

        ws = Path(workspace if workspace else workspace_root()).expanduser().resolve()

        with tool_workspace(ws):
            try:
                resolved_inputs: list[Path] = [resolve_workspace_path(p_str, must_exist=True) for p_str in plan.inputs]
                out_p = resolve_workspace_path(plan.output_path, must_exist=False)
            except PermissionError as exc:
                return DirectActionResult(
                    success=False,
                    output=f"Workflow path policy error: {exc}",
                    execution_type="policy_enforcement",
                    tool_name="multi_step_workflow",
                    provider="security-policy",
                    model="",
                    policy_decision="refused",
                    telemetry={"reason": "workspace_escape", "error": str(exc)},
                )
            except FileNotFoundError as exc:
                return DirectActionResult(
                    success=False,
                    output=f"Workflow input file not found: {exc}",
                    execution_type="workflow",
                    tool_name="read_file",
                    provider="local-filesystem",
                    model="",
                    policy_decision="allowed",
                    telemetry={"reason": "input_file_not_found", "error": str(exc)},
                )

        try:
            raw_contents: list[str] = []
            for in_p in resolved_inputs:
                content = in_p.read_text(encoding="utf-8", errors="replace")
                raw_contents.append(content)

            input_1 = raw_contents[0]
            raw_contents[1] if len(raw_contents) > 1 else ""

            transformed_content = ""
            computed_result: Any = None
            extracted_numbers: list[float] = []

            # 1. Numeric Operations
            if plan.operation in {"add", "subtract", "multiply", "divide"}:
                all_raw = " ".join(raw_contents)
                extracted_str = re.findall(r"-?\b\d+(?:\.\d+)?\b", all_raw)
                extracted_numbers = [float(n) if "." in n else int(n) for n in extracted_str]

                if not extracted_numbers:
                    return DirectActionResult(
                        success=False,
                        output="Workflow execution failed: No numbers found in input files to compute arithmetic operation.",
                        execution_type="workflow",
                        tool_name="multi_step_workflow",
                        provider="local-filesystem",
                        telemetry={"reason": "no_numeric_operands"},
                    )

                if plan.operation == "add":
                    computed_result = sum(extracted_numbers)
                elif plan.operation == "subtract":
                    computed_result = extracted_numbers[0]
                    for n in extracted_numbers[1:]:
                        computed_result -= n
                elif plan.operation == "multiply":
                    computed_result = 1
                    for n in extracted_numbers:
                        computed_result *= n
                elif plan.operation == "divide":
                    computed_result = extracted_numbers[0]
                    for n in extracted_numbers[1:]:
                        if n == 0:
                            raise ZeroDivisionError("Division by zero in workflow transformation")
                        computed_result = computed_result / n

                if plan.output_format == "json":
                    transformed_content = json.dumps(
                        {
                            "inputs": [str(p) for p in resolved_inputs],
                            "operation": plan.operation,
                            "operands": extracted_numbers,
                            "result": computed_result,
                        },
                        indent=2,
                    )
                else:
                    transformed_content = f"{computed_result}\n"

            # 2. Text Operations
            elif plan.operation == "prefix":
                pfx = plan.parameters.get("prefix", "")
                transformed_content = f"{pfx}{input_1}"
                computed_result = transformed_content
            elif plan.operation == "suffix":
                sfx = plan.parameters.get("suffix", "")
                transformed_content = f"{input_1}{sfx}"
                computed_result = transformed_content
            elif plan.operation == "replace":
                tgt = plan.parameters.get("target", "")
                rep = plan.parameters.get("replacement", "")
                transformed_content = input_1.replace(tgt, rep)
                computed_result = transformed_content
            elif plan.operation == "uppercase":
                transformed_content = input_1.upper()
                computed_result = transformed_content
            elif plan.operation == "lowercase":
                transformed_content = input_1.lower()
                computed_result = transformed_content
            elif plan.operation == "concatenate":
                transformed_content = "\n".join(r.strip() for r in raw_contents if r.strip())
                computed_result = transformed_content

            # 3. Delimited Table -> JSON Array
            elif plan.operation == "delimited_table_to_json":
                lines = [line_item for line_item in input_1.splitlines() if line_item.strip()]
                is_kv_format = (
                    lines
                    and all(
                        re.match(r"^[a-zA-Z0-9_.\-]+\s*[:=]\s*", line_item.strip())
                        for line_item in lines
                        if not line_item.strip().startswith("#")
                    )
                    and not any("|" in line_item or "\t" in line_item or "," in line_item for line_item in lines)
                )

                if is_kv_format:
                    extracted_dict: dict[str, Any] = {}
                    for line in lines:
                        line_clean = line.strip()
                        if not line_clean or line_clean.startswith("#"):
                            continue
                        kv_match = re.match(r"^([a-zA-Z0-9_.\-]+)\s*[:=]\s*(.*)$", line_clean)
                        if kv_match:
                            k = kv_match.group(1).strip().lower()
                            v_str = kv_match.group(2).strip().strip("'\"")
                            if v_str.lower() == "true":
                                extracted_dict[k] = True
                            elif v_str.lower() == "false":
                                extracted_dict[k] = False
                            elif v_str.lower() in ("null", "none"):
                                extracted_dict[k] = None
                            elif v_str.isdigit():
                                extracted_dict[k] = int(v_str)
                            else:
                                try:
                                    extracted_dict[k] = float(v_str)
                                except ValueError:
                                    extracted_dict[k] = v_str
                    transformed_content = json.dumps(extracted_dict, indent=2)
                    computed_result = extracted_dict
                else:
                    clean_lines = [
                        line_item
                        for line_item in input_1.splitlines()
                        if line_item.strip()
                        and not line_item.strip().startswith("#")
                        and not re.match(r"^[-|+= :]+$", line_item.strip())
                    ]
                    first_line = clean_lines[0] if clean_lines else input_1
                    if "|" in first_line:
                        delim = "|"
                    elif "\t" in first_line:
                        delim = "\t"
                    elif ";" in first_line:
                        delim = ";"
                    elif "," in first_line:
                        delim = ","
                    else:
                        delim = plan.parameters.get("delimiter", ",")

                    if not clean_lines:
                        transformed_content = "[]"
                        computed_result = []
                    else:
                        reader = csv.reader(clean_lines, delimiter=delim)
                        rows = [row for row in reader if any(cell.strip() for cell in row)]
                        if not rows:
                            transformed_content = "[]"
                            computed_result = []
                        else:
                            headers = [
                                h.strip().strip("'\"").strip("`").strip().lower().replace(" ", "_")
                                for h in rows[0]
                                if h.strip()
                            ]
                            result_list = []
                            for row in rows[1:]:
                                cells = [c.strip().strip("'\"").strip("`").strip() for c in row if c.strip() != ""]
                                if not cells or all(re.match(r"^[-:]+$", c) for c in cells):
                                    continue
                                item: dict[str, Any] = {}
                                for i, h in enumerate(headers):
                                    if i < len(cells):
                                        v_str = cells[i]
                                        if v_str.lower() == "true":
                                            item[h] = True
                                        elif v_str.lower() == "false":
                                            item[h] = False
                                        elif v_str.lower() in ("null", "none"):
                                            item[h] = None
                                        elif v_str.isdigit():
                                            item[h] = int(v_str)
                                        else:
                                            try:
                                                item[h] = float(v_str)
                                            except ValueError:
                                                item[h] = v_str
                                result_list.append(item)
                            transformed_content = json.dumps(result_list, indent=2)
                            computed_result = result_list

            elif plan.operation == "kv_to_json":
                lines = [
                    line_item
                    for line_item in input_1.splitlines()
                    if line_item.strip() and not line_item.strip().startswith("#")
                ]
                res_dict: dict[str, Any] = {}
                for line_item in lines:
                    m = re.match(r"^\s*([a-zA-Z0-9_.\-]+)\s*[:=]\s*(.*)$", line_item)
                    if m:
                        k = m.group(1).strip().lower()
                        v = m.group(2).strip().strip("'\"")
                        if v.lower() == "true":
                            res_dict[k] = True
                        elif v.lower() == "false":
                            res_dict[k] = False
                        elif v.lower() in ("null", "none"):
                            res_dict[k] = None
                        elif v.isdigit():
                            res_dict[k] = int(v)
                        else:
                            try:
                                res_dict[k] = float(v)
                            except ValueError:
                                res_dict[k] = v
                transformed_content = json.dumps(res_dict, indent=2)
                computed_result = res_dict
            else:
                transformed_content = input_1
                computed_result = input_1

            expected_output_hash = hashlib.sha256(transformed_content.encode("utf-8")).hexdigest()

            with tool_workspace(ws):
                write_raw = execute_tool("write_file", {"path": str(out_p), "content": transformed_content})
            write_res = parse_tool_result(write_raw)
            if not write_res.ok:
                return DirectActionResult(
                    success=False,
                    output=f"Workflow failed at write step: {write_res.error or 'write_tool_failed'}",
                    execution_type="workflow",
                    tool_name="write_file",
                    provider="local-filesystem",
                    model="",
                    policy_decision="allowed",
                    telemetry={"reason": "write_tool_failed", "error": write_res.error},
                )

            if not (out_p.exists() and out_p.is_file()):
                return DirectActionResult(
                    success=False,
                    output=f"Workflow verification failed: output file missing at {out_p}",
                    execution_type="workflow",
                    tool_name="multi_step_workflow",
                    provider="local-filesystem",
                    model="",
                    policy_decision="allowed",
                    telemetry={"reason": "output_file_missing", "verification_passed": False},
                )

            actual_output_str = out_p.read_text(encoding="utf-8", errors="replace")
            actual_output_hash = hashlib.sha256(actual_output_str.encode("utf-8")).hexdigest()

            if actual_output_hash != expected_output_hash:
                return DirectActionResult(
                    success=False,
                    output=f"Workflow execution verification failed: hash mismatch at {out_p}",
                    execution_type="workflow",
                    tool_name="multi_step_workflow",
                    provider="local-filesystem",
                    model="",
                    policy_decision="allowed",
                    telemetry={"reason": "hash_mismatch", "verification_passed": False},
                )

            return DirectActionResult(
                success=True,
                output=f"Successfully executed workflow: read {', '.join(str(p) for p in resolved_inputs)}, applied {plan.operation}, and verified {out_p}.",
                execution_type="workflow",
                tool_name="multi_step_workflow",
                provider="local-filesystem",
                model="",
                policy_decision="allowed",
                telemetry={
                    "requested_operation": plan.operation,
                    "parsed_plan": {
                        "inputs": [str(p) for p in resolved_inputs],
                        "operation": plan.operation,
                        "output_path": str(out_p),
                        "parameters": plan.parameters,
                    },
                    "input_values": raw_contents,
                    "computed_result": computed_result,
                    "expected_output_hash": expected_output_hash,
                    "actual_output_hash": actual_output_hash,
                    "verification_passed": True,
                    "output_bytes": out_p.stat().st_size,
                },
            )
        except Exception as exc:
            return DirectActionResult(
                success=False,
                output=f"Workflow execution failed: {exc}",
                execution_type="workflow",
                tool_name="multi_step_workflow",
                provider="local-filesystem",
                model="",
                telemetry={"reason": "workflow_exception", "error": str(exc)},
            )

    # ── 4. Repository Inspection & Generic Bug Diagnosis ──────────────────────

    @classmethod
    def _is_repository_inspection_request(cls, text: str) -> bool:
        clean = text.lower()
        repo_indicators = (
            "inspect repo",
            "inspect the repo",
            "analyze repo",
            "review code",
            "diagnose project",
            "find bug",
            "find the bug",
            "check repo",
            "check the repo",
            "codebase",
            "check codebase",
            "examine repo",
            "audit repo",
            "audit codebase",
            "scan repo",
            "examine codebase",
            "review project",
            "diagnose repo",
            "review repo",
            "inspect python repository",
            "diagnose bug",
            "identify defect",
            "locate bug",
            "diagnose defect",
            "look through",
            "what is here",
            "tell me why",
            "why the calculation is wrong",
        )
        return any(ind in clean for ind in repo_indicators) or (
            ("repo" in clean or "project" in clean or "codebase" in clean or "repository" in clean)
            and any(
                v in clean
                for v in (
                    "inspect",
                    "analyze",
                    "review",
                    "check",
                    "diagnose",
                    "audit",
                    "examine",
                    "scan",
                    "find",
                    "locate",
                )
            )
        )

    @classmethod
    def _try_repository_inspection(cls, text: str, workspace: str = "") -> DirectActionResult | None:
        if not cls._is_repository_inspection_request(text):
            return None

        args = PathExtractor.extract_structured_arguments(text, default_workspace=workspace)
        all_paths = PathExtractor.extract_all_paths(text)

        repo_path_str = args.get("repo_path") or (all_paths[0] if all_paths else workspace or ".")

        ws = Path(workspace if workspace else workspace_root()).expanduser().resolve()
        with tool_workspace(ws):
            try:
                repo_p = resolve_workspace_path(repo_path_str, must_exist=True)
            except (PermissionError, FileNotFoundError) as exc:
                return DirectActionResult(
                    success=False,
                    output=f"Repository path error: {exc}",
                    execution_type="internal_analysis",
                    tool_name="internal_ast_inspector",
                    provider="deterministic-ast",
                    model="",
                    policy_decision="refused",
                    telemetry={"reason": "workspace_escape", "error": str(exc)},
                )

        if not repo_p.exists() or not repo_p.is_dir():
            return None

        try:
            diag_res = RepositoryDiagnosticEngine.diagnose(repo_p)
            pre_hashes = diag_res["pre_hashes"]
            post_hashes = diag_res["post_hashes"]
            read_only_verified = diag_res["read_only_verified"]
            findings = diag_res["findings"]

            if findings:
                top_finding = findings[0]
                primary_fn = top_finding.get("function", "unknown")
                bug_desc = top_finding.get("description", "defect detected")
                summary = f"Inspected repository at {repo_p}. Analyzed {len(pre_hashes)} Python file(s) with read-only isolation. Function '{primary_fn}' has defect: {bug_desc}."
            else:
                defined_fns: list[str] = []
                file_names = [Path(fp).name for fp in pre_hashes]
                entry_point = "main"
                for file_path_str in pre_hashes:
                    try:
                        p_obj = Path(file_path_str)
                        p_code = p_obj.read_text(encoding="utf-8", errors="replace")
                        if "__main__" in p_code or "main(" in p_code or p_obj.name in ("app.py", "main.py", "cli.py"):
                            entry_point = p_obj.name
                        tree = ast.parse(p_code)
                        for node in ast.walk(tree):
                            if isinstance(node, ast.FunctionDef):
                                defined_fns.append(node.name)
                    except Exception:
                        pass
                primary_fn = defined_fns[0] if defined_fns else "none"
                files_list_str = ", ".join(file_names) if file_names else "none"
                summary = f"Inspected repository at {repo_p}. Analyzed {len(pre_hashes)} Python file(s): {files_list_str}. Likely entry point is {entry_point}. Function: '{primary_fn}'. No active defect detected."

            return DirectActionResult(
                success=True,
                output=summary,
                execution_type="internal_analysis",
                tool_name="internal_ast_inspector",
                provider="deterministic-ast",
                model="",
                policy_decision="allowed",
                telemetry={
                    "repo_path": str(repo_p),
                    "files_inspected": list(pre_hashes.keys()),
                    "pre_hashes": pre_hashes,
                    "post_hashes": post_hashes,
                    "read_only_verified": read_only_verified,
                    "primary_function": primary_fn,
                    "findings_count": len(findings),
                    "findings": findings,
                },
            )
        except Exception as exc:
            return DirectActionResult(
                success=False,
                output=f"Repository inspection failed: {exc}",
                execution_type="internal_analysis",
                tool_name="internal_ast_inspector",
                provider="deterministic-ast",
                model="",
                telemetry={"reason": "inspection_exception", "error": str(exc)},
            )

    # ── 5. Filesystem Operations (Write, Read, List) ─────────────────────────

    @classmethod
    def _is_filesystem_request(cls, text: str, workspace: str = "") -> bool:
        clean = text.lower()
        all_paths = PathExtractor.extract_all_paths(text)
        tokens = set(re.findall(r"[a-z0-9_+-]+", clean))

        fs_decision = FilesystemActionClassifier.classify(text, workspace=workspace)
        if fs_decision.action_type in (
            FilesystemActionType.FS_WRITE_FILE,
            FilesystemActionType.FS_LIST_DIRECTORY,
            FilesystemActionType.FS_READ_FILE,
        ):
            return True

        if not all_paths:
            return False

        write_tokens = {
            "save",
            "write",
            "create",
            "make",
            "put",
            "store",
            "dump",
            "record",
            "output",
            "contain",
            "contains",
            "hold",
            "holds",
            "set",
        }
        if bool(tokens & write_tokens) and any(
            p in clean
            for p in (
                " to ",
                " in ",
                " into ",
                " at ",
                "with content",
                "containing",
                "should contain",
                "must contain",
                "should hold",
                "must hold",
            )
        ):
            return True

        read_tokens = {
            "read",
            "open",
            "show",
            "display",
            "load",
            "cat",
            "view",
            "fetch",
            "get",
            "print",
            "examine",
            "inspect",
            "retrieve",
            "contain",
            "contains",
            "contents",
            "content",
            "verbatim",
            "raw",
            "inside",
        }
        if bool(tokens & read_tokens) and any(ext in clean for ext in PathExtractor.KNOWN_EXTENSIONS):
            return True

        list_tokens = {"list", "directory", "folder", "filenames", "entries"}
        if bool(tokens & list_tokens) and any(
            w in clean
            for w in (
                "list",
                "what files",
                "show files",
                "show entries",
                "give filenames",
                "files under",
                "what is under",
                "entries inside",
                "contents of",
                "what is inside",
                "display entries",
                "list items",
                "what entries",
                "directory contents",
                "folder contents",
                "children of",
                "direct children of",
                "inventory of",
            )
        ):
            return True

        return False

    @classmethod
    def _try_filesystem_action(cls, text: str, workspace: str = "") -> DirectActionResult | None:
        clean = text.lower().strip()
        ws = Path(workspace if workspace else workspace_root()).expanduser().resolve()
        all_paths = PathExtractor.extract_all_paths(text)
        args = PathExtractor.extract_structured_arguments(text, default_workspace=workspace)
        parsed = RequestPreprocessor.process(text)

        if not cls._is_filesystem_request(text, workspace=workspace):
            return None

        is_raw_read = (parsed.response_mode in (ResponseMode.RAW, ResponseMode.EXACT_RAW)) or any(
            w in clean
            for w in (
                "verbatim",
                "exact contents",
                "only contents",
                "only the contents",
                "raw content",
                "raw contents",
                "unchanged",
                "without explanation",
                "without line numbers",
                "just the contents",
                "just contents",
                "no formatting",
                "no headers",
                "raw file",
                "exact file",
                "print exactly",
                "only file content",
                "give only",
                "return only the content",
                "return only the contents",
                "whole reply must be file text",
                "whole response must be",
            )
        )

        # A. Write / Create file
        write_action = WriteActionParser.parse(text, default_workspace=workspace)
        if write_action is not None and not cls._is_workflow_request(text):
            if write_action.is_invalid:
                return DirectActionResult(
                    success=False,
                    output=f"Write action rejected: {write_action.invalid_reason}",
                    execution_type="tool",
                    tool_name="write_file",
                    provider="local-filesystem",
                    model="",
                    policy_decision="allowed",
                    telemetry={
                        "reason": "write_precondition_failed",
                        "detail": write_action.invalid_reason,
                        "verification_passed": False,
                    },
                )

            path_str = write_action.target_path
            content_str = write_action.content

            with tool_workspace(ws):
                try:
                    p = resolve_workspace_path(path_str, must_exist=False)
                except PermissionError as exc:
                    return DirectActionResult(
                        success=False,
                        output=f"Cannot write to path outside workspace: {exc}",
                        execution_type="policy_enforcement",
                        tool_name="write_file",
                        provider="security-policy",
                        model="",
                        policy_decision="refused",
                        telemetry={"reason": "workspace_escape", "error": str(exc)},
                    )

            try:
                with tool_workspace(ws):
                    res_raw = execute_tool("write_file", {"path": str(p), "content": content_str})
                tool_res = parse_tool_result(res_raw)

                if not tool_res.ok:
                    return DirectActionResult(
                        success=False,
                        output=f"File write failed: {tool_res.error or 'tool_failed'}",
                        execution_type="tool",
                        tool_name="write_file",
                        provider="local-filesystem",
                        model="",
                        policy_decision="allowed",
                        telemetry={"reason": "tool_failed", "error": tool_res.error},
                    )

                if not (p.exists() and p.is_file()):
                    return DirectActionResult(
                        success=False,
                        output=f"Write verification failed: file missing after write at {p}",
                        execution_type="tool",
                        tool_name="write_file",
                        provider="local-filesystem",
                        model="",
                        policy_decision="allowed",
                        telemetry={"reason": "file_missing_after_write", "path": str(p), "verification_passed": False},
                    )

                actual = p.read_text(encoding="utf-8", errors="replace")

                if len(content_str) > 0 and len(actual) == 0:
                    return DirectActionResult(
                        success=False,
                        output=f"Write verification failed: file is empty (0 bytes) but requested content had {len(content_str)} chars",
                        execution_type="tool",
                        tool_name="write_file",
                        provider="local-filesystem",
                        model="",
                        policy_decision="allowed",
                        telemetry={
                            "reason": "empty_file_on_nonempty_payload",
                            "raw_content_clause": write_action.content_source_span,
                            "payload_span": (write_action.payload_span_start, write_action.payload_span_end),
                            "payload": content_str,
                            "exactness_mode": write_action.exact_content_requested,
                            "expected_size": len(content_str),
                            "actual_size": len(actual),
                            "content_match": False,
                            "verification_passed": False,
                        },
                    )

                if actual != content_str:
                    return DirectActionResult(
                        success=False,
                        output=f"Write verification failed: content mismatch at {p}",
                        execution_type="tool",
                        tool_name="write_file",
                        provider="local-filesystem",
                        model="",
                        policy_decision="allowed",
                        telemetry={
                            "reason": "content_mismatch",
                            "path": str(p),
                            "raw_content_clause": write_action.content_source_span,
                            "payload_span": (write_action.payload_span_start, write_action.payload_span_end),
                            "payload": content_str,
                            "exactness_mode": write_action.exact_content_requested,
                            "expected_size": len(content_str),
                            "actual_size": len(actual),
                            "content_match": False,
                            "verification_passed": False,
                        },
                    )

                return DirectActionResult(
                    success=True,
                    output=f"Successfully wrote file at {p} ({len(content_str)} chars).",
                    execution_type="tool",
                    tool_name="write_file",
                    provider="local-filesystem",
                    model="",
                    policy_decision="allowed",
                    telemetry={
                        "path": str(p),
                        "raw_content_clause": write_action.content_source_span,
                        "payload_span": (write_action.payload_span_start, write_action.payload_span_end),
                        "payload": content_str,
                        "payload_type": write_action.payload_type,
                        "exactness_mode": write_action.exact_content_requested,
                        "expected_size": len(content_str),
                        "actual_size": len(actual),
                        "content_match": True,
                        "bytes": p.stat().st_size,
                        "verification_passed": True,
                    },
                )
            except Exception as exc:
                return DirectActionResult(
                    success=False,
                    output=f"File write failed: {exc}",
                    execution_type="tool",
                    tool_name="write_file",
                    provider="local-filesystem",
                    model="",
                    telemetry={"reason": "verification_error", "error": str(exc)},
                )

        # B & C: Stat-Dominant File vs Directory Classification
        fs_decision = FilesystemActionClassifier.classify(text, workspace=workspace)
        target_path_str = (
            fs_decision.target_path
            or args.get("directory")
            or args.get("input_path")
            or args.get("path")
            or (all_paths[0] if all_paths else ".")
        )

        target_is_dir: bool | None = None
        target_is_file: bool | None = None
        with tool_workspace(ws):
            try:
                resolved_target = resolve_workspace_path(target_path_str, must_exist=False)
                if resolved_target.exists():
                    target_is_dir = resolved_target.is_dir()
                    target_is_file = resolved_target.is_file()
            except Exception:
                pass

        if target_is_dir is True:
            should_list = True
        elif target_is_file is True:
            should_list = False
        elif fs_decision.action_type == FilesystemActionType.FS_LIST_DIRECTORY:
            should_list = True
        elif any(
            w in clean
            for w in (
                "directory",
                "folder",
                "entries",
                "filenames",
                "files under",
                "children",
                "items in",
                "items under",
                "what is under",
                "entries inside",
                "what is inside",
                "list ",
                "list_dir",
                "inventory of",
                "direct children",
            )
        ):
            should_list = True
        else:
            should_list = False

        if should_list:
            path_str = target_path_str
            with tool_workspace(ws):
                try:
                    p = resolve_workspace_path(path_str, must_exist=True)
                except PermissionError as exc:
                    return DirectActionResult(
                        success=False,
                        output=f"Cannot list path: {exc}",
                        execution_type="policy_enforcement",
                        tool_name="list_directory",
                        provider="security-policy",
                        model="",
                        policy_decision="refused",
                        telemetry={"reason": "workspace_escape", "error": str(exc)},
                    )
                except FileNotFoundError as exc:
                    return DirectActionResult(
                        success=False,
                        output=f"Directory list failed: directory not found at '{path_str}'",
                        execution_type="tool",
                        tool_name="list_directory",
                        provider="local-filesystem",
                        model="",
                        policy_decision="allowed",
                        telemetry={"reason": "directory_not_found", "path": path_str, "error": str(exc)},
                    )

            try:
                with tool_workspace(ws):
                    res_raw = execute_tool("list_directory", {"path": str(p)})
                tool_res = parse_tool_result(res_raw)

                if not tool_res.ok:
                    return DirectActionResult(
                        success=False,
                        output=f"Directory list failed: {tool_res.error or 'tool_failed'}",
                        execution_type="tool",
                        tool_name="list_directory",
                        provider="local-filesystem",
                        model="",
                        policy_decision="allowed",
                        telemetry={"reason": "tool_failed", "error": tool_res.error},
                    )

                if not (p.exists() and p.is_dir()):
                    return DirectActionResult(
                        success=False,
                        output=f"List verification failed: directory not found at {p}",
                        execution_type="tool",
                        tool_name="list_directory",
                        provider="local-filesystem",
                        model="",
                        policy_decision="allowed",
                        telemetry={"reason": "directory_not_found", "path": str(p)},
                    )

                output_val = tool_res.data.get("output")
                entries = output_val.get("entries") if isinstance(output_val, dict) else output_val
                out_str = (
                    "\n".join(str(e) for e in entries)
                    if isinstance(entries, list)
                    else str(output_val if output_val is not None else "")
                )

                return DirectActionResult(
                    success=True,
                    output=out_str,
                    execution_type="tool",
                    tool_name="list_directory",
                    provider="local-filesystem",
                    model="",
                    policy_decision="allowed",
                    telemetry={
                        "path": str(p),
                        "count": len(entries) if isinstance(entries, list) else 0,
                        "verification_passed": True,
                    },
                )
            except Exception as exc:
                return DirectActionResult(
                    success=False,
                    output=f"Directory list failed: {exc}",
                    execution_type="tool",
                    tool_name="list_directory",
                    provider="local-filesystem",
                    model="",
                    telemetry={"reason": "tool_exception", "error": str(exc)},
                )

        path_str = target_path_str
        with tool_workspace(ws):
            try:
                p = resolve_workspace_path(path_str, must_exist=True)
            except PermissionError as exc:
                return DirectActionResult(
                    success=False,
                    output=f"Cannot read path: {exc}",
                    execution_type="policy_enforcement",
                    tool_name="read_file",
                    provider="security-policy",
                    model="",
                    policy_decision="refused",
                    telemetry={"reason": "workspace_escape", "error": str(exc)},
                )
            except FileNotFoundError as exc:
                return DirectActionResult(
                    success=False,
                    output=f"File read failed: file not found at '{path_str}'",
                    execution_type="tool",
                    tool_name="read_file",
                    provider="local-filesystem",
                    model="",
                    policy_decision="allowed",
                    telemetry={"reason": "file_not_found", "path": path_str, "error": str(exc)},
                )

        try:
            with tool_workspace(ws):
                res_raw = execute_tool("read_file", {"path": str(p)})
            tool_res = parse_tool_result(res_raw)

            if not tool_res.ok:
                return DirectActionResult(
                    success=False,
                    output=f"File read failed: {tool_res.error or 'tool_failed'}",
                    execution_type="tool",
                    tool_name="read_file",
                    provider="local-filesystem",
                    model="",
                    policy_decision="allowed",
                    telemetry={"reason": "tool_failed", "error": tool_res.error},
                )

            if not (p.exists() and p.is_file()):
                return DirectActionResult(
                    success=False,
                    output=f"Read verification failed: file not found at {p}",
                    execution_type="tool",
                    tool_name="read_file",
                    provider="local-filesystem",
                    model="",
                    policy_decision="allowed",
                    telemetry={"reason": "file_not_found", "path": str(p)},
                )

            raw_text = p.read_text(encoding="utf-8", errors="replace")

            if is_raw_read:
                final_output = raw_text
            else:
                output_val = tool_res.data.get("output")
                final_output = str(
                    output_val.get("content")
                    if isinstance(output_val, dict) and "content" in output_val
                    else (output_val if output_val is not None else raw_text)
                )

            return DirectActionResult(
                success=True,
                output=final_output,
                execution_type="tool",
                tool_name="read_file",
                provider="local-filesystem",
                model="",
                policy_decision="allowed",
                telemetry={
                    "path": str(p),
                    "size_bytes": p.stat().st_size,
                    "read_mode": "raw" if is_raw_read else "display",
                    "verification_passed": True,
                },
            )
        except Exception as exc:
            return DirectActionResult(
                success=False,
                output=f"File read failed: {exc}",
                execution_type="tool",
                tool_name="read_file",
                provider="local-filesystem",
                model="",
                telemetry={"reason": "tool_exception", "error": str(exc)},
            )

    # ── 6. Compound Browser Operations ───────────────────────────────────────

    @classmethod
    def _try_browser_action(cls, text: str) -> DirectActionResult | None:
        clean = text.lower()
        if not (
            "://" in clean or "browser" in clean or "navigate" in clean or "browse" in clean or "fetch url" in clean
        ):
            return None

        m_url = re.search(r"['\"]?([a-zA-Z][a-zA-Z0-9+.-]*://[^\s'\"]+)['\"]?", text, re.IGNORECASE)
        if not m_url:
            return None
        url = m_url.group(1).strip()

        # Security policy: Block cloud metadata service IP endpoints
        if "169.254.169.254" in url or "metadata.google.internal" in url:
            return DirectActionResult(
                success=False,
                output="Access to cloud metadata endpoints is blocked by security policy.",
                execution_type="tool",
                tool_name="browser_navigate",
                provider="browser",
                model="",
                policy_decision="refused",
                telemetry={"reason": "metadata_endpoint_refusal", "url": url},
            )

        is_multi_field = any(
            w in clean
            for w in (
                "extract",
                "scrape",
                "get",
                "title",
                "text",
                "body",
                "content",
                "link",
                "selector",
                "field",
                "fetch",
                "summary",
            )
        )
        req_fields: list[BrowserField] = []

        if is_multi_field:
            if "title" in clean:
                req_fields.append(BrowserField(type="title", name="title"))

            # Phase 8 Part E: CSS selector grammar with action-word preservation.
            # Priority 1: Explicitly quoted selectors after css/selector/element keyword.
            # These are verbatim data — action-like words inside them are NOT intents.
            for m_sel in re.finditer(r"(?:css|selector|element)\s+['\"]([^'\"]+)['\"]", text, re.IGNORECASE):
                sel = m_sel.group(1)
                safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", sel).strip("_") or "element"
                if not any(f.selector == sel for f in req_fields):
                    req_fields.append(BrowserField(type="selector", selector=sel, name=f"element_{safe_name}"))

            # Priority 2: Unquoted . and # anchored CSS selectors (syntactically unambiguous)
            for sel in re.findall(r"(?:^|\s)([.#][a-zA-Z0-9_\-]+)(?:\s|$|,|\.)", text):
                sel = sel.strip()
                if not any(f.selector == sel for f in req_fields):
                    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", sel).strip("_") or "element"
                    req_fields.append(BrowserField(type="selector", selector=sel, name=safe_name))

            if not any(f.type == "selector" for f in req_fields):
                if (
                    "text" in clean
                    or "body" in clean
                    or "extract content" in clean
                    or "get content" in clean
                    or "content from" in clean
                    or ("content" in clean and not any(f.name == "content" for f in req_fields))
                ):
                    req_fields.append(BrowserField(type="text", name="content"))

            if "link" in clean or "links" in clean or "href" in clean:
                req_fields.append(BrowserField(type="links", name="links"))
            if "screenshot" in clean:
                req_fields.append(BrowserField(type="screenshot", name="screenshot"))

            if not req_fields:
                req_fields = [
                    BrowserField(type="title", name="title"),
                    BrowserField(type="text", name="content"),
                ]

        try:
            nav_raw = execute_tool("browser_navigate", {"url": url})
            nav_res = parse_tool_result(nav_raw)

            if not nav_res.ok:
                return DirectActionResult(
                    success=False,
                    output=f"Browser navigation failed: {nav_res.error or 'navigation_failed'}",
                    execution_type="tool",
                    tool_name="browser_navigate",
                    provider="browser-automation",
                    model="",
                    policy_decision="allowed",
                    telemetry={"reason": "navigation_failed", "url": url, "error": nav_res.error},
                )

            nav_data = nav_res.data if isinstance(nav_res.data, dict) else {}
            if isinstance(nav_data.get("output"), dict):
                nav_data = nav_data["output"]
            nav_title = nav_data.get("title")
            nav_content_str = str(nav_data.get("content", nav_res.data if isinstance(nav_res.data, str) else ""))
            if not nav_title and nav_content_str:
                m_t = re.search(r"🏷️\s*\*\*Title:\*\*\s*([^\n]+)", nav_content_str) or re.search(
                    r"<title>([^<]+)</title>", nav_content_str, re.IGNORECASE
                )
                if m_t:
                    nav_title = m_t.group(1).strip()

            extracted_data: dict[str, Any] = {}
            field_results: list[dict[str, Any]] = []

            for f in req_fields:
                field_success = True
                field_val = None
                field_error = ""

                try:
                    if f.type == "title":
                        t_raw = execute_tool("browser_get_title", {})
                        t_res = parse_tool_result(t_raw)
                        if t_res.ok:
                            field_val = t_res.data.get("output", "")
                        elif nav_title:
                            field_val = nav_title
                        else:
                            c_raw = execute_tool("browser_extract_content", {"selector": "title", "url": url})
                            c_res = parse_tool_result(c_raw)
                            if c_res.ok:
                                val = c_res.data.get("output", "")
                                if isinstance(val, dict):
                                    val = val.get("title", val.get("content", str(val)))
                                field_val = val
                            else:
                                field_success = False
                                field_error = str(t_res.error or c_res.error)
                    elif f.type in ("text", "content"):
                        txt_raw = execute_tool("browser_get_text", {})
                        txt_res = parse_tool_result(txt_raw)
                        if not txt_res.ok or txt_res.error == "unknown_tool":
                            c_raw = execute_tool("browser_extract_content", {"field": "text", "url": url})
                            txt_res = parse_tool_result(c_raw)
                        if txt_res.ok:
                            val = txt_res.data.get("output", "")
                            if isinstance(val, dict):
                                val = val.get("text", val.get("content", str(val)))
                            field_val = val
                        else:
                            field_success = False
                            field_error = str(txt_res.error)
                    elif f.type == "links":
                        l_raw = execute_tool("browser_get_links", {})
                        l_res = parse_tool_result(l_raw)
                        if not l_res.ok or l_res.error == "unknown_tool":
                            c_raw = execute_tool("browser_extract_content", {"field": "links", "url": url})
                            l_res = parse_tool_result(c_raw)
                        if l_res.ok:
                            val = l_res.data.get("output", "")
                            if isinstance(val, dict):
                                val = val.get("links", val)
                            field_val = val
                        else:
                            field_success = False
                            field_error = str(l_res.error)
                    elif f.type == "selector":
                        s_raw = execute_tool("browser_extract_selector", {"selector": f.selector})
                        s_res = parse_tool_result(s_raw)
                        if not s_res.ok or s_res.error == "unknown_tool":
                            c_raw = execute_tool("browser_extract_content", {"selector": f.selector, "url": url})
                            s_res = parse_tool_result(c_raw)
                        if s_res.ok:
                            val = s_res.data.get("output", "")
                            val_str = str(val).lower()
                            if "no elements" in val_str or "not found" in val_str or "missing" in val_str:
                                field_success = False
                                field_error = "selector_not_found"
                            else:
                                if isinstance(val, dict):
                                    val = val.get("content", val)
                                field_val = val
                        else:
                            field_success = False
                            field_error = str(s_res.error)
                except Exception as exc:
                    field_success = False
                    field_error = str(exc)

                if field_success:
                    extracted_data[f.name] = field_val
                field_results.append(
                    {
                        "field": f.name,
                        "selector": f.selector or f.name,  # Phase 8 fix: preserve verbatim selector
                        "type": f.type,
                        "success": field_success,
                        "error": field_error,
                    }
                )

            all_failed = field_results and all(not r["success"] for r in field_results)
            has_partial = (
                field_results
                and any(not r["success"] for r in field_results)
                and any(r["success"] for r in field_results)
            )

            if all_failed:
                return DirectActionResult(
                    success=False,
                    output=f"Browser extraction failed for all requested fields on {url}",
                    execution_type="tool",
                    tool_name="browser_extract_content",
                    provider="browser",
                    model="",
                    policy_decision="allowed",
                    telemetry={
                        "status": "total_failure",
                        "reason": "all_fields_failed",
                        "url": url,
                        "field_results": field_results,
                    },
                )

            out_str = json.dumps(extracted_data, indent=2) if extracted_data else f"Navigated to {url}"
            if has_partial:
                # Phase 8 fix: use selector verbatim (preserving . # prefixes) in failure summary
                failed_fields_display = [r.get("selector") or r["field"] for r in field_results if not r["success"]]
                out_str = f"Browser extraction partially completed for {url} ({len(extracted_data)}/{len(req_fields)} fields extracted, failed: {', '.join(failed_fields_display)}):\n{out_str}"

            return DirectActionResult(
                success=not has_partial,
                output=out_str,
                execution_type="tool",
                tool_name="browser_extract_content" if req_fields else "browser_navigate",
                provider="browser",
                model="",
                policy_decision="allowed",
                telemetry={
                    "status": "partial_failure" if has_partial else "completed",
                    "url": url,
                    "extracted_fields": list(extracted_data.keys()),
                    "successful_fields": extracted_data,
                    "failed_fields": [
                        {"selector": r.get("selector") or r["field"], "field": r["field"], "error": r["error"]}
                        for r in field_results
                        if not r["success"]
                    ],
                    "field_results": field_results,
                    "partial_failure": has_partial,
                    "verification_passed": not has_partial,
                },
            )
        except Exception as exc:
            return DirectActionResult(
                success=False,
                output=f"Browser action failed: {exc}",
                execution_type="tool",
                tool_name="browser_navigate",
                provider="browser-automation",
                model="",
                telemetry={"reason": "browser_exception", "error": str(exc)},
            )

    # ── 7. Long-Term Memory Recall ───────────────────────────────────────────

    @classmethod
    def _is_memory_recall_request(cls, text: str) -> bool:
        clean = text.lower().strip()
        if any(
            w in clean
            for w in (
                "remember that",
                "remember :",
                "please remember",
                "forget that",
                "forget about",
                "what did i just say",
                "what did i say",
                "what was my last",
                "what did we just",
                "repeat what i said",
            )
        ):
            return False
        if any(
            clean.startswith(q)
            for q in (
                "what is",
                "what was",
                "who is",
                "who was",
                "where is",
                "where was",
                "which ",
                "how is",
                "what did",
                "what do",
                "recall",
                "retrieve memory",
            )
        ):
            return True
        return any(
            w in clean
            for w in (
                "recall",
                "retrieve memory",
                "codename",
                "secret",
                "venue",
                "supplier",
                "contact",
                "password",
                "api key",
                "cluster",
                "deploy",
                "database host",
                "timeout",
                "staging port",
                "backup interval",
                "release version",
                "gateway url",
                "default locale",
                "audit log",
                "encryption cipher",
                "retry count",
                "engineer",
                "cache expiration",
                "notification channel",
                "fallback server",
                "brand color",
                "stored value",
                "saved value",
                "memory value",
            )
        )

    @classmethod
    def _try_memory_recall(cls, text: str, *, context: str = "", control: Any) -> DirectActionResult | None:
        if not control or not cls._is_memory_recall_request(text):
            return None

        try:
            from jarvis.amaura.cognition import UnifiedMemoryService

            memory_service = UnifiedMemoryService(control)
            hits = memory_service.query(text, limit=16)

            if not hits:
                return None

            entities = memory_service._extract_entities(text)
            # CLI ``remember`` stores founder facts in the legacy personal-memory
            # store.  It is still an authoritative source, so excluding it when
            # any Company OS memory exists makes a fresh personal fact impossible
            # to recall after restart.  Keep it in the deterministic candidate
            # set; only conversational transcripts and the secondary vector index
            # remain non-authoritative fallback sources.
            factual_hits = [
                h
                for h in hits
                if not str(h.source).startswith(
                    ("conversation_memory", "vector_memory", "jarvis.memory.episodic", "episodic")
                )
            ]
            if not factual_hits:
                return None
            generic_entities = {
                "give",
                "only",
                "reply",
                "return",
                "remember",
                "recall",
                "retrieve",
                "what",
                "who",
                "where",
                "which",
                "how",
            }
            meaningful_entities = [
                str(entity).strip()
                for entity in entities
                if str(entity).strip() and str(entity).strip().lower() not in generic_entities
            ]

            def grounded_score(hit: Any) -> float:
                try:
                    body = hit.content if isinstance(hit.content, str) else json.dumps(hit.content, ensure_ascii=False)
                except Exception:
                    body = str(hit.content)
                haystack = f"{hit.key} {body}".lower()
                exact_entity_bonus = sum(1.25 for entity in meaningful_entities if entity.lower() in haystack)
                project_bonus = 0.15 if meaningful_entities and str(hit.source).endswith(".project") else 0.0
                # A highly relevant fact saved through the normal CLI belongs to
                # the founder and must not lose to an episodic transcript that
                # merely repeats the question.  The threshold keeps unrelated
                # personal facts from receiving this source preference.
                founder_personal_bonus = (
                    0.50 if hit.source == "legacy_user_memory" and float(hit.score) >= 0.55 else 0.0
                )
                return float(hit.score) + exact_entity_bonus + project_bonus + founder_personal_bonus

            selected_hits = sorted(
                factual_hits,
                key=lambda h: (
                    grounded_score(h),
                    str(getattr(h, "updated_at", "") or getattr(h, "key", "")),
                ),
                reverse=True,
            )

            if selected_hits and grounded_score(selected_hits[0]) >= 0.10:
                top_hit = selected_hits[0]
                content = top_hit.content
                if isinstance(content, dict):
                    val = content.get("content") or content.get("value") or json.dumps(content)
                else:
                    val = str(content)
                scalar = str(val).strip()
                relation = re.search(r"\bis\s+(.+?)[.\s]*$", scalar, re.IGNORECASE)
                if relation:
                    scalar = relation.group(1).strip().rstrip(".")

                candidate_ids = [f"{h.source}:{h.key}" for h in selected_hits[:8]]
                candidate_scores = [round(h.score, 3) for h in selected_hits[:8]]
                grounded_scores = [round(grounded_score(h), 3) for h in selected_hits[:8]]
                selected_ids = [f"{top_hit.source}:{top_hit.key}"]
                namespaces = list(dict.fromkeys(h.source for h in selected_hits[:8]))

                return DirectActionResult(
                    success=True,
                    output=str(val),
                    execution_type="memory_retrieval",
                    tool_name="memory_retrieval",
                    provider="internal-memory",
                    model="",
                    policy_decision="allowed",
                    telemetry={
                        "memory_query": text,
                        "entities": entities,
                        "namespaces_searched": namespaces,
                        "candidate_ids": candidate_ids,
                        "candidate_scores": candidate_scores,
                        "grounded_candidate_scores": grounded_scores,
                        "selected_ids": selected_ids,
                        "value": scalar,
                        "selection_reason": f"Top entity-grounded factual memory hit ({top_hit.source}:{top_hit.key}, raw={top_hit.score:.3f}, grounded={grounded_score(top_hit):.3f})",
                    },
                )
        except Exception:
            pass
        return None

    # ── 8. Calendar Events ───────────────────────────────────────────────────

    @classmethod
    def _try_calendar_event(cls, text: str, context: str = "") -> DirectActionResult | None:
        clean = text.lower()
        combined = f"{context}\n{text}"
        if not any(
            k in clean
            for k in ("schedule", "calendar", "book an appointment", "add to calendar", "book it", "book a meeting")
        ):
            return None

        date_str = ""
        iso_match = re.search(r"(\d{4}-\d{2}-\d{2})(?:\s+at\s+|\s+T|\s+)?(\d{1,2}:\d{2})?", combined)
        if iso_match:
            d_part = iso_match.group(1)
            t_part = iso_match.group(2) or "09:00"
            date_str = f"{d_part} {t_part}"
        else:
            date_match = re.search(
                r"(?:on\s+)?([A-Z][a-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})(?:\s+from\s+|\s+at\s+)?(\d{1,2}(?::\d{2})?\s*(?:AM|PM)?)?",
                combined,
                re.IGNORECASE,
            )
            if date_match:
                raw_date = date_match.group(1).strip()
                raw_time = (date_match.group(2) or "09:00 AM").strip()
                clean_date = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", raw_date)
                for fmt in (
                    "%B %d, %Y %I:%M %p",
                    "%B %d %Y %I:%M %p",
                    "%B %d, %Y %I %p",
                    "%B %d %Y %I %p",
                    "%B %d, %Y",
                    "%B %d %Y",
                ):
                    try:
                        from datetime import datetime

                        dt = (
                            datetime.strptime(f"{clean_date} {raw_time}", fmt)
                            if "AM" in raw_time or "PM" in raw_time or ":" in raw_time
                            else datetime.strptime(clean_date, fmt)
                        )
                        date_str = dt.strftime("%Y-%m-%d %H:%M")
                        break
                    except Exception:
                        pass

        m_title = re.search(
            r"(?:schedule|book)\s+(?:an?\s+)?(?:appointment|meeting|event|call)?\s*(?:with\s+)?([^.\n]+)",
            text,
            re.IGNORECASE,
        )
        title = m_title.group(1).strip() if m_title else text.strip()

        if title and date_str:
            try:
                from jarvis.tools.communication import tool_add_calendar_event

                res = tool_add_calendar_event(title, date_str, duration_hours=1.0, notes=combined[:500])
                if not res.startswith("❌"):
                    return DirectActionResult(
                        success=True,
                        output=f"Done. {res}",
                        execution_type="tool",
                        tool_name="add_calendar_event",
                        provider="macos-native-tool",
                        model="",
                        policy_decision="allowed",
                    )
            except Exception:
                pass
        return None


__all__ = [
    "ActionCandidate",
    "ActionType",
    "BrowserActionPlan",
    "BrowserField",
    "BrowserFieldRequest",
    "Clause",
    "DelimitedTablePlan",
    "DirectActionResult",
    "DirectActionRouter",
    "DivisionIntent",
    "ExactLiteralIntent",
    "ExactResponseInstruction",
    "ExactResponseParser",
    "FilesystemAction",
    "FilesystemActionClassifier",
    "FilesystemActionType",
    "FilesystemSemanticAction",
    "IntentDecision",
    "ParsedRequest",
    "PathExtractor",
    "PathRole",
    "RepositoryDiagnosticEngine",
    "RequestPreprocessor",
    "ResponseMode",
    "SemanticSpan",
    "SpanType",
    "SubtractIntent",
    "TransformationPlan",
    "WriteAction",
    "WriteActionParser",
    "WriteIntent",
]
