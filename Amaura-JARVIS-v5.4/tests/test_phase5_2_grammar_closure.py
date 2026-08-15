"""Phase 5.2 Test Suite: Natural-Language Grammar Closure & Deterministic Routing Repair.

Validates:
1. Write Content-Span Grammar (>= 200 generative permutations)
2. Directory List Intent Generalization (>= 100 generative permutations + dotted/nested dirs + negative controls)
3. Exact Response Formal Grammar (>= 500 generative permutations)
4. Exact Response Concurrency Bursts (20, 40, 60 simultaneous requests with 0 model calls, 0 crosstalk)
5. API Boundary Tests (POST /api/chat and POST /api/chat/stream)
6. Failure Injection Suite (>= 15 distinct failure modes)
"""

import asyncio
import concurrent.futures
import json
import os
import random
import string
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from jarvis.server import app
from jarvis.amaura.cognition import ExecutiveKernel, ExecutiveRequest
from jarvis.amaura.direct_action import (
    DirectActionResult,
    DirectActionRouter,
    ExactResponseInstruction,
    ExactResponseParser,
    FilesystemActionClassifier,
    FilesystemActionType,
    FilesystemSemanticAction,
    PathExtractor,
    WriteAction,
    WriteActionParser,
)
from jarvis.tools.security import tool_workspace


def _random_token(length: int = 10) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits + "_-", k=length))


# =============================================================================
# 1. WRITE CONTENT-SPAN PARSER PROPERTY TESTS (>= 200 permutations)
# =============================================================================

def test_write_action_parser_property_generation():
    """Generative property test asserting parsed payload == expected payload for >= 200 combinations."""
    verbs = ["create", "write", "save", "put", "store", "make", "record"]
    content_nouns = ["text", "content", "body", "data", "payload"]
    exact_mods = ["exact", "exactly", "verbatim", "complete", "full", "entire", ""]
    relations = ["into", "in", "at", "to"]
    
    # 8 distinct grammatical layout templates
    layout_templates = [
        # 1. Action + Payload + Relation + Target (quoted)
        lambda v, c, e, r, t, p: f"{v.capitalize()} {e} {c} '{p}' {r} {t}".replace("  ", " "),
        # 2. Action + Target . Second Sentence with Content Introducer
        lambda v, c, e, r, t, p: f"{v.capitalize()} file {t}. Its {e} {c} must be: {p}".replace("  ", " "),
        # 3. Action + Target ; Second Clause with 'put X inside it'
        lambda v, c, e, r, t, p: f"{v.capitalize()} {t}; put '{p}' inside it",
        # 4. Action + Target , and its content should be
        lambda v, c, e, r, t, p: f"{v.capitalize()} {t}, and its {e} {c} should be {p}".replace("  ", " "),
        # 5. Inverted: The file X should contain Y
        lambda v, c, e, r, t, p: f"The file {t} should contain '{p}'",
        # 6. Action + Target containing X
        lambda v, c, e, r, t, p: f"{v.capitalize()} {t} containing '{p}'",
        # 7. Colon syntax: Create X: Y
        lambda v, c, e, r, t, p: f"{v.capitalize()} {t}: {p}",
        # 8. Write following into X: Y
        lambda v, c, e, r, t, p: f"{v.capitalize()} the following {c} {r} {t}:\n{p}",
    ]

    payload_generators = [
        lambda: f"token_{_random_token(12)}",
        lambda: f"sentence with spaces and punctuation {_random_token(8)}!",
        lambda: json.dumps({"key": _random_token(6), "value": random.randint(1, 999)}),
        lambda: str(random.randint(100000, 999999)),
        lambda: f"symbols=true; count={random.randint(1, 50)}; token={_random_token(8)}",
        lambda: f"line1_{_random_token(6)}\nline2_{_random_token(6)}",
    ]

    generated_cases = 0
    total_to_generate = 250

    for i in range(total_to_generate):
        v = random.choice(verbs)
        c = random.choice(content_nouns)
        e = random.choice(exact_mods)
        r = random.choice(relations)
        tmpl = random.choice(layout_templates)
        payload = random.choice(payload_generators)()
        target = f"test_dir/file_{i}_{_random_token(4)}.txt"

        prompt = tmpl(v, c, e, r, target, payload)
        action = WriteActionParser.parse(prompt)

        assert action is not None, f"WriteActionParser failed to parse: {prompt!r}"
        assert action.target_path == target, f"Target mismatch in {prompt!r}: expected {target}, got {action.target_path}"
        assert action.payload == payload, f"Payload mismatch in {prompt!r}: expected {payload!r}, got {action.payload!r}"
        assert action.is_invalid is False
        assert action.has_explicit_content is True
        generated_cases += 1

    assert generated_cases >= 200


