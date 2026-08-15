"""Compatibility adapters behind the Phase 9 SemanticRequestGraph.

These adapters never classify a competing top-level action. They normalize
syntax, collapse legacy exact-response entry points onto the semantic graph,
and preserve only explicitly-targeted non-arithmetic transformation workflows
behind the graph/effect firewall.
"""
from __future__ import annotations

import re
from typing import Any

_INSTALLED = False


def install_semantic_adapters() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from jarvis.amaura import direct_action as da
    from jarvis.amaura import semantic_core as core

    original_parse = core.SemanticParser.parse.__func__

    def normalized_parse(cls: Any, text: str, known_extensions: tuple[str, ...]) -> Any:
        # Syntax-only normalization before the one central semantic parse.
        normalized = re.sub(r"^(\s*(?:echo|repeat))\s*:\s*", r"\1 ", text, flags=re.IGNORECASE)

        # Canonicalize explicit write grammars while preserving the semantic
        # contract. These rewrites are allowed only when the sentence itself
        # names both payload and destination; path order is never used to infer
        # an output role.
        save_match = re.match(
            r"^\s*(?:save|write|store|put)\s+(['\"`])(?P<payload>.*?)\1\s+"
            r"(?:to|into|in|at)\s+['\"`]?(?P<path>[~/A-Za-z0-9_.\-/]+)['\"`]?\s*[.!]?\s*$",
            normalized,
            re.IGNORECASE | re.DOTALL,
        )
        if save_match:
            payload = save_match.group("payload")
            path = save_match.group("path")
            delimiter = "`" if "`" not in payload else "'"
            normalized = f'Create "{path}" containing {delimiter}{payload}{delimiter}'
        else:
            create_match = re.match(
                r"^\s*create\s+(?:a\s+)?(?:text\s+)?file\s+at\s+['\"`]?(?P<path>[~/A-Za-z0-9_.\-/]+)['\"`]?\s+"
                r"containing\s+(?:exactly\s+)?(?:this\s+)?(?:text|content|payload)?\s*:\s*(?P<payload>.+?)\s*$",
                normalized,
                re.IGNORECASE | re.DOTALL,
            )
            if create_match:
                payload = create_match.group("payload").strip()
                path = create_match.group("path")
                delimiter = "`" if "`" not in payload else "'"
                normalized = f'Create "{path}" containing {delimiter}{payload}{delimiter}'

        graph = original_parse(cls, normalized, known_extensions)
        graph.original_text = text

        # Phase 8 compatibility: absolute paths are commonly unquoted. Preserve
        # semantic operand roles for those forms rather than textual order.
        if graph.action == core.SemanticAction.ARITHMETIC and graph.arithmetic is not None:
            plan = graph.arithmetic
            lower = normalized.lower()
            if plan.operation == "subtract" and plan.provenance == "positional" and re.search(r"\b(?:subtract|take|deduct)\b.+?\b(?:from|away\s+from)\b", lower):
                plan.left_path, plan.right_path = plan.right_path, plan.left_path
                plan.left_role, plan.right_role = "minuend", "subtrahend"
                plan.provenance = "subtract_from_unquoted"
                if len(graph.paths) >= 2:
                    graph.paths[0] = core.PathBinding(plan.left_path, core.SemanticPathRole.INPUT, "minuend")
                    graph.paths[1] = core.PathBinding(plan.right_path, core.SemanticPathRole.SECONDARY_INPUT, "subtrahend")
            elif plan.operation == "divide" and plan.provenance == "positional" and re.search(r"\bdivide\b.+?\binto\b", lower):
                plan.left_path, plan.right_path = plan.right_path, plan.left_path
                plan.left_role, plan.right_role = "numerator", "denominator"
                plan.provenance = "divide_into_unquoted"
                if len(graph.paths) >= 2:
                    graph.paths[0] = core.PathBinding(plan.left_path, core.SemanticPathRole.INPUT, "numerator")
                    graph.paths[1] = core.PathBinding(plan.right_path, core.SemanticPathRole.SECONDARY_INPUT, "denominator")
        return graph

    core.SemanticParser.parse = classmethod(normalized_parse)

    # Collapse cognition.py's direct ExactResponseParser.parse() fast path onto
    # the same semantic graph. There is no second exact parser anymore.
    def exact_via_graph(cls: Any, text: str, workspace: str = "") -> Any:
        graph = core.SemanticParser.parse(text, da.RequestPreprocessor.KNOWN_EXTENSIONS)
        if graph.action != core.SemanticAction.EXACT_LITERAL:
            return None
        return da.DirectActionResult(
            success=True,
            output=graph.literal_payload,
            execution_type="semantic_graph",
            tool_name="exact_response",
            provider="semantic-core",
            model="",
            policy_decision="allowed",
            telemetry={
                "semantic_action": graph.action.value,
                "side_effects": "none",
                "verification_passed": True,
            },
        )

    da.ExactResponseParser.parse = classmethod(exact_via_graph)

    # Repository execution is invoked only after SemanticRequestGraph classified
    # the request as REPOSITORY. The legacy adapter must not re-veto that action.
    original_repo_try = da.DirectActionRouter._try_repository_inspection.__func__

    def graph_authorized_repo_try(cls: Any, text: str, workspace: str = "") -> Any:
        original_descriptor = cls.__dict__.get("_is_repository_inspection_request")
        cls._is_repository_inspection_request = classmethod(lambda _cls, _text: True)
        try:
            return original_repo_try(cls, text, workspace=workspace)
        finally:
            if original_descriptor is not None:
                cls._is_repository_inspection_request = original_descriptor

    da.DirectActionRouter._try_repository_inspection = classmethod(graph_authorized_repo_try)

    # Preserve healthy Phase 8 transformations (CSV/TSV -> JSON, prefix/suffix,
    # KV conversion, replace/concatenate) only as a post-graph compatibility
    # path. Safety requirements: core graph did not recognize another action,
    # arithmetic is excluded, and an explicit output role is proven first.
    core_can_handle = da.DirectActionRouter.can_handle.__func__
    core_execute = da.DirectActionRouter.execute.__func__

    def safe_legacy_workflow(cls: Any, text: str) -> tuple[bool, str]:
        graph = core.SemanticParser.parse(text, da.RequestPreprocessor.KNOWN_EXTENSIONS)
        if graph.action != core.SemanticAction.UNKNOWN:
            return False, ""
        lower = text.lower()
        if re.search(r"\b(?:add|sum|total|subtract|minus|difference|deduct|multiply|product|divide|quotient)\b", lower):
            return False, ""
        paths = core.extract_paths(text, da.RequestPreprocessor.KNOWN_EXTENSIONS)
        output = core._explicit_output(text, paths)
        if not output:
            return False, ""
        return bool(cls._is_workflow_request(text)), output

    def compat_can_handle(cls: Any, text: str) -> bool:
        if core_can_handle(cls, text):
            return True
        legacy, _ = safe_legacy_workflow(cls, text)
        return legacy

    def compat_execute(cls: Any, text: str, *, context: str = "", control: Any = None, workspace: str = "") -> Any:
        graph = core.SemanticParser.parse(text, da.RequestPreprocessor.KNOWN_EXTENSIONS)
        if graph.action != core.SemanticAction.UNKNOWN:
            result = core_execute(cls, text, context=context, control=control, workspace=workspace)
            # Preserve the public compatibility contract for concrete tool-backed
            # operations while the semantic graph remains visible in telemetry.
            if result is not None and graph.action in {
                core.SemanticAction.FILE_READ,
                core.SemanticAction.FILE_WRITE,
                core.SemanticAction.DIRECTORY_LIST,
                core.SemanticAction.BROWSER,
                core.SemanticAction.SCREENSHOT,
            }:
                result.execution_type = "tool"
            return result

        legacy, output = safe_legacy_workflow(cls, text)
        if not legacy:
            return None

        token_effect = core._EFFECT_SCOPE.set(frozenset({"write_file"}))
        token_output = core._OUTPUT_SCOPE.set(frozenset({output}))
        try:
            result = cls._try_multi_step_workflow(text, workspace=workspace)
        finally:
            core._OUTPUT_SCOPE.reset(token_output)
            core._EFFECT_SCOPE.reset(token_effect)

        render_graph = core.SemanticRequestGraph(
            original_text=text,
            action=core.SemanticAction.UNKNOWN,
            response_mode=core._response_mode(text),
            paths=[core.PathBinding(output, core.SemanticPathRole.OUTPUT, "explicit_legacy_transform_output")],
        )
        return core._render(da, render_graph, result)

    da.DirectActionRouter.can_handle = classmethod(compat_can_handle)
    da.DirectActionRouter.execute = classmethod(compat_execute)
    _INSTALLED = True
