"""Governed worker execution with an evidence-aware completion guard.

The stable execution implementation lives in :mod:`executor_core`. This module
preserves its historical import surface while adding one narrow policy: when a
task has acceptance criteria, a worker may not terminate on prose before it has
produced successful governed tool evidence. The guard performs at most one
corrective reprompt per model turn. If the model still refuses to call a tool,
the guard may synthesize one bounded, read-only evidence bootstrap using an
already-authorized tool and the canonical task objective. All execution still
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


def _successful_tool_evidence(messages: list[dict[str, Any]]) -> bool:
    """Return True only for a successful governed tool result already in context."""
    for message in messages:
        if message.get("role") != "tool":
            continue
        try:
            parsed = parse_tool_result(str(message.get("content") or ""))
        except Exception:
            continue
        if parsed.ok:
            return True
    return False


def _bootstrap_already_attempted(messages: list[dict[str, Any]]) -> bool:
    """Prevent a failing deterministic bootstrap from looping forever."""
    for message in messages:
        if str(message.get("tool_call_id") or "").startswith(_BOOTSTRAP_CALL_PREFIX):
            return True
        for call in message.get("tool_calls") or []:
            if isinstance(call, dict) and str(call.get("id") or "").startswith(_BOOTSTRAP_CALL_PREFIX):
                return True
    return False


def _task_objective(messages: list[dict[str, Any]]) -> str:
    """Extract the canonical task objective without trusting arbitrary page/tool text."""
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
        objective = " ".join(str(packet.get("objective") or "").split()).strip()
        if objective:
            return objective[:500]
    return ""


def _deterministic_bootstrap(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
) -> tuple[str, dict[str, Any]] | None:
    """Choose one safe evidence-gathering call from the already-authorized tools.

    This is intentionally tiny and read-only. It does not invent URLs, paths, or
    external side effects. The core runner will still authorize and execute the
    returned call exactly like a model-generated call.
    """
    if _bootstrap_already_attempted(messages):
        return None
    objective = _task_objective(messages)
    if not objective:
        return None
    names = {
        str((definition.get("function") or {}).get("name") or "").strip()
        for definition in tools or []
    }
    if "web_search" in names:
        return "web_search", {"query": objective, "max_results": 5}
    if "deep_research" in names:
        return "deep_research", {"topic": objective, "num_queries": 3}
    if "amaura_company_status" in names:
        return "amaura_company_status", {}
    if "amaura_resource_inventory" in names:
        return "amaura_resource_inventory", {}
    return None


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
    """OpenAI-shaped response for one policy-owned read-only evidence bootstrap."""

    def __init__(self, *, model: str, tool_name: str, arguments: dict[str, Any], call_index: int):
        call = SimpleNamespace(
            id=f"{_BOOTSTRAP_CALL_PREFIX}{call_index}",
            type="function",
            function=SimpleNamespace(name=tool_name, arguments=json.dumps(arguments, sort_keys=True)),
        )
        self.choices = [
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[call],
                )
            )
        ]
        self.model = model
        self.usage = SimpleNamespace(prompt_tokens=0, completion_tokens=0)


class _EvidenceAwareClient:
    """Prevent prose-only completion when task acceptance requires evidence."""

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

    def _sync_metadata(self, *, corrective_reprompts: int = 0, bootstrap_tool: str = "") -> None:
        metadata = dict(getattr(self._inner, "last_execution_metadata", {}) or {})
        if corrective_reprompts:
            metadata["evidence_guard"] = "corrective_tool_use"
            metadata["evidence_guard_corrective_reprompts"] = corrective_reprompts
        if bootstrap_tool:
            metadata["evidence_guard"] = "deterministic_read_only_bootstrap"
            metadata["evidence_guard_bootstrap_tool"] = bootstrap_tool
        self.last_execution_metadata = metadata

    def chat_sync(
        self,
        *,
        model_id: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Any:
        needs_evidence = self.evidence_required and not _successful_tool_evidence(messages)
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
        corrective_messages = [
            *messages,
            {"role": "assistant", "content": proposed_summary or "I have not produced evidence yet."},
            {
                "role": "user",
                "content": (
                    "Your previous response cannot satisfy this task's acceptance criteria because it contains "
                    "no successful governed tool evidence. Do not repeat a prose-only completion. Use one or more "
                    "authorized tools now to inspect or execute the work and produce verifiable evidence tied to "
                    "the acceptance criteria. After tool results are available, provide a concise summary. "
                    f"Authorized tools: {', '.join(tool_names)}"
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

        bootstrap = _deterministic_bootstrap(messages, tools)
        if bootstrap is not None:
            tool_name, arguments = bootstrap
            synthetic = _SyntheticToolResponse(
                model=str(getattr(corrected, "model", "") or getattr(first, "model", "") or model_id),
                tool_name=tool_name,
                arguments=arguments,
                call_index=len(messages),
            )
            self._sync_metadata(corrective_reprompts=1, bootstrap_tool=tool_name)
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
        "_SyntheticToolResponse",
        "_bootstrap_already_attempted",
        "_deterministic_bootstrap",
        "_successful_tool_evidence",
        "_task_objective",
        "_token_counts",
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
