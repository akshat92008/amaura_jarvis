from __future__ import annotations

import json
import stat
import subprocess
import time
from pathlib import Path

import pytest

from jarvis.amaura.antigravity_bridge import AntigravityDeliveryAdapter
from jarvis.amaura.brain import GoalRequest
from jarvis.amaura.cognition import ExecutiveKernel, ExecutiveRequest
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.gitops import (
    WorktreeRecord,
    cleanup_task_worktree,
    finalize_task_commit,
    prepare_task_worktree,
)
from jarvis.amaura.models import GovernanceError
from jarvis.amaura.verification import SecureVerifierRunner
from jarvis.server import ChatRequest, JarvisGoalRequest, VoiceRequest


@pytest.fixture(autouse=True)
def _stable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("AMAURA_JARVIS_LLM_PLANNER", "0")
    monkeypatch.setenv("AMAURA_JARVIS_INTENT_MODEL", "0")
    monkeypatch.setenv("AMAURA_ANTIGRAVITY_REQUIRE_AUTONOMY_SETTINGS", "0")
    monkeypatch.setenv("AMAURA_ANTIGRAVITY_REQUIRE_MODEL_PROVENANCE", "1")
    monkeypatch.setenv("AMAURA_VERIFIER_MODE", "host")
    monkeypatch.setenv("AMAURA_ALLOW_HOST_VERIFICATION", "1")
    monkeypatch.setenv("AMAURA_RESOURCE_LEDGER", str(tmp_path / "resource-ledger.json"))


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Amaura Test"], cwd=path, check=True)
    (path / "README.md").write_text("# fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=path, check=True)
    return path


def _fake_stream_agy(path: Path, *, sleep_seconds: float = 0.0) -> Path:
    script = path / "agy-v52"
    script.write_text(
        f"""#!/usr/bin/env python3
import json, pathlib, sys, time
if "--version" in sys.argv or (len(sys.argv) > 1 and sys.argv[1] == "version"):
    print("Antigravity CLI v1.1.11"); raise SystemExit(0)
assert "--sandbox" in sys.argv
assert "--new-project" in sys.argv
assert "--project=default-cli-project" not in sys.argv
assert "--add-dir" in sys.argv and pathlib.Path(sys.argv[sys.argv.index("--add-dir")+1]).resolve() == pathlib.Path.cwd().resolve()
added_dirs=[pathlib.Path(sys.argv[i+1]).resolve() for i,v in enumerate(sys.argv[:-1]) if v == "--add-dir"]
git_marker=pathlib.Path.cwd()/".git"
if git_marker.is_file():
    git_dir=pathlib.Path(git_marker.read_text().split(":",1)[1].strip()).resolve()
    assert git_dir.parents[1] in added_dirs
assert "--mode" in sys.argv and sys.argv[sys.argv.index("--mode")+1] == "accept-edits"
assert sys.argv[sys.argv.index("--output-format")+1] == "stream-json"
print(json.dumps({{"type":"assistant","model":"gemini-test"}}), flush=True)
time.sleep({sleep_seconds!r})
repo=pathlib.Path.cwd(); (repo/"agy_fix.py").write_text("VALUE = 52\\n")
result={{"schema":"amaura.antigravity-result.v1","success":True,"summary":"Implemented safely","changed_files":["agy_fix.py"],"verification_commands":["python -m py_compile agy_fix.py"],"remaining_failures":[],"models_used":["gemini-test"],"conversation_id":"agy-v52"}}
print(json.dumps({{"type":"result","result":result}}), flush=True)
""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def test_all_public_founder_coding_defaults_are_antigravity():
    assert ExecutiveRequest(text="Build it").coding_backend == "antigravity"
    assert GoalRequest(objective="Build it").coding_backend == "antigravity"
    assert ChatRequest(message="Build it").coding_backend == "antigravity"
    assert VoiceRequest(text="Build it").coding_backend == "antigravity"
    assert JarvisGoalRequest(objective="Build it").coding_backend == "antigravity"


def test_memory_mutation_requires_operator_authority(tmp_path: Path):
    control = AmauraControlPlane(tmp_path / "amaura.db")
    try:
        kernel = ExecutiveKernel(control)
        denied = kernel.handle(
            ExecutiveRequest(text="Remember that deployments require my approval"),
            allow_missions=False,
            allow_memory_mutation=False,
        )
        assert denied.state == "authorization_required"
        assert not kernel.memory.list(scope="personal")
        allowed = kernel.handle(
            ExecutiveRequest(text="Remember that deployments require my approval"),
            allow_missions=False,
            allow_memory_mutation=True,
        )
        assert allowed.intent == "memory_write"
        assert kernel.memory.list(scope="personal")
    finally:
        control.close()


def test_finalize_commit_disables_repository_git_hooks(tmp_path: Path):
    repo = _git_repo(tmp_path / "repo")
    work = tmp_path / "work"
    subprocess.run(["git", "worktree", "add", "-qb", "amaura-test", str(work)], cwd=repo, check=True)
    marker = tmp_path / "hook-fired"
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    hook = hooks / "pre-commit"
    hook.write_text(f"#!/bin/sh\necho fired > {marker}\n", encoding="utf-8")
    hook.chmod(0o755)
    (work / "README.md").write_text("# changed\n", encoding="utf-8")
    record = WorktreeRecord(
        str(repo),
        str(work),
        "amaura-test",
        "master",
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
    )
    commit = finalize_task_commit(record, task_id="task-v52", title="Safe commit")
    assert commit.commit
    assert not marker.exists(), "Amaura-managed git commit must not execute repository hooks"


def test_antigravity_blocks_workspace_executable_customizations(tmp_path: Path):
    repo = _git_repo(tmp_path / "repo")
    (repo / ".agents").mkdir()
    (repo / ".agents" / "hooks.json").write_text('{"hooks":[]}', encoding="utf-8")
    adapter = AntigravityDeliveryAdapter(command=str(_fake_stream_agy(tmp_path)))
    with pytest.raises(GovernanceError, match="workspace customizations"):
        adapter.run_with_result(repository_path=str(repo), objective="Change it", idempotency_key="x")


def test_antigravity_blocks_project_scoped_unsandboxed_permission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _git_repo(tmp_path / "repo")
    project_settings = tmp_path / "project-permissions.json"
    project_settings.write_text(json.dumps({"permissions": {"allow": ["unsandboxed(git push)"]}}), encoding="utf-8")
    monkeypatch.setenv("AMAURA_ANTIGRAVITY_PROJECT_SETTINGS", str(project_settings))
    adapter = AntigravityDeliveryAdapter(command=str(_fake_stream_agy(tmp_path)))
    with pytest.raises(GovernanceError, match="project-scoped permissions"):
        adapter.run_with_result(repository_path=str(repo), objective="Change it", idempotency_key="x")


def test_antigravity_pause_terminates_running_process_tree(tmp_path: Path):
    repo = _git_repo(tmp_path / "repo")
    adapter = AntigravityDeliveryAdapter(command=str(_fake_stream_agy(tmp_path, sleep_seconds=10.0)))
    started = time.monotonic()
    with pytest.raises(GovernanceError, match="process tree terminated"):
        adapter.run_with_result(
            repository_path=str(repo),
            objective="Long task",
            idempotency_key="cancel",
            should_cancel=lambda: time.monotonic() - started > 0.5,
            timeout_seconds=60,
        )
    assert time.monotonic() - started < 5.0
    assert not (repo / "agy_fix.py").exists()


def test_antigravity_exposes_only_linked_worktree_git_metadata(tmp_path: Path):
    repo = _git_repo(tmp_path / "repo-linked")
    worktree = tmp_path / "linked-worktree"
    subprocess.run(
        ["git", "worktree", "add", "-qb", "amaura-linked-test", str(worktree)],
        cwd=repo,
        check=True,
    )
    agy = _fake_stream_agy(tmp_path)
    result = AntigravityDeliveryAdapter(command=str(agy), receipt_key="a" * 32).run_with_result(
        repository_path=str(worktree),
        objective="Implement fixture in linked worktree",
        idempotency_key="linked-worktree",
    )
    common_dir = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=worktree,
            text=True,
        ).strip()
    ).resolve()
    assert result.verification["changed_files"] == ["agy_fix.py"]
    assert common_dir == (repo / ".git").resolve()


def test_antigravity_changed_files_preserves_first_porcelain_filename(tmp_path: Path):
    repo = _git_repo(tmp_path / "repo-porcelain")
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    (repo / "README.md").write_text("# changed\n", encoding="utf-8")
    assert AntigravityDeliveryAdapter._changed_files(repo, base) == ["README.md"]


def test_independent_verifier_uses_headless_sdl_environment(tmp_path: Path):
    environment = SecureVerifierRunner._clean_environment(str(tmp_path))
    assert environment["SDL_VIDEODRIVER"] == "dummy"
    assert environment["SDL_AUDIODRIVER"] == "dummy"
    assert environment["SDL_RENDER_DRIVER"] == "software"


def test_independent_verifier_can_fallback_after_macos_sandbox_abort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = _git_repo(tmp_path / "repo-verifier-fallback")
    calls: list[list[str]] = []

    monkeypatch.setenv("AMAURA_VERIFIER_MODE", "native")
    monkeypatch.setenv("AMAURA_VERIFIER_HOST_FALLBACK_ON_SANDBOX_ABORT", "1")
    monkeypatch.setenv("AMAURA_ALLOW_HOST_VERIFICATION", "1")
    monkeypatch.setattr("jarvis.amaura.verification.platform.system", lambda: "Darwin")
    monkeypatch.setattr("jarvis.amaura.verification.shutil.which", lambda name: f"/usr/bin/{name}")

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        if argv[0] == "sandbox-exec":
            return subprocess.CompletedProcess(argv, -6, "", "")
        return subprocess.CompletedProcess(argv, 0, "ok\n", "")

    monkeypatch.setattr("jarvis.amaura.verification.subprocess.run", fake_run)
    result = SecureVerifierRunner().run(repo, "pytest", timeout_seconds=30)
    assert result.passed
    assert result.isolation == "host-breakglass-after-macos-sandbox-abort"
    assert result.network_disabled is False
    assert len(calls) == 2
    assert calls[0][0] == "sandbox-exec"
    assert calls[1] == ["pytest"]


def test_space_path_repository_uses_isolated_clone_and_imports_verified_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo = _git_repo(tmp_path / "repo with spaces")
    monkeypatch.setenv("AMAURA_WORKTREE_ROOT", str(tmp_path / "amaura-worktrees"))
    record = prepare_task_worktree(repo, "task-space-path")
    worktree = Path(record.worktree_path)
    assert record.isolation_mode == "isolated_clone"
    assert (worktree / ".git").is_dir()
    (worktree / "feature.txt").write_text("verified\n", encoding="utf-8")
    commit = finalize_task_commit(record, task_id="task-space-path", title="Space-safe fixture")
    imported = subprocess.check_output(
        ["git", "rev-parse", record.branch],
        cwd=repo,
        text=True,
    ).strip()
    assert imported == commit.commit
    cleanup_task_worktree(
        {
            "id": "task-space-path",
            "metadata": {
                "git_repository_root": str(repo),
                "git_worktree_path": str(worktree),
                "git_branch": record.branch,
                "git_isolation_mode": record.isolation_mode,
            },
        },
        require_clean=False,
    )
    assert not worktree.exists()


def test_desktop_primary_backend_is_antigravity():
    html = (Path(__file__).parents[1] / "desktop-app" / "renderer" / "hud.html").read_text(encoding="utf-8")
    assert '<option value="antigravity" selected>Antigravity CLI (primary)</option>' in html
    assert "Auto (Noryx if available)" not in html


def test_autonomous_git_rejects_executable_local_filters(tmp_path: Path):
    repo = _git_repo(tmp_path / "repo-filter")
    marker = tmp_path / "filter-fired"
    # A Git clean/smudge/process filter is executable code even when hooks are
    # disabled. Autonomous Amaura operations must fail before `git add` can run it.
    subprocess.run(
        ["git", "config", "--local", "filter.evil.clean", f"sh -c 'echo fired > {marker}; cat'"],
        cwd=repo,
        check=True,
    )
    work = tmp_path / "work-filter"
    subprocess.run(["git", "worktree", "add", "-qb", "amaura-filter-test", str(work)], cwd=repo, check=True)
    (work / "README.md").write_text("# changed\n", encoding="utf-8")
    record = WorktreeRecord(
        str(repo),
        str(work),
        "amaura-filter-test",
        "master",
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
    )
    with pytest.raises(GovernanceError, match="executable mechanisms"):
        finalize_task_commit(record, task_id="task-filter", title="Unsafe filter")
    assert not marker.exists(), "Amaura must reject executable Git filters before they can run"
