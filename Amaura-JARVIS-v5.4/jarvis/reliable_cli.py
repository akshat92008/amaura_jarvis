"""Hardened entry point for the founder-facing JARVIS CLI.

The core executive stack remains the source of truth.  This module only adds a
small front-door reliability boundary for patterns that must never depend on a
free-form model deciding the intent:

* explicit mission/work-item result queries read durable Company OS state;
* vague follow-ups bind to the most recent mission created in that CLI session;
* repository audits/inspections become governed missions deterministically;
* clearly new software projects do not inherit the JARVIS source checkout as
  their target workspace;
* a governance/runtime failure never kills the interactive CLI process;
* a transient conversational-provider miss gets one bounded retry.

No tool authorization, risk limit, reviewer independence, or Company OS policy
is weakened here.
"""

from __future__ import annotations

import re
import time
from typing import Any

from jarvis.agent import JarvisAgent

_ORIGINAL_RUN_EXECUTIVE = JarvisAgent.run_executive
_UNAVAILABLE_MESSAGE = "The interactive cognition service is temporarily unavailable. Please try again shortly."
_SESSION_BINDINGS_ATTR = "_amaura_session_goal_bindings"

_WORK_ITEM_RE = re.compile(r"\b(?:goal|task|proj|mile)_[A-Za-z0-9]+\b", re.IGNORECASE)
_STATUS_WORDS = {
    "result",
    "results",
    "status",
    "progress",
    "outcome",
    "output",
    "show",
    "give",
    "finished",
    "complete",
    "completed",
    "done",
}
_VAGUE_WORK_ITEM_NOUNS = {"task", "mission", "goal", "project", "work"}
_VAGUE_REFERENCE_WORDS = {
    "that",
    "this",
    "it",
    "my",
    "gave",
    "assigned",
    "created",
    "started",
    "requested",
    "asked",
}
_REPO_NOUNS = {
    "repo",
    "repository",
    "codebase",
    "folder",
    "directory",
    "project",
}
_REPO_ACTIONS = {
    "audit",
    "inspect",
    "analyse",
    "analyze",
    "review",
    "diagnose",
    "debug",
    "assess",
    "investigate",
}
_NEW_PROJECT_VERBS = {"build", "create", "develop", "make", "generate", "start", "scaffold"}
_NEW_PROJECT_NOUNS = {
    "app",
    "application",
    "website",
    "webapp",
    "software",
    "game",
    "api",
    "cli",
    "tool",
    "plugin",
    "extension",
}
_EXISTING_TARGET_PHRASES = {
    "this repo",
    "this repository",
    "current repo",
    "current repository",
    "this codebase",
    "current codebase",
    "existing repo",
    "existing repository",
}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9][a-z0-9_+-]*", str(text).lower()))


def _is_work_item_result_query(text: str) -> bool:
    if not _WORK_ITEM_RE.search(text):
        return False
    tokens = _tokens(text)
    return bool(tokens & _STATUS_WORDS)


def _is_vague_work_item_result_query(text: str) -> bool:
    """Recognize same-session follow-ups without guessing a global work item.

    Examples include ``what are the results of task I gave you`` and ``status of
    that mission``.  This route is used only when the current agent already has
    a durable same-session mission binding; otherwise normal reference
    resolution remains authoritative.
    """
    if _WORK_ITEM_RE.search(text):
        return False
    tokens = _tokens(text)
    return bool(tokens & _STATUS_WORDS) and bool(tokens & _VAGUE_WORK_ITEM_NOUNS) and bool(
        tokens & _VAGUE_REFERENCE_WORDS
    )


def _is_repo_audit(text: str) -> bool:
    clean = " ".join(str(text).lower().split())
    tokens = _tokens(clean)
    has_target = bool(tokens & _REPO_NOUNS) or "amaura jarvis" in clean or "jarvis folder" in clean
    has_action = bool(tokens & _REPO_ACTIONS) or "go through" in clean or "deep dive" in clean
    return has_target and has_action


def _is_new_software_project(text: str) -> bool:
    clean = " ".join(str(text).lower().split())
    tokens = _tokens(clean)
    if any(phrase in clean for phrase in _EXISTING_TARGET_PHRASES):
        return False
    # An explicit repository-ish path means the user selected an existing
    # workspace.  Desktop/name language alone is a destination, not a repo.
    if re.search(r"(?:^|\s)(?:/|~/|\.\.?/)[^\s]+", str(text)):
        return False
    return bool(tokens & _NEW_PROJECT_VERBS and tokens & _NEW_PROJECT_NOUNS)


def _forced_intent(text: str) -> str | None:
    if _is_work_item_result_query(text):
        return "status"
    if _is_repo_audit(text) or _is_new_software_project(text):
        return "mission"
    return None


