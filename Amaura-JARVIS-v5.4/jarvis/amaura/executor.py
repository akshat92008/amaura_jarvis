"""Governed worker execution with an evidence-aware completion guard.

The stable execution implementation lives in :mod:`executor_core`. This module
preserves its historical import surface while adding one narrow policy: when a
task has acceptance criteria, a worker may not terminate on prose before it has
produced successful governed tool evidence. The guard performs at most one
corrective reprompt per model turn and otherwise fails closed.
"""

from __future__ import annotations

import sys
from contextvars import ContextVar
from types import ModuleType, SimpleNamespace
from typing import Any

from jarvis.amaura import executor_core as _core
from jarvis.amaura.models import GovernanceError
from jarvis.tools.result import parse_tool_result

_BaseGovernedTaskRunner = _core.GovernedTaskRunner

# Preserve the executor module's historical import surface, including private
# helpers used by qualification tests. The proxy module installed below keeps
# monkeypatches of those names synchronized with executor_core, whose function
# globals remain authoritative.
for _export_name in dir(_core):
    if not _export_name.startswith("__"):
        globals()[_export_name] = getattr(_core, _export_name)


_EVIDENCE_REQUIRED: ContextVar[bool] = ContextVar("amaura_evidence_required", default=False)


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

    def _sync_metadata(self, *, corrective_reprompts: int = 0) -> None:
        metadata = dict(getattr(self._inner, "last_execution_metadata", {}) or {})
        if corrective_reprompts:
            metadata["evidence_guard"] = "corrective_tool_use"
            metadata["evidence_guard_corrective_reprompts"] = corrective_reprompts
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
        if not (getattr(corrected_message, "tool_calls", None) or []):
            raise GovernanceError(
                "Employee failed to produce verifiable evidence after one bounded corrective tool-use prompt. "
                "Agent prose is insufficient."
            )
        return _AggregatedResponse([first, corrected])


class GovernedTaskRunner(_BaseGovernedTaskRunner):
    """Core task runner with bounded evidence-aware worker cognition."""

    def _client(self, route: dict[str, Any], employee: Any) -> _EvidenceAwareClient:
        return _EvidenceAwareClient(
            super()._client(route, employee),
            evidence_required=_EVIDENCE_REQUIRED.get(),
        )

    def run(self, task_id: str, max_iterations: int = 12) -> dict[str, Any]:
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
        "_EVIDENCE_REQUIRED",
        "_EvidenceAwareClient",
        "_ExecutorProxyModule",
        "_successful_tool_evidence",
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
_core.GovernedTaskRunner = GovernedTaskRunner
_current_module = sys.modules[__name__]
_current_module.__class__ = _ExecutorProxyModule
