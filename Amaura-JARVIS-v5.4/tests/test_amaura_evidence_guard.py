from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import jarvis.amaura.executor as executor
from jarvis.amaura.executor import _EvidenceAwareClient
from jarvis.amaura.models import GovernanceError


def _response(content: str, *, tool_calls=None, prompt_tokens: int = 1, completion_tokens: int = 1):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=content,
                    tool_calls=list(tool_calls or []),
                )
            )
        ],
        model="fake-model",
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        ),
    )


def _tool_call():
    return SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(name="web_fetch", arguments='{"url":"https://example.com"}'),
    )


def _tool_definition():
    return {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch public text",
            "parameters": {"type": "object"},
        },
    }


def _named_tool_definition(name: str):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "qualification tool",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def _web_search_definition():
    return {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search public web results",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    }


def _packet_messages(objective: str, criteria: list[str] | None = None):
    return [
        {
            "role": "user",
            "content": "JARVIS TASK PACKET:\n"
            + json.dumps({"objective": objective, "acceptance_criteria": criteria or ["verified"]}),
        }
    ]


def _successful_tool_message(call_id: str = "call-1") -> dict[str, str]:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": '{"ok":true,"data":{"output":"verified"},"error":null,"external_id":"","retryable":false}',
    }


class _FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.last_execution_metadata = {
            "actual_provider": "fake",
            "actual_model": "fake-model",
        }

    def chat_sync(self, *, model_id, messages, tools=None):
        self.calls.append({"model_id": model_id, "messages": list(messages), "tools": tools})
        return self.responses.pop(0)


def test_prose_only_completion_is_corrected_then_tool_call_is_returned():
    inner = _FakeClient(
        [
            _response("Done", prompt_tokens=3, completion_tokens=2),
            _response("Using evidence", tool_calls=[_tool_call()], prompt_tokens=5, completion_tokens=4),
        ]
    )
    client = _EvidenceAwareClient(inner, evidence_required=True)

    result = client.chat_sync(
        model_id="fake-model",
        messages=[{"role": "user", "content": "task"}],
        tools=[_tool_definition()],
    )

    assert len(inner.calls) == 2
    assert result.choices[0].message.tool_calls
    assert result.usage.prompt_tokens == 8
    assert result.usage.completion_tokens == 6
    assert client.last_execution_metadata["evidence_guard_corrective_reprompts"] == 1
    correction = inner.calls[1]["messages"][-1]["content"]
    assert "governed evidence packet is incomplete" in correction
    assert "web_fetch" in correction


def test_acceptance_criteria_without_callable_tools_fail_closed_before_model_call():
    inner = _FakeClient([_response("Done")])
    client = _EvidenceAwareClient(inner, evidence_required=True)

    with pytest.raises(GovernanceError, match="no callable authorized tools"):
        client.chat_sync(model_id="fake-model", messages=[{"role": "user", "content": "task"}], tools=None)

    assert inner.calls == []


def test_prose_only_completion_is_allowed_when_acceptance_evidence_is_not_required():
    inner = _FakeClient([_response("Informational answer")])
    client = _EvidenceAwareClient(inner, evidence_required=False)

    result = client.chat_sync(model_id="fake-model", messages=[{"role": "user", "content": "task"}], tools=None)

    assert result.choices[0].message.content == "Informational answer"
    assert len(inner.calls) == 1


def test_successful_prior_tool_result_allows_completion_summary_without_reprompt():
    inner = _FakeClient([_response("Verified summary")])
    client = _EvidenceAwareClient(inner, evidence_required=True)
    messages = [
        {"role": "user", "content": "task"},
        _successful_tool_message(),
    ]

    result = client.chat_sync(model_id="fake-model", messages=messages, tools=[_tool_definition()])

    assert result.choices[0].message.content == "Verified summary"
    assert len(inner.calls) == 1