def _safe_error_response(*, intent: str, message: str, error_type: str, detail: str = "") -> dict[str, Any]:
    return {
        "intent": intent,
        "message": message,
        "session_id": "",
        "goal_id": "",
        "state": "rejected" if error_type == "governance" else "failed",
        "result": {
            "frontdoor_recovered": True,
            "error_type": error_type,
            "detail": detail[:1000],
        },
        "context_sources": [],
        "model_provenance": {
            "provider": "frontdoor-recovery",
            "model": "",
            "fallback_used": True,
            "fallback_reason": error_type,
        },
    }


def _session_bindings(agent: JarvisAgent) -> dict[str, str]:
    bindings = getattr(agent, _SESSION_BINDINGS_ATTR, None)
    if not isinstance(bindings, dict):
        bindings = {}
        setattr(agent, _SESSION_BINDINGS_ATTR, bindings)
    return bindings


def _result_goal_id(result: dict[str, Any]) -> str:
    goal_id = str(result.get("goal_id") or "")
    if goal_id:
        return goal_id
    inner = result.get("result") or {}
    if not isinstance(inner, dict):
        return ""
    goal = inner.get("goal") or {}
    if isinstance(goal, dict) and goal.get("id"):
        return str(goal["id"])
    execution = inner.get("execution") or {}
    if isinstance(execution, dict) and execution.get("goal_id"):
        return str(execution["goal_id"])
    mission = inner.get("mission") or {}
    if isinstance(mission, dict):
        mission_goal = mission.get("goal") or {}
        if isinstance(mission_goal, dict) and mission_goal.get("id"):
            return str(mission_goal["id"])
    return ""


def _remember_session_goal(agent: JarvisAgent, session_id: str, result: dict[str, Any]) -> None:
    goal_id = _result_goal_id(result)
    if goal_id.startswith("goal_"):
        _session_bindings(agent)[session_id] = goal_id


def _kernel_for(agent: JarvisAgent, control: Any):
    """Reuse the same ExecutiveKernel as normal run_executive for session continuity."""
    from jarvis.amaura.cognition import ExecutiveKernel

    lock = getattr(agent, "_executive_lock", None)
    if lock is None:
        return ExecutiveKernel(control)
    with lock:
        kernel = getattr(agent, "_executive_kernel", None)
        kernel_control = getattr(agent, "_executive_control", None)
        if kernel is None or kernel_control is not control:
            kernel = ExecutiveKernel(control)
            agent._executive_kernel = kernel
            agent._executive_control = control
        return kernel


def _bound_status_response(
    agent: JarvisAgent,
    *,
    control: Any,
    session_id: str,
) -> dict[str, Any] | None:
    """Read status for the mission created most recently in this exact session."""
    goal_id = _session_bindings(agent).get(session_id, "")
    if not goal_id:
        return None
    try:
        kernel = _kernel_for(agent, control)
        mission = kernel.brain.status(goal_id)
    except Exception:
        # A stale binding must never produce a fabricated answer. Forget it and
        # allow the normal durable resolver to try instead.
        _session_bindings(agent).pop(session_id, None)
        return None

    goal = mission.get("goal") or {}
    title = str(goal.get("title") or "current mission")
    state = str(mission.get("state") or goal.get("state") or "unknown")
    states = mission.get("states") or {}
    state_text = ", ".join(f"{name}={count}" for name, count in sorted(states.items())) or "no task state recorded"

    summaries: list[str] = []
    for task in mission.get("active_tasks") or mission.get("tasks") or []:
        summary = str(task.get("summary") or "").strip()
        if summary:
            summaries.append(f"- {task.get('title') or task.get('id')}: {summary[:1000]}")
    if summaries:
        result_text = "\nRecorded task results:\n" + "\n".join(summaries[:6])
    else:
        result_text = "\nNo completed task result has been recorded yet."

    pending = mission.get("pending_approvals") or []
    approval_text = f"\nPending founder approvals: {len(pending)}." if pending else ""
    message = (
        f"Your current-session mission {goal_id} ({title}) is {state}. "
        f"Task states: {state_text}.{result_text}{approval_text}"
    )
    return {
        "intent": "status",
        "message": message,
        "session_id": session_id,
        "goal_id": goal_id,
        "state": state,
        "result": {"mission": mission, "session_bound": True},
        "context_sources": [f"session-mission:{goal_id}"],
        "frontdoor": {"session_bound_status": True, "bound_goal_id": goal_id},
        "model_provenance": {
            "provider": "company-store",
            "model": "",
            "fallback_used": False,
            "fallback_reason": "",
        },
    }


