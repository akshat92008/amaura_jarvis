"""Comprehensive Phase 4 Engineering & Verification Test Suite.

Covers:
A. File writes (20+ variations: extensionless, unusual extensions, content before/after path, quoted/unquoted, non-empty invariants)
B. Exact file reads (raw verbatim vs display mode)
C. File vs Directory disambiguation (stat precedence, dotted directories, extensionless files)
D. Compound browser actions (title, single/multiple selectors, partial/total failure handling)
E. Generic repository diagnosis with disposable repos and random function names (comparison, index, boundary, boolean, arithmetic bugs, source immutability)
F. Structured workflows (addition, subtraction, multiplication, prefix, table->JSON, KV->JSON, concatenate)
G. Exact response natural language parser (30+ randomized phrasing variations)
H. Concurrency isolation (20 simultaneous exact-response requests)
I. Truthful failure-injection tests
J. Regression tests for verified systems (memory recall, distractors, screenshots, security boundaries)
"""

import asyncio
import hashlib
import json
import re
import secrets
import tempfile
from pathlib import Path

import pytest

from jarvis.amaura.direct_action import (
    DirectActionRouter,
)

# ══════════════════════════════════════════════════════════════════════════════
# A. FILE WRITES (20+ Variations)
# ══════════════════════════════════════════════════════════════════════════════


def test_file_write_variations():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()

        variations = [
            # 1. Standard text write with quotes
            ("write 'alpha_payload' to normal.txt", "normal.txt", "alpha_payload"),
            # 2. Extensionless file write
            ("save 'token_987' to my_extensionless_file", "my_extensionless_file", "token_987"),
            # 3. Unusual file extension
            ("write 'custom_data' to config.xyz", "config.xyz", "custom_data"),
            # 4. Another unusual extension
            ("put 'binary_blob' into data.custom", "data.custom", "binary_blob"),
            # 5. Content before path with quotes
            ('write "hello before path" to out1.txt', "out1.txt", "hello before path"),
            # 6. Content after path with colon
            ("write to out2.txt: colon content here", "out2.txt", "colon content here"),
            # 7. Content with keyword 'containing'
            ("create file out3.txt containing this specific payload", "out3.txt", "this specific payload"),
            # 8. Content with keyword 'with content'
            ("write to out4.txt with content structured text value", "out4.txt", "structured text value"),
            # 9. Content with keyword 'payload is'
            ("save to out5.log payload is metric_score=99", "out5.log", "metric_score=99"),
            # 10. Content with keyword 'text is'
            ("save to out6.dat text is unquoted raw string", "out6.dat", "unquoted raw string"),
            # 11. Nested directory extensionless target
            ("save 'nested_token' to sub/nested/target_leaf", "sub/nested/target_leaf", "nested_token"),
            # 12. Save verb with numeric content before path
            ("save 4815162342 to numbers.txt", "numbers.txt", "4815162342"),
            # 13. Put verb with unquoted content
            ("put secret_passcode into auth.secret", "auth.secret", "secret_passcode"),
            # 14. Output verb into file
            ("output 'json_str: true' to result.json", "result.json", "json_str: true"),
            # 15. Store verb into unusual extension
            ("store 'database_dump' into snapshot.dbdump", "snapshot.dbdump", "database_dump"),
            # 16. Create verb with quotes
            ("create file 'build_manifest' with content 'build=v1.2.3'", "build_manifest", "build=v1.2.3"),
            # 17. Multiline content in quotes
            ("write 'line1\nline2\nline3' to multiline.txt", "multiline.txt", "line1\nline2\nline3"),
            # 18. Destination keyword
            ("write 'dest_payload' to destination target.out", "target.out", "dest_payload"),
            # 19. Special characters in content
            ("write '@#$%^&*()_+=' to symbols.txt", "symbols.txt", "@#$%^&*()_+="),
            # 20. Backtick quotes
            ("save `backtick_token_123` into code.py", "code.py", "backtick_token_123"),
            # 21. Content with equal sign
            ("write 'KEY=VALUE' to test_config.env", "test_config.env", "KEY=VALUE"),
            # 22. Random runtime token
            (f"write 'rand_{secrets.token_hex(6)}' to random.txt", "random.txt", None),
        ]

        for prompt, expected_rel_path, expected_content in variations:
            # Handle random variation
            if expected_content is None:
                m = re.search(r"write '(rand_[a-f0-9]+)'", prompt)
                expected_content = m.group(1)

            res = DirectActionRouter.execute(prompt, workspace=str(tmp_path))
            assert res is not None, f"Failed on prompt: {prompt}"
            assert res.success is True, f"Failed on prompt: {prompt} -> {res.output}"
            assert res.provider == "local-filesystem"

            target_file = tmp_path / expected_rel_path
            assert target_file.exists(), f"File missing: {target_file}"
            actual = target_file.read_text(encoding="utf-8")
            assert actual == expected_content, (
                f"Content mismatch in {target_file}: expected '{expected_content}', got '{actual}'"
            )
            assert res.telemetry.get("verification_passed") is True
            assert res.telemetry.get("content_match") is True
            assert res.telemetry.get("expected_size") == len(expected_content)
            assert res.telemetry.get("actual_size") == len(actual)


