from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

import jarvis.amaura.capability_runtime as runtime_module
import jarvis.amaura.resource_control as resource_module
from jarvis.amaura.capability_runtime import (
    CAPABILITY_OPERATION_CONTRACTS,
    CapabilityExecutionError,
    PlaywrightAdapter,
    RemotionAdapter,
)
from jarvis.amaura.models import GovernanceError
from jarvis.amaura.resource_control import (
    CrossProcessResourceLedger,
    HostMemorySnapshot,
    MemoryPolicy,
)
from jarvis.tools.security import tool_workspace


def _host(*, pressure: str = "green", available_mb: int = 5000, swap_used_mb: int = 0) -> HostMemorySnapshot:
    return HostMemorySnapshot(
        total_mb=8192,
        available_mb=available_mb,
        used_percent=35.0 if pressure == "green" else 85.0 if pressure == "yellow" else 95.0,
        swap_used_mb=swap_used_mb,
        swap_total_mb=4096,
        swap_percent=0.0 if pressure == "green" else 35.0 if pressure == "yellow" else 70.0,
        mac_free_percent=55.0 if pressure == "green" else 12.0 if pressure == "yellow" else 5.0,
        pressure=pressure,
        sampled_at=1.0,
    )


def test_v361_default_memory_policy_matches_small_mac_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "AMAURA_RAM_NORMAL_TARGET_MB",
        "AMAURA_RAM_BURST_LIMIT_MB",
        "AMAURA_RAM_ABSOLUTE_LIMIT_MB",
        "AMAURA_RAM_PRESSURE_LIMIT_MB",
    ):
        monkeypatch.delenv(key, raising=False)
    policy = MemoryPolicy.from_env()
    assert policy.normal_target_mb == 1500
    assert policy.burst_limit_mb == 2500
    assert policy.absolute_limit_mb == 3000
    assert policy.pressure_limit_mb == 1000



def test_native_resource_fallback_works_without_psutil(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resource_module, "psutil", None)
    monkeypatch.setattr(resource_module, "_NATIVE_MEMORY_CACHE", (0.0, None))
    monkeypatch.setattr(resource_module, "_PS_TABLE_CACHE", (0.0, {}))
    snapshot = resource_module.sample_host_memory(MemoryPolicy())
    assert snapshot.available_mb >= 0
    assert snapshot.pressure in {"green", "yellow", "red"}
    assert resource_module.process_tree_rss_mb(os.getpid()) >= 0

def test_cross_process_ledger_allows_only_one_heavy_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMAURA_RESOURCE_LEDGER_PATH", str(tmp_path / "ledger.json"))
    monkeypatch.setattr(resource_module, "sample_host_memory", lambda policy=None: _host())
    monkeypatch.setattr(resource_module, "process_tree_rss_mb", lambda pid: 120)
    ledger = CrossProcessResourceLedger(MemoryPolicy())
    first, reason, _ = ledger.try_reserve(capability="whisper", ram_mb=1600, heavy=True)
    assert first and reason == "reserved"
    second, reason, _ = ledger.try_reserve(capability="docling", ram_mb=1800, heavy=True)
    assert second is None
    assert "another heavy capability" in reason
    ledger.release(first)
    assert ledger.snapshot()["reserved_mb"] == 0


def test_pressure_mode_blocks_new_heavy_workers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMAURA_RESOURCE_LEDGER_PATH", str(tmp_path / "ledger.json"))
    monkeypatch.setattr(resource_module, "sample_host_memory", lambda policy=None: _host(pressure="yellow", available_mb=1200))
    monkeypatch.setattr(resource_module, "process_tree_rss_mb", lambda pid: 100)
    reservation, reason, state = CrossProcessResourceLedger(MemoryPolicy()).try_reserve(
        capability="browser_use", ram_mb=1400, heavy=True
    )
    assert reservation is None
    assert "yellow" in reason
    assert state["host"]["pressure"] == "yellow"


def test_isolated_worker_environment_scrubs_unrelated_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMAURA_GITHUB_TOKEN", "super-secret")
    monkeypatch.setenv("AMAURA_GMAIL_CLIENT_SECRET", "gmail-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "paid-secret")
    monkeypatch.setenv("AMAURA_WHISPER_MODEL", "tiny")
    env = runtime_module._capability_worker_env("faster_whisper", tmp_path)
    assert env["AMAURA_WHISPER_MODEL"] == "tiny"
    assert "AMAURA_GITHUB_TOKEN" not in env
    assert "AMAURA_GMAIL_CLIENT_SECRET" not in env
    assert "OPENAI_API_KEY" not in env
    assert env["AMAURA_CAPABILITY_WORKER"] == "1"


def test_subprocess_tree_is_killed_when_rss_ceiling_is_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_module, "process_tree_rss_mb", lambda pid: 9999)
    monkeypatch.setattr(runtime_module, "sample_host_memory", lambda policy=None: _host())
    with pytest.raises(CapabilityExecutionError, match="RSS ceiling"):
        runtime_module._run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=10, max_rss_mb=300)


def test_mcp_contract_exposes_server_id_not_process_launch_parameters() -> None:
    list_contract = CAPABILITY_OPERATION_CONTRACTS["mcp"]["list_tools"]
    call_contract = CAPABILITY_OPERATION_CONTRACTS["mcp"]["call_tool"]
    assert list_contract["required"] == ("server_id",)
    assert call_contract["required"] == ("server_id", "tool_name")
    flattened = set(list_contract["required"] + list_contract["optional"] + call_contract["required"] + call_contract["optional"])
    assert {"command", "args", "env_keys"}.isdisjoint(flattened)


class _Request:
    def __init__(self, url: str, resource_type: str = "document"):
        self.url = url
        self.resource_type = resource_type


class _Route:
    def __init__(self, url: str, resource_type: str = "document"):
        self.request = _Request(url, resource_type)
        self.action = ""

    def abort(self, _reason: str) -> None:
        self.action = "abort"

    def continue_(self) -> None:
        self.action = "continue"


def test_playwright_request_guard_blocks_private_and_websocket_destinations() -> None:
    private = _Route("http://127.0.0.1:9999/admin")
    PlaywrightAdapter._route_guard(private)
    assert private.action == "abort"

    websocket = _Route("https://93.184.216.34/socket", resource_type="websocket")
    PlaywrightAdapter._route_guard(websocket)
    assert websocket.action == "abort"


def test_remotion_render_rejects_template_tampering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMAURA_REMOTION_VERSION", "4.0.477")
    with tool_workspace(tmp_path):
        adapter = RemotionAdapter()
        adapter.execute("bootstrap_project", {"project_path": "template"})
        source = tmp_path / "template" / "src" / "Root.tsx"
        source.write_text(source.read_text() + "\n// tampered\n", encoding="utf-8")
        with pytest.raises(GovernanceError, match="source changed after approval"):
            adapter._verify_project(tmp_path / "template", require_lock=False)
