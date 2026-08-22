"""Deterministic same-session mission-control guard for the founder CLI.

This layer runs after :mod:`jarvis.reliable_cli`.  It prevents conversational
follow-ups such as ``execute it`` or ``approve the task ... build it`` from
being interpreted as brand-new goals when the current CLI session already has a
bound mission.  It also scopes terse confirmations to that mission only.

The guard never widens authority: held missions are activated through
``JarvisBrain.activate`` and task approvals still flow through the founder-only
``AmauraControlPlane.decide_approval`` boundary.
"""

from __future__ import annotations

import re
from typing import Any

from jarvis.agent import JarvisAgent
from jarvis.reliable_cli import _kernel_for, _session_bindings

_PREVIOUS_RUN_EXECUTIVE = JarvisAgent.run_executive
_WORK_ITEM_RE = re.compile(r"\b(?:goal|task|proj|mile)_[A-Za-z0-9]+\b", re.IGNORECASE)

_BARE_AFFIRMATIONS = {
    "yes",
    "yep",
    "yeah",
    "sure",
    "ok",
    "okay",
    "approve",
    "approved",
    "go ahead",
    "do it",
    "proceed",
}
_CONTROL_ACTIONS = {
    "approve",
    "activate",
    "execute",
    "run",
    "start",
    "continue",
    "resume",
    "finish",
    "complete",
    "build",
    "focus",
    "proceed",
}
_CONTROL_REFERENCES = {
    "it",
    "that",
    "this",
    "task",
    "mission",
    "goal",
    "project",
    "work",
    "one",
    "first",
    "same",
}
_GENERIC_TITLE_WORDS = {
    "a",
    "an",
    "the",
    "build",
    "create",
    "make",
    "develop",
    "game",
    "app",
    "application",
    "project",
    "mission",
    "task",
    "like",
    "full",
}


def _clean(text: str) -> str:
    return " ".join(str(text).strip().lower().split())


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9][a-z0-9_+-]*", _clean(text)))


def _control_action(text: str) -> str:
    clean = _clean(text)
    tokens = _tokens(clean)
    if "cancel" in tokens or "stop" in tokens:
        return "cancel"
    if "pause" in tokens:
        return "pause"
    if clean in _BARE_AFFIRMATIONS or tokens & _CONTROL_ACTIONS:
        return "activate"
    return ""


def _explicit_bound_control_language(text: str) -> bool:
    """Return True only for language that explicitly refers back to existing work."""
    if _WORK_ITEM_RE.search(text):
        # Explicit ids are already handled safely by the core reference resolver.
        return False
    clean = _clean(text)
    tokens = _tokens(clean)
    if clean in _BARE_AFFIRMATIONS:
        return True
    if (tokens & {"cancel", "stop", "pause"}) and (tokens & _CONTROL_REFERENCES):
        return True
    if (tokens & _CONTROL_ACTIONS) and (tokens & _CONTROL_REFERENCES):
        return True
    if "go ahead" in clean and (tokens & _CONTROL_REFERENCES):
        return True
    return False


def _title_matches_control(text: str, mission: dict[str, Any]) -> bool:
    """Allow ``execute street fighter`` without hijacking unrelated new projects."""
    action_tokens = _tokens(text) & _CONTROL_ACTIONS
    if not action_tokens:
        return False
    goal = mission.get("goal") or {}
    title_tokens = _tokens(str(goal.get("title") or "")) - _GENERIC_TITLE_WORDS
    if not title_tokens:
        return False
    return bool((_tokens(text) - _GENERIC_TITLE_WORDS) & title_tokens)


def _response(
    *,
    session_id: str,
    goal_id: str,
    mission: dict[str, Any],
    message: str,
    action: str,
    changed: bool,
) -> dict[str, Any]:
    return {
        "intent": "mission_control",
        "message": message,
        "session_id": session_id,
        "goal_id": goal_id,
        "state": str(mission.get("state") or ""),
        "result": {
            "mission": mission,
            "session_bound": True,
            "action": action,
            "changed": changed,
        },
        "context_sources": [f"session-mission:{goal_id}"],
        "frontdoor": {
            "session_bound_control": True,
            "bound_goal_id": goal_id,
            "action": action,
            "changed": changed,
        },
        "model_provenance": {
            "provider": "company-store",
            "model": "",
            "fallback_used": False,
            "fallback_reason": "",
        },
    }


def _control_error_response(*, session_id: str, goal_id: str, error: Exception) -> dict[str, Any]:
    return {
        "intent": "mission_control",
        "message": (
            f"I could not safely apply that command to current-session mission {goal_id}. "
            "I changed nothing and did not create a new mission."
        ),
        "session_id": session_id,
        "goal_id": goal_id,
        "state": "failed",
        "result": {
            "session_bound": True,
            "action": "control_error",
            "changed": False,
            "error_type": type(error).__name__,
        },
        "context_sources": [f"session-mission:{goal_id}"],
        "frontdoor": {
            "session_bound_control": True,
            "bound_goal_id": goal_id,
            "action": "control_error",
            "changed": False,
        },
        "model_provenance": {
            "provider": "company-store",
            "model": "",
            "fallback_used": False,
            "fallback_reason": "control_error",
        },
    }