def test_failed_tool_result_does_not_count_as_successful_evidence():
    inner = _FakeClient(
        [
            _response("Done anyway"),
            _response("Retry with a tool", tool_calls=[_tool_call()]),
        ]
    )
    client = _EvidenceAwareClient(inner, evidence_required=True)
    messages = [
        {"role": "user", "content": "task"},
        {
            "role": "tool",
            "tool_call_id": "call-0",
            "content": '{"ok":false,"data":{},"error":"failed","external_id":"","retryable":false}',
        },
    ]

    result = client.chat_sync(model_id="fake-model", messages=messages, tools=[_tool_definition()])

    assert result.choices[0].message.tool_calls
    assert len(inner.calls) == 2


def test_second_prose_only_research_response_bootstraps_authorized_web_search():
    inner = _FakeClient(
        [
            _response("I can answer from general knowledge", prompt_tokens=3, completion_tokens=2),
            _response("Here is the answer without sources", prompt_tokens=4, completion_tokens=3),
        ]
    )
    client = _EvidenceAwareClient(inner, evidence_required=True)
    objective = "Collect real Amaura product evidence, credible sources, audience questions, and content gaps."
    messages = _packet_messages(objective)

    result = client.chat_sync(
        model_id="fake-model",
        messages=messages,
        tools=[_web_search_definition()],
    )

    assert len(inner.calls) == 2
    call = result.choices[0].message.tool_calls[0]
    assert call.function.name == "web_search"
    assert json.loads(call.function.arguments) == {"max_results": 5, "query": objective}
    assert call.id.startswith("call_arch_evidence_bootstrap_")
    assert result.usage.prompt_tokens == 7
    assert result.usage.completion_tokens == 5
    assert client.last_execution_metadata["evidence_guard"] == "deterministic_read_only_bootstrap"
    assert client.last_execution_metadata["evidence_guard_bootstrap_tool"] == "web_search"
    assert client.last_execution_metadata["evidence_guard_bootstrap_call_count"] == 1


def test_multi_criterion_research_bootstrap_gathers_one_bounded_search_per_criterion():
    criteria = [
        "Source register complete",
        "Amaura relevance explained",
        "No competitor copying",
    ]
    objective = "Research demand and verified context"
    inner = _FakeClient([_response("Done"), _response("Still prose")])
    client = _EvidenceAwareClient(inner, evidence_required=True)

    result = client.chat_sync(
        model_id="fake-model",
        messages=_packet_messages(objective, criteria),
        tools=[_web_search_definition()],
    )

    calls = result.choices[0].message.tool_calls
    assert len(calls) == 3
    assert all(call.function.name == "web_search" for call in calls)
    queries = [json.loads(call.function.arguments)["query"] for call in calls]
    for criterion, query in zip(criteria, queries, strict=True):
        assert objective in query
        assert criterion in query
    assert all(call.id.startswith("call_arch_evidence_bootstrap_") for call in calls)
    assert client.last_execution_metadata["evidence_guard_bootstrap_call_count"] == 3
    assert client.last_execution_metadata["evidence_guard_bootstrap_criteria_count"] == 3


def test_multi_criterion_research_does_not_accept_one_generic_successful_search_then_prose():
    criteria = ["criterion one", "criterion two", "criterion three"]
    messages = [*_packet_messages("Research verified demand", criteria), _successful_tool_message()]
    inner = _FakeClient([_response("One result is enough"), _response("Still prose")])
    client = _EvidenceAwareClient(inner, evidence_required=True)

    result = client.chat_sync(model_id="fake-model", messages=messages, tools=[_web_search_definition()])

    assert len(inner.calls) == 2
    assert len(result.choices[0].message.tool_calls) == 3
    correction = inner.calls[1]["messages"][-1]["content"]
    assert "1/3" in correction
    assert "criterion one" in correction
    assert "criterion three" in correction