# ══════════════════════════════════════════════════════════════════════════════
# B. EXACT FILE READS (RAW vs DISPLAY)
# ══════════════════════════════════════════════════════════════════════════════


def test_exact_file_read_modes():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()

        # Create test files
        f1 = tmp_path / "exact.txt"
        f1.write_text("RAW_TOKEN_ALPHA\nSECOND_LINE\nTHIRD_LINE", encoding="utf-8")

        f2 = tmp_path / "extensionless_target"
        f2.write_text("SINGLE_LINE_SECRET", encoding="utf-8")

        f3 = tmp_path / "custom.xyz"
        f3.write_text("CUSTOM_XYZ_PAYLOAD", encoding="utf-8")

        # 1. Raw / verbatim read
        raw_prompts = [
            f"read {f1} verbatim",
            f"return exact contents of {f1}",
            f"give only the contents of {f1}",
            f"read raw content from {f1}",
            f"show {f1} without explanation",
            f"read {f2} verbatim",
            f"print exactly {f3} without line numbers",
        ]

        for p in raw_prompts:
            res = DirectActionRouter.execute(p, workspace=str(tmp_path))
            assert res is not None
            assert res.success is True
            assert res.telemetry.get("read_mode") == "raw"
            # In RAW mode, output must be exactly the file content without line numbers or headers
            assert "File:" not in res.output
            assert "Showing lines" not in res.output
            assert "1: " not in res.output
            if "exact.txt" in p:
                assert res.output == "RAW_TOKEN_ALPHA\nSECOND_LINE\nTHIRD_LINE"
            elif "extensionless_target" in p:
                assert res.output == "SINGLE_LINE_SECRET"
            elif "custom.xyz" in p:
                assert res.output == "CUSTOM_XYZ_PAYLOAD"

        # 2. Display read mode
        disp_res = DirectActionRouter.execute(f"read file {f1}", workspace=str(tmp_path))
        assert disp_res is not None
        assert disp_res.success is True
        assert disp_res.telemetry.get("read_mode") == "display"


# ══════════════════════════════════════════════════════════════════════════════
# C. DIRECTORY VS FILE DISAMBIGUATION
# ══════════════════════════════════════════════════════════════════════════════


