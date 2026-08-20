"""Narrow semantic hardening for deterministic multi-step workflow routing.

Filesystem paths, URLs and quoted payloads are data, not action vocabulary.
The legacy workflow planner still performs arithmetic substring checks over the
raw request, so randomized file names such as ``device_add123.txt`` can
accidentally turn a key/value-to-JSON extraction into arithmetic. This decorator
keeps the stable planner/path-role logic, then validates only arithmetic
operations against the preprocessor's masked classifier view before execution.
"""

from __future__ import annotations

import re
from typing import Any

_INSTALLED = False

_ARITHMETIC_PATTERNS: dict[str, tuple[str, ...]] = {
    "add": (
        r"\bsum\b",
        r"\btotal\b",
        r"\badd\b",
        r"\baddition\b",
        r"\bcalculate\s+(?:the\s+)?sum\b",
        r"\bcompute\s+(?:the\s+)?sum\b",
    ),
    "subtract": (
        r"\bsubtract\b",
        r"\bdifference\b",
        r"\bminus\b",
        r"\bsubtraction\b",
        r"\bdeduct\b",
        r"\baway\s+from\b",
    ),
    "multiply": (
        r"\bmultiply\b",
        r"\bproduct\b",
        r"\bmultiplication\b",
        r"\btimes\b",
    ),
    "divide": (
        r"\bdivide\b",
        r"\bquotient\b",
        r"\bdivision\b",
        r"\bdivided\s+by\b",
    ),
}


def _intent_requests_arithmetic(masked_view: str, operation: str) -> bool:
    return any(
        re.search(pattern, masked_view, re.IGNORECASE)
        for pattern in _ARITHMETIC_PATTERNS.get(operation, ())
    )


def _repair_false_positive_arithmetic(plan: Any, masked_view: str) -> Any:
    operation = str(getattr(plan, "operation", "") or "")
    if operation not in _ARITHMETIC_PATTERNS or _intent_requests_arithmetic(masked_view, operation):
        return plan

    output_format = str(getattr(plan, "output_format", "") or "").lower()
    output_path = str(getattr(plan, "output_path", "") or "").lower()
    inputs = list(getattr(plan, "inputs", []) or [])

    # Match the legacy planner's non-arithmetic behavior after removing the
    # accidental trigger. JSON destinations use the existing deterministic
    # structured-text parser, which handles key:value, CSV/TSV and table input.
    if output_format == "json" or output_path.endswith(".json"):
        plan.operation = "delimited_table_to_json"
        plan.output_format = "json"
    else:
        plan.operation = "concatenate" if len(inputs) > 1 else "identity"
    plan.parameters = {}
    plan.input_roles = []
    return plan


def install_direct_action_semantic_repair() -> None:
    """Install the masked arithmetic-intent guard once after semantic decorators."""
    global _INSTALLED
    if _INSTALLED:
        return

    from jarvis.amaura.direct_action import DirectActionRouter, RequestPreprocessor

    # Read the raw class descriptor instead of the bound method. This preserves
    # the original classmethod semantics and avoids assigning directly to a
    # statically-declared method, which is rejected by strict mypy.
    current_descriptor: Any = DirectActionRouter.__dict__.get("_parse_workflow_plan")
    if current_descriptor is None:
        raise RuntimeError("DirectActionRouter._parse_workflow_plan is unavailable")
    current = DirectActionRouter._parse_workflow_plan
    if getattr(current, "_arch_masked_workflow_guard", False):
        _INSTALLED = True
        return
    original = current_descriptor.__func__

    def guarded_parse_workflow_plan(cls: type[Any], text: str, default_workspace: str = "") -> Any:
        plan = original(cls, text, default_workspace=default_workspace)
        if plan is None:
            return None
        parsed = RequestPreprocessor.process(text)
        return _repair_false_positive_arithmetic(plan, parsed.masked_classifier_view)

    guarded_parse_workflow_plan._arch_masked_workflow_guard = True  # type: ignore[attr-defined]
    DirectActionRouter._parse_workflow_plan = classmethod(guarded_parse_workflow_plan)  # type: ignore[method-assign,assignment]
    _INSTALLED = True


__all__ = ["install_direct_action_semantic_repair"]
