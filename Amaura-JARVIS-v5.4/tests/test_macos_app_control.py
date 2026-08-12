import pytest
import sys
from jarvis.amaura.cognition import IntentEngine, ExecutiveKernel, ExecutiveRequest
from jarvis.amaura.capability_runtime import MacOSAppAdapter, CapabilityRuntime, GovernanceError, CapabilityExecutionError

def test_intent_engine_boundary():
    engine = IntentEngine()
    
    # Governed missions (desktop actions)
    assert engine.classify("open Safari") == "macos_app"
    assert engine.classify("please launch Terminal") == "macos_app"
    assert engine.classify("quit Finder") == "macos_app"
    assert engine.classify("close Chrome") == "macos_app"
    assert engine.classify("focus Xcode") == "macos_app"
    
    # Action verbs with PLEASE
    assert engine.classify("please open Safari") == "macos_app"
    assert engine.classify("please quit Notes") == "macos_app"
    
    # Safe conversational bounds
    assert engine.classify("tell me about Safari") == "conversation"
    assert engine.classify("what is Finder") == "conversation"
    assert engine.classify("how do I open Spotify") == "conversation"

def test_macos_app_adapter_validation(monkeypatch):
    adapter = MacOSAppAdapter()
    
    # Mock subprocess.run to prevent actual app launch during testing
    import subprocess
    def mock_run(*args, **kwargs):
        class MockResult:
            returncode = 0
            stderr = ""
        return MockResult()
    monkeypatch.setattr(subprocess, "run", mock_run)
    
    # Fake being on darwin
    monkeypatch.setattr(sys, "platform", "darwin")
    
    # Valid allowlisted app
    result = adapter.execute("open", {"name": "safari"})
    assert result.ok is True
    assert result.output["app"] == "safari"
    
    # Valid allowlisted app with varying casing
    result = adapter.execute("open", {"name": " System Settings "})
    assert result.ok is True
    assert result.output["app"] == "System Settings"
    
    # Unknown/nonexistent app (not in allowlist)
    with pytest.raises(GovernanceError, match="not in the strict allowlist"):
        adapter.execute("open", {"name": "malware_app"})
        
    # Malicious string
    with pytest.raises(GovernanceError, match="not in the strict allowlist"):
        adapter.execute("open", {"name": "Safari; rm -rf /"})
        
    # Required missing
    with pytest.raises(GovernanceError, match="Application name is required"):
        adapter.execute("open", {})

def test_capability_runtime_registration():
    runtime = CapabilityRuntime()
    assert "macos_app" in runtime.adapters
    health = runtime.health("macos_app")
    assert health["capability"] == "macos_app"
    assert "open" in health["contracts"]

def test_cognition_dict_response_regression(monkeypatch):
    """Regression test: CapabilityRuntime.execute() returns a dict, not a CapabilityResult object.
    cognition.py must use res.get('ok') instead of res.ok.
    """
    class MockMemory:
        def record_episode(self, *args, **kwargs):
            pass
        def context(self, *args, **kwargs):
            return "context", []

    class MockControlPlane:
        pass
        
    engine = ExecutiveKernel(MockControlPlane())
    engine.memory = MockMemory()
    engine._consolidate_async = lambda *args, **kwargs: None

    import jarvis.amaura.capability_runtime
    
    def mock_execute(self, capability, operation, params=None):
        assert capability == "macos_app"
        return {"ok": True, "output": {"app": "safari"}, "error": "", "duration": 0.1, "artifacts": []}
    
    monkeypatch.setattr(jarvis.amaura.capability_runtime.CapabilityRuntime, "execute", mock_execute)
    
    request = ExecutiveRequest(text="open safari", session_id="test-123", force_intent="macos_app")
    response = engine.handle(request)
    assert response.intent == "macos_app"
    assert "✅ Successfully opened" in response.message

def test_cognition_plan_only_isolation(monkeypatch):
    """Ensure that autonomy='plan_only' prevents execution of macos_app actions."""
    class MockMemory:
        def record_episode(self, *args, **kwargs):
            pass
        def context(self, *args, **kwargs):
            return "context", []

    class MockControlPlane:
        pass
        
    engine = ExecutiveKernel(MockControlPlane())
    engine.memory = MockMemory()
    engine._consolidate_async = lambda *args, **kwargs: None

    import jarvis.amaura.capability_runtime
    
    executed = False
    def mock_execute(self, capability, operation, params=None):
        nonlocal executed
        executed = True
        return {"ok": True, "output": {"app": "safari"}}
    
    monkeypatch.setattr(jarvis.amaura.capability_runtime.CapabilityRuntime, "execute", mock_execute)
    
    request = ExecutiveRequest(text="open safari", session_id="test-123", force_intent="macos_app", autonomy="plan_only")
    response = engine.handle(request)
    assert response.intent == "macos_app"
    assert response.state == "held"
    assert executed is False