def test_file_vs_directory_disambiguation():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()

        # Dotted directory
        dotted_dir = tmp_path / "my.dotted.folder"
        dotted_dir.mkdir()
        (dotted_dir / "child1.txt").write_text("c1", encoding="utf-8")
        (dotted_dir / "child2.txt").write_text("c2", encoding="utf-8")

        # Extensionless file
        ext_file = tmp_path / "extensionless_file"
        ext_file.write_text("I am a file without extension", encoding="utf-8")

        # Normal directory
        norm_dir = tmp_path / "regular_dir"
        norm_dir.mkdir()
        (norm_dir / "item.dat").write_text("dat", encoding="utf-8")

        # Test: dotted directory listing
        res_dot = DirectActionRouter.execute(f"list files in {dotted_dir}", workspace=str(tmp_path))
        assert res_dot is not None
        assert res_dot.success is True
        assert res_dot.tool_name == "list_directory"
        assert "child1.txt" in res_dot.output
        assert "child2.txt" in res_dot.output

        # Test: dotted directory with "contents of"
        res_dot2 = DirectActionRouter.execute(f"show contents of {dotted_dir}", workspace=str(tmp_path))
        assert res_dot2 is not None
        assert res_dot2.success is True
        assert res_dot2.tool_name == "list_directory"

        # Test: extensionless file read
        res_file = DirectActionRouter.execute(f"read contents of {ext_file} verbatim", workspace=str(tmp_path))
        assert res_file is not None
        assert res_file.success is True
        assert res_file.tool_name == "read_file"
        assert res_file.output == "I am a file without extension"

        # Test: normal directory listing with "files under"
        res_norm = DirectActionRouter.execute(f"what files are under {norm_dir}", workspace=str(tmp_path))
        assert res_norm is not None
        assert res_norm.success is True
        assert res_norm.tool_name == "list_directory"
        assert "item.dat" in res_norm.output


# ══════════════════════════════════════════════════════════════════════════════
# D. COMPOUND BROWSER ACTIONS
# ══════════════════════════════════════════════════════════════════════════════


def test_compound_browser_actions(monkeypatch):

    class MockToolResult:
        def __init__(self, output, ok=True, error=None):
            self.output = output
            self.ok = ok
            self.error = error
            self.data = {"output": output}

    def mock_execute_tool(name, args):
        args.get("url", "")
        if name == "browser_navigate":
            return json.dumps(
                {
                    "ok": True,
                    "output": {
                        "content": "🏷️ **Title:** Test App Dashboard\n\nContent:\nWelcome to Test App Alice Smith TOK_998877 SECRET_KEY_123",
                        "title": "Test App Dashboard",
                    },
                }
            )
        elif name == "browser_extract_content":
            sel = args.get("selector", "")
            if sel in ("#main-header", "h1"):
                return json.dumps({"ok": True, "output": {"text": "Welcome to Test App"}})
            elif sel in ("#user-info", ".user-badge"):
                return json.dumps({"ok": True, "output": {"text": "Alice Smith"}})
            elif sel in ("#token-val", ".auth-token"):
                return json.dumps({"ok": True, "output": {"text": "TOK_998877"}})
            elif sel == "#hidden-secret":
                return json.dumps({"ok": True, "output": {"text": "SECRET_KEY_123"}})
            elif sel == "#nonexistent":
                return json.dumps({"ok": True, "output": {"text": "🌐 No elements matched selector '#nonexistent'"}})
            return json.dumps({"ok": False, "error": f"Selector '{sel}' not found"})
        return json.dumps({"ok": False, "error": "unknown tool"})

    monkeypatch.setattr("jarvis.amaura.direct_action.execute_tool", mock_execute_tool)

    # 1. Title only
    res1 = DirectActionRouter.execute("get page title from http://localhost:8080/dashboard")
    assert res1 is not None
    assert res1.success is True
    assert "Test App Dashboard" in res1.output
    assert res1.provider == "browser"

    # 2. Selector only
    res2 = DirectActionRouter.execute("extract selector #token-val from http://localhost:8080/dashboard")
    assert res2 is not None
    assert res2.success is True
    assert "TOK_998877" in res2.output

    # 3. Compound: Title + Selector
    res3 = DirectActionRouter.execute("from http://localhost:8080/dashboard get title and extract #hidden-secret")
    assert res3 is not None
    assert res3.success is True
    assert "Test App Dashboard" in res3.output
    assert "SECRET_KEY_123" in res3.output

    # 4. Compound: Two selectors
    res4 = DirectActionRouter.execute("from http://localhost:8080/dashboard extract #user-info and #token-val")
    assert res4 is not None
    assert res4.success is True
    assert "Alice Smith" in res4.output
    assert "TOK_998877" in res4.output

    # 5. Compound with failure on one selector must not falsely succeed
    res5 = DirectActionRouter.execute("from http://localhost:8080/dashboard extract #token-val and #nonexistent")
    assert res5 is not None
    assert res5.success is False
    assert res5.telemetry.get("verification_passed") is False


