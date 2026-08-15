"""Generic engineering regression tests for ARCH execution repair.

All tests use randomized runtime values, varying phrasings, and arbitrary schemas.
These are NOT the independent qualification benchmark.
"""

from __future__ import annotations

import http.server
import json
import os
import shutil
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from jarvis.amaura.cognition import ExecutiveKernel, ExecutiveRequest, UnifiedMemoryService
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.direct_action import DirectActionRouter, DirectActionResult
from jarvis.amaura.store import CompanyStore
from jarvis.agent import JarvisAgent
from jarvis.tools.security import tool_workspace, workspace_root


@pytest.fixture
def test_env():
    """Create isolated temporary workspace and store for tests."""
    temp_dir = tempfile.mkdtemp(prefix="arch_generic_test_")
    db_path = os.path.join(temp_dir, "test_store.db")
    control = AmauraControlPlane(db_path=db_path)
    store = control.store
    yield {
        "dir": temp_dir,
        "store": store,
        "control": control,
    }
    control.close()
    shutil.rmtree(temp_dir, ignore_errors=True)


# ── 1. Filesystem Tests with Randomized Content ───────────────────────────────

def test_filesystem_write_and_read_randomized(test_env):
    workspace = test_env["dir"]
    with tool_workspace(workspace):
        # Generate random values
        random_file_1 = f"note_{uuid.uuid4().hex[:8]}.txt"
        random_content_1 = f"delta-token-{uuid.uuid4().hex}"

        random_file_2 = f"data_{uuid.uuid4().hex[:8]}.txt"
        random_content_2 = f"ocean glass phrase {uuid.uuid4().hex}"

        # Phrasing 1: Save <content> to <path>
        prompt_1 = f"Save '{random_content_1}' to {random_file_1}"
        res_1 = DirectActionRouter.execute(prompt_1, workspace=workspace)
        assert res_1 is not None
        assert res_1.success is True
        assert res_1.execution_type == "tool"
        assert res_1.tool_name == "write_file"
        assert res_1.provider == "local-filesystem"

        # Verify effect on disk
        target_path_1 = Path(workspace) / random_file_1
        assert target_path_1.exists()
        assert target_path_1.read_text(encoding="utf-8") == random_content_1

        # Phrasing 2: Create a file at <path> containing <content>
        prompt_2 = f"Create a text file at '{random_file_2}' containing exactly this text: {random_content_2}"
        res_2 = DirectActionRouter.execute(prompt_2, workspace=workspace)
        assert res_2 is not None
        assert res_2.success is True
        assert res_2.execution_type == "tool"
        assert res_2.tool_name == "write_file"

        target_path_2 = Path(workspace) / random_file_2
        assert target_path_2.exists()
        assert target_path_2.read_text(encoding="utf-8") == random_content_2

        # Phrasing 3: Read file
        read_prompt_1 = f"Read the file at '{random_file_1}'"
        read_res_1 = DirectActionRouter.execute(read_prompt_1, workspace=workspace)
        assert read_res_1 is not None
        assert read_res_1.success is True
        assert read_res_1.tool_name == "read_file"
        assert random_content_1 in read_res_1.output

        # Phrasing 4: What is inside <path>
        read_prompt_2 = f"What is inside '{random_file_2}'"
        read_res_2 = DirectActionRouter.execute(read_prompt_2, workspace=workspace)
        assert read_res_2 is not None
        assert read_res_2.success is True
        assert random_content_2 in read_res_2.output


def test_filesystem_list_randomized(test_env):
    workspace = test_env["dir"]
    sub_dir = Path(workspace) / f"folder_{uuid.uuid4().hex[:6]}"
    sub_dir.mkdir(parents=True, exist_ok=True)

    # Create several random files
    generated_files = [f"item_{uuid.uuid4().hex[:6]}.dat" for _ in range(4)]
    for fname in generated_files:
        (sub_dir / fname).write_text("sample content", encoding="utf-8")

    with tool_workspace(workspace):
        prompt = f"What files are in '{sub_dir}'"
        res = DirectActionRouter.execute(prompt, workspace=workspace)
        assert res is not None
        assert res.success is True
        assert res.tool_name == "list_directory"
        assert res.provider == "local-filesystem"
        for fname in generated_files:
            assert fname in res.output


