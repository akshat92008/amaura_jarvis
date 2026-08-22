"""Comprehensive Intent Routing and Dispatch Test Suite.

Tests generic intent understanding, argument/path extraction, capability selection,
governance policy enforcement, and truthful execution across >20 natural language
paraphrases per capability and adversarial ambiguity test cases.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

from jarvis.amaura.brain import GoalRequest
from jarvis.amaura.cognition import ExecutiveKernel, ExecutiveRequest, IntentEngine
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.direct_action import DirectActionRouter
from jarvis.amaura.store import CompanyStore
from jarvis.tools.security import tool_workspace
from jarvis.user_memory import UserMemory


@pytest.fixture
def routing_env():
    temp_dir = tempfile.mkdtemp(prefix="arch_routing_test_")
    ws = Path(temp_dir).resolve()
    db_path = str(ws / "routing_test_store.db")
    store = CompanyStore(db_path=db_path)
    control = AmauraControlPlane(db_path=db_path)
    yield {"dir": str(ws), "store": store, "control": control}
    shutil.rmtree(temp_dir, ignore_errors=True)


# ── 1. Filesystem Read Paraphrases (>20 variations) ───────────────────────────

READ_PARAPHRASES = [
    "Read the file at '{path}'",
    "Please read '{path}'",
    "Open and display contents of '{path}'",
    "What is inside '{path}'?",
    "Show me the text inside '{path}'",
    "Cat '{path}'",
    "Load the text from '{path}'",
    "Fetch the file contents from '{path}'",
    "Display the file at '{path}'",
    "View file '{path}'",
    "Can you read the file located at '{path}'?",
    "Print out the content of '{path}'",
    "Open '{path}' and show me what's written there",
    "Examine contents of '{path}'",
    "Read from input file '{path}'",
    "Get text from '{path}'",
    "Read contents of file '{path}'",
    "Please display what is stored in '{path}'",
    "Inspect the contents of '{path}'",
    "Retrieve the content from '{path}'",
    "What does '{path}' contain?",
    "Show content of '{path}'",
]


@pytest.mark.parametrize("template", READ_PARAPHRASES)
def test_filesystem_read_paraphrases(routing_env, template):
    ws = Path(routing_env["dir"])
    fname = f"sample_{uuid.uuid4().hex[:6]}.txt"
    content = f"sample_payload_{uuid.uuid4().hex}"
    fpath = ws / fname
    fpath.write_text(content, encoding="utf-8")

    prompt = template.format(path=str(fpath))
    with tool_workspace(ws):
        res = DirectActionRouter.execute(prompt, workspace=str(ws))
        assert res is not None, f"Failed to route prompt: {prompt}"
        assert res.success is True, f"Failed execution for prompt: {prompt} -> {res.output}"
        assert res.execution_type == "tool"
        assert res.tool_name == "read_file"
        assert res.provider == "local-filesystem"
        assert content in res.output


# ── 2. Filesystem Write Paraphrases (>20 variations) ──────────────────────────

WRITE_PARAPHRASES = [
    ("Save '{content}' to '{path}'", True),
    ("Write '{content}' into '{path}'", True),
    ("Create a file at '{path}' containing '{content}'", True),
    ("Put '{content}' in '{path}'", True),
    ("Store '{content}' at file '{path}'", True),
    ("Please write the text '{content}' to '{path}'", True),
    ("Save the text '{content}' into '{path}'", True),
    ("Output '{content}' to '{path}'", True),
    ("Create file '{path}' with content '{content}'", True),
    ("Write data '{content}' to '{path}'", True),
    ("Save content '{content}' at '{path}'", True),
    ("Please save '{content}' to file '{path}'", True),
    ("Write '{content}' to destination '{path}'", True),
    ("Put the following in '{path}': '{content}'", True),
    ("Record '{content}' into '{path}'", True),
    ("Dump '{content}' to '{path}'", True),
    ("Create a new file '{path}' with text '{content}'", True),
    ("Store the payload '{content}' in file '{path}'", True),
    ("Write out '{content}' at '{path}'", True),
    ("Please create '{path}' containing '{content}'", True),
    ("Write to '{path}' with data '{content}'", True),
]


@pytest.mark.parametrize("template, is_valid", WRITE_PARAPHRASES)
def test_filesystem_write_paraphrases(routing_env, template, is_valid):
    ws = Path(routing_env["dir"])
    fname = f"write_{uuid.uuid4().hex[:6]}.txt"
    content = f"write_payload_{uuid.uuid4().hex}"
    fpath = ws / fname

    prompt = template.format(content=content, path=str(fpath))
    with tool_workspace(ws):
        res = DirectActionRouter.execute(prompt, workspace=str(ws))
        assert res is not None, f"Failed to route write prompt: {prompt}"
        assert res.success is True, f"Failed write execution: {res.output}"
        assert res.execution_type == "tool"
        assert res.tool_name == "write_file"
        assert fpath.exists()
        assert fpath.read_text(encoding="utf-8") == content


# ── 3. Directory List Paraphrases (>20 variations) ────────────────────────────

LIST_PARAPHRASES = [
    "List files in '{path}'",
    "List directory '{path}'",
    "List folder '{path}'",
    "What files are in '{path}'?",
    "Show files in '{path}'",
    "Show entries in '{path}'",
    "Give filenames from '{path}'",
    "Show the contents of '{path}'",
    "List the contents of folder '{path}'",
    "What is inside directory '{path}'?",
    "Show me what files exist under '{path}'",
    "Display entries inside '{path}'",
    "List directory contents for '{path}'",
    "Please list all files in '{path}'",
    "What files exist in '{path}'?",
    "List items under directory '{path}'",
    "Show files located in '{path}'",
    "What entries are inside folder '{path}'?",
    "List files under '{path}'",
    "List directory at '{path}'",
    "Show directory contents of '{path}'",
]


@pytest.mark.parametrize("template", LIST_PARAPHRASES)
def test_directory_list_paraphrases(routing_env, template):
    ws = Path(routing_env["dir"])
    sub_dir = ws / f"subdir_{uuid.uuid4().hex[:6]}"
    sub_dir.mkdir(parents=True, exist_ok=True)
    f1 = sub_dir / "alpha.txt"
    f2 = sub_dir / "beta.json"
    f1.write_text("a", encoding="utf-8")
    f2.write_text("{}", encoding="utf-8")

    prompt = template.format(path=str(sub_dir))
    with tool_workspace(ws):
        res = DirectActionRouter.execute(prompt, workspace=str(ws))
        assert res is not None, f"Failed to route list prompt: {prompt}"
        assert res.success is True, f"Failed list execution: {res.output}"
        assert res.execution_type == "tool"
        assert res.tool_name == "list_directory"
        assert "alpha.txt" in res.output or "beta.json" in res.output


# ── 4. Memory Recall Paraphrases (>20 variations) ─────────────────────────────

MEMORY_RECALL_PARAPHRASES = [
    ("Remember that the deploy cluster is {val}", "What is the deploy cluster?"),
    ("Remember that primary supplier is {val}", "Who is the primary supplier?"),
    ("Remember that secret codename is {val}", "What is the secret codename?"),
    ("Remember that production database host is {val}", "What is the production database host?"),
    ("Remember that launch venue is {val}", "Where is the launch venue?"),
    ("Remember that brand color is {val}", "What is the brand color?"),
    ("Remember that API timeout seconds is {val}", "What is the API timeout seconds?"),
    ("Remember that test framework choice is {val}", "Which test framework choice was made?"),
    ("Remember that security lead contact is {val}", "Who is the security lead contact?"),
    ("Remember that staging port is {val}", "What is the staging port?"),
    ("Remember that backup interval is {val}", "What is the backup interval?"),
    ("Remember that release version target is {val}", "What is the release version target?"),
    ("Remember that gateway URL is {val}", "What is the gateway URL?"),
    ("Remember that default locale is {val}", "What is the default locale?"),
    ("Remember that audit log path is {val}", "What is the audit log path?"),
    ("Remember that encryption cipher is {val}", "What is the encryption cipher?"),
    ("Remember that maximum retry count is {val}", "What is the maximum retry count?"),
    ("Remember that lead engineer name is {val}", "Who is the lead engineer name?"),
    ("Remember that cache expiration policy is {val}", "What is the cache expiration policy?"),
    ("Remember that notification channel is {val}", "What is the notification channel?"),
    ("Remember that fallback server address is {val}", "What is the fallback server address?"),
]


@pytest.mark.parametrize("store_tpl, query_tpl", MEMORY_RECALL_PARAPHRASES)
def test_memory_recall_paraphrases(routing_env, store_tpl, query_tpl):
    unique_val = f"val_{uuid.uuid4().hex[:8]}"
    store_prompt = store_tpl.format(val=unique_val)
    query_prompt = query_tpl

    kernel = ExecutiveKernel(routing_env["control"])

    # Store memory via ExecutiveKernel (intent: memory_write)
    store_res = kernel.handle(ExecutiveRequest(text=store_prompt, session_id="test_routing_session"))
    assert store_res is not None
    assert store_res.intent == "memory_write"

    # Recall memory via DirectActionRouter with control plane
    recall_res = DirectActionRouter.execute(query_prompt, control=routing_env["control"])
    assert recall_res is not None, f"Failed recall for prompt: {query_prompt}"
    assert recall_res.success is True, f"Failed memory recall: {recall_res.output}"
    assert recall_res.execution_type == "memory_retrieval"
    assert unique_val in recall_res.output
    assert "candidate_scores" in recall_res.telemetry
    assert "memory_query" in recall_res.telemetry


def test_memory_recall_includes_founder_cli_personal_facts(routing_env, monkeypatch, tmp_path):
    """A fresh CLI ``remember`` fact must win over unrelated operational memory."""
    import jarvis.user_memory as user_memory_module

    monkeypatch.setattr(user_memory_module, "PREFS_FILE", tmp_path / "personal.json")
    codename = f"final-verify-{uuid.uuid4().hex}"
    UserMemory().add_fact(f"my final verification codename is {codename}")

    # This reproduces the prior failure mode: an unrelated, newer operational
    # transcript repeats the recall question and would otherwise outrank the
    # founder fact through lexical overlap alone.
    ExecutiveKernel(routing_env["control"]).memory.remember(
        key="unrelated_operational_record",
        value=(
            "User: What is my final verification codename? "
            "Assistant: unrelated historical task summary."
        ),
        scope="episodic",
        actor="jarvis",
    )

    result = DirectActionRouter.execute(
        "What is my final verification codename?", control=routing_env["control"]
    )

    assert result is not None
    assert result.success is True
    assert result.execution_type == "memory_retrieval"
    assert codename in result.output
    assert any("legacy_user_memory" in item for item in result.telemetry["candidate_ids"])


# ── 5. Repository Inspection Paraphrases (>20 variations) ──────────────────────

REPO_PARAPHRASES = [
    "Inspect repository at '{path}'",
    "Analyze repo at '{path}'",
    "Review code in repository '{path}'",
    "Check repo at '{path}'",
    "Diagnose project at '{path}'",
    "Inspect codebase at '{path}'",
    "Analyze repository '{path}'",
    "Find bug in repository at '{path}'",
    "Audit codebase located at '{path}'",
    "Review repo at '{path}'",
    "Inspect the code repository at '{path}'",
    "Check project repository at '{path}'",
    "Analyze codebase at '{path}'",
    "Inspect python repository at '{path}'",
    "Examine repo at '{path}'",
    "Review project code in '{path}'",
    "Perform code audit on repo '{path}'",
    "Inspect code in '{path}'",
    "Diagnose repo at '{path}'",
    "Analyze project repository at '{path}'",
    "Check the repo located at '{path}'",
]


@pytest.mark.parametrize("template", REPO_PARAPHRASES)
def test_repository_inspection_paraphrases(routing_env, template):
    ws = Path(routing_env["dir"])
    repo_dir = ws / f"repo_{uuid.uuid4().hex[:6]}"
    repo_dir.mkdir(parents=True, exist_ok=True)
    calc_py = repo_dir / "calc.py"
    calc_py.write_text(
        'def compute_total(a, b):\n    """Add two numbers."""\n    return a - b\n',
        encoding="utf-8",
    )

    prompt = template.format(path=str(repo_dir))
    with tool_workspace(ws):
        res = DirectActionRouter.execute(prompt, workspace=str(ws))
        assert res is not None, f"Failed to route repo prompt: {prompt}"
        assert res.success is True, f"Failed repo execution: {res.output}"
        assert res.execution_type == "internal_analysis"
        assert res.tool_name == "internal_ast_inspector"
        assert res.provider == "deterministic-ast"
        assert "compute_total" in res.output
        assert res.telemetry.get("read_only_verified") is True


# ── 6. Adversarial Ambiguity & Boundary Routing ───────────────────────────────


def test_adversarial_macos_app_vs_filesystem(routing_env):
    """Verify macOS app verbs don't capture filesystem requests."""
    engine = IntentEngine()

    # Desktop app commands -> macos_app
    assert engine.classify("open Safari") == "macos_app"
    assert engine.classify("quit Finder") == "macos_app"
    assert engine.classify("launch Spotify") == "macos_app"
    assert engine.classify("please close Terminal") == "macos_app"
    assert engine.classify("show Notes") == "macos_app"

    # Filesystem commands -> NOT macos_app
    assert engine.classify("open /tmp/report.txt") != "macos_app"
    assert engine.classify("open file data.json") != "macos_app"
    assert engine.classify("show files in /workspace/data") != "macos_app"
    assert engine.classify("show contents of /tmp/doc.md") != "macos_app"
    assert engine.classify("open the project at /workspace/repo") != "macos_app"
    assert engine.classify("show folder 'test_dir'") != "macos_app"


