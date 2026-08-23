"""Authoritative tests for SessionMissionContext and multi-turn conversational continuity.

Validates:
1. Isolated real CompanyStore persistence (jarvis.session_context namespace).
2. Exact 6-turn regression from the failed audit (zero new goals created).
3. Paraphrase robustness for deictic/control language.
4. Historical poisoning resistance (seeded old goals are never picked for pronouns).
5. Protection of genuinely new objectives (build a snake game != build it).
6. Fail-closed referential control language (zero goals created without active mission).
7. Multi-mission session switching and named scoping.
8. Session restart semantics.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from jarvis.amaura.cognition import ExecutiveKernel, ExecutiveRequest
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.models import TaskState
from jarvis.amaura.session_context import SessionMissionContext


@pytest.fixture
def isolated_control() -> AmauraControlPlane:
    tmpdir = tempfile.TemporaryDirectory()
    db_path = Path(tmpdir.name) / "amaura.db"
    control = AmauraControlPlane(db_path=db_path)
    yield control
    tmpdir.cleanup()


def test_session_mission_context_persistence(isolated_control: AmauraControlPlane):
    """Test 1: SessionMissionContext persists to CompanyStore knowledge table."""
    session_ctx = SessionMissionContext(isolated_control)
    session_id = "sess_persist_test"

    # Initially None
    assert session_ctx.get_active_goal(session_id) is None

    # Cannot set non-existent goal
    assert not session_ctx.set_active_goal(session_id, "goal_nonexistent")

    # Create real programme in store
    prog = isolated_control.store.insert_work_item(
        {
            "id": "goal_weather123",
            "item_type": "programme",
            "title": "Test Weather Mission",
            "owner_id": "operator",
            "metadata": {"dynamic_goal": True, "executive_session_id": session_id},
        }
    )
    goal_id = str(prog["id"])

    # Set active goal
    assert session_ctx.set_active_goal(session_id, goal_id, reason="created")

    # Cached lookup
    assert session_ctx.get_active_goal(session_id) == goal_id

    # Verify persisted knowledge in DB
    rec = isolated_control.store.get_knowledge(SessionMissionContext.NAMESPACE, session_id)
    assert rec["value"]["current_goal_id"] == goal_id
    assert rec["value"]["reason"] == "created"

    # New instance reading from DB
    new_session_ctx = SessionMissionContext(isolated_control)
    assert new_session_ctx.get_active_goal(session_id) == goal_id


def test_exact_audit_sequence_continuity(isolated_control: AmauraControlPlane):
    """Test 2: Exact regression from the failed audit sequence.

    Turn 0: Create fighter game mission.
    Turn 1: "what are the results of the task i gave you?"
    Turn 2: "what's its status?"
    Turn 3: "continue it"
    Turn 4: "focus on that first"
    Turn 5: "yes"
    Turn 6: "execute it"

    Asserts:
    - Every follow-up turn targets the exact expected goal ID.
    - Zero new goals created by follow-ups.
    - Zero historical goals modified.
    """
    kernel = ExecutiveKernel(isolated_control)
    session_id = "sess_audit_fighter"

    # Turn 0: Create the game mission
    init_req = ExecutiveRequest(
        text="build me a small arcade fighting game with sounds on my Desktop called founder-test-fighter",
        session_id=session_id,
    )
    init_resp = kernel.handle(init_req)
    assert init_resp.goal_id
    expected_goal_id = init_resp.goal_id

    # Verify initial programme count = 1
    progs_before = [
        it for it in isolated_control.store.list_work_items(limit=100) if it.get("item_type") == "programme"
    ]
    assert len(progs_before) == 1
    assert progs_before[0]["id"] == expected_goal_id

    # Sequence of follow-up turns
    turns = [
        ("what are the results of the task i gave you?", "status"),
        ("what's its status?", "status"),
        ("continue it", "mission_control"),
        ("focus on that first", "mission_control"),
        ("yes", "mission_control"),
        ("execute it", "mission_control"),
    ]

    for prompt, _expected_intent in turns:
        req = ExecutiveRequest(text=prompt, session_id=session_id)
        resp = kernel.handle(req)

        # Assert target goal match
        actual_target = (
            resp.goal_id
            or resp.result.get("reference", {}).get("target_id")
            or resp.result.get("item", {}).get("id")
            or resp.result.get("goal_id")
        )
        assert (
            actual_target == expected_goal_id
        ), f"Prompt '{prompt}' targeted '{actual_target}', expected '{expected_goal_id}'"

        # Assert zero new goals created
        current_progs = [
            it for it in isolated_control.store.list_work_items(limit=100) if it.get("item_type") == "programme"
        ]
        assert (
            len(current_progs) == 1
        ), f"Prompt '{prompt}' created a new goal! Total goals now: {len(current_progs)}"
        assert current_progs[0]["id"] == expected_goal_id


def test_paraphrase_continuity_regressions(isolated_control: AmauraControlPlane):
    """Test 3: Paraphrase regressions for deictic/control language."""
    kernel = ExecutiveKernel(isolated_control)
    session_id = "sess_paraphrase_test"

    init_req = ExecutiveRequest(
        text="build me a small arcade fighting game with sounds on my Desktop called founder-test-fighter",
        session_id=session_id,
    )
    init_resp = kernel.handle(init_req)
    expected_goal_id = init_resp.goal_id

    paraphrases = [
        "bro continue that game first",
        "nah work on that one first",
        "what happened with the thing i asked you to build",
        "go ahead with it",
        "finish that",
        "resume my current project",
        "status of that",
        "did it finish",
        "yes do it",
        "execute the same one",
    ]

    for prompt in paraphrases:
        req = ExecutiveRequest(text=prompt, session_id=session_id)
        resp = kernel.handle(req)

        actual_target = (
            resp.goal_id
            or resp.result.get("reference", {}).get("target_id")
            or resp.result.get("item", {}).get("id")
            or resp.result.get("goal_id")
        )
        assert (
            actual_target == expected_goal_id
        ), f"Paraphrase '{prompt}' targeted '{actual_target}', expected '{expected_goal_id}'"

        current_progs = [
            it for it in isolated_control.store.list_work_items(limit=100) if it.get("item_type") == "programme"
        ]
        assert len(current_progs) == 1, f"Paraphrase '{prompt}' created a duplicate goal!"


def test_historical_poisoning_isolation(isolated_control: AmauraControlPlane):
    """Test 4: Historical poisoning test.

    Seed the database with many tempting old tasks from yesterday/previous weeks.
    Verify that pronoun references in a new session with an active mission NEVER touch
    or select historical items.
    """
    # Seed historical tasks
    isolated_control.store.insert_work_item(
        {
            "id": "goal_oldgame1",
            "item_type": "programme",
            "title": "build arcade game with sound",
            "owner_id": "operator",
            "metadata": {"dynamic_goal": True, "executive_session_id": "old_session_1"},
        }
    )
    isolated_control.store.insert_work_item(
        {
            "id": "goal_oldresearch",
            "item_type": "programme",
            "title": "research AI coding agents and trends",
            "owner_id": "operator",
            "metadata": {"dynamic_goal": True, "executive_session_id": "old_session_2"},
        }
    )
    isolated_control.store.insert_work_item(
        {
            "id": "goal_oldreview",
            "item_type": "programme",
            "title": "review pull request for authentication",
            "owner_id": "operator",
            "metadata": {"dynamic_goal": True, "executive_session_id": "old_session_3"},
        }
    )
    for i in range(5):
        isolated_control.store.insert_work_item(
            {
                "id": f"task_old{i}",
                "item_type": "task",
                "title": f"historical task {i}",
                "owner_id": "operator",
                "state": TaskState.IN_PROGRESS.value,
            }
        )

    assert len(isolated_control.store.list_work_items(limit=100)) == 8

    kernel = ExecutiveKernel(isolated_control)
    session_id = "sess_current_poison_test"

    # Create current mission
    init_req = ExecutiveRequest(
        text="build me a small arcade fighting game with sounds on my Desktop called founder-test-fighter",
        session_id=session_id,
    )
    init_resp = kernel.handle(init_req)
    current_goal_id = init_resp.goal_id
    assert current_goal_id

    # Pronoun queries
    pronouns = [
        "what are the results of the task i gave you?",
        "what's its status?",
        "continue it",
        "focus on that first",
        "execute it",
    ]

    for p in pronouns:
        req = ExecutiveRequest(text=p, session_id=session_id)
        resp = kernel.handle(req)

        actual_target = (
            resp.goal_id
            or resp.result.get("reference", {}).get("target_id")
            or resp.result.get("item", {}).get("id")
            or resp.result.get("goal_id")
        )
        assert (
            actual_target == current_goal_id
        ), f"Historical poisoning leak! Prompt '{p}' selected '{actual_target}', not '{current_goal_id}'"


def test_protect_new_objectives(isolated_control: AmauraControlPlane):
    """Test 5: Negative control - genuine new requests must not be hijacked."""
    kernel = ExecutiveKernel(isolated_control)
    session_id = "sess_new_obj_test"

    # First mission
    r1 = kernel.handle(ExecutiveRequest(text="build a snake game on desktop", session_id=session_id))
    g1 = r1.goal_id
    assert g1

    # Second genuine new mission
    r2 = kernel.handle(ExecutiveRequest(text="research Nvidia GPU architecture", session_id=session_id))
    g2 = r2.goal_id
    assert g2
    assert g1 != g2

    # Verify both programmes exist in DB
    progs = [
        it for it in isolated_control.store.list_work_items(limit=100) if it.get("item_type") == "programme"
    ]
    assert len(progs) == 2

    # Follow-up "continue it" should target the most recent active goal g2
    r3 = kernel.handle(ExecutiveRequest(text="continue it", session_id=session_id))
    assert r3.goal_id == g2


def test_unresolved_referential_control_creates_zero_goals(isolated_control: AmauraControlPlane):
    """Test 6: Referential control language without active mission returns reference_required and creates 0 goals."""
    kernel = ExecutiveKernel(isolated_control)
    session_id = "sess_fresh_no_anchor"

    progs_before = [
        it for it in isolated_control.store.list_work_items(limit=100) if it.get("item_type") == "programme"
    ]
    assert len(progs_before) == 0

    prompts = [
        "execute it",
        "focus on that first",
        "continue it",
        "resume that",
        "finish it",
        "yes",
    ]

    for p in prompts:
        req = ExecutiveRequest(text=p, session_id=session_id)
        resp = kernel.handle(req)
        assert resp.state == "reference_required"
        assert "couldn't resolve" in resp.message.lower() or "clarify" in resp.message.lower()

        progs_after = [
            it for it in isolated_control.store.list_work_items(limit=100) if it.get("item_type") == "programme"
        ]
        assert len(progs_after) == 0, f"Prompt '{p}' created a junk goal row!"


def test_session_scoped_multi_mission_switching(isolated_control: AmauraControlPlane):
    """Test 7: Switching between multiple named missions in one session."""
    kernel = ExecutiveKernel(isolated_control)
    session_id = "sess_multi_mission"

    r_game = kernel.handle(ExecutiveRequest(text="build an arcade fighter game", session_id=session_id))
    game_id = r_game.goal_id
    assert game_id

    r_res = kernel.handle(ExecutiveRequest(text="research AI agent benchmarks", session_id=session_id))
    res_id = r_res.goal_id
    assert res_id
    assert game_id != res_id

    # Switch to game via named reference
    r_game_stat = kernel.handle(ExecutiveRequest(text="what's the status of the game project?", session_id=session_id))
    assert r_game_stat.result.get("reference", {}).get("target_id") == game_id

    # Now "continue it" targets game_id
    r_cont_game = kernel.handle(ExecutiveRequest(text="continue it", session_id=session_id))
    assert r_cont_game.goal_id == game_id

    # Switch to research via named reference
    r_res_stat = kernel.handle(ExecutiveRequest(text="what's the status of the research task?", session_id=session_id))
    assert r_res_stat.result.get("reference", {}).get("target_id") == res_id

    # Now "continue it" targets res_id
    r_cont_res = kernel.handle(ExecutiveRequest(text="continue it", session_id=session_id))
    assert r_cont_res.goal_id == res_id


def test_session_restart_semantics(isolated_control: AmauraControlPlane):
    """Test 8: Restart semantics.

    - Session A creates goal_A.
    - Session B (new session ID) with pronoun reference fails-closed (reference_required).
    - Session B with explicit ID 'goal_A give me results' resolves and sets goal_A as active.
    - Session B subsequent 'continue it' targets goal_A.
    """
    kernel = ExecutiveKernel(isolated_control)
    session_a = "sess_restart_A"
    session_b = "sess_restart_B"

    # Session A creates a mission
    r_init = kernel.handle(ExecutiveRequest(text="build an arcade fighter game", session_id=session_a))
    goal_id = r_init.goal_id
    assert goal_id

    # Session B (new process/session) sends pronoun -> fail-closed
    r_pronoun_b = kernel.handle(ExecutiveRequest(text="what's its status?", session_id=session_b))
    assert r_pronoun_b.state == "reference_required"

    # Session B uses explicit ID
    r_explicit_b = kernel.handle(ExecutiveRequest(text=f"{goal_id} give me results", session_id=session_b))
    assert r_explicit_b.result.get("reference", {}).get("target_id") == goal_id

    # Session B subsequent pronoun targets goal_id
    r_followup_b = kernel.handle(ExecutiveRequest(text="continue it", session_id=session_b))
    assert r_followup_b.goal_id == goal_id