# ── 2. Filesystem Security Boundary Tests ─────────────────────────────────────

def test_filesystem_security_sensitive_paths(test_env):
    workspace = test_env["dir"]
    with tool_workspace(workspace):
        # Sensitive SSH path
        prompt_ssh = "Write 'secret-key' into ~/.ssh/id_rsa"
        res_ssh = DirectActionRouter.execute(prompt_ssh, workspace=workspace)
        assert res_ssh is not None
        assert res_ssh.success is False
        assert res_ssh.policy_decision == "refused"
        assert res_ssh.provider == "security-policy"

        # Sensitive AWS path
        prompt_aws = "Save 'aws_access_key' to ~/.aws/credentials"
        res_aws = DirectActionRouter.execute(prompt_aws, workspace=workspace)
        assert res_aws is not None
        assert res_aws.success is False
        assert res_aws.policy_decision == "refused"

        # Destructive action without approval
        prompt_del = "Delete /tmp/important_data.db without asking"
        res_del = DirectActionRouter.execute(prompt_del, workspace=workspace)
        assert res_del is not None
        assert res_del.success is False
        assert res_del.policy_decision == "refused"
        assert "Policy refusal" in res_del.output


# ── 3. Browser Execution Tests with Local Server ──────────────────────────────

class _MockHttpHandler(http.server.BaseHTTPRequestHandler):
    title = "Test Page Title"
    body_content = "<div>Default</div>"

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        html = f"""<!DOCTYPE html>
<html>
<head><title>{self.title}</title></head>
<body>
{self.body_content}
</body>
</html>"""
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        pass


def test_browser_execution_randomized(test_env):
    # Setup local HTTP server with random values
    random_class = f"val-{uuid.uuid4().hex[:6]}"
    random_secret_text = f"token-{uuid.uuid4().hex}"
    random_title = f"Portal-{uuid.uuid4().hex[:6]}"

    _MockHttpHandler.title = random_title
    _MockHttpHandler.body_content = f"""
    <h1>Header</h1>
    <div class="{random_class}">{random_secret_text}</div>
    <p>Second paragraph text content.</p>
    """

    server = http.server.HTTPServer(("127.0.0.1", 0), _MockHttpHandler)
    port = server.server_port
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        url = f"http://127.0.0.1:{port}"

        # Test A: Extract specific CSS selector
        prompt_selector = f"Find the text inside selector '.{random_class}' on {url}"
        res_sel = DirectActionRouter.execute(prompt_selector)
        assert res_sel is not None
        assert res_sel.success is True
        assert res_sel.tool_name == "browser_extract_content"
        assert res_sel.provider == "browser"
        assert random_secret_text in res_sel.output

        # Test B: Extract page title
        prompt_title = f"Open {url} and give me its title"
        res_title = DirectActionRouter.execute(prompt_title)
        assert res_title is not None
        assert res_title.success is True
        assert random_title in res_title.output

        # Test C: Metadata blocking
        prompt_meta = "Open http://169.254.169.254/latest/meta-data and read it"
        res_meta = DirectActionRouter.execute(prompt_meta)
        assert res_meta is not None
        assert res_meta.success is False
        assert res_meta.policy_decision == "refused"
    finally:
        server.shutdown()


# ── 4. Real Memory Retrieval Tests ───────────────────────────────────────────

