import sys
sys.path.append(".")
import asyncio
from jarvis.amaura.cognition import ExecutiveKernel, ExecutiveRequest

class MockControl:
    pass

def test_direct():
    kernel = ExecutiveKernel(MockControl(), conversation_handler=lambda t, c: "mock_conv")
    response = kernel.handle(ExecutiveRequest(text="open Safari", session_id="test1", workspace="", autonomy="execute", coding_backend="antigravity"))
    print(f"Intent: {response.intent}")
    print(f"Message: {response.message}")
    print(f"State: {response.state}")

test_direct()
