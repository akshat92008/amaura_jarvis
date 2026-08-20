"""Governed worker execution with an evidence-aware completion guard.

The stable execution implementation lives in :mod:`executor_core`. This module
preserves its historical import surface while adding one narrow policy: when a
task has acceptance criteria, a worker may not terminate on prose before it has
produced successful governed tool evidence. The guard performs at most one
corrective reprompt per model turn. If the model still refuses to call a tool,
the guard may synthesize a bounded set of read-only evidence calls using only
already-authorized tools and the canonical task packet. All execution still
passes through the normal tool authorization and evidence pipeline.
"""

from __future__ import annotations

import json
import sys
from contextvars import ContextVar
from types import ModuleType, SimpleNamespace
from typing import Any

from jarvis.amaura import executor_core as _core
from jarvis.amaura.models import GovernanceError
from jarvis.tools.result import parse_tool_result

_BaseGovernedTaskRunner = _core.GovernedTaskRunner
GovernedReviewRunner = _core.GovernedReviewRunner

# Preserve the executor module's historical import surface, including private
# helpers used by qualification tests. The proxy module installed below keeps
# monkeypatches of those names synchronized with executor_core, whose function
# globals remain authoritative.
for _export_name in dir(_core):
    if not _export_name.startswith("__"):
        globals()[_export_name] = getattr(_core, _export_name)


_EVIDENCE_REQUIRED: ContextVar[bool] = ContextVar("amaura_evidence_required", default=False)
_BOOTSTRAP_CALL_PREFIX = "call_arch_evidence_bootstrap_"
_MAX_CRITERION_BOOTSTRAP_CALLS = 4


def _successful_tool_evidence_count(messages: list[dict[str, Any]]) -> int:
    """Count successful governed tool results already present in model context."""
    count = 0
    for message in messages:
        if message.get("role") != "tool":
            continue
        try:
            parsed = parse_tool_result(str(message.get("content") or ""))
        except Exception:
            continue
        if parsed.ok:
            count += 1
    return count


def _successful_tool_evidence(messages: list[dict[str, Any]]) -> bool:
    """Return True only when at least one successful governed tool result exists."""
    return _successful_tool_evidence_count(messages) > 0


def _bootstrap_already_attempted(messages: list[dict[str, Any]]) -> bool:
    """Prevent a failing deterministic bootstrap from looping forever."""
    for message in messages:
        if str(message.get("tool_call_id") or "").startswith(_BOOTSTRAP_CALL_PREFIX):
            return True
        for call in message.get("tool_calls") or []:
            if isinstance(call, dict) and str(call.get("id") or "").startswith(_BOOTSTRAP_CALL_PREFIX):
                return True
    return False


