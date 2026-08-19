from __future__ import annotations

from jarvis.amaura.cognition import ExecutiveRequest
from jarvis.arch_grounding import ArchExecutiveKernel, needs_authoritative_world


def test_company_state_questions_are_authoritatively_grounded():
    assert needs_authoritative_world("What is the current state of Amaura Labs and what should we work on first?")
    assert needs_authoritative_world("How is our company doing on revenue and distribution?")
    assert needs_authoritative_world("What are the company priorities right now?")


def test_actionable_company_requests_stay_on_governed_execution_path():
    assert not needs_authoritative_world("Run Amaura Labs while I study")
    assert not needs_authoritative_world("Fix the highest priority engineering task for Amaura")
    assert not needs_authoritative_world("Publish the company update")


def test_unrelated_chat_does_not_pay_for_company_world_context():
    assert not needs_authoritative_world("Explain photosynthesis")
    assert not needs_authoritative_world("What is the weather like?")


def test_grounded_company_question_forces_one_fresh_world_snapshot():
    class FakeWorld:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bool]] = []

        def get(self, *, refresh: bool = True):
            self.calls.append(("get", refresh))
            return {
                "captured_at": "fresh-now",
                "counts": {"active_programmes": 15, "running_tasks": 2},
            }

        def context(self, query: str = "", *, refresh: bool = False) -> str:
            self.calls.append(("context", refresh))
            return '{"counts":{"active_programmes":15,"running_tasks":2}}'

    class FakeMemory:
        def context(self, query: str, *, limit: int = 10):
            return "", []

        def record_episode(self, **_kwargs) -> None:
            return None

    kernel = object.__new__(ArchExecutiveKernel)
    world = FakeWorld()
    kernel.world = world
    kernel.memory = FakeMemory()
    kernel._history_context = lambda _session_id: ""
    kernel._conversation = lambda _text, context: context
    kernel._record_turn = lambda *_args: None
    kernel._consolidate_async = lambda **_kwargs: None

    response = kernel.handle(
        ExecutiveRequest(text="What is the current state of Amaura Labs?", session_id="test")
    )

    assert world.calls == [("get", True), ("context", False)]
    assert response.result["grounding"] == "authoritative_world_model"
    assert response.result["captured_at"] == "fresh-now"
    assert response.result["world_counts"]["active_programmes"] == 15
