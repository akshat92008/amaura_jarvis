"""Phase 5 Tests: Workspace Security Independence from Model Services (Phase 7)."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from jarvis.amaura.cognition import ExecutiveKernel, ExecutiveRequest
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.direct_action import DirectActionRouter


def test_workspace_security_refusal_when_model_gateway_offline():
    """Security boundary check must execute and refuse outside-workspace writes even when model service is offline."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        outside_path = tmp_path.parent / "escape_outside_secret.txt"
        prompt = f"Save 'malicious payload' into {outside_path}"

        # Mock CognitiveModelGateway.generate to raise Exception (simulating total outage)
        with patch(
            "jarvis.amaura.model_gateway.CognitiveModelGateway.generate",
            side_effect=RuntimeError("Cognition Service Down"),
        ):
            with patch("jarvis.amaura.model_gateway.CognitiveModelGateway.available", return_value=False):
                res = DirectActionRouter.execute(prompt, workspace=str(tmp_path))
                assert res is not None
                assert res.success is False
                assert res.policy_decision == "refused"
                assert "Cannot write to path outside workspace" in res.output or "workspace" in res.output.lower()
                assert "temporarily unavailable" not in res.output.lower()


def test_workspace_security_refusal_through_executive_kernel():
    """ExecutiveKernel.handle must return policy refusal directly without calling model gateway when outside workspace."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        outside_path = tmp_path.parent / "escape_through_kernel.txt"
        prompt = f"Create {outside_path}. Its complete content must be: evil"

        control = AmauraControlPlane(tmp_path / "control")
        kernel = ExecutiveKernel(control)

        with patch(
            "jarvis.amaura.model_gateway.CognitiveModelGateway.generate", side_effect=RuntimeError("LLM Offline")
        ):
            with patch("jarvis.amaura.model_gateway.CognitiveModelGateway.available", return_value=False):
                req = ExecutiveRequest(text=prompt, session_id="test_security", workspace=str(tmp_path))
                resp = kernel.handle(req)
                assert resp is not None
                assert resp.state == "refused"
                assert "Cannot write to path outside workspace" in resp.message or "workspace" in resp.message.lower()
                assert "interactive cognition service is temporarily unavailable" not in resp.message.lower()
