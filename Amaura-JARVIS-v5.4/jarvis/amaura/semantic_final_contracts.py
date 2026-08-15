"""Final typed compatibility contracts for ARCH's semantic execution boundary.

These contracts close public API phrasings discovered by the maintained release
suite without restoring parser competition or positional write inference.

* repository nouns + explicit inspection verbs bind a REPOSITORY role;
* ``save json file to`` is syntax-normalized into the already verified JSON
  transform contract;
* two-input numeric summation executes as a typed workflow with an explicitly
  bound output and independent persisted-result verification; and
* workspace-policy rejections retain truthful public provenance.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

_INSTALLED = False


def install_semantic_final_contracts() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from jarvis.amaura import direct_action as da
    from jarvis.amaura import semantic_core as core

    current_parse = core.SemanticParser.parse.__func__

    def parse_with_repository_contract(
        cls: Any,
        text: str,
        known_extensions: tuple[str, ...],
    ) -> Any:
        graph = current_parse(cls, text, known_extensions)
        lower = text.lower()
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

    core.SemanticParser.parse = classmethod(parse_with_repository_contract)

    current_execute = da.DirectActionRouter.execute.__func__

    def _explicit_sum_contract(text: str) -> tuple[str, str, str] | None:
        """Return two inputs + explicit output only for the supported sum grammar."""
        if not re.search(r"\b(?:sum|add|total)\s+(?:the\s+)?numbers?\b", text, re.IGNORECASE):
            return None
        if not re.search(r"\b(?:write|save|store)\s+(?:the\s+)?total\s+(?:to|into|at)\b", text, re.IGNORECASE):
            return None
        paths = core.extract_paths(text, da.RequestPreprocessor.KNOWN_EXTENSIONS)
        if len(paths) != 3:
            return None
        # Output is proven by its own mutation clause, not by position.
        output = ""
        lower = text.lower()
        for candidate in paths:
            escaped = re.escape(candidate.lower())
            if re.search(
                rf"\b(?:write|save|store)\s+(?:the\s+)?total\s+(?:to|into|at)\s+['\"`]?{escaped}",
                lower,
            ):
                output = candidate
                break
        if not output:
            return None
        inputs = [path for path in paths if path != output]
        if len(inputs) != 2:
            return None
        return inputs[0], inputs[1], output

    def _numbers(raw: str) -> list[float]:
        return [float(token) for token in re.findall(r"[-+]?\d+(?:\.\d+)?", raw)]

    def _format_number(value: float) -> str:
        return str(int(value)) if value.is_integer() else str(value)

    def _execute_sum(text: str, workspace: str) -> Any | None:
        contract = _explicit_sum_contract(text)
        if contract is None:
            return None
        input_a, input_b, output_path = contract
        ws = Path(workspace if workspace else da.workspace_root()).expanduser().resolve()
        effect_token = core._EFFECT_SCOPE.set(frozenset({"write_file"}))
        output_token = core._OUTPUT_SCOPE.set(frozenset({output_path}))
        try:
            with da.tool_workspace(ws):
                path_a = da.resolve_workspace_path(input_a, must_exist=True)
                path_b = da.resolve_workspace_path(input_b, must_exist=True)
                path_out = da.resolve_workspace_path(output_path, must_exist=False)
            if not path_a.is_file() or not path_b.is_file():
                raise FileNotFoundError("numeric aggregate inputs must be regular files")
            values_a = _numbers(path_a.read_text(encoding="utf-8", errors="replace"))
            values_b = _numbers(path_b.read_text(encoding="utf-8", errors="replace"))
            if not values_a and not values_b:
                raise ValueError("numeric aggregate inputs contain no numbers")
            total = sum(values_a) + sum(values_b)
            payload = _format_number(total)
            expected_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            with da.tool_workspace(ws):
                tool_result = da.parse_tool_result(
                    da.execute_tool("write_file", {"path": str(path_out), "content": payload})
                )
            if not tool_result.ok:
                return da.DirectActionResult(
                    False,
                    f"Aggregate write failed: {tool_result.error or 'write tool failed'}",
                    execution_type="workflow",
                    tool_name="multi_step_workflow",
                    provider="local-filesystem",
                    telemetry={"reason": "tool_failed", "verification_passed": False},
                )
            observed = path_out.read_text(encoding="utf-8", errors="replace")
            actual_hash = hashlib.sha256(observed.encode("utf-8")).hexdigest()
            if observed.strip() != payload:
                return da.DirectActionResult(
                    False,
                    "Aggregate verification failed: persisted total differs from semantic recomputation.",
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
            return da.DirectActionResult(
                True,
                f"Computed and independently verified total {payload} at {path_out}.",
                execution_type="workflow",
                tool_name="multi_step_workflow",
                provider="local-filesystem",
                telemetry={
                    "computed_result": int(total) if total.is_integer() else total,
                    "verification_passed": True,
                    "expected_output_hash": expected_hash,
                    "actual_output_hash": actual_hash,
                    "input_paths": [str(path_a), str(path_b)],
                    "output_path": str(path_out),
                    "semantic_verifier": "recomputed_sum_equals_persisted_total",
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
        except Exception as exc:
            return da.DirectActionResult(
                False,
                f"Aggregate workflow failed: {exc}",
                execution_type="workflow",
                tool_name="multi_step_workflow",
                provider="local-filesystem",
                telemetry={"reason": "aggregate_failed", "error": str(exc), "verification_passed": False},
            )
        finally:
            core._OUTPUT_SCOPE.reset(output_token)
            core._EFFECT_SCOPE.reset(effect_token)

    def execute_with_final_contracts(
        cls: Any,
        text: str,
        *,
        context: str = "",
        control: Any = None,
        workspace: str = "",
    ) -> Any:
        aggregate = _execute_sum(text, workspace)
        if aggregate is not None:
            return core._render(
                da,
                core.SemanticRequestGraph(
                    original_text=text,
                    action=core.SemanticAction.ARITHMETIC,
                    response_mode=core._response_mode(text),
                ),
                aggregate,
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
        return result

    da.DirectActionRouter.execute = classmethod(execute_with_final_contracts)
    _INSTALLED = True
