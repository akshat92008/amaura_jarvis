import json
from pathlib import Path

import pytest

from jarvis.amaura.capability_runtime import (
    ADAPTER_TYPES,
    CapabilityExecutionError,
    CapabilityRuntime,
    CapabilityScheduler,
    MCPAdapter,
)
from jarvis.amaura.models import GovernanceError
from jarvis.amaura.policy import PolicyEngine
from jarvis.amaura.registry import get_agent
from jarvis.amaura.resources import CapabilityRouter
from jarvis.tools.amaura import AMAURA_DISPATCH, AMAURA_TOOL_DEFINITIONS
from jarvis.tools.security import tool_workspace


def test_oss_capability_inventory_is_complete_and_lazy():
    runtime = CapabilityRuntime()
    keys = {row["key"] for row in runtime.inventory()}
    assert keys == {adapter.descriptor.key for adapter in ADAPTER_TYPES}
    assert {
        "playwright",
        "crawl4ai",
        "browser_use",
        "searxng",
        "docling",
        "pymupdf",
        "paddleocr",
        "llamaindex",
        "qdrant_fastembed",
        "faster_whisper",
        "kokoro",
        "ffmpeg",
        "remotion",
        "image_tools",
        "comfyui",
        "mcp",
        "langfuse",
        "antigravity",
    } <= keys


def test_resource_inventory_does_not_require_optional_modules():
    inventory = CapabilityRouter().inventory()
    assert len(inventory) >= 30
    assert any(item["key"] == "docling" for item in inventory)
    assert any(item["key"] == "qdrant_fastembed" for item in inventory)


def test_pipeline_plans_prefer_lightweight_then_fallbacks():
    runtime = CapabilityRuntime()
    document = runtime.plan("document_ingest")
    assert [step["capability"] for step in document["steps"]] == [
        "pymupdf",
        "docling",
        "paddleocr",
        "llamaindex",
        "qdrant_fastembed",
    ]
    web = runtime.plan("lead_research")
    assert [step["capability"] for step in web["steps"]] == ["searxng", "crawl4ai", "playwright"]
    video = runtime.plan("reel")
    assert video["steps"][-1]["capability"] == "ffmpeg"


def test_scheduler_serializes_heavy_workers():
    scheduler = CapabilityScheduler(budget_mb=5600)
    descriptor = next(adapter.descriptor for adapter in ADAPTER_TYPES if adapter.descriptor.key == "docling")
    with scheduler.reserve(descriptor):
        with pytest.raises(CapabilityExecutionError):
            with scheduler.reserve(descriptor, timeout=0.05):
                pass
    assert scheduler.status()["active_mb"] == 0
    assert scheduler.status()["active_heavy_jobs"] == 0


def test_antigravity_handoff_is_workspace_bound_and_human_in_loop(tmp_path, monkeypatch):
    monkeypatch.setenv("AMAURA_ANTIGRAVITY_ENABLED", "1")
    repo = tmp_path / "repo"
    repo.mkdir()
    with tool_workspace(tmp_path):
        result = CapabilityRuntime().execute(
            "antigravity",
            "prepare_handoff",
            {
                "repo_path": "repo",
                "objective": "Implement the approved landing page",
                "acceptance_criteria": ["tests pass", "no secrets"],
                "test_commands": ["pytest -q"],
                "output_path": "handoffs/task.json",
            },
        )
    output = Path(result["output"]["output_path"])
    assert output.is_file()
    packet = json.loads(output.read_text())
    assert packet["founder_review_required"] is True
    assert packet["execution_mode"] == "manual_founder_handoff"
    assert result["artifacts"][0]["sha256"]


def test_mcp_tool_calls_fail_closed_without_operator_enable(monkeypatch):
    adapter = MCPAdapter()
    monkeypatch.setattr(adapter, "available", lambda: (True, "test"))
    monkeypatch.setattr("jarvis.amaura.capability_runtime.shutil.which", lambda _: "/bin/echo")
    monkeypatch.delenv("AMAURA_MCP_TOOL_CALLS_ENABLED", raising=False)
    with pytest.raises(GovernanceError, match="MCP tool calls are disabled"):
        adapter.execute(
            "call_tool",
            {"command": "fake-mcp", "tool_name": "send", "arguments": {}, "founder_approved": True},
        )


