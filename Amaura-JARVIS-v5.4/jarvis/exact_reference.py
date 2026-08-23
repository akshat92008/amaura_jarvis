"""Fail-closed exact work-item reference handling for the founder CLI.

Literal Company OS ids are database primary keys, not natural-language hints.
For status/result queries containing exactly one ``goal_``, ``task_``,
``proj_`` or ``mile_`` id, this outer runtime guard reads CompanyStore
directly. Missing ids and ambiguous multi-id queries terminate at this layer;
they never fall through to model/fuzzy reference resolution.
"""

from __future__ import annotations

import re
from typing import Any

from jarvis.agent import JarvisAgent

_PREVIOUS_RUN_EXECUTIVE = JarvisAgent.run_executive
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


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9][a-z0-9_+-]*", str(text).lower()))


def _explicit_ids(text: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _WORK_ITEM_RE.findall(str(text)):
        item_id = match.lower()
        if item_id not in seen:
            seen.add(item_id)
            ordered.append(item_id)
    return ordered


def _is_explicit_status_query(text: str) -> bool:
    return bool(_explicit_ids(text)) and bool(_tokens(text) & _STATUS_WORDS)


def _base_response(*, session_id: str, item_id: str, state: str, message: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "intent": "status",
        "message": message,
        "session_id": session_id,
        "goal_id": item_id if item_id.startswith("goal_") else "",
        "state": state,
        "result": result,
        "context_sources": [f"exact-work-item:{item_id}"],
        "frontdoor": {
            "exact_work_item_reference": True,
            "work_item_id": item_id,
        },
        "model_provenance": {
            "provider": "company-store",
            "model": "",
            "fallback_used": False,
            "fallback_reason": "",
        },
    }


def _not_found(*, session_id: str, item_id: str) -> dict[str, Any]:
    return _base_response(
        session_id=session_id,
        item_id=item_id,
        state="not_found",
        message=(
            f"No Company OS work item exists with the exact id {item_id}. "
            "I did not substitute or infer another mission."
        ),
        result={"found": False, "work_item_id": item_id, "exact_lookup": True},
    )


def _goal_status(agent: JarvisAgent, control: Any, session_id: str, goal_id: str, item: dict[str, Any]) -> dict[str, Any]:
    from jarvis.reliable_cli import _kernel_for

    try:
        mission = _kernel_for(agent, control).brain.status(goal_id)
    except Exception as exc:
        return _base_response(
            session_id=session_id,
            item_id=goal_id,
            state="status_unavailable",
            message=(
                f"The exact mission {goal_id} exists, but its detailed status could not be read safely. "
                "I did not substitute another mission."
            ),
            result={
                "found": True,
                "work_item": item,
                "exact_lookup": True,
                "status_read_failed": True,
                "error_type": type(exc).__name__,
            },
        )

    goal = mission.get("goal") or item
    title = str(goal.get("title") or goal_id)
    state = str(mission.get("state") or goal.get("state") or "unknown")
    states = mission.get("states") or {}
    state_text = ", ".join(f"{name}={count}" for name, count in sorted(states.items())) or "no task state recorded"
    summaries: list[str] = []
    for task in mission.get("active_tasks") or mission.get("tasks") or []:
        summary = str(task.get("summary") or "").strip()
        if summary:
            summaries.append(f"- {task.get('title') or task.get('id')}: {summary[:1000]}")
    result_text = "\nRecorded task results:\n" + "\n".join(summaries[:6]) if summaries else "\nNo completed task result has been recorded yet."
    pending = mission.get("pending_approvals") or []
    approval_text = f"\nPending founder approvals: {len(pending)}." if pending else ""
    return _base_response(
        session_id=session_id,
        item_id=goal_id,
        state=state,
        message=f"Exact mission {goal_id} ({title}) is {state}. Task states: {state_text}.{result_text}{approval_text}",
        result={"found": True, "mission": mission, "exact_lookup": True},
    )


def _item_status(*, control: Any, session_id: str, item_id: str, item: dict[str, Any]) -> dict[str, Any]:
    state = str(item.get("state") or "unknown")
    title = str(item.get("title") or item_id)
    summary = str(item.get("summary") or "").strip()
    owner = str(item.get("owner_id") or "")
    reviewer = str(item.get("reviewer_id") or "")
    details = [f"Exact {item.get('item_type') or 'work item'} {item_id} ({title}) is {state}."]
    if summary:
        details.append(f"Recorded result: {summary[:2000]}")
    else:
        details.append("No recorded result/summary is available yet.")
    if owner:
        details.append(f"Owner: {owner}.")
    if reviewer:
        details.append(f"Reviewer: {reviewer}.")
    return _base_response(
        session_id=session_id,
        item_id=item_id,
        state=state,
        message=" ".join(details),
        result={"found": True, "work_item": item, "exact_lookup": True},
    )


def exact_reference_run_executive(
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
    if _is_explicit_status_query(user_input):
        ids = _explicit_ids(user_input)
        if len(ids) != 1:
            return {
                "intent": "status",
                "message": "Your request contains multiple explicit Company OS ids. Specify exactly one id so I do not guess.",
                "session_id": session_id,
                "goal_id": "",
                "state": "ambiguous_reference",
                "result": {"exact_lookup": True, "ambiguous": True, "work_item_ids": ids},
                "context_sources": [],
                "frontdoor": {"exact_work_item_reference": True, "ambiguous": True},
                "model_provenance": {"provider": "company-store", "model": "", "fallback_used": False, "fallback_reason": ""},
            }

        item_id = ids[0]
        try:
            item = control.store.get_work_item(item_id)
        except KeyError:
            return _not_found(session_id=session_id, item_id=item_id)
        except Exception as exc:
            return _base_response(
                session_id=session_id,
                item_id=item_id,
                state="status_unavailable",
                message=(
                    f"I could not safely read the exact Company OS item {item_id}. "
                    "I did not substitute another mission."
                ),
                result={"found": None, "exact_lookup": True, "error_type": type(exc).__name__},
            )

        if item_id.startswith("goal_"):
            return _goal_status(self, control, session_id, item_id, item)
        return _item_status(control=control, session_id=session_id, item_id=item_id, item=item)

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


def install_exact_reference_guard() -> None:
    if getattr(JarvisAgent.run_executive, "_amaura_exact_reference_guard", False):
        return
    exact_reference_run_executive._amaura_exact_reference_guard = True  # type: ignore[attr-defined]
    JarvisAgent.run_executive = exact_reference_run_executive  # type: ignore[method-assign]