def _run_forced(
    agent: JarvisAgent,
    user_input: str,
    *,
    control: Any,
    session_id: str,
    workspace: str,
    autonomy: str,
    coding_backend: str,
    allow_missions: bool,
    allow_memory_mutation: bool,
    intent: str,
) -> dict[str, Any]:
    from jarvis.amaura.cognition import ExecutiveRequest

    is_new_project = intent == "mission" and _is_new_software_project(user_input)
    request_workspace = "" if is_new_project else workspace
    metadata: dict[str, Any] = {
        "frontdoor_forced_intent": intent,
        "workspace_source": "managed_new_project" if is_new_project else "explicit_or_cli_context",
    }
    if is_new_project:
        # This flag makes GoalCompiler use its safe deterministic new-software
        # plan even when a later layer supplies/provisions a workspace.
        metadata["managed_new_project"] = True

    kernel = _kernel_for(agent, control)
    response = kernel.handle(
        ExecutiveRequest(
            text=user_input,
            session_id=session_id,
            workspace=request_workspace,
            autonomy=autonomy,  # type: ignore[arg-type]
            coding_backend=coding_backend,  # type: ignore[arg-type]
            force_intent=intent,  # type: ignore[arg-type]
            metadata=metadata,
        ),
        allow_missions=allow_missions,
        allow_memory_mutation=allow_memory_mutation,
    )
    payload = response.model_dump(mode="json")
    payload["frontdoor"] = {
        "forced_intent": intent,
        "new_project_isolated": is_new_project,
    }
    _remember_session_goal(agent, session_id, payload)
    return payload


def reliable_run_executive(
    self: JarvisAgent,
    user_input: str,
    *,
    control: Any,
    session_id: str = "default",
    workspace: str = "",
    autonomy: str = "execute_until_approval",
    coding_backend: str = "antigravity",
    allow_missions: bool = True,
    allow_memory_mutation: bool = True,
    on_token: Any = None,
) -> dict[str, Any]:
    """Execute one turn with deterministic front-door routing and crash recovery."""
    from jarvis.amaura.models import GovernanceError

    forced = _forced_intent(user_input)
    try:
        if _is_vague_work_item_result_query(user_input):
            bound = _bound_status_response(self, control=control, session_id=session_id)
            if bound is not None:
                return bound

        if forced:
            return _run_forced(
                self,
                user_input,
                control=control,
                session_id=session_id,
                workspace=workspace,
                autonomy=autonomy,
                coding_backend=coding_backend,
                allow_missions=allow_missions,
                allow_memory_mutation=allow_memory_mutation,
                intent=forced,
            )

        result = _ORIGINAL_RUN_EXECUTIVE(
            self,
            user_input,
            control=control,
            session_id=session_id,
            workspace=workspace,
            autonomy=autonomy,
            coding_backend=coding_backend,
            allow_missions=allow_missions,
            allow_memory_mutation=allow_memory_mutation,
            on_token=on_token,
        )
        _remember_session_goal(self, session_id, result)

        # One bounded retry is enough to absorb a stale pooled connection or a
        # single transient gateway miss.  We intentionally do not reset the
        # circuit breaker or silently broaden provider/data authority.
        if str(result.get("message") or "").strip() == _UNAVAILABLE_MESSAGE and on_token is None:
            time.sleep(0.15)
            retry = _ORIGINAL_RUN_EXECUTIVE(
                self,
                user_input,
                control=control,
                session_id=session_id,
                workspace=workspace,
                autonomy=autonomy,
                coding_backend=coding_backend,
                allow_missions=allow_missions,
                allow_memory_mutation=allow_memory_mutation,
                on_token=on_token,
            )
            _remember_session_goal(self, session_id, retry)
            retry.setdefault("frontdoor", {})
            retry["frontdoor"]["transient_retry"] = True
            return retry
        return result
    except GovernanceError as exc:
        return _safe_error_response(
            intent=forced or "mission",
            message=f"Governance rejected this request safely: {exc}. JARVIS remains online.",
            error_type="governance",
            detail=str(exc),
        )
    except Exception as exc:  # pragma: no cover - exercised with injected failure in tests
        return _safe_error_response(
            intent=forced or "conversation",
            message="JARVIS recovered from an internal execution error and remains online. The request was not marked successful.",
            error_type=type(exc).__name__,
            detail=str(exc),
        )


def install_reliability_boundary() -> None:
    """Patch the process-local JarvisAgent entrypoint exactly once."""
    if getattr(JarvisAgent.run_executive, "_amaura_reliable_boundary", False):
        return
    reliable_run_executive._amaura_reliable_boundary = True  # type: ignore[attr-defined]
    JarvisAgent.run_executive = reliable_run_executive  # type: ignore[method-assign]


def main() -> Any:
    install_reliability_boundary()
    from jarvis.cli import main as legacy_main

    return legacy_main()


if __name__ == "__main__":
    main()
