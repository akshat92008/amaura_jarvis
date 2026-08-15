"""Final public-contract normalization for the Phase 9 semantic boundary.

This module fixes two compatibility contracts without introducing a competing
router:

1. An explicit read -> transform/extract -> write request must remain one
   workflow, rather than being prematurely classified as a plain FILE_READ.
2. Exact-response callers historically expose ``tool_name='echo'`` in
   provenance; execution still uses the SemanticRequestGraph and has no effects.

The transform normalizer is deliberately fail-closed: it requires at least two
syntactically valid paths and an output path explicitly introduced by mutation
language.  Path order alone never authorizes a destination.
"""
from __future__ import annotations

import re
from typing import Any

_INSTALLED = False


def install_semantic_release_contracts() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from jarvis.amaura import direct_action as da
    from jarvis.amaura import semantic_core as core

    current_parse = core.SemanticParser.parse.__func__

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

    def parse_with_workflow_precedence(
        cls: Any,
        text: str,
        known_extensions: tuple[str, ...],
    ) -> Any:
        graph = current_parse(cls, text, known_extensions)
        paths = core.extract_paths(text, known_extensions)
        output = _explicit_transform_output(text, paths)
        has_explicit_transform = (
            len(paths) >= 2
            and bool(output)
            and bool(re.search(
                r"\b(?:read|load|fetch)\b.*\b(?:extract|convert|transform)\b|"
                r"\b(?:extract|convert|transform)\b.*\b(?:save|write|create|export)\b",
                text,
                re.IGNORECASE | re.DOTALL,
            ))
        )
        if has_explicit_transform:
            # UNKNOWN here does not mean unparsed. It is the compatibility signal
            # consumed by the already-installed graph-authorized workflow adapter,
            # which independently proves the same explicit output before enabling
            # write_file in the effect scope.
            return core.SemanticRequestGraph(
                original_text=text,
                action=core.SemanticAction.UNKNOWN,
                response_mode=core._response_mode(text),
                evidence=["explicit_transform_workflow_precedence"],
            )
        return graph

    core.SemanticParser.parse = classmethod(parse_with_workflow_precedence)

    current_router_execute = da.DirectActionRouter.execute.__func__

    def execute_with_public_exact_provenance(
        cls: Any,
        text: str,
        *,
        context: str = "",
        control: Any = None,
        workspace: str = "",
    ) -> Any:
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

    da.DirectActionRouter.execute = classmethod(execute_with_public_exact_provenance)

    current_exact_parse = da.ExactResponseParser.parse.__func__

    def exact_with_public_provenance(cls: Any, text: str, workspace: str = "") -> Any:
        result = current_exact_parse(cls, text, workspace=workspace)
        if result is not None:
            result.tool_name = "echo"
        return result

    da.ExactResponseParser.parse = classmethod(exact_with_public_provenance)
    _INSTALLED = True
