"""
Comprehensive Unit Tests for Iron Man JARVIS Modules.

Covers:
- Situational Awareness Engine (jarvis/awareness.py)
- Dynamic Personality Engine (jarvis/personality.py)
- Post-Mission Reflection & Learning (jarvis/reflection.py)
- Relational Knowledge Graph (jarvis/knowledge_graph.py)
- Autonomous Heartbeat Engine (jarvis/heartbeat.py)
- Automated Morning Briefing (jarvis/morning_briefing.py)
- House Party Protocol (jarvis/fleet.py)
- Multi-tier Speaker (jarvis/voice/speaker.py)
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
import pytest

from jarvis.awareness import (
    ActiveWindowTracker,
    SituationalAwareness,
    TimeAwareness,
    UserIdleDetector,
    get_awareness,
)
from jarvis.fleet import house_party_protocol
from jarvis.heartbeat import (
    AlertUrgency,
    HeartbeatEngine,
    HeartbeatEvent,
    HeartbeatEventType,
    SystemMonitor,
    get_heartbeat,
)
from jarvis.knowledge_graph import (
    KnowledgeGraph,
    get_knowledge_graph,
)
from jarvis.morning_briefing import compose_morning_briefing
from jarvis.personality import (
    FrustrationDetector,
    PersonalityEngine,
    PersonalityMode,
    get_personality,
)
from jarvis.reflection import (
    Lesson,
    PostMissionReflector,
    TaskLog,
    get_reflector,
)
from jarvis.voice.speaker import Speaker, get_speaker


def test_situational_awareness():
    aw = get_awareness()
    ctx = aw.get_full_context()
    assert ctx is not None
    assert ctx.greeting in ("Good morning, sir", "Good afternoon, sir", "Good evening, sir", "Burning the midnight oil, sir")
    assert isinstance(ctx.idle_seconds, (int, float))

    addon = aw.get_prompt_addon()
    assert "[SITUATIONAL AWARENESS]" in addon
    assert "Time:" in addon


def test_personality_engine():
    p = get_personality()
    assert p is not None
    assert p.mode in PersonalityMode

    # Test mode determination
    mode_err = p.determine_mode("Traceback (most recent call last): IndexError: list index out of range")
    assert mode_err == PersonalityMode.COMBAT

    prompt = p.get_personality_prompt()
    assert isinstance(prompt, str) and len(prompt) > 0

    # Test frustration detection
    fd = FrustrationDetector()
    score_calm = fd.detect("Could you please show me the time?")
    assert score_calm == 0.0

    score_frustrated = fd.detect("WHY IS THIS STILL BROKEN UGH THIS DOES NOT WORK")
    assert score_frustrated > 0.5


def test_reflection_engine(tmp_path: Path):
    reflector = get_reflector()
    task_log = TaskLog(
        task_id="test-task-1",
        user_prompt="Calculate transpose of matrix",
        messages=[],
        tools_called=[{"name": "edit_file", "result": "ok"}],
        duration_seconds=5.2,
        final_outcome="success",
        user_corrections=[],
    )
    lesson = reflector.reflect(task_log)
    assert lesson is not None
    assert lesson.outcome == "success"

    stats = reflector.get_stats()
    assert "total_lessons" in stats
    assert stats["total_lessons"] >= 1

    prompt = reflector.get_pre_flight_prompt("transpose matrix calculation")
    # Should either return a string or None
    assert prompt is None or isinstance(prompt, str)


def test_knowledge_graph():
    kg = get_knowledge_graph()
    e1 = kg.add_entity(name="TestTonyStark", entity_type="person", properties={"status": "genius"})
    assert e1.name == "TestTonyStark"

    e2 = kg.add_entity(name="TestArcReactor", entity_type="technology", properties={"output": "3GJ/s"})
    assert e2.name == "TestArcReactor"

    rel = kg.add_relation(source_name="TestTonyStark", target_name="TestArcReactor", relation_type="invented")
    assert rel.relation_type == "invented"

    neighbors = kg.get_neighborhood("TestTonyStark")
    assert "entities" in neighbors
    assert any(ent.name == "TestArcReactor" for ent in neighbors["entities"])


def test_heartbeat_system_monitor():
    monitor = SystemMonitor()
    tel = monitor.poll()
    assert "cpu_count" in tel
    assert "platform" in tel
    alerts = monitor.check_alerts(tel)
    assert isinstance(alerts, list)


def test_morning_briefing():
    briefing = compose_morning_briefing(user_name="Mr. Stark")
    assert "Mr. Stark" in briefing
    assert "System & Hardware Telemetry" in briefing
    assert "Core Processor" in briefing


def test_house_party_protocol():
    report = house_party_protocol("Audit perimeter defense")
    assert "HOUSE PARTY PROTOCOL ENGAGED" in report
    assert "MARK_42" in report
    assert "HEARTBREAKER" in report
    assert "SILVER_CENTURION" in report
    assert "IGOR" in report
    assert "VERONICA" in report


def test_speaker_clean_for_speech():
    cleaned = Speaker._clean_for_speech("Hello **world**! Check `code_here`. Visit https://example.com")
    assert "world" in cleaned
    assert "**" not in cleaned
    assert "https://" not in cleaned