def test_adversarial_memory_write_vs_recall():
    """Verify distinct routing between memory store and recall."""
    engine = IntentEngine()

    assert engine.classify("Remember that server is 10.0.0.1") == "memory_write"
    assert engine.classify("Please remember: token is secret_123") == "memory_write"
    assert engine.classify("Forget about the staging password") == "memory_forget"

    assert engine.classify("What did I say about the server?") == "conversation"
    assert engine.classify("What is the token?") == "conversation"


def test_out_of_workspace_policy_refusal_truthful(routing_env):
    """Verify that requests targeting paths outside workspace yield truthful policy refusals."""
    ws = Path(routing_env["dir"])
    outside_path = "/etc/passwd"

    with tool_workspace(ws):
        # Read outside workspace
        res_read = DirectActionRouter.execute(f"Read file at '{outside_path}'", workspace=str(ws))
        assert res_read is not None
        assert res_read.success is False
        assert res_read.execution_type == "policy_enforcement"
        assert res_read.policy_decision == "refused"
        assert res_read.telemetry.get("reason") == "workspace_escape"

        # Write outside workspace
        res_write = DirectActionRouter.execute(f"Save 'malicious' to '{outside_path}'", workspace=str(ws))
        assert res_write is not None
        assert res_write.success is False
        assert res_write.execution_type == "policy_enforcement"
        assert res_write.policy_decision == "refused"
        assert res_write.telemetry.get("reason") == "workspace_escape"

        # List outside workspace
        res_list = DirectActionRouter.execute("List files in '/etc'", workspace=str(ws))
        assert res_list is not None
        assert res_list.success is False
        assert res_list.execution_type == "policy_enforcement"
        assert res_list.policy_decision == "refused"
        assert res_list.telemetry.get("reason") == "workspace_escape"


