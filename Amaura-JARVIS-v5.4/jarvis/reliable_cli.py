"""Hardened entry point for the founder-facing JARVIS CLI.

The core executive stack remains the source of truth.  This module only adds a
small front-door reliability boundary for patterns that must never depend on a
free-form model deciding the intent:

* explicit mission/work-item result queries read durable Company OS state;
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
    from jarvis.amaura.cognition import ExecutiveKernel, ExecutiveRequest

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

    kernel = ExecutiveKernel(control)
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

        # One bounded retry is enough to absorb a stale pooled connection or a
        # single transient gateway miss.  We intentionally do not reset the
        # circuit breaker or silently broaden provider/data authority.
        if (
            str(result.get("message") or "").strip() == _UNAVAILABLE_MESSAGE
            and on_token is None
        ):
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