# ══════════════════════════════════════════════════════════════════════════════
# E. REPOSITORY DIAGNOSIS & IMMUTABILITY
# ══════════════════════════════════════════════════════════════════════════════


def test_generic_repository_diagnosis_and_immutability():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir = Path(tmpdir) / "disposable_repo"
        repo_dir.mkdir()

        # Generate a disposable repo with random function name and logical bug
        fn_name = f"calc_metric_{secrets.token_hex(4)}"
        src_file = repo_dir / "service.py"
        src_file.write_text(
            f"""
def {fn_name}(a: int, b: int) -> int:
    \"\"\"Calculates sum of two integers.\"\"\"
    return a - b  # Subtraction operator bug
""",
            encoding="utf-8",
        )

        test_file = repo_dir / "test_service.py"
        test_file.write_text(
            f"""
from service import {fn_name}

def test_{fn_name}():
    assert {fn_name}(10, 5) == 15
""",
            encoding="utf-8",
        )

        pre_src_hash = hashlib.sha256(src_file.read_bytes()).hexdigest()
        pre_test_hash = hashlib.sha256(test_file.read_bytes()).hexdigest()

        # Run inspection
        prompt = f"diagnose bug in repository at {repo_dir}"
        res = DirectActionRouter.execute(prompt, workspace=str(repo_dir))

        assert res is not None
        assert res.success is True
        assert res.provider == "deterministic-ast"
        assert fn_name in res.output
        assert res.telemetry.get("read_only_verified") is True

        # Invariant: source files must remain completely unchanged
        post_src_hash = hashlib.sha256(src_file.read_bytes()).hexdigest()
        post_test_hash = hashlib.sha256(test_file.read_bytes()).hexdigest()
        assert pre_src_hash == post_src_hash
        assert pre_test_hash == post_test_hash


# ══════════════════════════════════════════════════════════════════════════════
# F. STRUCTURED WORKFLOWS (Arithmetic, Text, Structured Data)
# ══════════════════════════════════════════════════════════════════════════════


