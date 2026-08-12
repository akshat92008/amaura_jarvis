import pytest
import sys
from jarvis.amaura.cognition import IntentEngine
from jarvis.amaura.capability_runtime import MacOSAppAdapter, CapabilityRuntime, GovernanceError, CapabilityExecutionError

def test_intent_engine_boundary():
    engine = IntentEngine()
    
    # Governed missions (desktop actions)
    assert engine.classify("open Safari") == "mission"
    assert engine.classify("launch Finder") == "mission"
    assert engine.classify("activate Safari") == "mission"
    assert engine.classify("quit Spotify") == "mission"
    assert engine.classify("close Terminal") == "mission"
    
    # Action verbs with PLEASE
    assert engine.classify("please open Safari") == "mission"
    assert engine.classify("please quit Notes") == "mission"
    
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
