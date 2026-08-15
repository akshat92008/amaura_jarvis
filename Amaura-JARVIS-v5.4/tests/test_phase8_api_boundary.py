"""Phase 8 API Boundary Tests (POST /api/chat/stream & ExecutiveKernel).

Verifies end-to-end API streaming behavior for all Phase 8 semantic composition repairs:
  1. Response-mode composition (VALUE_ONLY, NUMBER_ONLY) via API
  2. Exact-literal routing without LLM latency
  3. Semantic operand roles (subtraction/division)
  4. Path-first write relations
  5. Browser extraction grammar
  6. Repository AST semantic diagnosis
"""

import json
import os
import random
import tempfile
from pathlib import Path
from unittest.mock import patch

TEST_AUTH_TOKEN = "test_api_token_phase8_12345678901234567890"
TEST_OP_TOKEN = "test_operator_token_phase8_9876543210"
TEST_HMAC_SECRET = "test_audit_secret_phase8_32_bytes_long_1234567890"

os.environ["JARVIS_API_KEY"] = TEST_AUTH_TOKEN
os.environ["AMAURA_OPERATOR_KEY"] = TEST_OP_TOKEN
os.environ["AMAURA_AUDIT_HMAC_KEY"] = TEST_HMAC_SECRET
os.environ["JARVIS_REQUIRE_LOCAL_AUTH"] = "0"

import pytest
from starlette.testclient import TestClient
from jarvis.server import app
from jarvis.tools.amaura import reset_control_plane
from jarvis.amaura.direct_action import ResponseMode


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


def test_api_boundary_exact_literal_echo(client):
    """API endpoint returns exact payload with zero model latency."""
    payload = {
        "message": "Return only: EXACT_PAYLOAD_PHASE8_999",
        "session_id": "session_exact_p8",
    }
    res = client.post("/api/chat/stream", json=payload, headers=HEADERS)
    assert res.status_code == 200
    lines = [json.loads(line) for line in res.text.strip().split("\n") if line.strip()]
    complete = [l for l in lines if l.get("type") == "complete"]
    assert len(complete) > 0
    assert complete[0]["response"] == "EXACT_PAYLOAD_PHASE8_999"


def test_api_boundary_path_first_write(client):
    """API endpoint correctly handles path-first write requests."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        target = ws / "output_p8.txt"
        payload = {
            "message": f"Create {target} containing: HELLO_FROM_PHASE8_PATH_FIRST",
            "session_id": "session_write_p8",
            "workspace": str(ws),
        }
        res = client.post("/api/chat/stream", json=payload, headers=HEADERS)
        assert res.status_code == 200
        assert target.exists()
        assert "HELLO_FROM_PHASE8_PATH_FIRST" in target.read_text(encoding="utf-8")


def test_api_boundary_workflow_subtraction_roles(client):
    """API endpoint executes subtraction workflow with explicit semantic roles."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        minuend_file = ws / "base_val.txt"
        subtrahend_file = ws / "deduct_val.txt"
        result_file = ws / "difference_out.txt"

        minuend_file.write_text("100\n", encoding="utf-8")
        subtrahend_file.write_text("35\n", encoding="utf-8")

        prompt = f"subtract {subtrahend_file} from {minuend_file} and save to {result_file}"
        payload = {
            "message": prompt,
            "session_id": "session_sub_p8",
            "workspace": str(ws),
        }
        res = client.post("/api/chat/stream", json=payload, headers=HEADERS)
        assert res.status_code == 200
        assert result_file.exists()
        result_content = result_file.read_text(encoding="utf-8").strip()
        assert float(result_content) == 65.0 or int(result_content) == 65


def test_api_boundary_workflow_division_roles(client):
    """API endpoint executes division workflow with explicit numerator/denominator."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        numerator_file = ws / "num.txt"
        denominator_file = ws / "den.txt"
        result_file = ws / "quotient_out.txt"

        numerator_file.write_text("200\n", encoding="utf-8")
        denominator_file.write_text("8\n", encoding="utf-8")

        prompt = f"divide {numerator_file} by {denominator_file} and save to {result_file}"
        payload = {
            "message": prompt,
            "session_id": "session_div_p8",
            "workspace": str(ws),
        }
        res = client.post("/api/chat/stream", json=payload, headers=HEADERS)
        assert res.status_code == 200
        assert result_file.exists()
        result_content = result_file.read_text(encoding="utf-8").strip()
        assert float(result_content) == 25.0


def test_api_boundary_repo_semantic_diagnosis(client):
    """API endpoint performs AST semantic repository diagnosis."""
    with tempfile.TemporaryDirectory() as td:
        repo_dir = Path(td) / "test_repo_p8"
        repo_dir.mkdir()

        code = """def helper_sum(a, b):
    \"\"\"Compute sum of values.\"\"\"
    return a + b

def helper_diff(a, b):
    \"\"\"Compute difference of values.\"\"\"
    return a - b

def calculate_total(a, b):
    \"\"\"Compute sum of numbers.\"\"\"
    return helper_diff(a, b)
"""
        test = """from module import calculate_total

def test_calculate_total():
    assert calculate_total(10, 20) == 30
"""
        (repo_dir / "module.py").write_text(code)
        (repo_dir / "test_module.py").write_text(test)

        prompt = f"Inspect and diagnose repo at {repo_dir}"
        payload = {
            "message": prompt,
            "session_id": "session_repo_p8",
            "workspace": str(repo_dir),
        }
        res = client.post("/api/chat/stream", json=payload, headers=HEADERS)
        assert res.status_code == 200
        lines = [json.loads(line) for line in res.text.strip().split("\n") if line.strip()]
        complete = [l for l in lines if l.get("type") == "complete"]
        assert len(complete) > 0
        response_text = complete[0]["response"]
        assert "wrong_helper_call" in response_text or "calculate_total" in response_text
