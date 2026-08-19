from __future__ import annotations

from jarvis.arch_grounding import needs_authoritative_world


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
