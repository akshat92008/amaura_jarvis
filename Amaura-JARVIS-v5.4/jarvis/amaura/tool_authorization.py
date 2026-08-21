"""Fail-closed worker tool authorization with recoverable denial feedback."""

from __future__ import annotations

import json
from typing import Any

from jarvis.amaura.models import GovernanceError
from jarvis.amaura.security import redact_sensitive_text


def authorization_denial_result(
    control: Any,
    *,
    task_id: str,
    agent_id: str,
    tool_name: str,
    args: dict[str, Any],
) -> str | None:
    """Authorize a worker tool call or return a structured failed tool result.

    Policy remains fail-closed: denied operations are never executed. Returning a
    normal failed tool result lets the worker observe the denial and recover with
    an approved tool instead of crashing the entire governed mission.
    """
    try:
        control.authorize_tool(task_id, agent_id, tool_name, args)
    except GovernanceError as exc:
        detail = redact_sensitive_text(str(exc))[:1000]
        return json.dumps(
            {
                "ok": False,
                "data": {},
                "error": f"Policy denied tool request: {detail}",
                "code": "POLICY_DENIED",
                "external_id": "",
                "retryable": False,
            }
        )
    return None


__all__ = ["authorization_denial_result"]