def test_multi_criterion_research_allows_summary_after_bounded_evidence_target_is_met():
    criteria = ["criterion one", "criterion two", "criterion three"]
    messages = [
        *_packet_messages("Research verified demand", criteria),
        _successful_tool_message("call-1"),
        _successful_tool_message("call-2"),
        _successful_tool_message("call-3"),
    ]
    inner = _FakeClient([_response("Evidence-backed summary")])
    client = _EvidenceAwareClient(inner, evidence_required=True)

    result = client.chat_sync(model_id="fake-model", messages=messages, tools=[_web_search_definition()])

    assert result.choices[0].message.content == "Evidence-backed summary"
    assert len(inner.calls) == 1


def test_criterion_bootstrap_is_capped_even_when_task_has_many_criteria():
    criteria = [f"criterion {index}" for index in range(10)]
    calls = executor._deterministic_bootstrap_calls(
        _packet_messages("Research demand", criteria),
        [_web_search_definition()],
    )

    assert len(calls) == executor._MAX_CRITERION_BOOTSTRAP_CALLS == 4


def test_cashflow_objective_prefers_cashflow_dashboard_over_generic_company_status():
    bootstrap = executor._deterministic_bootstrap(
        _packet_messages("Reconcile active cash-flow streams and verify runway evidence."),
        [
            _named_tool_definition("amaura_company_status"),
            _named_tool_definition("amaura_cashflow_dashboard"),
        ],
    )

    assert bootstrap == ("amaura_cashflow_dashboard", {})


def test_operating_objective_prefers_company_status_over_web_search():
    bootstrap = executor._deterministic_bootstrap(
        _packet_messages("Create an operating snapshot of company tasks and blockers."),
        [
            _web_search_definition(),
            _named_tool_definition("amaura_company_status"),
        ],
    )

    assert bootstrap == ("amaura_company_status", {})


def test_repository_objective_prefers_read_only_project_structure_over_web_search():
    bootstrap = executor._deterministic_bootstrap(
        _packet_messages("Inspect repository health and source code structure."),
        [
            _web_search_definition(),
            _named_tool_definition("get_project_structure"),
            _named_tool_definition("git_status"),
        ],
    )

    assert bootstrap == ("get_project_structure", {"max_depth": 3})


def test_non_query_snapshot_bootstrap_is_not_duplicated_for_multiple_criteria():
    calls = executor._deterministic_bootstrap_calls(
        _packet_messages("Create an operating snapshot of company tasks and blockers.", ["one", "two", "three"]),
        [_named_tool_definition("amaura_company_status")],
    )

    assert calls == [("amaura_company_status", {})]


def test_second_prose_only_response_fails_closed_after_one_corrective_reprompt():
    inner = _FakeClient([_response("Done"), _response("Still done")])
    client = _EvidenceAwareClient(inner, evidence_required=True)

    with pytest.raises(GovernanceError, match="one bounded corrective tool-use prompt"):
        client.chat_sync(
            model_id="fake-model",
            messages=[{"role": "user", "content": "task"}],
            tools=[_tool_definition()],
        )

    assert len(inner.calls) == 2


def test_bootstrap_cannot_repeat_after_a_prior_synthetic_call():
    messages = [
        *_packet_messages("Research demand", ["one", "two"]),
        {
            "role": "tool",
            "tool_call_id": "call_arch_evidence_bootstrap_1_0",
            "content": '{"ok":false,"data":{},"error":"network","external_id":"","retryable":false}',
        },
    ]

    assert executor._deterministic_bootstrap_calls(messages, [_web_search_definition()]) == []


def test_legacy_executor_monkeypatches_are_mirrored_into_core(monkeypatch):
    original = executor._core.fetch_public_text

    def fake_fetch(url: str, max_length: int = 10_000):
        return f"fake:{url}:{max_length}"

    monkeypatch.setattr(executor, "fetch_public_text", fake_fetch)
    assert executor._core.fetch_public_text is fake_fetch
    monkeypatch.setattr(executor, "fetch_public_text", original)
    assert executor._core.fetch_public_text is original