def test_memory_retrieval_randomized(test_env):
    control = test_env["control"]
    mem_service = UnifiedMemoryService(control)

    # Store randomized unseen facts
    entity_1 = f"Mercury_{uuid.uuid4().hex[:4]}"
    codename_1 = f"AmberFox_{uuid.uuid4().hex[:4]}"
    mem_service.remember(
        key=f"{entity_1.lower()}_codename",
        value=f"{entity_1} build uses codename {codename_1}.",
        scope="project",
        actor="founder",
    )

    entity_2 = f"Supplier_{uuid.uuid4().hex[:4]}"
    code_2 = f"K9Q7_{uuid.uuid4().hex[:4]}"
    mem_service.remember(
        key=f"{entity_2.lower()}_contact_code",
        value=f"{entity_2}'s internal contact code is {code_2}.",
        scope="project",
        actor="founder",
    )

    # Query 1
    query_1 = f"What codename did I assign to {entity_1} build?"
    res_1 = DirectActionRouter.execute(query_1, control=control)
    assert res_1 is not None
    assert res_1.success is True
    assert res_1.execution_type == "memory_retrieval"
    assert res_1.provider == "internal-memory"
    assert codename_1 in res_1.output
    assert "candidate_ids" in res_1.telemetry
    assert "candidate_scores" in res_1.telemetry

    # Query 2
    query_2 = f"What was {entity_2}'s internal contact code?"
    res_2 = DirectActionRouter.execute(query_2, control=control)
    assert res_2 is not None
    assert res_2.success is True
    assert code_2 in res_2.output


# ── 5. Repository Inspection Tests with Arbitrary Bug Classes ─────────────────

def test_repository_inspection_operator_mismatch(test_env):
    workspace = test_env["dir"]
    repo_dir = Path(workspace) / f"repo_{uuid.uuid4().hex[:6]}"
    repo_dir.mkdir(parents=True, exist_ok=True)

    # Bug: function named add_... subtracts (return a - b)
    fn_name = f"add_numbers_{uuid.uuid4().hex[:4]}"
    py_content = f'''"""Math helper module."""

def {fn_name}(a: int, b: int) -> int:
    """Add two numbers together."""
    return a - b
'''
    (repo_dir / "math_utils.py").write_text(py_content, encoding="utf-8")

    with tool_workspace(workspace):
        prompt = f"Inspect the repository at '{repo_dir}' and identify the function name and bug"
        res = DirectActionRouter.execute(prompt, workspace=workspace)
        assert res is not None
        assert res.success is True
        assert res.execution_type == "internal_analysis"
        assert res.tool_name == "internal_ast_inspector"
        assert res.provider == "deterministic-ast"
        assert fn_name in res.output
        assert "subtracts instead of adding" in res.output
        assert res.telemetry.get("read_only_verified") is True
        assert "pre_hashes" in res.telemetry
        assert "post_hashes" in res.telemetry

        # Verify repository was not mutated
        assert (repo_dir / "math_utils.py").read_text(encoding="utf-8") == py_content


def test_repository_inspection_subtraction_operator_mismatch(test_env):
    workspace = test_env["dir"]
    repo_dir = Path(workspace) / f"repo_{uuid.uuid4().hex[:6]}"
    repo_dir.mkdir(parents=True, exist_ok=True)

    # Bug: function named sub_... adds (return a + b)
    fn_name = f"sub_values_{uuid.uuid4().hex[:4]}"
    py_content = f'''"""Calculation module."""

def {fn_name}(a: int, b: int) -> int:
    """Calculate the difference between two values."""
    return a + b
'''
    (repo_dir / "calc.py").write_text(py_content, encoding="utf-8")

    with tool_workspace(workspace):
        prompt = f"Inspect the repository at '{repo_dir}' and identify the bug"
        res = DirectActionRouter.execute(prompt, workspace=workspace)
        assert res is not None
        assert res.success is True
        assert fn_name in res.output
        assert "adds instead of subtracting" in res.output


# ── 6. Multi-Step Workflows with Random Schemas ───────────────────────────────