def test_new_capability_tools_are_published_and_governed():
    names = {item["function"]["name"] for item in AMAURA_TOOL_DEFINITIONS}
    assert {"amaura_capability_plan", "amaura_capability_health", "amaura_execute_capability"} <= names
    assert {"amaura_capability_plan", "amaura_capability_health", "amaura_execute_capability"} <= set(AMAURA_DISPATCH)
    jarvis = get_agent("jarvis")
    assert "amaura_execute_capability" in jarvis.tools
    research = get_agent("content_research")
    assert "amaura_execute_capability" in research.tools
    voice = get_agent("voice_production")
    assert "amaura_execute_capability" in voice.tools


def test_capability_execution_requires_matching_employee_permission():
    task = {
        "id": "t1",
        "owner_id": "content_research",
        "state": "in_progress",
        "risk": "low",
        "action_type": "research",
        "budget_cents": 100,
        "metadata": {"workspace": "."},
    }
    decision = PolicyEngine.validate_tool_action(
        task,
        "content_research",
        "amaura_execute_capability",
        {"capability": "crawl4ai", "operation": "crawl", "params": {"url": "https://example.com"}},
    )
    assert decision.allowed, decision.reasons


def test_public_resource_inventory_includes_executor_health(monkeypatch):
    # The tool must remain useful even when optional projects are not installed.
    payload = json.loads(AMAURA_DISPATCH["amaura_resource_inventory"]())
    assert "resources" in payload
    assert "executors" in payload
    assert "mac_8gb_profile" in payload
    assert payload["mac_8gb_profile"]["recommended_concurrent_agent_runs"] == 2


def test_capability_policy_is_operation_specific():
    research_task = {
        "id": "t-research",
        "owner_id": "content_research",
        "state": "in_progress",
        "risk": "low",
        "action_type": "research",
        "budget_cents": 100,
        "metadata": {"workspace": "."},
    }
    allowed = PolicyEngine.validate_tool_action(
        research_task,
        "content_research",
        "amaura_execute_capability",
        {"capability": "crawl4ai", "operation": "crawl", "params": {"url": "https://example.com"}},
    )
    assert allowed.allowed, allowed.reasons

    denied = PolicyEngine.validate_tool_action(
        research_task,
        "content_research",
        "amaura_execute_capability",
        {"capability": "remotion", "operation": "render", "params": {}},
    )
    assert not denied.allowed
    assert any("requires one of" in reason for reason in denied.reasons)


def test_arbitrary_mcp_side_effects_are_not_employee_executable():
    task = {
        "id": "t-mcp",
        "owner_id": "jarvis",
        "state": "in_progress",
        "risk": "low",
        "action_type": "internal",
        "budget_cents": 100,
        "metadata": {"workspace": "."},
    }
    decision = PolicyEngine.validate_tool_action(
        task,
        "jarvis",
        "amaura_execute_capability",
        {"capability": "mcp", "operation": "call_tool", "params": {"tool_name": "anything"}},
    )
    assert not decision.allowed
    assert any("not approved for AI employee execution" in reason for reason in decision.reasons)


def test_antigravity_handoff_is_allowed_for_jarvis_plan_permission():
    task = {
        "id": "t-engineering",
        "owner_id": "jarvis",
        "state": "in_progress",
        "risk": "low",
        "action_type": "internal",
        "budget_cents": 100,
        "metadata": {"workspace": "."},
    }
    decision = PolicyEngine.validate_tool_action(
        task,
        "jarvis",
        "amaura_execute_capability",
        {"capability": "antigravity", "operation": "prepare_handoff", "params": {}},
    )
    assert decision.allowed, decision.reasons


def test_heavy_python_capability_can_execute_in_disposable_worker(tmp_path, monkeypatch):
    import jarvis.amaura.capability_runtime as runtime_module

    monkeypatch.setenv("AMAURA_ANTIGRAVITY_ENABLED", "1")
    monkeypatch.setattr(runtime_module, "ISOLATED_PYTHON_CAPABILITIES", frozenset({"antigravity"}))
    repo = tmp_path / "repo"
    repo.mkdir()
    with tool_workspace(tmp_path):
        result = runtime_module.CapabilityRuntime().execute(
            "antigravity",
            "prepare_handoff",
            {
                "repo_path": "repo",
                "objective": "Verify isolated worker lifecycle",
                "output_path": "handoff.json",
                "timeout": 30,
            },
        )
    assert result["ok"] is True
    assert (tmp_path / "handoff.json").is_file()
    assert not list(tmp_path.glob(".amaura-capability-request-*.json"))
    assert not list(tmp_path.glob(".amaura-capability-response-*.json"))


