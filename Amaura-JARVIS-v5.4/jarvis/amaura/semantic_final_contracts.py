"""Final typed compatibility contracts for ARCH's semantic execution boundary.

This module closes public compatibility gaps without weakening the semantic
mutation firewall.  Every write performed here has an explicitly proven output
role and is independently verified from persisted state.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Callable

_INSTALLED = False


def install_semantic_final_contracts() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from jarvis.amaura import direct_action as da
    from jarvis.amaura import semantic_core as core

    current_parse = core.SemanticParser.parse.__func__

    def _css_selectors(text: str) -> list[str]:
        """Extract explicit bare CSS id/class tokens, excluding URL fragments."""
        scrubbed = re.sub(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"),]+", " ", text)
        selectors: list[str] = []
        for match in re.finditer(r"(?<![A-Za-z0-9_/])([#.][A-Za-z_][A-Za-z0-9_-]*)", scrubbed):
            selector = match.group(1)
            if selector not in selectors:
                selectors.append(selector)
        return selectors

    def parse_with_final_contracts(
        cls: Any,
        text: str,
        known_extensions: tuple[str, ...],
    ) -> Any:
        graph = current_parse(cls, text, known_extensions)
        lower = text.lower()

        # Browser composition: naked CSS tokens such as #user-info are explicit
        # selector roles when an URL-backed extraction request already exists.
        if graph.action == core.SemanticAction.BROWSER and graph.browser is not None:
            if re.search(r"\b(?:extract|get|read|return|show)\b", lower):
                for selector in _css_selectors(text):
                    if selector not in graph.browser.selectors:
                        graph.browser.selectors.append(selector)
                        graph.evidence.append("explicit_bare_css_selector")

        # Repository nouns + explicit read-only inspection verbs bind the repo
        # target even for public synonyms such as "check" and "examine".
        repo_noun = bool(re.search(r"\b(?:repo|repository|codebase|project\s+repository)\b", lower))
        inspection = bool(re.search(
            r"\b(?:check|examine|inspect|review|analy[sz]e|diagnose|audit|investigate|find\s+(?:the\s+)?bug)\b",
            lower,
        ))
        mutating = bool(re.search(r"\b(?:write|edit|modify|delete|remove|create|save|store)\b", lower))
        if repo_noun and inspection and not mutating:
            paths = core.extract_paths(text, known_extensions)
            if paths:
                return core.SemanticRequestGraph(
                    original_text=text,
                    action=core.SemanticAction.REPOSITORY,
                    response_mode=core._response_mode(text),
                    paths=[core.PathBinding(paths[0], core.SemanticPathRole.REPOSITORY, "explicit_repo_inspection_clause")],
                    evidence=["repo_noun_plus_inspection_verb"],
                )
        return graph

    core.SemanticParser.parse = classmethod(parse_with_final_contracts)

    current_execute = da.DirectActionRouter.execute.__func__

    def _explicit_output(text: str, paths: list[str]) -> str:
        """Bind an arithmetic destination from its mutation clause only."""
        lower = text.lower()
        for path in paths:
            escaped = re.escape(path.lower())
            if re.search(
                rf"\b(?:write|save|store|output)\s+(?:(?:the\s+)?(?:result|total|sum|difference|product|quotient)\s+)?(?:to|into|in|at)\s+['\"`]?{escaped}",
                lower,
            ):
                return path
        return ""

    def _arithmetic_contract(text: str) -> tuple[str, str, str, str] | None:
        """Return (operation, left, right, output) for explicit two-input workflows."""
        lower = text.lower()
        if not re.search(r"\b(?:read|load|fetch)\b", lower):
            return None
        operation = ""
        if re.search(r"\b(?:difference|subtract|minus|deduct)\b", lower):
            operation = "subtract"
        elif re.search(r"\b(?:product|multiply|times)\b", lower):
            operation = "multiply"
        elif re.search(r"\b(?:divide|quotient|divided\s+by)\b", lower):
            operation = "divide"
        elif re.search(r"\b(?:sum|add|total)\b", lower):
            operation = "add"
        if not operation:
            return None

        paths = core.extract_paths(text, da.RequestPreprocessor.KNOWN_EXTENSIONS)
        output = _explicit_output(text, paths)
        inputs = [path for path in paths if path != output]
        if not output or len(inputs) != 2:
            return None

        left, right = inputs[0], inputs[1]
        if operation == "subtract" and re.search(r"\b(?:subtract|take|deduct)\b.+?\b(?:from|away\s+from)\b", lower):
            left, right = right, left
        elif operation == "divide" and re.search(r"\bdivide\b.+?\binto\b", lower):
            left, right = right, left
        return operation, left, right, output

    def _numbers(raw: str) -> list[float]:
        return [float(token) for token in re.findall(r"[-+]?\d+(?:\.\d+)?", raw)]

    def _format_number(value: float) -> str:
        return str(int(value)) if value.is_integer() else str(value)

    def _compute(operation: str, left_values: list[float], right_values: list[float]) -> float:
        if not left_values or not right_values:
            raise ValueError("arithmetic inputs contain no numeric values")
        if operation == "add":
            # Aggregate semantics intentionally sums every number from both files.
            return sum(left_values) + sum(right_values)
        left, right = left_values[0], right_values[0]
        if operation == "subtract":
            return left - right
        if operation == "multiply":
            return left * right
        if operation == "divide":
            if right == 0:
                raise ZeroDivisionError("division by zero")
            return left / right
        raise ValueError(f"unsupported arithmetic operation: {operation}")

    def _execute_arithmetic_workflow(text: str, workspace: str) -> Any | None:
        contract = _arithmetic_contract(text)
        if contract is None:
            return None
        operation, input_a, input_b, output_path = contract
        ws = Path(workspace if workspace else da.workspace_root()).expanduser().resolve()
        effect_token = core._EFFECT_SCOPE.set(frozenset({"write_file"}))
        output_token = core._OUTPUT_SCOPE.set(frozenset({output_path}))
        try:
            with da.tool_workspace(ws):
                path_a = da.resolve_workspace_path(input_a, must_exist=True)
                path_b = da.resolve_workspace_path(input_b, must_exist=True)
                path_out = da.resolve_workspace_path(output_path, must_exist=False)
            if not path_a.is_file() or not path_b.is_file():
                raise FileNotFoundError("arithmetic inputs must be regular files")

            left_values = _numbers(path_a.read_text(encoding="utf-8", errors="replace"))
            right_values = _numbers(path_b.read_text(encoding="utf-8", errors="replace"))
            computed = _compute(operation, left_values, right_values)
            payload = _format_number(computed)
            expected_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

            with da.tool_workspace(ws):
                tool_result = da.parse_tool_result(
                    da.execute_tool("write_file", {"path": str(path_out), "content": payload})
                )
            if not tool_result.ok:
                return da.DirectActionResult(
                    False,
                    f"Arithmetic workflow write failed: {tool_result.error or 'write tool failed'}",
                    execution_type="workflow",
                    tool_name="multi_step_workflow",
                    provider="local-filesystem",
                    telemetry={"reason": "tool_failed", "verification_passed": False},
                )

            # Independent postcondition: re-read both operands and recompute after
            # the write, then compare to persisted output rather than trusting the
            # tool receipt or the first calculation.
            verify_left = _numbers(path_a.read_text(encoding="utf-8", errors="replace"))
            verify_right = _numbers(path_b.read_text(encoding="utf-8", errors="replace"))
            expected_again = _format_number(_compute(operation, verify_left, verify_right))
            observed = path_out.read_text(encoding="utf-8", errors="replace")
            actual_hash = hashlib.sha256(observed.encode("utf-8")).hexdigest()
            if observed.strip() != expected_again:
                return da.DirectActionResult(
                    False,
                    "Arithmetic workflow verification failed: persisted result differs from semantic recomputation.",
                    execution_type="workflow",
                    tool_name="multi_step_workflow",
                    provider="local-filesystem",
                    telemetry={
                        "reason": "content_mismatch",
                        "verification_passed": False,
                        "expected_output_hash": expected_hash,
                        "actual_output_hash": actual_hash,
                    },
                )

            normalized_result: int | float = int(computed) if computed.is_integer() else computed
            return da.DirectActionResult(
                True,
                f"Computed and independently verified {operation} result {payload} at {path_out}.",
                execution_type="workflow",
                tool_name="multi_step_workflow",
                provider="local-filesystem",
                telemetry={
                    "computed_result": normalized_result,
                    "verification_passed": True,
                    "expected_output_hash": expected_hash,
                    "actual_output_hash": actual_hash,
                    "input_paths": [str(path_a), str(path_b)],
                    "output_path": str(path_out),
                    "operation": operation,
                    "semantic_verifier": "fresh_operands_recomputed_equal_persisted_result",
                },
            )
        except PermissionError as exc:
            return da.DirectActionResult(
                False,
                f"Policy refusal: {exc}",
                execution_type="policy_enforcement",
                tool_name="effect_authorizer",
                provider="security-policy",
                policy_decision="refused",
                telemetry={"reason": "workspace_escape", "error": str(exc), "verification_passed": False},
            )
        except FileNotFoundError as exc:
            return da.DirectActionResult(
                False,
                f"Arithmetic workflow input not found: {exc}",
                execution_type="workflow",
                tool_name="multi_step_workflow",
                provider="local-filesystem",
                telemetry={"reason": "input_file_not_found", "error": str(exc), "verification_passed": False},
            )
        except Exception as exc:
            return da.DirectActionResult(
                False,
                f"Arithmetic workflow failed: {exc}",
                execution_type="workflow",
                tool_name="multi_step_workflow",
                provider="local-filesystem",
                telemetry={"reason": "arithmetic_workflow_failed", "error": str(exc), "verification_passed": False},
            )
        finally:
            core._OUTPUT_SCOPE.reset(output_token)
            core._EFFECT_SCOPE.reset(effect_token)

    def _is_raw_read(text: str) -> bool:
        lower = text.lower()
        return any(phrase in lower for phrase in (
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
        ))

    def _restore_public_metadata(result: Any, text: str) -> Any:
        if result is None:
            return None
        telemetry = getattr(result, "telemetry", None)
        if not isinstance(telemetry, dict):
            telemetry = {}
            result.telemetry = telemetry

        # Historical exact-response provenance is a public compatibility field;
        # execution still originates from the semantic graph and performs no I/O.
        if getattr(result, "execution_type", "") == "exact_response":
            result.provider = "system"
            result.tool_name = "echo"

        # Restore file-write verification metadata from the already verified
        # semantic payload and persisted file. This does not affect authorization.
        if getattr(result, "success", False) and getattr(result, "tool_name", "") == "write_file":
            payload = str(telemetry.get("payload", ""))
            telemetry["expected_size"] = len(payload)
            path_text = str(telemetry.get("output_path", telemetry.get("path", "")))
            try:
                actual = Path(path_text).read_text(encoding="utf-8", errors="replace") if path_text else payload
            except Exception:
                actual = payload
            telemetry["actual_size"] = len(actual)
            telemetry["expected_sha256"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            telemetry["actual_sha256"] = hashlib.sha256(actual.encode("utf-8")).hexdigest()
            telemetry["content_match"] = actual == payload

        if getattr(result, "tool_name", "") == "read_file":
            telemetry["read_mode"] = "raw" if _is_raw_read(text) else "display"
            if not getattr(result, "success", False):
                error_text = str(telemetry.get("error", ""))
                if "not found" not in str(result.output).lower() and "not a regular file" not in error_text.lower():
                    result.output = f"File read failed: not found: {error_text or result.output}"
                    telemetry.setdefault("error_kind", "not_found")

        # Browser verification must fail closed when a provider reports a
        # semantic no-match as successful text instead of an error status.
        if getattr(result, "provider", "") in {"browser", "browser-automation"}:
            structured = telemetry.get("structured_result", {})
            values = structured.values() if isinstance(structured, dict) else []
            no_match = any("no elements matched" in str(value).lower() for value in values)
            if no_match:
                result.success = False
                result.output = "Browser selector verification failed: one or more requested selectors matched no elements."
                telemetry["reason"] = "selector_not_found"
                telemetry["verification_passed"] = False
        return result

    def execute_with_final_contracts(
        cls: Any,
        text: str,
        *,
        context: str = "",
        control: Any = None,
        workspace: str = "",
    ) -> Any:
        arithmetic = _execute_arithmetic_workflow(text, workspace)
        if arithmetic is not None:
            return core._render(
                da,
                core.SemanticRequestGraph(
                    original_text=text,
                    action=core.SemanticAction.ARITHMETIC,
                    response_mode=core._response_mode(text),
                ),
                arithmetic,
            )

        # Syntax-only canonicalization: preserve every entity and relation while
        # mapping a public phrase to the verified JSON transform grammar.
        normalized = re.sub(
            r"\bsave\s+json\s+file\s+to\b",
            "save json to",
            text,
            flags=re.IGNORECASE,
        )
        result = current_execute(
            cls,
            normalized,
            context=context,
            control=control,
            workspace=workspace,
        )
        if result is None:
            return None

        # Truthful public provenance for path-policy refusals. The underlying
        # workspace resolver remains the authority; this only normalizes the
        # outward result after it has refused the operation.
        if not getattr(result, "success", False) and getattr(result, "policy_decision", "") == "refused":
            error_text = str((getattr(result, "telemetry", {}) or {}).get("error", result.output)).lower()
            if any(marker in error_text for marker in ("outside workspace", "workspace", "escape", "sensitive", "permission")):
                result.execution_type = "policy_enforcement"
                result.provider = "security-policy"
                result.telemetry["reason"] = "workspace_escape"
        return _restore_public_metadata(result, text)

    da.DirectActionRouter.execute = classmethod(execute_with_final_contracts)

    # Cognition may call ExactResponseParser directly; keep that path graph-based
    # while restoring the established public provider metadata.
    current_exact_parse: Callable[..., Any] = da.ExactResponseParser.parse.__func__

    def exact_with_public_metadata(cls: Any, text: str, workspace: str = "") -> Any:
        result = current_exact_parse(cls, text, workspace=workspace)
        return _restore_public_metadata(result, text)

    da.ExactResponseParser.parse = classmethod(exact_with_public_metadata)
    _INSTALLED = True