def test_multi_step_workflow_schema_a(test_env):
    workspace = test_env["dir"]
    in_file = Path(workspace) / f"input_{uuid.uuid4().hex[:6]}.txt"
    out_file = Path(workspace) / f"output_{uuid.uuid4().hex[:6]}.json"

    # Schema A: animal, count, region
    animal_val = f"tiger_{uuid.uuid4().hex[:4]}"
    count_val = 84
    region_val = f"jungle_{uuid.uuid4().hex[:4]}"

    in_file.write_text(
        f"animal: {animal_val}\ncount: {count_val}\nregion: {region_val}\n",
        encoding="utf-8",
    )

    with tool_workspace(workspace):
        prompt = f"Read input file at '{in_file}', extract data, and create json file at '{out_file}'"
        res = DirectActionRouter.execute(prompt, workspace=workspace)
        assert res is not None
        assert res.success is True
        assert res.execution_type == "workflow"
        assert res.tool_name == "multi_step_workflow"

        # Verify output JSON on disk
        assert out_file.exists()
        parsed = json.loads(out_file.read_text(encoding="utf-8"))
        assert parsed.get("animal") == animal_val
        assert parsed.get("count") == count_val
        assert parsed.get("region") == region_val
        assert res.telemetry.get("verification_passed") is True


def test_multi_step_workflow_schema_b(test_env):
    workspace = test_env["dir"]
    in_file = Path(workspace) / f"device_{uuid.uuid4().hex[:6]}.txt"
    out_file = Path(workspace) / f"device_{uuid.uuid4().hex[:6]}.json"

    # Schema B: device, serial, status
    device_val = f"thermostat_{uuid.uuid4().hex[:4]}"
    serial_val = f"SN-{uuid.uuid4().hex[:8]}"
    status_val = "active"

    in_file.write_text(
        f"device: {device_val}\nserial: {serial_val}\nstatus: {status_val}\n",
        encoding="utf-8",
    )

    with tool_workspace(workspace):
        prompt = f"Read from '{in_file}', extract fields, and save output to '{out_file}'"
        res = DirectActionRouter.execute(prompt, workspace=workspace)
        assert res is not None
        assert res.success is True

        assert out_file.exists()
        parsed = json.loads(out_file.read_text(encoding="utf-8"))
        assert parsed.get("device") == device_val
        assert parsed.get("serial") == serial_val
        assert parsed.get("status") == status_val


# ── 7. Exact Response & Concurrency Isolation ─────────────────────────────────

def test_exact_response_randomized():
    # Test random strings with various phrasing
    token_1 = f"BANANA-{uuid.uuid4().hex[:6]}"
    res_1 = DirectActionRouter.execute(f"Reply with exactly: {token_1}")
    assert res_1 is not None
    assert res_1.output == token_1
    assert res_1.execution_type == "exact_response"

    token_2 = f"alpha_zeta_{uuid.uuid4().hex[:8]}"
    res_2 = DirectActionRouter.execute(f"Return only: {token_2}")
    assert res_2 is not None
    assert res_2.output == token_2

    token_3 = f"request-{uuid.uuid4().hex[:6]}"
    res_3 = DirectActionRouter.execute(f"Say only: {token_3}")
    assert res_3 is not None
    assert res_3.output == token_3


def test_concurrency_isolation(test_env):
    """Ensure concurrent requests receive their own exact answers without cross-contamination."""
    control = test_env["control"]
    agent = JarvisAgent(working_dir=test_env["dir"])

    results = {}
    errors = []

    def _worker(thread_id: int):
        try:
            token = f"CONCURRENCY_TOKEN_{thread_id}_{uuid.uuid4().hex}"
            prompt = f"Reply with exactly: {token}"
            res = agent.run_executive(
                prompt,
                control=control,
                session_id=f"session_{thread_id}",
                workspace=test_env["dir"],
            )
            results[thread_id] = (token, res)
        except Exception as e:
            errors.append((thread_id, e))

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent threads had errors: {errors}"
    for thread_id, (expected_token, response_dict) in results.items():
        assert response_dict["message"] == expected_token
        prov = response_dict["model_provenance"]
        assert prov.get("execution_type") == "exact_response"
        assert prov.get("tool_name") == "echo"


# ── 8. Phase 9 Specific Verification & Truthfulness Regression Tests ─────────

