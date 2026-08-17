from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from jarvis.amaura.autopilot import AutonomousCompanyRuntime
from jarvis.amaura.evidence import create_review_attestation, verify_review_attestation
from jarvis.amaura.tool_governance import legacy_tool_allowed
from jarvis.tools.communication import send_imessage_local, tool_add_calendar_event, tool_add_reminder

KEY = "review-attestation-key-longer-than-thirty-two-bytes"


def test_read_only_mode_cannot_mutate_crm_or_communications():
    with patch.dict(os.environ, {"JARVIS_LEGACY_TOOL_MODE": "read_only"}, clear=False):
        assert legacy_tool_allowed("amaura_company_status")
        assert not legacy_tool_allowed("amaura_update_crm")
        assert not legacy_tool_allowed("send_imessage")
        assert not legacy_tool_allowed("write_file")


def test_full_legacy_mode_requires_explicit_break_glass():
    with patch.dict(
        os.environ, {"JARVIS_LEGACY_TOOL_MODE": "full", "AMAURA_ENABLE_BREAK_GLASS_LEGACY_TOOLS": "0"}, clear=False
    ):
        assert not legacy_tool_allowed("amaura_update_crm")
    with patch.dict(
        os.environ, {"JARVIS_LEGACY_TOOL_MODE": "full", "AMAURA_ENABLE_BREAK_GLASS_LEGACY_TOOLS": "1"}, clear=False
    ):
        assert legacy_tool_allowed("amaura_update_crm")


def test_review_attestation_binds_actual_provider_and_requested_model():
    attestation = create_review_attestation(
        task_id="task-1",
        reviewer_id="qa",
        reviewer_model="actual-reviewer",
        reviewer_provider="nvidia",
        requested_reviewer_model="requested-reviewer",
        decision={"approve": True},
        deterministic_review={"approve": True, "submission_sha256": "a" * 64},
        key=KEY,
    )
    assert verify_review_attestation(attestation, key=KEY)
    attestation["reviewer_provider"] = "groq"
    assert not verify_review_attestation(attestation, key=KEY)


class _Store:
    def __init__(self):
        self.controls = {}
        self.events = []
        self.audits = []

    def set_control(self, key, value, actor):
        self.controls[key] = value

    def publish_event(self, event_type, subject, details):
        self.events.append((event_type, subject, details))

    def audit(self, *args):
        self.audits.append(args)


def test_autopilot_poison_cycle_opens_circuit_without_killing_runtime():
    """Persistent transient poison opens a visible circuit but keeps the daemon alive.

    v7 deliberately changes the old v5.5 contract that permanently disabled the
    company after the threshold. Security/integrity failures have a separate
    fail-closed path; ordinary runtime/provider poison remains observable and
    bounded by backoff while the service stays available for later recovery.
    """
    runtime = object.__new__(AutonomousCompanyRuntime)
    store = _Store()
    runtime.control = SimpleNamespace(store=store)
    runtime.supervisor = SimpleNamespace(worker_id="test-autopilot")
    runtime.tick = Mock(side_effect=RuntimeError("poison event"))
    sleeps = []
    with patch.dict(
        os.environ,
        {
            "AMAURA_AUTOPILOT_CRASH_THRESHOLD": "3",
            "AMAURA_AUTOPILOT_FAILURE_BACKOFF_BASE_SECONDS": "1",
            "AMAURA_AUTOPILOT_FAILURE_BACKOFF_MAX_SECONDS": "8",
        },
        clear=False,
    ), patch("jarvis.amaura.autopilot.random.uniform", return_value=0.0):
        runtime.run_forever(max_cycles=10, sleep_fn=sleeps.append)
    assert runtime.tick.call_count == 10
    assert sleeps == [1.0, 2.0, 4.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0]
    assert "autopilot_enabled" not in store.controls
    assert store.controls["autopilot.crash_circuit"] == "open"
    assert any(event[0] == "company.autopilot.circuit_opened" for event in store.events)


def test_imessage_user_data_is_passed_as_arguments_not_script_source():
    dangerous_recipient = 'x" & do shell script "touch /tmp/pwn" & "'
    dangerous_message = 'hello"\nend tell\ndo shell script "touch /tmp/pwn2"'
    completed = SimpleNamespace(returncode=0, stdout="", stderr="")
    with patch("jarvis.tools.communication.subprocess.run", return_value=completed) as run:
        result = send_imessage_local(dangerous_recipient, dangerous_message)
    assert result.startswith("✅")
    osascript_call = [call.args[0] for call in run.call_args_list if call.args[0][0] == "osascript"][0]
    assert dangerous_recipient not in osascript_call[2]
    assert dangerous_message not in osascript_call[2]
    assert osascript_call[-2:] == [dangerous_recipient, dangerous_message]


def test_reminder_preserves_notes_via_argument_binding():
    completed = SimpleNamespace(returncode=0, stdout="", stderr="")
    with patch("jarvis.tools.communication.subprocess.run", return_value=completed) as run:
        result = tool_add_reminder("Revenue review", "Include CRM pipeline")
    assert result.startswith("✅")
    osascript_call = [call.args[0] for call in run.call_args_list if call.args[0][0] == "osascript"][0]
    assert osascript_call[-2:] == ["Revenue review", "Include CRM pipeline"]


def test_calendar_contract_uses_requested_time_duration_and_notes():
    completed = SimpleNamespace(returncode=0, stdout="", stderr="")
    with patch("jarvis.tools.communication.subprocess.run", return_value=completed) as run:
        result = tool_add_calendar_event("Launch review", "2030-02-03 14:30", 1.5, "Go/no-go")
    assert result.startswith("✅")
    osascript_call = [call.args[0] for call in run.call_args_list if call.args[0][0] == "osascript"][0]
    assert osascript_call[-8:] == ["Launch review", "Go/no-go", "2030", "2", "3", "14", "30", "5400"]
