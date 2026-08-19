from __future__ import annotations

import os

from jarvis.arch import configure_arch_runtime


def test_arch_enables_single_runtime_loops(monkeypatch):
    monkeypatch.delenv("ARCH_RUNTIME", raising=False)
    monkeypatch.setenv("AMAURA_JARVIS_PROACTIVE", "0")
    monkeypatch.setenv("AMAURA_JARVIS_MISSION_RUNNER", "0")
    monkeypatch.setenv("AMAURA_COMPANY_AUTOPILOT_RUNTIME", "0")

    configure_arch_runtime()

    assert os.environ["ARCH_RUNTIME"] == "1"
    assert os.environ["AMAURA_JARVIS_PROACTIVE"] == "1"
    assert os.environ["AMAURA_JARVIS_MISSION_RUNNER"] == "1"
    assert os.environ["AMAURA_COMPANY_AUTOPILOT_RUNTIME"] == "1"


def test_arch_caps_heavy_work_for_8gb_target(monkeypatch):
    monkeypatch.setenv("AMAURA_AUTOPILOT_MAX_WORK_UNITS", "8")
    monkeypatch.setenv("AMAURA_COMPANY_AUTOPILOT_WORK_UNITS", "6")
    monkeypatch.setenv("AMAURA_RAM_NORMAL_TARGET_MB", "4096")
    monkeypatch.setenv("AMAURA_RAM_BURST_LIMIT_MB", "4096")
    monkeypatch.setenv("AMAURA_RAM_ABSOLUTE_LIMIT_MB", "8192")
    monkeypatch.setenv("AMAURA_RAM_PRESSURE_LIMIT_MB", "4096")
    monkeypatch.setenv("AMAURA_ANTIGRAVITY_RESERVATION_MB", "4096")
    monkeypatch.setenv("AMAURA_ANTIGRAVITY_MAX_RSS_MB", "4096")
    monkeypatch.setenv("AMAURA_SWAP_GROWTH_ABORT_MB", "2048")

    configure_arch_runtime()

    assert os.environ["AMAURA_AUTOPILOT_MAX_WORK_UNITS"] == "1"
    assert os.environ["AMAURA_COMPANY_AUTOPILOT_WORK_UNITS"] == "1"
    assert os.environ["AMAURA_RAM_NORMAL_TARGET_MB"] == "768"
    assert os.environ["AMAURA_RAM_BURST_LIMIT_MB"] == "1536"
    assert os.environ["AMAURA_RAM_ABSOLUTE_LIMIT_MB"] == "2048"
    assert os.environ["AMAURA_RAM_PRESSURE_LIMIT_MB"] == "768"
    assert os.environ["AMAURA_ANTIGRAVITY_RESERVATION_MB"] == "768"
    assert os.environ["AMAURA_ANTIGRAVITY_MAX_RSS_MB"] == "1536"
    assert os.environ["AMAURA_SWAP_GROWTH_ABORT_MB"] == "192"
