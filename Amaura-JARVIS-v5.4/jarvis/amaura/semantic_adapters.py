"""Compatibility adapters behind the Phase 9 SemanticRequestGraph.

The adapters in this module do not create a second routing system.  They only
normalize established public phrasings into typed graph intents/roles and keep a
small set of mature transformations behind the graph's effect firewall.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
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

    def _explicit_write_parts(text: str) -> tuple[str, str] | None:
        """Return (payload, target) only when both roles are explicit in grammar."""
        patterns = (
            # payload first: Save 'x' to 'file', Write data 'x' to destination 'file', etc.
            r"^\s*(?:please\s+)?(?:save|write|put|store|output|record|dump)\s+(?:out\s+)?(?:the\s+)?(?:text\s+|data\s+|content\s+|payload\s+|following\s+)?(?P<q>['\"`])(?P<payload>.*?)(?P=q)\s+(?:to|into|in|at)\s+(?:file\s+|destination\s+)?(?P<qp>['\"`]?)(?P<path>[~/A-Za-z0-9_.\-/]+)(?P=qp)\s*[.!]?\s*$",
            # target first: Create file 'p' containing/with content 'x'.
            r"^\s*(?:please\s+)?create\s+(?:a\s+)?(?:new\s+)?(?:text\s+)?file\s+(?:at\s+)?(?P<qp>['\"`]?)(?P<path>[~/A-Za-z0-9_.\-/]+)(?P=qp)\s+(?:containing|with\s+(?:content|text|data|payload))\s+(?:exactly\s+)?(?:this\s+)?(?:text\s*:?[ ]*)?(?P<q>['\"`])(?P<payload>.*?)(?P=q)\s*[.!]?\s*$",
            # "Please create 'p' containing 'x'".
            r"^\s*(?:please\s+)?create\s+(?P<qp>['\"`])(?P<path>[^'\"`\n]+)(?P=qp)\s+containing\s+(?P<q>['\"`])(?P<payload>.*?)(?P=q)\s*[.!]?\s*$",
            # "Put the following in 'p': 'x'".
            r"^\s*(?:please\s+)?put\s+the\s+following\s+in\s+(?P<qp>['\"`])(?P<path>[^'\"`\n]+)(?P=qp)\s*:\s*(?P<q>['\"`])(?P<payload>.*?)(?P=q)\s*[.!]?\s*$",
            # "Write to 'p' with data 'x'".
            r"^\s*(?:please\s+)?write\s+to\s+(?P<qp>['\"`])(?P<path>[^'\"`\n]+)(?P=qp)\s+with\s+(?:data|content|text|payload)\s+(?P<q>['\"`])(?P<payload>.*?)(?P=q)\s*[.!]?\s*$",
        )
        for pattern in patterns:
            match = re.match(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                return match.group("payload"), match.group("path")
        return None

    def _known_file(path: str, known_extensions: tuple[str, ...]) -> bool:
        return any(path.lower().endswith(ext) for ext in known_extensions)

    def _quoted_target(text: str) -> str:
        """Extract a quoted target from a read/list grammar, never from free text."""
        patterns = (
            r"\b(?:files?|entries|items|filenames|directory|folder)\b[^'\"`\n]*['\"`]([^'\"`\n]+)['\"`]",
            r"\b(?:inside|under|from|in|at|of|located\s+at)\b\s*['\"`]([^'\"`\n]+)['\"`]",
            r"['\"`]([^'\"`\n]+)['\"`]\s*(?:contain|contains|contain\?|\?|$)",
        )
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        return ""

    def _read_semantics(text: str) -> bool:
        lower = text.lower()
        return bool(re.search(
            r"\b(?:read|open|display|show|cat|load|fetch|view|print|examine|inspect|retrieve)\b",
            lower,
        )) or bool(re.search(
            r"\b(?:get\s+text|what\s+is\s+inside|what\s+does\b.+\bcontain|content\s+of|contents\s+of|text\s+inside|stored\s+in|what(?:'s|\s+is)\s+written)\b",
            lower,
        ))

    def _list_semantics(text: str) -> bool:
        lower = text.lower()
        return bool(re.search(
            r"\b(?:list\s+(?:all\s+)?(?:files|directory|folder|entries|items)|show\s+(?:me\s+)?(?:files|entries)|give\s+filenames|what\s+(?:files|entries)\b|directory\s+contents|folder\s+contents|files\s+exist)\b",
            lower,
        ))

    def normalized_parse(cls: Any, text: str, known_extensions: tuple[str, ...]) -> Any:
        # Syntax-only normalization before the one central semantic parse.
        normalized = re.sub(r"^(\s*(?:echo|repeat))\s*:\s*", r"\1 ", text, flags=re.IGNORECASE)
        normalized = re.sub(
            r"^(\s*(?:reply|respond|return|say))\s+(?:with\s+)?(?:only\s+)?exactly\s*:\s*",
            r"\1 exactly ",
            normalized,
            flags=re.IGNORECASE,
        )
        normalized = re.sub(
            r"^(\s*(?:return|say))\s+only\s*:\s*",
            r"\1 exactly ",
            normalized,
            flags=re.IGNORECASE,
        )

        # Canonicalize public write phrasings only when grammar proves both
        # payload and destination.  No positional path fallback exists here.
        write_parts = _explicit_write_parts(normalized)
        if write_parts is not None:
            payload, path = write_parts
            delimiter = "`" if "`" not in payload else "'"
            normalized = f'Create "{path}" containing {delimiter}{payload}{delimiter}'

        graph = original_parse(cls, normalized, known_extensions)
        graph.original_text = text

        paths = core.extract_paths(normalized, known_extensions)
        explicit_quoted_target = _quoted_target(normalized)
        if explicit_quoted_target and explicit_quoted_target not in paths:
            # Only read/list grammar may promote a non-path-looking quoted token
            # (e.g. a directory name without slash/extension) to a typed target.
            paths = [explicit_quoted_target, *paths]

        # File-content language wins over the broad repository "inspect" verb.
        # A known file extension is required so "inspect /repo" stays REPOSITORY.
        if paths and _known_file(paths[0], known_extensions) and _read_semantics(normalized):
            graph = core.SemanticRequestGraph(
                original_text=text,
                action=core.SemanticAction.FILE_READ,
                response_mode=core._response_mode(text),
                paths=[core.PathBinding(paths[0], core.SemanticPathRole.INPUT, "explicit_file_content_target")],
                evidence=["typed_file_read_compatibility"],
            )

        # Directory listing paraphrases may use a bare quoted directory name.
        if _list_semantics(normalized):
            target = paths[0] if paths else explicit_quoted_target
            if target and not _known_file(target, known_extensions):
                graph = core.SemanticRequestGraph(
                    original_text=text,
                    action=core.SemanticAction.DIRECTORY_LIST,
                    response_mode=core._response_mode(text),
                    paths=[core.PathBinding(target, core.SemanticPathRole.TARGET, "explicit_directory_target")],
                    evidence=["typed_directory_list_compatibility"],
                )

        # Memory questions historically allow natural phrasings without saying
        # "memory".  Reuse the mature predicate only after no other typed action.
        if graph.action == core.SemanticAction.UNKNOWN and da.DirectActionRouter._is_memory_recall_request(normalized):
            graph = core.SemanticRequestGraph(
                original_text=text,
                action=core.SemanticAction.MEMORY_RECALL,
                response_mode=core._response_mode(text),
                evidence=["legacy_memory_predicate_enriched_graph"],
            )

        # Explicit read-transform-write requests are delegated only after proving
        # a destination role.  They never authorize "last path = output".
        transform_paths = core.extract_paths(normalized, known_extensions)
        transform_output = explicit_transform_output(normalized, transform_paths)
        has_transform_shape = (
            len(transform_paths) >= 2
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

        # Phase 8 compatibility: absolute operands are commonly unquoted.  Roles
        # are derived from the operator grammar, never textual last-path order.
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

    # Extend structured arguments only with language-proven transformation roles.
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

    # Collapse cognition.py's direct exact fast path onto the same graph while
    # retaining the public provenance contract expected by callers.
    def exact_via_graph(cls: Any, text: str, workspace: str = "") -> Any:
        graph = core.SemanticParser.parse(text, da.RequestPreprocessor.KNOWN_EXTENSIONS)
        if graph.action != core.SemanticAction.EXACT_LITERAL:
            return None
        return da.DirectActionResult(
            success=True,
            output=graph.literal_payload,
            execution_type="exact_response",
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

    # Repository execution is invoked only after the graph classified REPOSITORY;
    # the legacy adapter must not re-veto that already-typed action.
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

    def _parse_scalar(value: str) -> Any:
        stripped = value.strip()
        if re.fullmatch(r"[-+]?\d+", stripped):
            return int(stripped)
        if re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+)", stripped):
            return float(stripped)
        if stripped.lower() == "true":
            return True
        if stripped.lower() == "false":
            return False
        if stripped.lower() in {"null", "none"}:
            return None
        return stripped

    def _verified_key_value_json(text: str, workspace: str, output: str) -> Any | None:
        """Execute the common key:value -> JSON workflow without legacy re-parsing."""
        if not output.lower().endswith(".json"):
            return None
        paths = core.extract_paths(text, da.RequestPreprocessor.KNOWN_EXTENSIONS)
        input_candidates = [path for path in paths if path != output]
        if len(input_candidates) != 1:
            return None
        input_path = input_candidates[0]
        if not re.search(r"\b(?:extract\s+(?:data|fields)|convert\b|json\b)\b", text, re.IGNORECASE):
            return None

        ws = Path(workspace if workspace else da.workspace_root()).expanduser().resolve()
        try:
            with da.tool_workspace(ws):
                resolved_input = da.resolve_workspace_path(input_path, must_exist=True)
                resolved_output = da.resolve_workspace_path(output, must_exist=False)
                read_result = da.parse_tool_result(da.execute_tool("read_file", {"path": str(resolved_input)}))
            if not read_result.ok:
                return da.DirectActionResult(
                    False,
                    f"Workflow read failed: {read_result.error or 'read tool failed'}",
                    execution_type="workflow",
                    tool_name="multi_step_workflow",
                    provider="local-filesystem",
                    telemetry={"reason": "tool_failed", "verification_passed": False},
                )
            raw = core._tool_output(read_result)
            if isinstance(raw, dict):
                raw = raw.get("content", raw.get("text", raw.get("output", "")))
            source = str(raw)
            parsed: dict[str, Any] = {}
            for line in source.splitlines():
                if not line.strip() or ":" not in line:
                    continue
                key, value = line.split(":", 1)
                key = key.strip()
                if key:
                    parsed[key] = _parse_scalar(value)
            if not parsed:
                return da.DirectActionResult(
                    False,
                    "Workflow source contained no key:value fields.",
                    execution_type="workflow",
                    tool_name="multi_step_workflow",
                    provider="local-filesystem",
                    telemetry={"reason": "transform_failed", "verification_passed": False},
                )
            payload = json.dumps(parsed, ensure_ascii=False, indent=2)
            with da.tool_workspace(ws):
                write_result = da.parse_tool_result(da.execute_tool("write_file", {"path": str(resolved_output), "content": payload}))
            if not write_result.ok:
                return da.DirectActionResult(
                    False,
                    f"Workflow write failed: {write_result.error or 'write tool failed'}",
                    execution_type="workflow",
                    tool_name="multi_step_workflow",
                    provider="local-filesystem",
                    telemetry={"reason": "tool_failed", "verification_passed": False},
                )
            try:
                observed = json.loads(resolved_output.read_text(encoding="utf-8"))
            except Exception as exc:
                return da.DirectActionResult(
                    False,
                    f"Workflow verification failed: {exc}",
                    execution_type="workflow",
                    tool_name="multi_step_workflow",
                    provider="local-filesystem",
                    telemetry={"reason": "content_mismatch", "verification_passed": False},
                )
            if observed != parsed:
                return da.DirectActionResult(
                    False,
                    "Workflow verification failed: persisted JSON does not match transformed source.",
                    execution_type="workflow",
                    tool_name="multi_step_workflow",
                    provider="local-filesystem",
                    telemetry={"reason": "content_mismatch", "verification_passed": False, "expected": parsed, "observed": observed},
                )
            return da.DirectActionResult(
                True,
                f"Successfully transformed {resolved_input} to {resolved_output} and independently verified the result.",
                execution_type="workflow",
                tool_name="multi_step_workflow",
                provider="local-filesystem",
                telemetry={
                    "verification_passed": True,
                    "input_path": str(resolved_input),
                    "output_path": str(resolved_output),
                    "value": parsed,
                },
            )
        except (PermissionError, FileNotFoundError) as exc:
            return da.DirectActionResult(
                False,
                f"Workflow path rejected: {exc}",
                execution_type="workflow",
                tool_name="multi_step_workflow",
                provider="security-policy" if isinstance(exc, PermissionError) else "local-filesystem",
                policy_decision="refused" if isinstance(exc, PermissionError) else "allowed",
                telemetry={"reason": "path_rejected", "error": str(exc), "verification_passed": False},
            )
        except Exception as exc:
            return da.DirectActionResult(
                False,
                f"Workflow failed: {exc}",
                execution_type="workflow",
                tool_name="multi_step_workflow",
                provider="local-filesystem",
                telemetry={"reason": "workflow_failed", "error": str(exc), "verification_passed": False},
            )

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

            error_text = str((result.telemetry or {}).get("error", result.output)).lower()
            policy_error = any(marker in error_text for marker in ("permission", "sensitive", "blocked", "outside workspace", "escape", "symlink"))
            if graph.action in {core.SemanticAction.FILE_READ, core.SemanticAction.FILE_WRITE, core.SemanticAction.DIRECTORY_LIST} and not result.success and policy_error:
                result.provider = "security-policy"
                result.policy_decision = "refused"

            if graph.action == core.SemanticAction.FILE_WRITE and not result.success:
                target = graph.output_path.lower()
                sensitive_target = any(marker in target for marker in ("~/.ssh", "~/.aws", "~/.gnupg", "/.ssh/", "/.aws/"))
                if sensitive_target:
                    result.provider = "security-policy"
                    result.policy_decision = "refused"
                if "content mismatch" in error_text:
                    result.telemetry["reason"] = "content_mismatch"
                    result.telemetry["verification_passed"] = False
                elif result.policy_decision != "refused":
                    result.telemetry["reason"] = "tool_failed"
                    result.telemetry["verification_passed"] = False
            return result

        legacy, output = safe_legacy_workflow(cls, text)
        if not legacy:
            return None

        token_effect = core._EFFECT_SCOPE.set(frozenset({"write_file"}))
        token_output = core._OUTPUT_SCOPE.set(frozenset({output}))
        try:
            verified = _verified_key_value_json(text, workspace, output)
            if verified is not None:
                result = verified
            else:
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