# ── 7. Multi-Step Workflow Composition ────────────────────────────────────────


def test_workflow_single_input_json_transform(routing_env):
    """Multi-step workflow: read key-value text file, extract JSON, save and verify."""
    ws = Path(routing_env["dir"])
    in_file = ws / "stats.txt"
    in_file.write_text("users: 1500\nactive: 420\nregion: eu-west\n", encoding="utf-8")
    out_file = ws / "stats.json"

    prompt = f"Read input file at '{in_file}', extract data, and save json file to '{out_file}'"
    with tool_workspace(ws):
        res = DirectActionRouter.execute(prompt, workspace=str(ws))
        assert res is not None
        assert res.success is True
        assert res.execution_type == "workflow"
        assert res.tool_name == "multi_step_workflow"
        assert res.telemetry.get("verification_passed") is True
        assert out_file.exists()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data.get("users") == 1500
        assert data.get("active") == 420
        assert data.get("region") == "eu-west"


def test_workflow_two_input_numeric_aggregate(routing_env):
    """Multi-step workflow: read two input files, sum numbers, write result."""
    ws = Path(routing_env["dir"])
    f1 = ws / "sales_a.txt"
    f2 = ws / "sales_b.txt"
    f1.write_text("100\n200\n300\n", encoding="utf-8")
    f2.write_text("400\n500\n", encoding="utf-8")
    out_file = ws / "total_sales.txt"

    prompt = f"Read from '{f1}' and '{f2}', sum the numbers, and write total to '{out_file}'"
    with tool_workspace(ws):
        res = DirectActionRouter.execute(prompt, workspace=str(ws))
        assert res is not None
        assert res.success is True
        assert res.execution_type == "workflow"
        assert res.tool_name == "multi_step_workflow"
        assert res.telemetry.get("verification_passed") is True
        assert out_file.exists()
        assert "1500" in out_file.read_text(encoding="utf-8")


