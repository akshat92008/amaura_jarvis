"""Phase 7 Test Suite 7: API Boundary Tests (POST /api/chat/stream & ExecutiveKernel)."""

import json
import os
import random
import tempfile
from pathlib import Path
from unittest.mock import patch

TEST_AUTH_TOKEN = "test_api_token_12345678901234567890"
TEST_OP_TOKEN = "test_operator_token_9876543210"
TEST_HMAC_SECRET = "test_audit_secret_32_bytes_long_1234567890"

os.environ["JARVIS_API_KEY"] = TEST_AUTH_TOKEN
os.environ["AMAURA_OPERATOR_KEY"] = TEST_OP_TOKEN
os.environ["AMAURA_AUDIT_HMAC_KEY"] = TEST_HMAC_SECRET
os.environ["JARVIS_REQUIRE_LOCAL_AUTH"] = "0"

import pytest
from starlette.testclient import TestClient
from jarvis.server import app
from jarvis.tools.amaura import reset_control_plane
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.cognition import ExecutiveKernel, ExecutiveRequest
from jarvis.amaura.direct_action import RequestPreprocessor, ActionType, ResponseMode


HEADERS = {
    "X-Jarvis-Key": TEST_AUTH_TOKEN,
    "X-Amaura-Operator-Key": TEST_OP_TOKEN,
}


@pytest.fixture(autouse=True)
def clean_amaura_env(tmp_path, monkeypatch):
    data_dir = tmp_path / "amaura_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AMAURA_DATA_DIR", str(data_dir))
    monkeypatch.setenv("AMAURA_AUDIT_HMAC_KEY", TEST_HMAC_SECRET)
    monkeypatch.setenv("JARVIS_API_KEY", TEST_AUTH_TOKEN)
    monkeypatch.setenv("AMAURA_OPERATOR_KEY", TEST_OP_TOKEN)
    monkeypatch.setenv("JARVIS_REQUIRE_LOCAL_AUTH", "0")
    reset_control_plane()
    yield
    reset_control_plane()


@pytest.fixture
def client():
    return TestClient(app)


def test_api_boundary_50_routing_collisions(client):
    """50 API boundary requests with misleading words in paths/quotes."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        for i in range(50):
            # Create files with misleading names
            f = ws / f"Desktop_screenshot_test_{i}.txt"
            f.write_text(f"content_{i}", encoding="utf-8")

            payload = {
                "message": f"read {f} and return exactly its contents",
                "session_id": f"session_collision_{i}",
                "workspace": str(ws),
            }
            res = client.post("/api/chat/stream", json=payload, headers=HEADERS)
            assert res.status_code == 200
            # Read NDJSON lines
            lines = [json.loads(line) for line in res.text.strip().split("\n") if line.strip()]
            complete = [l for l in lines if l.get("type") == "complete"]
            assert len(complete) > 0
            assert complete[0]["response"] == f"content_{i}"


def test_api_boundary_30_write_variations(client):
    """30 API boundary write variations."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        for i in range(30):
            target = ws / f"write_var_{i}.txt"
            content = f"Unique generated text payload: {i} - {random.randint(1000, 9999)}"
            prompt = f"Create {target}. Its complete content must be: {content}"

            payload = {
                "message": prompt,
                "session_id": f"session_write_{i}",
                "workspace": str(ws),
            }
            res = client.post("/api/chat/stream", json=payload, headers=HEADERS)
            assert res.status_code == 200
            assert target.exists()
            assert target.read_text(encoding="utf-8") == content


def test_api_boundary_20_screenshot_positives(client):
    """20 API boundary screenshot positive cases."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        for i in range(20):
            shot_file = ws / f"shot_{i}.png"
            prompt = f"take a screenshot and save to {shot_file}"

            # Mock native screenshot tool to create valid PNG
            def mock_exec(tool_name, args):
                if tool_name == "take_screenshot":
                    out_p = Path(args["output_path"])
                    # PNG header + dummy 1x1 image bytes
                    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
                    out_p.write_bytes(png_bytes)
                    return json.dumps({"ok": True, "data": {"output": f"Screenshot saved to {out_p}"}, "error": None})
                return json.dumps({"ok": False, "error": "unknown"})

            with patch("jarvis.amaura.direct_action.execute_tool", side_effect=mock_exec):
                payload = {
                    "message": prompt,
                    "session_id": f"session_shot_pos_{i}",
                    "workspace": str(ws),
                }
                res = client.post("/api/chat/stream", json=payload, headers=HEADERS)
                assert res.status_code == 200
                lines = [json.loads(l) for l in res.text.strip().split("\n") if l.strip()]
                complete = [l for l in lines if l.get("type") == "complete"][0]
                assert "Screenshot saved" in complete["response"]
                assert shot_file.exists()


def test_api_boundary_20_screenshot_negatives(client):
    """20 API boundary screenshot negative controls (must NOT execute screenshot)."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        for i in range(20):
            f = ws / f"note_{i}.txt"
            prompt = f'write "screenshot" to {f}'

            payload = {
                "message": prompt,
                "session_id": f"session_shot_neg_{i}",
                "workspace": str(ws),
            }
            res = client.post("/api/chat/stream", json=payload, headers=HEADERS)
            assert res.status_code == 200
            assert f.exists()
            assert f.read_text(encoding="utf-8") == "screenshot"