def _bound_control_response(
    agent: JarvisAgent,
    text: str,
    *,
    control: Any,
    session_id: str,
) -> dict[str, Any] | None:
    goal_id = _session_bindings(agent).get(session_id, "")
    if not goal_id:
        return None

    kernel = _kernel_for(agent, control)
    try:
        mission = kernel.brain.status(goal_id)
    except Exception:
        # Stale session binding: let the existing durable resolver handle the turn.
        _session_bindings(agent).pop(session_id, None)
        return None

    explicit = _explicit_bound_control_language(text)
    title_match = _title_matches_control(text, mission)
    clean = _clean(text)
    bare = clean in _BARE_AFFIRMATIONS
    if not explicit and not title_match:
        return None

    action = _control_action(text)
    if not action:
        return None

    pending = list(mission.get("pending_approvals") or [])
    state = str(mission.get("state") or "")
    lifecycle = str(mission.get("lifecycle_state") or "")
    metadata = dict((mission.get("goal") or {}).get("metadata") or {})
    mission_runnable = bool(metadata.get("mission_runnable"))

    if action == "cancel":
        updated = kernel.brain.cancel(goal_id, actor="founder", reason="Founder interactive CLI request")
        return _response(
            session_id=session_id,
            goal_id=goal_id,
            mission=updated,
            message=f"Cancelled current-session mission {goal_id}. No new mission was created.",
            action="cancel",
            changed=True,
        )

    if action == "pause":
        updated = kernel.brain.pause(goal_id, actor="founder", reason="Founder interactive CLI request")
        return _response(
            session_id=session_id,
            goal_id=goal_id,
            mission=updated,
            message=f"Paused current-session mission {goal_id}. No new mission was created.",
            action="pause",
            changed=True,
        )

    # A real task-level consequence still uses the founder approval boundary.
    if pending and state == "awaiting_approval":
        explicitly_approves = bare or "approve" in _tokens(text)
        if not explicitly_approves:
            return _response(
                session_id=session_id,
                goal_id=goal_id,
                mission=mission,
                message=(
                    f"Mission {goal_id} is waiting for founder approval. I did not approve anything from the vague "
                    "execution request. Say 'approve' only if you want to approve the single pending consequence."
                ),
                action="approval_required",
                changed=False,
            )
        if len(pending) != 1:
            return _response(
                session_id=session_id,
                goal_id=goal_id,
                mission=mission,
                message=(
                    f"Mission {goal_id} has {len(pending)} pending founder approvals. I did not choose among them. "
                    "Specify the approval/task id."
                ),
                action="approval_ambiguous",
                changed=False,
            )
        approval_id = str(pending[0].get("id") or "")
        if not approval_id:
            return _response(
                session_id=session_id,
                goal_id=goal_id,
                mission=mission,
                message=f"Mission {goal_id} has a malformed pending approval, so I changed nothing.",
                action="approval_invalid",
                changed=False,
            )
        control.decide_approval(
            approval_id,
            actor=control.founder_id,
            decision="approved",
            reason=f"Founder confirmed current-session mission {goal_id} in interactive CLI",
        )
        updated = kernel.brain.status(goal_id)
        return _response(
            session_id=session_id,
            goal_id=goal_id,
            mission=updated,
            message=f"Approved the single pending consequence for current-session mission {goal_id}.",
            action="approve",
            changed=True,
        )

    # Held/planned work is released exactly once.  If it is already runnable,
    # follow-up execution language is a no-op instead of a duplicate goal.
    if lifecycle in {"planned", "held"} or not mission_runnable:
        updated = kernel.brain.activate(goal_id, actor="founder")
        return _response(
            session_id=session_id,
            goal_id=goal_id,
            mission=updated,
            message=f"Activated current-session mission {goal_id}. No duplicate mission was created.",
            action="activate",
            changed=True,
        )

    if bare:
        # Do not let a bare confirmation fall into free-form chat and fabricate
        # an action after the mission is already running.
        return _response(
            session_id=session_id,
            goal_id=goal_id,
            mission=mission,
            message=(
                f"Current-session mission {goal_id} is already {state}. There is no pending approval to apply, "
                "so I changed nothing."
            ),
            action="noop",
            changed=False,
        )

    return _response(
        session_id=session_id,
        goal_id=goal_id,
        mission=mission,
        message=(
            f"Current-session mission {goal_id} is already {state}; I kept working under that same mission. "
            "No duplicate goal was created."
        ),
        action="continue_existing",
        changed=False,
    )


def session_bound_run_executive(
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
    if allow_missions:
        bound_goal_id = _session_bindings(self).get(session_id, "")
        recognized_bound_control = bool(bound_goal_id) and _explicit_bound_control_language(user_input)
        try:
            bound = _bound_control_response(self, user_input, control=control, session_id=session_id)
            if bound is not None:
                return bound
        except Exception as exc:
            if recognized_bound_control:
                return _control_error_response(session_id=session_id, goal_id=bound_goal_id, error=exc)
            # If the text was not explicit bound-control language, preserve the
            # existing reliable router instead of guessing a state-changing action.

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


def install_session_control_guard() -> None:
    if getattr(JarvisAgent.run_executive, "_amaura_session_control_guard", False):
        return
    session_bound_run_executive._amaura_session_control_guard = True  # type: ignore[attr-defined]
    JarvisAgent.run_executive = session_bound_run_executive  # type: ignore[method-assign]
