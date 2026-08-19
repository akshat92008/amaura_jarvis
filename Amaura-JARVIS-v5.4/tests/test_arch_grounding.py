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


class FakeWorld:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def get(self, *, refresh: bool = True):
        self.calls.append(("get", refresh))
        return {
            "captured_at": "fresh-now",
            "counts": {
                "active_programmes": 15,
                "held_programmes": 0,
                "running_tasks": 2,
                "failed_tasks": 0,
                "blocked_tasks": 0,
                "pending_approvals": 0,
                "open_alerts": 0,
            },
            "active_programmes": [],
            "running_tasks": [],
            "failed_tasks": [],
            "blocked_tasks": [],
            "pending_approvals": [],
            "open_alerts": [],
        }

    def context(self, query: str = "", *, refresh: bool = False) -> str:
        self.calls.append(("context", refresh))
        return '{"counts":{"active_programmes":15,"running_tasks":2}}'


class FakeMemory:
    def context(self, query: str, *, limit: int = 10):
        return "", []

    def record_episode(self, **_kwargs) -> None:
        return None


class FakeControl:
    def dashboard(self):
        return {
            "founder": "founder",
            "acquisition": {"leads": 3},
            "distribution": {"campaigns": 1},
            "telemetry": {"open_alerts": 0},
        }


def _kernel(conversation_answer: str) -> tuple[ArchExecutiveKernel, FakeWorld]:
    kernel = object.__new__(ArchExecutiveKernel)
    world = FakeWorld()
    kernel.world = world
    kernel.memory = FakeMemory()
    kernel.control = FakeControl()
    kernel._history_context = lambda _session_id: ""
    kernel._conversation = lambda _text, _context: conversation_answer
    kernel._record_turn = lambda *_args: None
    kernel._consolidate_async = lambda **_kwargs: None
    return kernel, world


def test_grounded_company_question_forces_one_fresh_world_snapshot():
    kernel, world = _kernel("Fresh company answer")

    response = kernel.handle(
        ExecutiveRequest(text="What is the current state of Amaura Labs?", session_id="test")
    )

    assert world.calls == [("get", True), ("context", False)]
    assert response.result["grounding"] == "authoritative_world_model"
    assert response.result["captured_at"] == "fresh-now"
    assert response.result["world_counts"]["active_programmes"] == 15
    assert response.result["cognition_degraded"] is False
    assert "company:dashboard" in response.context_sources


def test_grounded_company_question_has_zero_model_fallback_when_cognition_is_unavailable():
    kernel, world = _kernel("The interactive cognition service is temporarily unavailable. Please try again shortly.")
    world.get = lambda refresh=True: {
        "captured_at": "fresh-now",
        "counts": {
            "active_programmes": 12,
            "held_programmes": 0,
            "running_tasks": 0,
            "failed_tasks": 12,
            "blocked_tasks": 148,
            "pending_approvals": 0,
            "open_alerts": 14,
        },
        "active_programmes": [],
        "running_tasks": [],
        "failed_tasks": [{"id": "f1", "title": "Repair provider contract"}],
        "blocked_tasks": [],
        "pending_approvals": [],
        "open_alerts": [{"id": "a1", "code": "queue_blocked", "message": "Execution queue is blocked"}],
    }

    response = kernel.handle(
        ExecutiveRequest(
            text="JARVIS, what is the current state of Amaura Labs and what should we work on first?",
            session_id="test",
        )
    )

    assert response.result["cognition_degraded"] is True
    assert response.result["world_counts"]["blocked_tasks"] == 148
    assert "12 failed task(s)" in response.message
    assert "148 blocked task(s)" in response.message
    assert "14 open alert(s)" in response.message
    assert "Immediate priority: resolve the root execution blockers" in response.message
    assert "temporarily unavailable" not in response.message