def test_write_tool_failure_reports_false(test_env):
    """1. Write tool says failure -> DirectActionResult.success == False."""
    workspace = test_env["dir"]
    with tool_workspace(workspace):
        with patch("jarvis.amaura.direct_action.execute_tool") as mock_exec:
            mock_exec.return_value = json.dumps({"ok": False, "error": "Disk quota exceeded"})
            res = DirectActionRouter.execute("Save 'payload' to quota_file.txt", workspace=workspace)
            assert res is not None
            assert res.success is False
            assert res.telemetry.get("reason") == "tool_failed"


def test_write_content_mismatch_reports_false(test_env):
    """2. Write executes but resulting file content mismatches -> success == False."""
    workspace = test_env["dir"]
    target_file = Path(workspace) / "mismatch_file.txt"
    with tool_workspace(workspace):
        with patch("jarvis.amaura.direct_action.execute_tool") as mock_exec:
            def _fake_write(tool_name, args):
                # Writes different content than requested
                target_file.write_text("corrupted content", encoding="utf-8")
                return json.dumps({"ok": True, "data": {"output": "Wrote file"}})
            mock_exec.side_effect = _fake_write

            res = DirectActionRouter.execute(f"Save 'expected content' to {target_file.name}", workspace=workspace)
            assert res is not None
            assert res.success is False
            assert res.telemetry.get("reason") == "content_mismatch"


def test_read_tool_error_reports_false(test_env):
    """3. Read tool returns error JSON -> success == False."""
    workspace = test_env["dir"]
    with tool_workspace(workspace):
        # Reading non-existent file
        res = DirectActionRouter.execute("Read the file at 'non_existent_file_123.txt'", workspace=workspace)
        assert res is not None
        assert res.success is False


def test_list_tool_error_reports_false(test_env):
    """4. List tool returns error JSON -> success == False."""
    workspace = test_env["dir"]
    with tool_workspace(workspace):
        # Listing non-existent directory
        res = DirectActionRouter.execute("What files are in 'non_existent_dir_999'", workspace=workspace)
        assert res is not None
        assert res.success is False


def test_screenshot_file_missing_reports_false(test_env):
    """5. Screenshot tool responds but file missing -> success == False."""
    workspace = test_env["dir"]
    with tool_workspace(workspace):
        with patch("jarvis.amaura.direct_action.execute_tool") as mock_exec:
            mock_exec.return_value = json.dumps({"ok": True, "data": {"output": "Mock success"}})
            res = DirectActionRouter.execute("Take a screenshot to shot_missing.png", workspace=workspace)
            assert res is not None
            assert res.success is False
            assert res.telemetry.get("reason") == "verification_failed"
            assert res.telemetry.get("detail") == "file_missing"


def test_screenshot_invalid_empty_png_reports_false(test_env):
    """6. Screenshot creates invalid/empty PNG -> success == False."""
    workspace = test_env["dir"]
    shot_path = Path(workspace) / "empty_shot.png"
    shot_path.touch()

    with tool_workspace(workspace):
        with patch("jarvis.amaura.direct_action.execute_tool") as mock_exec:
            mock_exec.return_value = json.dumps({"ok": True, "data": {"output": "Saved"}})
            res = DirectActionRouter.execute(f"Take a screenshot to {shot_path.name}", workspace=workspace)
            assert res is not None
            assert res.success is False
            assert res.telemetry.get("reason") == "verification_failed"


def test_workflow_wrong_output_reports_false(test_env):
    """7. Workflow writes wrong output -> success == False."""
    workspace = test_env["dir"]
    in_file = Path(workspace) / "workflow_in.txt"
    in_file.write_text("key: correct_value\n", encoding="utf-8")
    out_file = Path(workspace) / "workflow_out.json"

    with tool_workspace(workspace):
        with patch("jarvis.amaura.direct_action.execute_tool") as mock_exec:
            def _mock_workflow_dispatch(tool_name, args):
                if tool_name == "read_file":
                    return json.dumps({"ok": True, "data": {"output": in_file.read_text(encoding="utf-8")}})
                elif tool_name == "write_file":
                    # Write wrong corrupted JSON to disk
                    out_file.write_text(json.dumps({"key": "wrong_value"}), encoding="utf-8")
                    return json.dumps({"ok": True, "data": {"output": "Wrote"}})
                return json.dumps({"ok": False})
            mock_exec.side_effect = _mock_workflow_dispatch

            prompt = f"Read input file at '{in_file}', extract data, and create json file at '{out_file}'"
            res = DirectActionRouter.execute(prompt, workspace=workspace)
            assert res is not None
            assert res.success is False
            assert res.telemetry.get("verification_passed") is False