def test_api_boundary_30_exact_literals(client):
    """30 API boundary exact explicit-literal cases."""
    for i in range(30):
        expected = f"API_EXACT_TOKEN_{i}_{random.randint(1000, 9999)}"
        prompt = f'reply exactly "{expected}" and nothing else'

        payload = {
            "message": prompt,
            "session_id": f"session_exact_{i}",
        }
        res = client.post("/api/chat/stream", json=payload, headers=HEADERS)
        assert res.status_code == 200
        lines = [json.loads(l) for l in res.text.strip().split("\n") if l.strip()]
        complete = [l for l in lines if l.get("type") == "complete"][0]
        assert complete["response"] == expected
        assert complete["model_provider"] in ("system", "deterministic-echo", "legacy", "local")


def test_api_boundary_20_exact_raw_reads(client):
    """20 API boundary exact-raw file read cases."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        for i in range(20):
            f = ws / f"raw_sample_{i}.txt"
            raw_text = f"Line 1 for {i}\nLine 2 for {i}\nFinal line"
            f.write_text(raw_text, encoding="utf-8")

            prompt = f"give me raw contents of {f}"
            payload = {
                "message": prompt,
                "session_id": f"session_raw_read_{i}",
                "workspace": str(ws),
            }
            res = client.post("/api/chat/stream", json=payload, headers=HEADERS)
            assert res.status_code == 200
            lines = [json.loads(l) for l in res.text.strip().split("\n") if l.strip()]
            complete = [l for l in lines if l.get("type") == "complete"][0]
            assert complete["response"] == raw_text


def test_api_boundary_20_arithmetic_workflows(client):
    """20 API boundary arithmetic workflow cases."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        for i in range(20):
            n1 = random.randint(50, 100)
            n2 = random.randint(1, 40)
            diff = n1 - n2

            f1 = ws / f"num1_{i}.num"
            f2 = ws / f"num2_{i}.num"
            f_out = ws / f"diff_{i}.num"

            f1.write_text(str(n1), encoding="utf-8")
            f2.write_text(str(n2), encoding="utf-8")

            prompt = f"take the number in {f2} away from {f1} and save to {f_out}"
            payload = {
                "message": prompt,
                "session_id": f"session_math_{i}",
                "workspace": str(ws),
            }
            res = client.post("/api/chat/stream", json=payload, headers=HEADERS)
            assert res.status_code == 200
            assert f_out.exists()
            assert int(f_out.read_text(encoding="utf-8").strip()) == diff


def test_api_boundary_20_repository_diagnoses(client):
    """20 API boundary repository defect diagnoses."""
    for i in range(20):
        with tempfile.TemporaryDirectory(prefix="api_repo_") as td:
            repo_p = Path(td)
            src = repo_p / "boundary_mod.py"
            src.write_text("""def is_valid_score(score: int) -> bool:
    '''Return True if score is at least 50.'''
    return score > 50
""")
            test_file = repo_p / "test_boundary.py"
            test_file.write_text("""from boundary_mod import is_valid_score
def test_boundary():
    assert is_valid_score(50) is True
""")
            prompt = f"inspect repo at {repo_p}"
            payload = {
                "message": prompt,
                "session_id": f"session_repo_{i}",
                "workspace": str(repo_p),
            }
            res = client.post("/api/chat/stream", json=payload, headers=HEADERS)
            assert res.status_code == 200
            lines = [json.loads(l) for l in res.text.strip().split("\n") if l.strip()]
            complete = [l for l in lines if l.get("type") == "complete"][0]
            assert "is_valid_score" in complete["response"]
            assert "comparison_boundary" in str(complete["executive"].get("result", {})) or "defect" in complete["response"]