def test_workspace_propagation_to_goal_request(routing_env):
    """Verify repository path in prompt auto-populates GoalRequest workspace."""
    ws = Path(routing_env["dir"])
    repo_dir = ws / "my_project"
    repo_dir.mkdir(parents=True, exist_ok=True)

    kernel = ExecutiveKernel(routing_env["control"])

    req = GoalRequest(
        objective=f"Inspect repository at '{repo_dir}' and run test suite",
        workspace="",
    )

    plan = kernel.brain.compiler.compile(req)
    assert plan.workspace == str(repo_dir)


# ── 8. Phase 3.1 Routing Contradiction & Actionable Guard Regressions ─────────


def test_macos_app_collision_file_read_rerouted(routing_env):
    """1. Initial classification = macos_app but path clearly identifies a file -> filesystem executes, conversation NOT called."""
    ws = Path(routing_env["dir"])
    fname = f"report_{uuid.uuid4().hex[:8]}.txt"
    payload = f"secret_content_{uuid.uuid4().hex}"
    fpath = ws / fname
    fpath.write_text(payload, encoding="utf-8")

    def _failing_conversation(*args, **kwargs):
        pytest.fail("Conversation fallback must not be called for actionable filesystem requests")

    kernel = ExecutiveKernel(routing_env["control"], conversation_handler=_failing_conversation)

    req = ExecutiveRequest(
        text=f"open {fpath}",
        session_id="test_collision_session",
        workspace=str(ws),
        force_intent="macos_app",
    )

    with tool_workspace(ws):
        response = kernel.handle(req)

    assert response is not None
    assert response.state == "completed"
    assert payload in response.message
    assert response.result.get("execution_type") == "tool"
    assert response.result.get("tool_name") == "read_file"
    assert response.result.get("provider") == "local-filesystem"


