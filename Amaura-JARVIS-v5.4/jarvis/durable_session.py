"""Durable current-session goal recovery for the founder CLI.

The in-process binding in :mod:`jarvis.reliable_cli` is a fast cache only.  The
canonical source of truth is CompanyStore: every dynamic goal created by the
ExecutiveKernel records ``executive_session_id`` in its metadata.  This guard
reconstructs the latest goal for the active CLI session before status/control
routing, preventing vague follow-ups from drifting into unrelated historical
work when an in-memory binding is missing.
"""

from __future__ import annotations

from typing import Any

from jarvis.agent import JarvisAgent
from jarvis.reliable_cli import _is_vague_work_item_result_query, _session_bindings

_PREVIOUS_RUN_EXECUTIVE = JarvisAgent.run_executive


def _item_time(item: dict[str, Any]) -> str:
    return str(item.get("updated_at") or item.get("created_at") or "")


def latest_session_goal(control: Any, session_id: str) -> str:
    """Return the newest dynamic programme created by this exact session."""
    try:
        programmes = control.store.list_work_items(item_type="programme", limit=1000)
    except Exception:
        return ""
    matches: list[dict[str, Any]] = []
    for item in programmes:
        metadata = item.get("metadata") or {}
        if not isinstance(metadata, dict):
            continue
        if not metadata.get("dynamic_goal"):
            continue
        if str(metadata.get("executive_session_id") or "") != session_id:
            continue
        goal_id = str(item.get("id") or "")
        if goal_id.startswith("goal_"):
            matches.append(item)
    if not matches:
        return ""
    matches.sort(key=lambda item: (_item_time(item), str(item.get("id") or "")))
    return str(matches[-1].get("id") or "")


def _seed_durable_binding(agent: JarvisAgent, control: Any, session_id: str) -> str:
    goal_id = latest_session_goal(control, session_id)
    if goal_id:
        _session_bindings(agent)[session_id] = goal_id
    return goal_id


def _status_for_goal(agent: JarvisAgent, control: Any, session_id: str, goal_id: str) -> dict[str, Any]:
    from jarvis.reliable_cli import _kernel_for

    try:
        mission = _kernel_for(agent, control).brain.status(goal_id)
    except Exception as exc:
        # Never fall back to fuzzy/global history once this session has an
        # authoritative goal.  Preserve the exact reference and fail closed.
        return {
            "intent": "status",
            "message": (
                f"I resolved your current-session mission as {goal_id}, but its durable status could not be read safely. "
                "I did not substitute results from another mission."
            ),
            "session_id": session_id,
            "goal_id": goal_id,
            "state": "status_unavailable",
            "result": {
                "session_bound": True,
                "status_read_failed": True,
                "error_type": type(exc).__name__,
            },
            "context_sources": [f"session-mission:{goal_id}"],
            "frontdoor": {
                "durable_session_bound_status": True,
                "bound_goal_id": goal_id,
                "status_read_failed": True,
            },
        }

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
    result_text = (
        "\nRecorded task results:\n" + "\n".join(summaries[:6])
        if summaries
        else "\nNo completed task result has been recorded yet."
    )
    pending = mission.get("pending_approvals") or []
    approval_text = f"\nPending founder approvals: {len(pending)}." if pending else ""
    return {
        "intent": "status",
        "message": (
            f"Your current-session mission {goal_id} ({title}) is {state}. "
            f"Task states: {state_text}.{result_text}{approval_text}"
        ),
        "session_id": session_id,
        "goal_id": goal_id,
        "state": state,
        "result": {"mission": mission, "session_bound": True, "durable_session_lookup": True},
        "context_sources": [f"session-mission:{goal_id}"],
        "frontdoor": {"durable_session_bound_status": True, "bound_goal_id": goal_id},
    }


def durable_session_run_executive(
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
    durable_goal = _seed_durable_binding(self, control, session_id)
    if durable_goal and _is_vague_work_item_result_query(user_input):
        return _status_for_goal(self, control, session_id, durable_goal)

    return _PREVIOUS_RUN_EXECUTIVE(
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


def install_durable_session_guard() -> None:
    if getattr(JarvisAgent.run_executive, "_amaura_durable_session_guard", False):
        return
    durable_session_run_executive._amaura_durable_session_guard = True  # type: ignore[attr-defined]
    JarvisAgent.run_executive = durable_session_run_executive  # type: ignore[method-assign]