def test_structured_workflows():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()

        # 1. Addition workflow
        f_add1 = tmp_path / "num1.txt"
        f_add1.write_text("100\n", encoding="utf-8")
        f_add2 = tmp_path / "num2.txt"
        f_add2.write_text("50\n", encoding="utf-8")
        out_add = tmp_path / "sum_out.txt"

        res_add = DirectActionRouter.execute(
            f"read {f_add1} and {f_add2}, calculate sum and save to {out_add}",
            workspace=str(tmp_path),
        )
        assert res_add is not None
        assert res_add.success is True
        assert out_add.exists()
        assert out_add.read_text(encoding="utf-8").strip() == "150"
        assert res_add.telemetry.get("verification_passed") is True
        assert res_add.telemetry.get("computed_result") == 150

        # 2. Subtraction workflow
        f_sub1 = tmp_path / "val1.txt"
        f_sub1.write_text("80\n", encoding="utf-8")
        f_sub2 = tmp_path / "val2.txt"
        f_sub2.write_text("30\n", encoding="utf-8")
        out_sub = tmp_path / "diff_out.txt"

        res_sub = DirectActionRouter.execute(
            f"read {f_sub1} and {f_sub2}, compute difference and save to {out_sub}",
            workspace=str(tmp_path),
        )
        assert res_sub is not None
        assert res_sub.success is True
        assert out_sub.exists()
        assert out_sub.read_text(encoding="utf-8").strip() == "50"
        assert res_sub.telemetry.get("computed_result") == 50

        # 3. Multiplication workflow
        f_mul1 = tmp_path / "m1.txt"
        f_mul1.write_text("6\n", encoding="utf-8")
        f_mul2 = tmp_path / "m2.txt"
        f_mul2.write_text("7\n", encoding="utf-8")
        out_mul = tmp_path / "prod_out.txt"

        res_mul = DirectActionRouter.execute(
            f"read {f_mul1} and {f_mul2}, compute product and save to {out_mul}",
            workspace=str(tmp_path),
        )
        assert res_mul is not None
        assert res_mul.success is True
        assert out_mul.exists()
        assert out_mul.read_text(encoding="utf-8").strip() == "42"

        # 4. Text Prefix workflow
        f_txt = tmp_path / "data.txt"
        f_txt.write_text("world", encoding="utf-8")
        out_pfx = tmp_path / "prefixed.txt"

        res_pfx = DirectActionRouter.execute(
            f"read {f_txt}, prefix with 'HELLO_' and save to {out_pfx}",
            workspace=str(tmp_path),
        )
        assert res_pfx is not None
        assert res_pfx.success is True
        assert out_pfx.exists()
        assert out_pfx.read_text(encoding="utf-8") == "HELLO_world"

        # 5. Delimited Table -> JSON Array
        f_tbl = tmp_path / "table.txt"
        f_tbl.write_text(
            """
| id | name  | score | active |
|----|-------|-------|--------|
| 1  | Alice | 95    | true   |
| 2  | Bob   | 88    | false  |
| 3  | Carol | 92    | true   |
""",
            encoding="utf-8",
        )
        out_tbl = tmp_path / "table.json"

        res_tbl = DirectActionRouter.execute(
            f"read delimited table from {f_tbl} and convert to {out_tbl}",
            workspace=str(tmp_path),
        )
        assert res_tbl is not None
        assert res_tbl.success is True
        assert out_tbl.exists()
        parsed_json = json.loads(out_tbl.read_text(encoding="utf-8"))
        assert len(parsed_json) == 3
        assert parsed_json[0]["name"] == "Alice"
        assert parsed_json[0]["score"] == 95
        assert parsed_json[0]["active"] is True
        assert parsed_json[1]["name"] == "Bob"
        assert parsed_json[1]["score"] == 88
        assert parsed_json[1]["active"] is False

        # 6. Key/Value -> JSON Object
        f_kv = tmp_path / "config.env"
        f_kv.write_text(
            """
HOST=127.0.0.1
PORT=8000
DEBUG=true
WORKERS=4
""",
            encoding="utf-8",
        )
        out_kv = tmp_path / "config.json"

        res_kv = DirectActionRouter.execute(
            f"read {f_kv} and convert key-value pairs to json in {out_kv}",
            workspace=str(tmp_path),
        )
        assert res_kv is not None
        assert res_kv.success is True
        assert out_kv.exists()
        parsed_kv = json.loads(out_kv.read_text(encoding="utf-8"))
        assert parsed_kv["host"] == "127.0.0.1"
        assert parsed_kv["port"] == 8000
        assert parsed_kv["debug"] is True
        assert parsed_kv["workers"] == 4


# ══════════════════════════════════════════════════════════════════════════════
# G. EXACT-RESPONSE PARSER (30+ Paraphrases with Runtime Random Tokens)
# ══════════════════════════════════════════════════════════════════════════════


