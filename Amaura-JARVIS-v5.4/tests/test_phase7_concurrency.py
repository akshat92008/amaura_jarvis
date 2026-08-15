"""Phase 7 Test Suite 8: Request Isolation and Concurrency (20, 40, 60, 80 Workers & Mixed-Action)."""

import concurrent.futures
import json
import random
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
import pytest

from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.cognition import ExecutiveKernel, ExecutiveRequest
from jarvis.amaura.direct_action import DirectActionRouter, ExactResponseParser


def _run_exact_literal_concurrency(worker_count: int):
    """Run concurrent exact-literal requests and assert 100% isolation and 0 crosstalk."""
    with tempfile.TemporaryDirectory() as td:
        control = AmauraControlPlane(Path(td) / "control")
        kernel = ExecutiveKernel(control)

        requests = [
            (f"SESSION_{worker_count}_{i}", f"PAYLOAD_WORKER_{worker_count}_INDEX_{i}_{random.randint(10000, 99999)}")
            for i in range(worker_count)
        ]

        def _execute_single(item):
            session_id, expected_payload = item
            prompt = f'reply with the quoted text "{expected_payload}" exactly'
            req = ExecutiveRequest(text=prompt, session_id=session_id)
            resp = kernel.handle(req)
            return session_id, expected_payload, resp

        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as pool:
            results = list(pool.map(_execute_single, requests))

        for session_id, expected_payload, resp in results:
            assert resp is not None
            assert resp.message == expected_payload, f"Crosstalk detected! Expected {expected_payload}, got {resp.message}"
            assert resp.session_id == session_id
            assert resp.result.get("tool_name") in ("echo", "deterministic_echo")


def test_concurrency_20_exact_literal():
    _run_exact_literal_concurrency(20)


def test_concurrency_40_exact_literal():
    _run_exact_literal_concurrency(40)


def test_concurrency_60_exact_literal():
    _run_exact_literal_concurrency(60)


def test_concurrency_80_exact_literal():
    _run_exact_literal_concurrency(80)


def test_mixed_action_concurrency_50_workers():
    """Simultaneously execute randomized file reads, directory listings, exact responses, memory queries."""
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        control = AmauraControlPlane(ws / "control")
        kernel = ExecutiveKernel(control)

        # Pre-create test files and directories
        test_files = {}
        for i in range(10):
            f = ws / f"mixed_file_{i}.txt"
            content = f"Mixed content line {i} - salt {random.randint(1000, 9999)}"
            f.write_text(content, encoding="utf-8")
            test_files[i] = (f, content)

        subdir = ws / "subfolder"
        subdir.mkdir()
        (subdir / "child.txt").write_text("child content")

        tasks = []
        for i in range(50):
            cat = i % 4
            session_id = f"mixed_session_{i}"

            if cat == 0:
                # Exact literal
                expected = f"MIXED_ECHO_{i}"
                prompt = f"echo: {expected}"
                tasks.append((cat, session_id, prompt, expected))
            elif cat == 1:
                # File read
                idx = i % 10
                f_path, content = test_files[idx]
                prompt = f"read {f_path} and return exactly its contents"
                tasks.append((cat, session_id, prompt, content))
            elif cat == 2:
                # Directory list
                prompt = f"list directory {subdir}"
                tasks.append((cat, session_id, prompt, "child.txt"))
            elif cat == 3:
                # Exact literal variation
                expected = f"TOKEN_EXACT_{i}_{random.randint(100, 999)}"
                prompt = f'return only "{expected}"'
                tasks.append((cat, session_id, prompt, expected))

        def _execute_mixed(task):
            cat, session_id, prompt, expected = task
            req = ExecutiveRequest(text=prompt, session_id=session_id, workspace=str(ws))
            resp = kernel.handle(req)
            return cat, session_id, resp, expected

        with concurrent.futures.ThreadPoolExecutor(max_workers=50) as pool:
            results = list(pool.map(_execute_mixed, tasks))

        for cat, session_id, resp, expected in results:
            assert resp is not None
            assert resp.session_id == session_id
            if cat in (0, 3):
                assert resp.message == expected
            elif cat == 1:
                assert resp.message == expected
            elif cat == 2:
                assert expected in resp.message
