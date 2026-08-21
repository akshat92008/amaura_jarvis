from __future__ import annotations

import json

from jarvis.amaura.models import GovernanceError
from jarvis.amaura.tool_authorization import authorization_denial_result


class _DeniedControl:
    def authorize_tool(self, task_id, agent_id, tool_name, args):
        raise GovernanceError(
            "Capability operation 'crawl4ai.crawl_domain' is not approved for AI employee execution"
        )


class _AllowedControl:
    def __init__(self):
        self.calls = []

    def authorize_tool(self, task_id, agent_id, tool_name, args):
        self.calls.append((task_id, agent_id, tool_name, args))


def test_policy_denial_is_structured_failed_tool_result() -> None:
    result = authorization_denial_result(
        _DeniedControl(),
        task_id="task_1",
        agent_id="content_research",
        tool_name="amaura_execute_capability",
        args={"capability": "crawl4ai", "operation": "crawl_domain"},
    )

    payload = json.loads(result or "{}")
    assert payload["ok"] is False
    assert payload["code"] == "POLICY_DENIED"
    assert payload["retryable"] is False
    assert "crawl4ai.crawl_domain" in payload["error"]


def test_allowed_tool_returns_no_denial_result() -> None:
    control = _AllowedControl()
    result = authorization_denial_result(
        control,
        task_id="task_2",
        agent_id="content_research",
        tool_name="web_search",
        args={"query": "Amaura AI assistant"},
    )

    assert result is None
    assert control.calls == [
        ("task_2", "content_research", "web_search", {"query": "Amaura AI assistant"})
    ]