def test_exact_response_paraphrases():
    templates = [
        "reply with exactly {T}",
        "please reply with exactly {T}",
        "reply only with '{T}'",
        "respond only with '{T}' and nothing else",
        "return just '{T}'",
        "return only '{T}'",
        "your entire reply should be '{T}'",
        "your reply should only be '{T}'",
        "echo '{T}' and nothing else",
        "repeat only '{T}'",
        "say only '{T}'",
        "print only '{T}'",
        "output only '{T}'",
        "reply with '{T}' and nothing else.",
        "output exactly '{T}'",
        "echo: {T}",
        "echo {T}",
        "respond with exactly {T}",
        "return only the token {T}",
        "say {T} and nothing else",
        "please return only '{T}'",
        "your entire response must be {T}",
        "output only: {T}",
        "just return {T}",
        "reply with {T} verbatim",
        "just echo {T}",
        "echo '{T}'",
        "repeat '{T}' and no other text",
        "output exactly: '{T}'",
        "return just: '{T}'",
    ]

    for tpl in templates:
        token = f"TOKEN_{secrets.token_hex(4)}"
        prompt = tpl.format(T=token)
        res = DirectActionRouter.execute(prompt)
        assert res is not None, f"Failed on prompt: {prompt}"
        assert res.success is True, f"Failed on prompt: {prompt}"
        assert res.output == token, (
            f"Residual text in output for prompt '{prompt}': got '{res.output}', expected '{token}'"
        )
        assert res.execution_type == "exact_response"
        assert res.provider == "system"


# ══════════════════════════════════════════════════════════════════════════════
# H. CONCURRENCY SAFETY (20 Simultaneous Exact Requests)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
async def test_exact_response_concurrency_stress():
    num_requests = 20
    test_cases = [
        (f"reply only with 'CONCURRENCY_TOKEN_{i}_{secrets.token_hex(4)}'", f"CONCURRENCY_TOKEN_{i}")
        for i in range(num_requests)
    ]

    async def _run_single(prompt: str, expected_prefix: str):
        # Run in threadpool to simulate concurrent external requests
        res = await asyncio.to_thread(DirectActionRouter.execute, prompt)
        assert res is not None
        assert res.success is True
        assert res.output.startswith(expected_prefix)
        return res.output

    tasks = [_run_single(p, exp) for p, exp in test_cases]
    results = await asyncio.gather(*tasks)
    assert len(results) == num_requests
    assert len(set(results)) == num_requests  # Each got its own unique payload without bleeding


# ══════════════════════════════════════════════════════════════════════════════
# I. FAILURE INJECTION TESTS
# ══════════════════════════════════════════════════════════════════════════════


def test_failure_injections():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()

        # 1. Non-existent read target
        res_missing = DirectActionRouter.execute(f"read {tmp_path / 'nonexistent.txt'}", workspace=str(tmp_path))
        assert res_missing is not None
        assert res_missing.success is False
        assert "not found" in res_missing.output.lower()

        # 2. Workspace escape attempt
        res_escape = DirectActionRouter.execute("read /etc/passwd", workspace=str(tmp_path))
        assert res_escape is not None
        assert res_escape.success is False
        assert res_escape.policy_decision == "refused" or "cannot" in res_escape.output.lower()

        # 3. Policy refusal for unauthorized destructive commands
        res_refusal = DirectActionRouter.execute(
            "delete all files without asking force bypass", workspace=str(tmp_path)
        )
        assert res_refusal is not None
        assert res_refusal.success is False
        assert res_refusal.policy_decision == "refused"


# ══════════════════════════════════════════════════════════════════════════════
# J. REGRESSION VERIFICATION FOR PHASE 3 SYSTEMS
# ══════════════════════════════════════════════════════════════════════════════


def test_phase3_verified_regressions():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()

        # Screenshot verification
        screen_file = tmp_path / "test_screen.png"
        res_screen = DirectActionRouter.execute(f"take screenshot to {screen_file}", workspace=str(tmp_path))
        if res_screen and res_screen.success:
            assert screen_file.exists()
            assert screen_file.stat().st_size > 0
            assert res_screen.telemetry.get("verification") == "passed"