def test_macos_app_collision_repo_rerouted(routing_env):
    """2. Initial classification = macos_app but path identifies repository -> repository dispatch, conversation NOT called."""
    ws = Path(routing_env["dir"])
    repo_dir = ws / f"project_{uuid.uuid4().hex[:6]}"
    repo_dir.mkdir(parents=True, exist_ok=True)
    (repo_dir / "mod.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

    def _failing_conversation(*args, **kwargs):
        pytest.fail("Conversation fallback must not be called for repository inspection")

    kernel = ExecutiveKernel(routing_env["control"], conversation_handler=_failing_conversation)

    req = ExecutiveRequest(
        text=f"Inspect repository at '{repo_dir}'",
        session_id="test_repo_collision",
        workspace=str(ws),
        force_intent="macos_app",
    )

    with tool_workspace(ws):
        response = kernel.handle(req)

    assert response is not None
    assert response.state == "completed"
    assert response.result.get("execution_type") == "internal_analysis"
    assert response.result.get("tool_name") == "internal_ast_inspector"
    assert "add" in response.message


def test_macos_app_actual_app_unchanged(routing_env, monkeypatch):
    """3. Actual app request -> macos_app remains unchanged."""
    import jarvis.amaura.capability_runtime

    executed_app = ""

    def mock_execute(self, capability, operation, params=None):
        nonlocal executed_app
        assert capability == "macos_app"
        executed_app = (params or {}).get("name", "")
        return {"ok": True, "output": {"app": executed_app}}

    monkeypatch.setattr(jarvis.amaura.capability_runtime.CapabilityRuntime, "execute", mock_execute)

    kernel = ExecutiveKernel(routing_env["control"])
    req = ExecutiveRequest(text="open Safari", session_id="test_app_control")
    response = kernel.handle(req)

    assert response.intent == "macos_app"
    assert response.state == "completed"
    assert "Successfully opened Safari" in response.message
    assert executed_app == "Safari"


def test_conversational_open_without_file_or_app(routing_env):
    """4. Conversational use of word 'open' without filesystem/app evidence -> conversation, no privileged tools."""
    called_conversation = False

    def _mock_conversation(text, context=""):
        nonlocal called_conversation
        called_conversation = True
        return "Let's discuss roadmaps and pricing strategy."

    kernel = ExecutiveKernel(routing_env["control"], conversation_handler=_mock_conversation)

    req = ExecutiveRequest(text="Can we open a discussion on pricing?", session_id="test_conv_open")
    response = kernel.handle(req)

    assert response.intent == "conversation"
    assert called_conversation is True
    assert "roadmaps and pricing strategy" in response.message


def test_macos_app_policy_violation_refusal(routing_env):
    """5. Filesystem policy violation -> security-policy refusal, NOT conversation fallback."""
    ws = Path(routing_env["dir"])
    outside_target = "/etc/shadow_unauthorized"

    def _failing_conversation(*args, **kwargs):
        pytest.fail("Conversation fallback must not be called for policy violations")

    kernel = ExecutiveKernel(routing_env["control"], conversation_handler=_failing_conversation)

    req = ExecutiveRequest(
        text=f"open {outside_target}",
        session_id="test_policy_violation",
        workspace=str(ws),
        force_intent="macos_app",
    )

    with tool_workspace(ws):
        response = kernel.handle(req)

    assert response is not None
    assert response.state == "refused"
    assert response.result.get("policy_decision") == "refused"
    assert response.result.get("provider") == "security-policy"