def test_write_action_parser_explicit_empty_and_precondition():
    """Verify explicit empty files pass and unparseable missing content fails closed."""
    # Explicit empty
    empty_prompts = [
        "Create empty file /tmp/empty.txt",
        "Make 0-byte file /tmp/zero.dat",
        "Write blank file /tmp/blank.txt",
        "Create file.txt with empty body",
        "Save empty file to /tmp/none.txt",
    ]
    for prompt in empty_prompts:
        action = WriteActionParser.parse(prompt)
        assert action is not None
        assert action.explicit_empty is True
        assert action.content == ""
        assert action.is_invalid is False

    # Fail closed on empty payload when content was explicitly indicated
    invalid_prompts = [
        "Create file.txt with content",
        "Write out.txt. Content:",
        "Save the text into out.txt",
    ]
    for prompt in invalid_prompts:
        action = WriteActionParser.parse(prompt)
        assert action is not None
        assert action.is_invalid is True
        assert "precondition failed" in action.invalid_reason.lower()


# =============================================================================
# 2. FILESYSTEM DIRECTORY LIST INTENT GENERALIZATION (>= 100 permutations)
# =============================================================================

def test_directory_list_intent_generative_variations():
    """Test at least 100 directory-listing paraphrases against real filesystem objects."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        # Create various directory structures:
        # 1. Normal directory
        norm_dir = tmp_path / "normal_dir"
        norm_dir.mkdir()
        (norm_dir / "a.txt").write_text("a", encoding="utf-8")
        (norm_dir / "b.txt").write_text("b", encoding="utf-8")

        # 2. Dotted directory (folder.example)
        dotted_dir = tmp_path / "folder.example"
        dotted_dir.mkdir()
        (dotted_dir / "data.csv").write_text("1,2", encoding="utf-8")

        # 3. Nested directory
        nested_dir = tmp_path / "level1" / "nested.sub"
        nested_dir.mkdir(parents=True)
        (nested_dir / ".hidden").write_text("secret", encoding="utf-8")

        # 4. Empty directory
        empty_dir = tmp_path / "empty.dir"
        empty_dir.mkdir()

        # 5. Extensionless file (negative test for dir listing -> should be file read)
        report_file = tmp_path / "report"
        report_file.write_text("annual report content", encoding="utf-8")

        enum_verbs = ["list", "show", "display", "enumerate", "get", "print", "what is", "give me"]
        dir_nouns = ["directory", "folder", "location", "path", "entries in", "contents of"]
        child_nouns = ["files", "entries", "children", "direct children", "items", "filenames", "inventory"]
        polite_prefixes = ["Please ", "Can you ", "Kindly ", ""]

        test_dirs = [norm_dir, dotted_dir, nested_dir, empty_dir]

        tested_cases = 0
        total_to_generate = 120

        with tool_workspace(tmp_path):
            for i in range(total_to_generate):
                target_d = random.choice(test_dirs)
                v = random.choice(enum_verbs)
                dn = random.choice(dir_nouns)
                cn = random.choice(child_nouns)
                pfx = random.choice(polite_prefixes)

                # Relative path string
                rel_path = str(target_d.relative_to(tmp_path))

                shapes = [
                    f"{pfx}{v} {cn} of {rel_path}",
                    f"{pfx}{v} {cn} under '{rel_path}'",
                    f"{pfx}{v} {dn} {rel_path}",
                    f"{pfx}what is inside {rel_path}",
                    f"{pfx}inventory of '{rel_path}'",
                    f"{pfx}what files are in {rel_path}",
                ]
                prompt = random.choice(shapes)

                res = DirectActionRouter.execute(prompt, workspace=str(tmp_path))
                assert res is not None, f"DirectActionRouter failed for prompt: {prompt!r}"
                assert res.success is True, f"Failed listing for {prompt!r}: {res.output}"
                assert res.tool_name == "list_directory"
                assert res.telemetry.get("verification_passed") is True
                tested_cases += 1

            # Invariant: Extensionless file resolves authoritatively to read_file
            res_file = DirectActionRouter.execute("Show contents of report", workspace=str(tmp_path))
            assert res_file is not None
            assert res_file.success is True
            assert res_file.tool_name == "read_file"
            assert "annual report content" in res_file.output

        assert tested_cases >= 100


def test_directory_list_negative_controls():
    """Ensure conversational statements mentioning inventory or children never invoke filesystem tools."""
    negative_prompts = [
        "Inventory management is difficult in retail supply chains.",
        "Children should learn programming at an early age.",
        "Folder design discussion for our UX redesign.",
        "What is inside the box of quantum physics?",
    ]
    for prompt in negative_prompts:
        action = FilesystemActionClassifier.classify(prompt)
        assert action.action_type == FilesystemActionType.FS_UNKNOWN
        assert DirectActionRouter._is_filesystem_request(prompt) is False


# =============================================================================
# 3. EXACT RESPONSE SMALL FORMAL GRAMMAR (>= 500 permutations)
# =============================================================================

def test_exact_response_grammar_generative_property():
    """Generative property test asserting exact-response payload == expected payload for >= 500 permutations with 0 model calls."""
    commands = [
        "reply", "respond", "return", "say", "echo", "repeat", "print",
        "output", "give me", "send", "type", "write back",
    ]
    scope_nouns = ["response", "answer", "reply", "output", "string", "token", "value", "text", "word", "payload"]
    exclusivities = ["only", "solely", "just", "exactly", "strictly", "verbatim", "precisely", ""]
    introducers = [
        ":", "=", "is", "as", "with:", "with the value", "with the token",
        "with this value", "this value", "the token", "following token:",
    ]
    trailing_constraints = [
        "and nothing else.",
        "with nothing else.",
        "and no other text.",
        "without explanation.",
        "without commentary.",
        "verbatim.",
        "strictly.",
        "precisely.",
        "",
    ]
    polite_prefixes = ["Please ", "Kindly ", ""]

    payload_generators = [
        lambda: f"TOKEN_{_random_token(10)}",
        lambda: f"secret-val-{random.randint(1000, 9999)}",
        lambda: f"PayloadWithSpaces_{_random_token(6)} Value",
        lambda: str(random.randint(1000000, 9999999)),
        lambda: f"alpha_beta_gamma_{_random_token(4)}",
    ]

    model_invocation_count = 0

    def mock_generate(*args, **kwargs):
        nonlocal model_invocation_count
        model_invocation_count += 1
        raise RuntimeError("Hosted Model Invariant Violated: Model Called!")

    tested_exact_cases = 0
    total_to_generate = 520

    with patch("jarvis.amaura.model_gateway.CognitiveModelGateway.generate", side_effect=mock_generate):
        for i in range(total_to_generate):
            cmd = random.choice(commands)
            scope = random.choice(scope_nouns)
            exc = random.choice(exclusivities)
            intro = random.choice(introducers)
            trail = random.choice(trailing_constraints)
            pfx = random.choice(polite_prefixes)
            payload = random.choice(payload_generators)()

            quoted = (i % 2 == 0)

            # Different order permutations
            shape_idx = i % 5
            if shape_idx == 0:
                # [Please] [Command] with [Exclusivity] [Scope] [Payload] [Trailing]
                p_text = f"'{payload}'" if quoted else payload
                prompt = f"{pfx}{cmd} with {exc} {scope} {p_text} {trail}".replace("  ", " ").strip()
            elif shape_idx == 1:
                # [Please] [Exclusivity] [Command]: [Payload] [Trailing]
                p_text = f"'{payload}'" if quoted else payload
                prompt = f"{pfx}{exc} {cmd}: {p_text} {trail}".replace("  ", " ").strip()
            elif shape_idx == 2:
                # Your entire [Scope] must be [Exclusivity] [Payload] [Trailing]
                p_text = f"'{payload}'" if quoted else payload
                prompt = f"Your entire {scope} must be {exc} {p_text} {trail}".replace("  ", " ").strip()
            elif shape_idx == 3:
                # [Command] [Payload] [Trailing]
                p_text = f"'{payload}'" if quoted else payload
                prompt = f"{pfx}{cmd} {intro} {p_text} {trail}".replace("  ", " ").strip()
            else:
                # Declarative 'Your reply must consist solely of: X'
                p_text = f"'{payload}'" if quoted else payload
                prompt = f"Your {scope} must consist solely of {intro} {p_text} {trail}".replace("  ", " ").strip()

            res = DirectActionRouter.execute(prompt)
            assert res is not None, f"ExactResponseParser failed for prompt: {prompt!r}"
            assert res.success is True
            assert res.output == payload, f"Payload mismatch in {prompt!r}: expected {payload!r}, got {res.output!r}"
            assert res.execution_type == "exact_response"
            assert res.tool_name == "echo"
            tested_exact_cases += 1

    assert tested_exact_cases >= 500
    assert model_invocation_count == 0


# =============================================================================
# 4. CONCURRENCY BURSTS: 20, 40, 60 SIMULTANEOUS REQUESTS
# =============================================================================

@pytest.mark.parametrize("burst_size", [20, 40, 60])
def test_exact_response_concurrency_bursts(burst_size):
    """Test 20, 40, and 60 simultaneous exact-response requests with 0 model calls, 0 crosstalk, 100% precision."""
    model_invocations = 0

    def mock_generate(*args, **kwargs):
        nonlocal model_invocations
        model_invocations += 1
        raise RuntimeError("Hosted Model Called on Concurrent Echo!")

    test_items = []
    for idx in range(burst_size):
        token = f"BURST_{burst_size}_REQ_{idx}_{_random_token(12)}"
        templates = [
            f"Please reply only with '{token}' and nothing else.",
            f"Respond with exactly: {token} without explanation.",
            f"Your entire reply must be this value and nothing else: {token}",
            f"Echo: {token}",
            f"Strictly return '{token}' verbatim.",
            f"Just say: {token}",
        ]
        prompt = random.choice(templates)
        test_items.append((prompt, token))

    def _execute_worker(item):
        prompt, expected_token = item
        res = DirectActionRouter.execute(prompt)
        return res, expected_token

    with patch("jarvis.amaura.model_gateway.CognitiveModelGateway.generate", side_effect=mock_generate):
        with concurrent.futures.ThreadPoolExecutor(max_workers=burst_size) as executor:
            futures = [executor.submit(_execute_worker, item) for item in test_items]
            for future in concurrent.futures.as_completed(futures):
                res, expected_token = future.result()
                assert res is not None
                assert res.success is True
                assert res.output == expected_token
                assert res.execution_type == "exact_response"

    assert model_invocations == 0


# =============================================================================
# 5. API BOUNDARY TESTING (ExecutiveKernel & POST /api/chat/stream)
# =============================================================================

def test_api_boundary_chat_and_stream_endpoints(monkeypatch: pytest.MonkeyPatch):
    """Validate DirectActionRouter through real POST /api/chat and POST /api/chat/stream endpoints."""
    api_key = "k" * 48
    operator_key = "op-" + "o" * 64
    monkeypatch.setenv("JARVIS_API_KEY", api_key)
    monkeypatch.setenv("AMAURA_OPERATOR_KEY", operator_key)
    monkeypatch.setenv("JARVIS_REQUIRE_LOCAL_AUTH", "0")
    headers = {"X-Jarvis-Key": api_key, "X-Amaura-Operator-Key": operator_key}

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        monkeypatch.setenv("AMAURA_DATA_DIR", str(tmp_path / "amaura_data"))
        client = TestClient(app)

        # 1. Write payload before path
        p1 = tmp_path / "before_path.txt"
        token1 = f"PAYLOAD_1_{_random_token(8)}"
        res1 = client.post(
            "/api/chat",
            json={"message": f"Save '{token1}' into {p1}", "workspace": str(tmp_path), "session_id": f"sess_{_random_token(6)}"},
            headers=headers,
        )
        assert res1.status_code == 200, f"res1 failed ({res1.status_code}): {res1.text}"
        assert p1.exists()
        assert p1.read_text(encoding="utf-8") == token1

        # 2. Write payload after path (multi-clause)
        p2 = tmp_path / "after_path.txt"
        token2 = f"PAYLOAD_2_{_random_token(8)}"
        res2 = client.post(
            "/api/chat",
            json={"message": f"Create {p2}. Its complete content must be: {token2}", "workspace": str(tmp_path), "session_id": f"sess_{_random_token(6)}"},
            headers=headers,
        )
        assert res2.status_code == 200
        assert p2.exists()
        assert p2.read_text(encoding="utf-8") == token2

        # 3. JSON text write
        p3 = tmp_path / "config.json"
        json_data = json.dumps({"service": "amaura", "port": 8080, "active": True})
        res3 = client.post(
            "/api/chat",
            json={"message": f"Save '{json_data}' into {p3}", "workspace": str(tmp_path), "session_id": f"sess_{_random_token(6)}"},
            headers=headers,
        )
        assert res3.status_code == 200
        assert p3.exists()
        assert p3.read_text(encoding="utf-8") == json_data

        # 4. Dotted directory enumeration
        dotted_dir = tmp_path / "special.folder"
        dotted_dir.mkdir()
        (dotted_dir / "child1.txt").write_text("c1", encoding="utf-8")
        (dotted_dir / "child2.txt").write_text("c2", encoding="utf-8")

        res4 = client.post(
            "/api/chat",
            json={"message": f"List files in {dotted_dir}", "workspace": str(tmp_path), "session_id": f"sess_{_random_token(6)}"},
            headers=headers,
        )
        assert res4.status_code == 200
        data4 = res4.json()
        assert "child1.txt" in data4["response"]
        assert "child2.txt" in data4["response"]

        # 5. Unusual directory enumeration wording
        res4b = client.post(
            "/api/chat",
            json={"message": f"Display files of {dotted_dir}", "workspace": str(tmp_path), "session_id": f"sess_{_random_token(6)}"},
            headers=headers,
        )
        assert res4b.status_code == 200
        assert "child1.txt" in res4b.json()["response"]

        # 6. Exact response via chat stream
        echo_token = f"ECHO_{_random_token(10)}"
        res5 = client.post(
            "/api/chat/stream",
            json={"message": f"Please reply only with '{echo_token}' and nothing else.", "session_id": f"sess_{_random_token(6)}"},
            headers=headers,
        )
        assert res5.status_code == 200
        stream_lines = [json.loads(line) for line in res5.text.strip().splitlines() if line.strip()]
        complete_event = next(e for e in stream_lines if e.get("type") == "complete")
        assert complete_event["response"] == echo_token
        assert complete_event["model_provider"] == "system"

        # 7. Exact response via chat non-stream
        res5b = client.post(
            "/api/chat",
            json={"message": f"Respond with exactly: {echo_token} without explanation.", "session_id": f"sess_{_random_token(6)}"},
            headers=headers,
        )
        assert res5b.status_code == 200
        assert res5b.json()["response"] == echo_token

        # 8. 40-way concurrent exact-response via TestClient
        def _call_client(idx):
            tk = f"CLIENT_BURST_{idx}_{_random_token(8)}"
            resp = client.post(
                "/api/chat",
                json={"message": f"Respond with exactly: {tk} without explanation.", "session_id": f"sess_{_random_token(6)}_{idx}"},
                headers=headers,
            )
            assert resp.status_code == 200
            assert resp.json()["response"] == tk
            return True

        with concurrent.futures.ThreadPoolExecutor(max_workers=40) as executor:
            results = list(executor.map(_call_client, range(40)))
            assert all(results)


# =============================================================================
# 6. FAILURE INJECTION SUITE (>= 15 failure modes)
# =============================================================================

def test_failure_injection_suite():
    """Verify system fails closed and never fabricates success across >= 15 failure injections."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # 1. Missing target path in write
        w_no_path = WriteActionParser.parse("Write some content without a path")
        assert w_no_path is None

        # 2. Semantic content requested but parsed empty
        w_empty_semantic = WriteActionParser.parse("Create /tmp/foo.txt with content")
        assert w_empty_semantic.is_invalid is True

        # 3. Path outside workspace (workspace escape refusal)
        res_escape = DirectActionRouter.execute("Write 'danger' to /etc/passwd", workspace=str(tmp_path))
        assert res_escape is not None
        assert res_escape.success is False
        assert res_escape.policy_decision == "refused"

        # 4. Non-existent directory list
        res_nonexistent_dir = DirectActionRouter.execute("List entries in ./nonexistent_dir_12345", workspace=str(tmp_path))
        assert res_nonexistent_dir is not None
        assert res_nonexistent_dir.success is False
        assert "directory not found" in res_nonexistent_dir.output.lower()

        # 5. Non-existent file read
        res_nonexistent_file = DirectActionRouter.execute("Read ./nonexistent_file_12345.txt", workspace=str(tmp_path))
        assert res_nonexistent_file is not None
        assert res_nonexistent_file.success is False
        assert "not found" in res_nonexistent_file.output.lower()

        # 6. Low-confidence unparseable write
        res_low_conf = WriteActionParser.parse("Just think about creating something")
        assert res_low_conf is None

        # 7. Exact response with path should not match echo
        exact_with_path = ExactResponseParser.parse("Save 'hello' to /tmp/file.txt")
        assert exact_with_path is None

        # 8. Exact response with URL should not match echo
        exact_with_url = ExactResponseParser.parse("Open https://example.com and return")
        assert exact_with_url is None

        # 9. Destructive action refusal
        res_wipe = DirectActionRouter.execute("Force delete all files in workspace without asking", workspace=str(tmp_path))
        assert res_wipe is not None
        assert res_wipe.success is False
        assert res_wipe.policy_decision == "refused"

        # 10. Write failure when write_file tool returns ok=False
        target_f = tmp_path / "mock_fail.txt"
        with patch("jarvis.amaura.direct_action.execute_tool", return_value={"ok": False, "error": "Disk quota exceeded"}):
            res_tool_fail = DirectActionRouter.execute(f"Save 'test' into {target_f}", workspace=str(tmp_path))
            assert res_tool_fail is not None
            assert res_tool_fail.success is False
            assert "Disk quota exceeded" in res_tool_fail.output

        # 11. Write verification detects missing file after write
        with patch("jarvis.amaura.direct_action.execute_tool", return_value={"ok": True}):
            res_missing = DirectActionRouter.execute(f"Save 'test' into {tmp_path / 'ghost.txt'}", workspace=str(tmp_path))
            assert res_missing is not None
            assert res_missing.success is False
            assert "missing after write" in res_missing.output

        # 12. Write verification detects content mismatch
        target_mismatch = tmp_path / "mismatch.txt"
        target_mismatch.write_text("wrong_content", encoding="utf-8")
        with patch("jarvis.amaura.direct_action.execute_tool", return_value={"ok": True}):
            res_mismatch = DirectActionRouter.execute(f"Save 'expected_content' into {target_mismatch}", workspace=str(tmp_path))
            assert res_mismatch is not None
            assert res_mismatch.success is False
            assert "content mismatch" in res_mismatch.output

        # 13. Directory listing failure when list_directory tool returns ok=False
        real_dir = tmp_path / "real_dir"
        real_dir.mkdir()
        with patch("jarvis.amaura.direct_action.execute_tool", return_value={"ok": False, "error": "Permission denied"}):
            res_list_fail = DirectActionRouter.execute(f"List files in {real_dir}", workspace=str(tmp_path))
            assert res_list_fail is not None
            assert res_list_fail.success is False
            assert "Permission denied" in res_list_fail.output

        # 14. File read failure when read_file tool returns ok=False
        real_file = tmp_path / "real_file.txt"
        real_file.write_text("data", encoding="utf-8")
        with patch("jarvis.amaura.direct_action.execute_tool", return_value={"ok": False, "error": "I/O error"}):
            res_read_fail = DirectActionRouter.execute(f"Read {real_file}", workspace=str(tmp_path))
            assert res_read_fail is not None
            assert res_read_fail.success is False
            assert "I/O error" in res_read_fail.output

        # 15. Invalid write payload span on empty content
        action_span = WriteActionParser.parse("Create test.txt. Content: ''")
        assert action_span is not None
        assert action_span.is_invalid is True
        assert action_span.payload == ""