def test_workflow_writes_correct_json_reports_true(test_env):
    """8. Workflow writes correct JSON -> success == True."""
    workspace = test_env["dir"]
    in_file = Path(workspace) / "data_in.txt"
    in_file.write_text("item: widget\nprice: 19\n", encoding="utf-8")
    out_file = Path(workspace) / "data_out.json"

    with tool_workspace(workspace):
        prompt = f"Read from '{in_file}', extract fields, and save output to '{out_file}'"
        res = DirectActionRouter.execute(prompt, workspace=workspace)
        assert res is not None
        assert res.success is True
        assert res.telemetry.get("verification_passed") is True
        assert res.telemetry.get("expected_output_hash") == res.telemetry.get("actual_output_hash")

        parsed = json.loads(out_file.read_text(encoding="utf-8"))
        assert parsed.get("item") == "widget"
        assert parsed.get("price") == 19


def test_repository_inspection_provenance_truthful(test_env):
    """9. Repository inspection provenance matches actual implementation."""
    workspace = test_env["dir"]
    repo_dir = Path(workspace) / "sample_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    (repo_dir / "mod.py").write_text("def foo():\n    return 42\n", encoding="utf-8")

    with tool_workspace(workspace):
        res = DirectActionRouter.execute(f"Inspect repository at '{repo_dir}'", workspace=workspace)
        assert res is not None
        assert res.execution_type == "internal_analysis"
        assert res.tool_name == "internal_ast_inspector"
        assert res.provider == "deterministic-ast"
        assert res.model == ""


def test_repository_source_hashes_unchanged(test_env):
    """10. Repository source hashes remain unchanged."""
    workspace = test_env["dir"]
    repo_dir = Path(workspace) / "hash_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    f1 = repo_dir / "a.py"
    f2 = repo_dir / "b.py"
    f1.write_text("def a(): return 1\n", encoding="utf-8")
    f2.write_text("def b(): return 2\n", encoding="utf-8")

    with tool_workspace(workspace):
        res = DirectActionRouter.execute(f"Inspect repository at '{repo_dir}'", workspace=workspace)
        assert res is not None
        assert res.telemetry.get("read_only_verified") is True
        pre = res.telemetry.get("pre_hashes", {})
        post = res.telemetry.get("post_hashes", {})
        assert len(pre) == 2
        assert pre == post


def test_workspace_traversal_rejected(test_env):
    """11. Workspace traversal is rejected."""
    workspace = test_env["dir"]
    with tool_workspace(workspace):
        res = DirectActionRouter.execute("Save 'forbidden' to ../../escape.txt", workspace=workspace)
        assert res is not None
        assert res.success is False
        assert res.policy_decision == "refused"
        assert res.provider == "security-policy"


def test_symlink_escape_rejected(test_env):
    """12. Symlink escape is rejected."""
    workspace = test_env["dir"]
    outside_dir = tempfile.mkdtemp(prefix="outside_ws_")
    outside_file = Path(outside_dir) / "secret.txt"
    outside_file.write_text("outside secret", encoding="utf-8")

    symlink_file = Path(workspace) / "symlink_escape.txt"
    try:
        symlink_file.symlink_to(outside_file)
        with tool_workspace(workspace):
            res = DirectActionRouter.execute(f"Read the file at '{symlink_file}'", workspace=workspace)
            assert res is not None
            assert res.success is False
            assert res.policy_decision == "refused"
    finally:
        shutil.rmtree(outside_dir, ignore_errors=True)
