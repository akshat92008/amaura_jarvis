"""Compatibility adapters behind the Phase 9 SemanticRequestGraph.

These adapters never classify a competing top-level action. They normalize
syntax, enrich typed roles for legacy public phrasings, collapse direct
exact-response entry points onto the semantic graph, and preserve only
explicitly-targeted transformations behind the graph/effect firewall.
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

    def explicit_transform_output(text: str, paths: list[str]) -> str:
        """Recognize only language-explicit transformation destinations."""
        lower = text.lower()
        for path in paths:
            escaped = re.escape(path.lower())
            patterns = (
                rf"\b(?:create|make)\s+(?:a\s+)?(?:json\s+|text\s+|output\s+)?file\s+(?:at|to|in)\s+['\"`]?{escaped}",
                rf"\b(?:save|write|store)\s+(?:the\s+)?(?:output|result|data|json)?\s*(?:to|at|in|into)\s+['\"`]?{escaped}",
            )
            if any(re.search(pattern, lower, re.IGNORECASE) for pattern in patterns):
                return path
        return ""

    def normalized_parse(cls: Any, text: str, known_extensions: tuple[str, ...]) -> Any:
        # Syntax-only normalization before the one central semantic parse.
        normalized = re.sub(r"^(\s*(?:echo|repeat))\s*:\s*", r"\1 ", text, flags=re.IGNORECASE)
        normalized = re.sub(
            r"^(\s*(?:reply|respond))\s+with\s+exactly\s*:\s*",
            r"\1 exactly ",
            normalized,
            flags=re.IGNORECASE,
        )

        # Canonicalize explicit write grammars while preserving the semantic
        # contract. Both payload and destination must be present in the sentence;
        # path order is never used to infer an output role.
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

        # Natural read phrasing retained from the pre-Phase-9 API. Map "what is
        # inside" to FILE_READ only when the target has a known file extension.
        if graph.action == core.SemanticAction.UNKNOWN:
            paths = core.extract_paths(normalized, known_extensions)
            if (
                paths
                and re.search(r"\bwhat\s+is\s+inside\b", normalized, re.IGNORECASE)
                and any(paths[0].lower().endswith(ext) for ext in known_extensions)
            ):
                graph = core.SemanticRequestGraph(
                    original_text=text,
                    action=core.SemanticAction.FILE_READ,
                    response_mode=core._response_mode(text),
                    paths=[core.PathBinding(paths[0], core.SemanticPathRole.INPUT, "natural_inside_file_read")],
                    evidence=["natural_inside_file_read"],
                )

        # Memory questions historically allow natural phrasings such as "What
        # codename did I assign..." without saying "memory". Reuse the mature
        # predicate only to enrich the graph after no other action was selected.
        if graph.action == core.SemanticAction.UNKNOWN and da.DirectActionRouter._is_memory_recall_request(normalized):
            graph = core.SemanticRequestGraph(
                original_text=text,
                action=core.SemanticAction.MEMORY_RECALL,
                response_mode=core._response_mode(text),
                evidence=["legacy_memory_predicate_enriched_graph"],
            )

        # Explicit read-transform-write requests are delegated to the retained
        # transformation executor only after proving an output destination. Mark
        # the graph UNKNOWN here so compat_execute can enter that gated adapter.
        paths = core.extract_paths(normalized, known_extensions)
        transform_output = explicit_transform_output(normalized, paths)
        has_transform_shape = (
            len(paths) >= 2
            and bool(transform_output)
            and bool(re.search(r"\b(?:read|extract|convert|transform|prefix|suffix|replace|concatenate)\b", normalized, re.IGNORECASE))
        )
        if graph.action == core.SemanticAction.FILE_WRITE and graph.errors and has_transform_shape:
            graph = core.SemanticRequestGraph(
                original_text=text,
                action=core.SemanticAction.UNKNOWN,
                response_mode=core._response_mode(text),
                evidence=["explicit_transform_compatibility"],
            )

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

    # Extend PathExtractor's structured arguments only with language-proven roles
    # needed by the retained transform executor. There is still no positional
    # output fallback in the active semantic path.
    base_structured_args = da.PathExtractor.extract_structured_arguments.__func__

    def structured_args_with_explicit_transforms(cls: Any, text: str, *, default_workspace: str = "") -> dict[str, Any]:
        args = dict(base_structured_args(cls, text, default_workspace=default_workspace))
        paths = core.extract_paths(text, da.RequestPreprocessor.KNOWN_EXTENSIONS)
        output = explicit_transform_output(text, paths)
        if output:
            args["output_path"] = output
            inputs = [path for path in paths if path != output]
            if inputs:
                args["input_path"] = inputs[0]
            if len(inputs) > 1:
                args["secondary_input_path"] = inputs[1]
        return args

    da.PathExtractor.extract_structured_arguments = classmethod(structured_args_with_explicit_transforms)

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
        output = core._explicit_output(text, paths) or explicit_transform_output(text, paths)
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
            if graph.action == core.SemanticAction.BROWSER and graph.browser is not None:
                url_lower = graph.browser.url.lower()
                if "169.254.169.254" in url_lower or "metadata.google.internal" in url_lower:
                    return da.DirectActionResult(
                        success=False,
                        output="Access to cloud metadata endpoints is blocked by security policy.",
                        execution_type="tool",
                        tool_name="browser_navigate",
                        provider="browser",
                        model="",
                        policy_decision="refused",
                        telemetry={"reason": "metadata_endpoint_refusal", "url": graph.browser.url},
                    )

            result = core_execute(cls, text, context=context, control=control, workspace=workspace)
            if result is None:
                return None

            if graph.action in {
                core.SemanticAction.FILE_READ,
                core.SemanticAction.FILE_WRITE,
                core.SemanticAction.DIRECTORY_LIST,
                core.SemanticAction.BROWSER,
                core.SemanticAction.SCREENSHOT,
            }:
                result.execution_type = "tool"
            if graph.action == core.SemanticAction.EXACT_LITERAL:
                result.execution_type = "exact_response"
            if graph.action == core.SemanticAction.BROWSER:
                result.provider = "browser"
            if graph.action == core.SemanticAction.POLICY_REFUSAL and "Policy refusal" not in result.output:
                result.output = f"Policy refusal: {result.output}"
            if graph.action == core.SemanticAction.FILE_WRITE and not result.success:
                error_text = str((result.telemetry or {}).get("error", result.output)).lower()
                target = graph.output_path.lower()
                sensitive_target = any(marker in target for marker in ("~/.ssh", "~/.aws", "~/.gnupg", "/.ssh/", "/.aws/"))
                policy_error = any(marker in error_text for marker in ("permission", "sensitive", "blocked", "outside workspace", "escape"))
                if sensitive_target or policy_error:
                    result.provider = "security-policy"
                    result.policy_decision = "refused"
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