def _task_packet(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract only the canonical task packet, never arbitrary tool/page text."""
    marker = "JARVIS TASK PACKET:\n"
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = str(message.get("content") or "")
        if marker not in content:
            continue
        payload = content.split(marker, 1)[1]
        try:
            packet = json.loads(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(packet, dict):
            return packet
    return {}


def _task_objective(messages: list[dict[str, Any]]) -> str:
    """Extract the canonical objective without trusting arbitrary page/tool text."""
    packet = _task_packet(messages)
    objective = " ".join(str(packet.get("objective") or "").split()).strip()
    return objective[:500] if objective else ""


def _task_acceptance_criteria(messages: list[dict[str, Any]]) -> list[str]:
    """Extract bounded canonical acceptance criteria for evidence planning."""
    packet = _task_packet(messages)
    raw = packet.get("acceptance_criteria") or []
    if not isinstance(raw, list):
        return []
    criteria: list[str] = []
    for item in raw:
        criterion = " ".join(str(item or "").split()).strip()
        if criterion:
            criteria.append(criterion[:300])
        if len(criteria) >= 12:
            break
    return criteria


def _tool_name_set(tools: list[dict[str, Any]] | None) -> set[str]:
    return {
        str((definition.get("function") or {}).get("name") or "").strip()
        for definition in tools or []
        if str((definition.get("function") or {}).get("name") or "").strip()
    }


def _evidence_target(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> int:
    """Return a bounded structural evidence target before prose completion.

    The reviewer remains the semantic authority. This target merely prevents a
    multi-criterion research task from stopping after one generic search result.
    Criterion-addressable public research tools can gather at most four distinct
    evidence items; repository/status tools retain the historical one-item
    threshold because one structured result may legitimately cover many criteria.
    """
    criteria = _task_acceptance_criteria(messages)
    if len(criteria) <= 1:
        return 1
    names = _tool_name_set(tools)
    if names.intersection({"web_search", "deep_research"}):
        return min(len(criteria), _MAX_CRITERION_BOOTSTRAP_CALLS)
    return 1


def _deterministic_bootstrap(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
) -> tuple[str, dict[str, Any]] | None:
    """Choose one safe evidence-gathering call from already-authorized tools.

    Only read-only calls with deterministic arguments are eligible. Selection is
    objective-aware so an operations or repository task is not forced through a
    generic web search merely because that tool is also available. The core
    runner still authorizes and executes the call through the normal policy and
    evidence pipeline.
    """
    if _bootstrap_already_attempted(messages):
        return None
    objective = _task_objective(messages)
    if not objective:
        return None
    objective_lower = objective.lower()
    names = _tool_name_set(tools)

    if "amaura_cashflow_dashboard" in names and any(
        term in objective_lower for term in ("cash-flow", "cashflow", "cash flow", "runway", "financial stream")
    ):
        return "amaura_cashflow_dashboard", {}
    if "amaura_venture_dashboard" in names and any(
        term in objective_lower for term in ("venture", "experiment", "portfolio", "monetisation", "monetization")
    ):
        return "amaura_venture_dashboard", {}
    if "amaura_company_status" in names and any(
        term in objective_lower
        for term in ("company", "operating", "operations", "task", "blocker", "programme", "program", "capacity")
    ):
        return "amaura_company_status", {}
    if "amaura_resource_inventory" in names and any(
        term in objective_lower for term in ("resource", "capability", "availability", "installed", "8gb", "8 gb")
    ):
        return "amaura_resource_inventory", {}
    if any(term in objective_lower for term in ("repository", "repo", "codebase", "security posture", "source code")):
        if "get_project_structure" in names:
            return "get_project_structure", {"max_depth": 3}
        if "git_status" in names:
            return "git_status", {}
    if "web_search" in names:
        return "web_search", {"query": objective, "max_results": 5}
    if "deep_research" in names:
        return "deep_research", {"topic": objective, "num_queries": 3}
    if "amaura_company_status" in names:
        return "amaura_company_status", {}
    if "amaura_cashflow_dashboard" in names:
        return "amaura_cashflow_dashboard", {}
    if "amaura_venture_dashboard" in names:
        return "amaura_venture_dashboard", {}
    if "amaura_resource_inventory" in names:
        return "amaura_resource_inventory", {}
    if "get_project_structure" in names:
        return "get_project_structure", {"max_depth": 3}
    if "git_status" in names:
        return "git_status", {}
    return None


def _deterministic_bootstrap_calls(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
) -> list[tuple[str, dict[str, Any]]]:
    """Build a bounded criterion-aware read-only bootstrap plan.

    Query-shaped tools can gather one independently auditable result per
    acceptance criterion (capped). Tools whose output is already a structured
    snapshot are executed only once. No URL, path, mutation argument, or external
    side effect is invented here.
    """
    base = _deterministic_bootstrap(messages, tools)
    if base is None:
        return []
    tool_name, arguments = base
    criteria = _task_acceptance_criteria(messages)
    objective = _task_objective(messages)
    if len(criteria) <= 1:
        return [base]

    selected = criteria[:_MAX_CRITERION_BOOTSTRAP_CALLS]
    if tool_name == "web_search":
        return [
            (
                "web_search",
                {
                    "query": f"{objective} Acceptance criterion: {criterion}"[:900],
                    "max_results": 5,
                },
            )
            for criterion in selected
        ]
    if tool_name == "deep_research":
        return [
            (
                "deep_research",
                {
                    "topic": f"{objective} Acceptance criterion: {criterion}"[:900],
                    "num_queries": 3,
                },
            )
            for criterion in selected
        ]
    if tool_name == "search_code":
        return [
            (
                "search_code",
                {"query": f"{objective} {criterion}"[:500]},
            )
            for criterion in selected
        ]
    return [(tool_name, arguments)]


def _token_counts(response: Any) -> tuple[int, int]:
    usage = getattr(response, "usage", None)
    return (
        int(getattr(usage, "prompt_tokens", 0) or 0),
        int(getattr(usage, "completion_tokens", 0) or 0),
    )


class _AggregatedResponse:
    """Proxy the final provider response while preserving corrective-call usage."""

    def __init__(self, responses: list[Any]):
        self._latest = responses[-1]
        self.choices = self._latest.choices
        self.model = getattr(self._latest, "model", "")
        prompt_tokens = 0
        completion_tokens = 0
        for response in responses:
            prompt, completion = _token_counts(response)
            prompt_tokens += prompt
            completion_tokens += completion
        self.usage = SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._latest, name)


class _SyntheticToolResponse:
    """OpenAI-shaped response for policy-owned read-only evidence bootstrap calls."""

    def __init__(
        self,
        *,
        model: str,
        calls: list[tuple[str, dict[str, Any]]],
        call_index: int,
    ):
        tool_calls = []
        for offset, (tool_name, arguments) in enumerate(calls):
            tool_calls.append(
                SimpleNamespace(
                    id=f"{_BOOTSTRAP_CALL_PREFIX}{call_index}_{offset}",
                    type="function",
                    function=SimpleNamespace(name=tool_name, arguments=json.dumps(arguments, sort_keys=True)),
                )
            )
        self.choices = [
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=tool_calls,
                )
            )
        ]
        self.model = model
        self.usage = SimpleNamespace(prompt_tokens=0, completion_tokens=0)


class _EvidenceAwareClient:
    """Prevent prose-only completion before bounded criterion evidence exists."""

    def __init__(self, inner: Any, *, evidence_required: bool):
        self._inner = inner
        self.evidence_required = evidence_required
        self.last_execution_metadata: dict[str, Any] = {}

    @staticmethod
    def _tool_names(tools: list[dict[str, Any]] | None) -> list[str]:
        names: list[str] = []
        for definition in tools or []:
            name = str((definition.get("function") or {}).get("name") or "").strip()
            if name and name not in names:
                names.append(name)
        return names

    def _sync_metadata(
        self,
        *,
        corrective_reprompts: int = 0,
        bootstrap_calls: list[tuple[str, dict[str, Any]]] | None = None,
        bootstrap_criteria_count: int = 0,
    ) -> None:
        metadata = dict(getattr(self._inner, "last_execution_metadata", {}) or {})
        if corrective_reprompts:
            metadata["evidence_guard"] = "corrective_tool_use"
            metadata["evidence_guard_corrective_reprompts"] = corrective_reprompts
        if bootstrap_calls:
            names = [name for name, _ in bootstrap_calls]
            metadata["evidence_guard"] = "deterministic_read_only_bootstrap"
            metadata["evidence_guard_bootstrap_tool"] = names[0]
            metadata["evidence_guard_bootstrap_tools"] = names
            metadata["evidence_guard_bootstrap_call_count"] = len(bootstrap_calls)
            metadata["evidence_guard_bootstrap_criteria_count"] = bootstrap_criteria_count
        self.last_execution_metadata = metadata

    def chat_sync(
        self,
        *,
        model_id: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Any:
        evidence_count = _successful_tool_evidence_count(messages)
        evidence_target = _evidence_target(messages, tools)
        needs_evidence = self.evidence_required and evidence_count < evidence_target
        if needs_evidence and not tools:
            raise GovernanceError(
                "Employee cannot satisfy acceptance criteria: no callable authorized tools are available "
                "to produce verifiable evidence."
            )

        first = self._inner.chat_sync(model_id=model_id, messages=messages, tools=tools)
        self._sync_metadata()
        if not needs_evidence:
            return first

        message = first.choices[0].message
        if getattr(message, "tool_calls", None) or []:
            return first

        proposed_summary = str(getattr(message, "content", "") or "").strip()
        tool_names = self._tool_names(tools)
        criteria = _task_acceptance_criteria(messages)
        criteria_text = "\n".join(
            f"- {index + 1}. {criterion}" for index, criterion in enumerate(criteria[:_MAX_CRITERION_BOOTSTRAP_CALLS])
        )
        if criteria_text:
            criteria_text = f"\nAcceptance criteria requiring evidence:\n{criteria_text}"
        corrective_messages = [
            *messages,
            {"role": "assistant", "content": proposed_summary or "I have not produced enough evidence yet."},
            {
                "role": "user",
                "content": (
                    "Your previous response cannot satisfy this task's acceptance criteria because the governed "
                    f"evidence packet is incomplete ({evidence_count}/{evidence_target} bounded evidence target). "
                    "Do not repeat a prose-only completion. Use one or more authorized tools now to gather "
                    "verifiable evidence that addresses each listed acceptance criterion. After tool results are "
                    "available, provide a concise summary. "
                    f"Authorized tools: {', '.join(tool_names)}"
                    f"{criteria_text}"
                ),
            },
        ]
        corrected = self._inner.chat_sync(
            model_id=model_id,
            messages=corrective_messages,
            tools=tools,
        )
        self._sync_metadata(corrective_reprompts=1)
        corrected_message = corrected.choices[0].message
        if getattr(corrected_message, "tool_calls", None) or []:
            return _AggregatedResponse([first, corrected])

        bootstrap_calls = _deterministic_bootstrap_calls(messages, tools)
        if bootstrap_calls:
            synthetic = _SyntheticToolResponse(
                model=str(getattr(corrected, "model", "") or getattr(first, "model", "") or model_id),
                calls=bootstrap_calls,
                call_index=len(messages),
            )
            self._sync_metadata(
                corrective_reprompts=1,
                bootstrap_calls=bootstrap_calls,
                bootstrap_criteria_count=min(len(criteria), _MAX_CRITERION_BOOTSTRAP_CALLS),
            )
            return _AggregatedResponse([first, corrected, synthetic])

        raise GovernanceError(
            "Employee failed to produce verifiable evidence after one bounded corrective tool-use prompt. "
            "Agent prose is insufficient and no safe deterministic evidence bootstrap was available."
        )


class GovernedTaskRunner(_BaseGovernedTaskRunner):
    """Core task runner with bounded evidence-aware worker cognition."""

    def _client(self, route: dict[str, Any], employee: Any) -> _EvidenceAwareClient:
        return _EvidenceAwareClient(
            super()._client(route, employee),
            evidence_required=_EVIDENCE_REQUIRED.get(),
        )

    def run(self, task_id: str, max_iterations: int = 12) -> dict[str, Any]:
        """Delegate to the core runner without changing its execution receipt contract.

        The delegated core implementation still records requested_route,
        actual_model, provider, input_tokens, and output_tokens in the model
        execution receipt; this wrapper only scopes the evidence guard.
        """
        task = self.control.store.get_work_item(task_id)
        token = _EVIDENCE_REQUIRED.set(bool(task.get("acceptance_criteria")))
        try:
            return super().run(task_id, max_iterations=max_iterations)
        finally:
            _EVIDENCE_REQUIRED.reset(token)


class _ExecutorProxyModule(ModuleType):
    """Mirror legacy executor monkeypatches into executor_core function globals."""

    _WRAPPER_ONLY = {
        "_AggregatedResponse",
        "_BaseGovernedTaskRunner",
        "_BOOTSTRAP_CALL_PREFIX",
        "_EVIDENCE_REQUIRED",
        "_EvidenceAwareClient",
        "_ExecutorProxyModule",
        "_MAX_CRITERION_BOOTSTRAP_CALLS",
        "_SyntheticToolResponse",
        "_bootstrap_already_attempted",
        "_deterministic_bootstrap",
        "_deterministic_bootstrap_calls",
        "_evidence_target",
        "_successful_tool_evidence",
        "_successful_tool_evidence_count",
        "_task_acceptance_criteria",
        "_task_objective",
        "_task_packet",
        "_token_counts",
        "_tool_name_set",
    }

    def __setattr__(self, name: str, value: Any) -> None:
        ModuleType.__setattr__(self, name, value)
        if name not in self._WRAPPER_ONLY and name in _core.__dict__:
            _core.__dict__[name] = value

    def __delattr__(self, name: str) -> None:
        ModuleType.__delattr__(self, name)
        if name not in self._WRAPPER_ONLY and name in _core.__dict__:
            del _core.__dict__[name]


# Make the guarded runner the public runner, while retaining the original core
# module for stable function globals and compatibility with existing tests.
_core.GovernedTaskRunner = GovernedTaskRunner  # type: ignore[misc]
sys.modules[__name__].__class__ = _ExecutorProxyModule