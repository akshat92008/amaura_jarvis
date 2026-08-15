"""Phase 5 Tests: Exact Response Generalization & Concurrency Reliability (Phases 15, 16, 17, 18, 19)."""

import concurrent.futures
import random
import string
from unittest.mock import patch
import pytest

from jarvis.amaura.direct_action import DirectActionRouter, ExactResponseParser


def _random_token(length: int = 10) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits + "_-", k=length))


def test_exact_response_paraphrase_variations():
    """Test at least 50 distinct paraphrases of exact response requests."""
    templates = [
        "Please reply only with '{payload}' and nothing else.",
        "Respond with exactly: {payload}",
        "Your entire reply must be this value and nothing else: {payload}",
        "Reply with solely this token: {payload}",
        "Your response should be only: '{payload}'",
        "Say exactly: {payload}",
        "Just say '{payload}' and no other text.",
        "Output solely this value: {payload}",
        "Return this token and nothing else: {payload}",
        "Echo: {payload}",
        "Repeat: {payload}",
        "Print exactly '{payload}' without explanation.",
        "Please respond with only the string '{payload}' verbatim.",
        "Your entire response must contain only: {payload}",
        "Give me only this value and nothing else: {payload}",
        "Return exactly: {payload}",
        "Say only: {payload}",
        "Just return: {payload}",
        "Respond with just '{payload}'",
        "Reply with: {payload}",
        "Echo '{payload}' and nothing else.",
        "Repeat '{payload}' verbatim.",
        "Your complete response must be: {payload}",
        "Please return solely this token: {payload}",
        "Output exactly: {payload}",
        "Respond only with: {payload}",
        "Return the value: {payload}",
        "Print the token: {payload}",
        "Just output: {payload}",
        "Type only: {payload}",
        "Write back solely: {payload}",
        "Send only the token '{payload}'",
        "Please say exactly '{payload}' without commentary.",
        "Your whole reply should be '{payload}'",
        "Your reply must consist of: {payload}",
        "Only reply with: {payload}",
        "Solely return: {payload}",
        "Exactly output: {payload}",
        "Strictly return '{payload}' and nothing else.",
        "Verbatim return: {payload}",
        "Please echo the string: {payload}",
        "Respond with only the token: {payload}",
        "Reply with just the value: {payload}",
        "Return only the text: {payload}",
        "Say solely: {payload}",
        "Print only: {payload}",
        "Echo this value and nothing else: {payload}",
        "Return verbatim: {payload}",
        "Respond strictly with '{payload}'",
        "Your entire reply must be solely this token: {payload}",
        "Just say: {payload}",
        "Output with no other text: {payload}",
    ]

    assert len(templates) >= 50

    model_called_count = 0

    def mock_generate(*args, **kwargs):
        nonlocal model_called_count
        model_called_count += 1
        raise RuntimeError("Hosted Model Called Unexpectedly!")

    with patch("jarvis.amaura.model_gateway.CognitiveModelGateway.generate", side_effect=mock_generate):
        for idx, template in enumerate(templates):
            token = f"TOKEN_{idx}_{_random_token(8)}"
            prompt = template.format(payload=token)
            
            res = DirectActionRouter.execute(prompt)
            assert res is not None, f"Failed for template {idx}: '{prompt}'"
            assert res.success is True
            assert res.output == token, f"Output mismatch for template {idx}. Expected '{token}', got '{res.output}'"
            assert res.execution_type == "exact_response"

    assert model_called_count == 0, f"Model was called {model_called_count} times on deterministic exact responses!"


def test_concurrency_20_simultaneous_requests():
    """Test 20 concurrent simultaneous exact-response requests with 0 model calls, 0 crosstalk, 0 failures."""
    model_invocations = 0

    def mock_generate(*args, **kwargs):
        nonlocal model_invocations
        model_invocations += 1
        raise RuntimeError("Model called in deterministic test")

    def _worker(worker_id: int):
        expected_payload = f"CONCURRENT_20_PAYLOAD_{worker_id}_{_random_token(8)}"
        prompt = f"Please reply only with this token and nothing else: {expected_payload}"
        res = DirectActionRouter.execute(prompt)
        return {
            "worker_id": worker_id,
            "expected": expected_payload,
            "actual": res.output if res else None,
            "success": res.success if res else False,
        }

    with patch("jarvis.amaura.model_gateway.CognitiveModelGateway.generate", side_effect=mock_generate):
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(_worker, i) for i in range(20)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == 20
    for r in results:
        assert r["success"] is True, f"Worker {r['worker_id']} failed"
        assert r["actual"] == r["expected"], f"Crosstalk detected: worker {r['worker_id']} got {r['actual']} instead of {r['expected']}"
    assert model_invocations == 0


def test_concurrency_40_simultaneous_requests():
    """Test 40 concurrent simultaneous exact-response requests with 0 model calls, 0 crosstalk, 0 failures."""
    model_invocations = 0

    def mock_generate(*args, **kwargs):
        nonlocal model_invocations
        model_invocations += 1
        raise RuntimeError("Model called in deterministic test")

    def _worker(worker_id: int):
        expected_payload = f"BURST_40_PAYLOAD_{worker_id}_{_random_token(8)}"
        prompt = f"Your entire reply must be this value and nothing else: {expected_payload}"
        res = DirectActionRouter.execute(prompt)
        return {
            "worker_id": worker_id,
            "expected": expected_payload,
            "actual": res.output if res else None,
            "success": res.success if res else False,
        }

    with patch("jarvis.amaura.model_gateway.CognitiveModelGateway.generate", side_effect=mock_generate):
        with concurrent.futures.ThreadPoolExecutor(max_workers=40) as executor:
            futures = [executor.submit(_worker, i) for i in range(40)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == 40
    for r in results:
        assert r["success"] is True, f"Worker {r['worker_id']} failed"
        assert r["actual"] == r["expected"], f"Crosstalk detected: worker {r['worker_id']} got {r['actual']} instead of {r['expected']}"
    assert model_invocations == 0