def test_yt_dlp_download_is_disabled_by_default(monkeypatch):
    from jarvis.amaura.capability_runtime import YtDlpAdapter

    adapter = YtDlpAdapter()
    monkeypatch.setattr(adapter, "available", lambda: (True, "test"))
    monkeypatch.setattr(adapter, "_base_argv", lambda: ["yt-dlp"])
    monkeypatch.delenv("AMAURA_MEDIA_DOWNLOADS_ENABLED", raising=False)
    with pytest.raises(GovernanceError, match="Media downloads are disabled"):
        adapter.execute(
            "download",
            {"url": "https://example.com/video", "rights_confirmed": True},
        )


def test_comfyui_local_endpoint_is_disabled_by_default_on_small_mac_profile(monkeypatch):
    from jarvis.amaura.capability_runtime import ComfyUIAdapter

    monkeypatch.setenv("COMFYUI_URL", "http://127.0.0.1:8188")
    monkeypatch.delenv("AMAURA_ALLOW_LOCAL_COMFYUI", raising=False)
    available, reason = ComfyUIAdapter().available()
    assert available is False
    assert "disabled by default" in reason


def test_operation_contracts_cover_remotion_bootstrap_and_audio_mux():
    from jarvis.amaura.capability_runtime import CAPABILITY_OPERATION_CONTRACTS

    assert "bootstrap_project" in CAPABILITY_OPERATION_CONTRACTS["remotion"]
    assert CAPABILITY_OPERATION_CONTRACTS["remotion"]["render"]["required"] == (
        "project_path",
        "composition",
        "output_path",
    )
    assert CAPABILITY_OPERATION_CONTRACTS["ffmpeg"]["mux_audio"]["required"] == (
        "source_path",
        "audio_path",
        "output_path",
    )


def test_remotion_bootstrap_creates_pinned_amaura_template_without_node(tmp_path, monkeypatch):
    from jarvis.amaura.capability_runtime import RemotionAdapter

    monkeypatch.setenv("AMAURA_REMOTION_VERSION", "4.0.477")
    with tool_workspace(tmp_path):
        result = RemotionAdapter().execute("bootstrap_project", {"project_path": "video-template"})
    project = tmp_path / "video-template"
    package = json.loads((project / "package.json").read_text())
    assert package["dependencies"]["remotion"] == "4.0.477"
    assert package["dependencies"]["@remotion/cli"] == "4.0.477"
    assert (project / "src" / "AmauraVideo.tsx").is_file()
    assert result.output["compositions"] == ["AmauraReel30", "AmauraShort60", "AmauraLandscape60"]


def test_browser_use_is_opt_in_even_when_package_is_present(monkeypatch):
    from jarvis.amaura.capability_runtime import BrowserUseAdapter

    monkeypatch.delenv("AMAURA_BROWSER_USE_AGENT_ENABLED", raising=False)
    monkeypatch.setattr("jarvis.amaura.capability_runtime._module_available", lambda _: True)
    available, reason = BrowserUseAdapter().available()
    assert available is False
    assert "disabled by default" in reason


def test_comfyui_execute_enforces_local_disable_not_only_health(monkeypatch):
    from jarvis.amaura.capability_runtime import CapabilityUnavailable, ComfyUIAdapter

    monkeypatch.setenv("COMFYUI_URL", "http://127.0.0.1:8188")
    monkeypatch.delenv("AMAURA_ALLOW_LOCAL_COMFYUI", raising=False)
    with pytest.raises(CapabilityUnavailable, match="disabled by default"):
        ComfyUIAdapter().execute("history", {"prompt_id": "abc"})


def test_media_operations_have_operation_specific_permissions():
    task = {
        "id": "t-media",
        "owner_id": "video_production",
        "state": "in_progress",
        "risk": "low",
        "action_type": "internal",
        "budget_cents": 100,
        "metadata": {"workspace": "."},
    }
    bootstrap = PolicyEngine.validate_tool_action(
        task,
        "video_production",
        "amaura_execute_capability",
        {"capability": "remotion", "operation": "bootstrap_project", "params": {}},
    )
    mux = PolicyEngine.validate_tool_action(
        task,
        "video_production",
        "amaura_execute_capability",
        {"capability": "ffmpeg", "operation": "mux_audio", "params": {}},
    )
    assert bootstrap.allowed, bootstrap.reasons
    assert mux.allowed, mux.reasons
