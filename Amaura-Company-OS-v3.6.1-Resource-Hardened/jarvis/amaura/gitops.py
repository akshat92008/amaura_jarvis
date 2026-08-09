"""Fail-closed Git worktree and merge operations for Amaura engineering tasks."""

from __future__ import annotations

import contextlib
import os
import shlex
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence

from jarvis.amaura.models import GovernanceError

_SOFTWARE_ACTIONS = {"software_delivery", "engineering", "repository_write"}
_SAFE_VALIDATION_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("python", "-m", "pytest"),
    ("python3", "-m", "pytest"),
    ("pytest",),
    ("python", "-m", "ruff"),
    ("python3", "-m", "ruff"),
    ("ruff",),
    ("python", "-m", "mypy"),
    ("python3", "-m", "mypy"),
    ("mypy",),
    ("npm", "test"),
    ("npm", "run", "test"),
    ("npm", "run", "build"),
    ("npm", "run", "lint"),
    ("pnpm", "test"),
    ("pnpm", "build"),
    ("pnpm", "lint"),
    ("cargo", "test"),
    ("cargo", "check"),
    ("go", "test"),
)


@dataclass(frozen=True, slots=True)
class WorktreeRecord:
    repository_root: str
    worktree_path: str
    branch: str
    base_branch: str
    base_commit: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CommitRecord:
    commit: str
    base_commit: str
    branch: str
    diff: str
    changed_files: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "commit": self.commit,
            "base_commit": self.base_commit,
            "branch": self.branch,
            "diff": self.diff,
            "changed_files": list(self.changed_files),
        }


@dataclass(frozen=True, slots=True)
class MergeRecord:
    repository_root: str
    branch: str
    previous_head: str
    merged_head: str
    validation_command: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def is_software_task(task: dict[str, Any]) -> bool:
    return str(task.get("action_type", "")) in _SOFTWARE_ACTIONS


def _run_git(
    repository: str | Path,
    args: Sequence[str],
    *,
    timeout: int = 60,
    allow_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(repository),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GovernanceError(f"Git command failed to execute: git {' '.join(args)}") from exc
    if completed.returncode != 0 and not allow_failure:
        detail = (completed.stderr or completed.stdout or "unknown git error").strip()
        raise GovernanceError(f"Git command failed: git {' '.join(args)}\n{detail}")
    return completed


def _repository_root(workspace: str | Path) -> Path:
    root = _run_git(workspace, ["rev-parse", "--show-toplevel"]).stdout.strip()
    if not root:
        raise GovernanceError("Assigned engineering workspace is not a Git repository")
    return Path(root).resolve()



def is_git_repository(workspace: str | Path) -> bool:
    try:
        _repository_root(workspace)
    except GovernanceError:
        return False
    return True


def _branch_name(task_id: str) -> str:
    safe = "".join(character if character.isalnum() or character in "-_" else "-" for character in task_id)
    return f"amaura-{safe[:80]}"


def _worktree_root() -> Path:
    return Path(os.environ.get("AMAURA_WORKTREE_ROOT", "/tmp/amaura-worktrees")).expanduser().resolve()


def prepare_task_worktree(workspace: str | Path, task_id: str) -> WorktreeRecord:
    """Create one isolated branch from an exact clean repository head."""
    repository = _repository_root(workspace)
    status = _run_git(repository, ["status", "--porcelain"]).stdout.strip()
    if status:
        raise GovernanceError(
            "Engineering workspace is dirty. Commit or stash local changes before Amaura starts a repository task."
        )
    base_branch = _run_git(repository, ["symbolic-ref", "--quiet", "--short", "HEAD"]).stdout.strip()
    if not base_branch:
        raise GovernanceError("Amaura repository tasks require a named base branch; detached HEAD is not allowed")
    base_commit = _run_git(repository, ["rev-parse", "HEAD"]).stdout.strip()
    branch = _branch_name(task_id)
    worktree_path = _worktree_root() / task_id
    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    if worktree_path.exists():
        existing_root = _run_git(worktree_path, ["rev-parse", "--show-toplevel"]).stdout.strip()
        existing_branch = _run_git(worktree_path, ["symbolic-ref", "--quiet", "--short", "HEAD"]).stdout.strip()
        if Path(existing_root).resolve() != worktree_path.resolve() or existing_branch != branch:
            raise GovernanceError(f"Unexpected worktree already exists at {worktree_path}")
        return WorktreeRecord(str(repository), str(worktree_path), branch, base_branch, base_commit)

    existing_branch = _run_git(repository, ["show-ref", "--verify", f"refs/heads/{branch}"], allow_failure=True)
    if existing_branch.returncode == 0:
        raise GovernanceError(
            f"Task branch '{branch}' already exists without its expected worktree. Reconcile or remove it before retrying."
        )
    _run_git(repository, ["worktree", "add", "-b", branch, str(worktree_path), base_commit], timeout=120)
    return WorktreeRecord(str(repository), str(worktree_path), branch, base_branch, base_commit)


def finalize_task_commit(
    record: WorktreeRecord,
    *,
    task_id: str,
    title: str,
) -> CommitRecord:
    """Commit all task changes and produce a base-relative immutable diff."""
    worktree = Path(record.worktree_path)
    _run_git(worktree, ["add", "-A"])
    changed = _run_git(worktree, ["diff", "--cached", "--name-only"]).stdout.splitlines()
    if changed:
        commit_message = f"feat(amaura): {title.strip()[:100] or 'repository update'} [{task_id}]"
        _run_git(
            worktree,
            [
                "-c",
                f"user.name={os.environ.get('AMAURA_GIT_AUTHOR_NAME', 'Amaura Agent')}",
                "-c",
                f"user.email={os.environ.get('AMAURA_GIT_AUTHOR_EMAIL', 'amaura@local.invalid')}",
                "commit",
                "-m",
                commit_message,
            ],
            timeout=120,
        )
    commit = _run_git(worktree, ["rev-parse", "HEAD"]).stdout.strip()
    if commit == record.base_commit:
        raise GovernanceError("Engineering task produced no repository change; completion is blocked")
    diff = _run_git(worktree, ["diff", "--binary", f"{record.base_commit}..{commit}"], timeout=120).stdout
    changed_files = tuple(
        line.strip()
        for line in _run_git(worktree, ["diff", "--name-only", f"{record.base_commit}..{commit}"]).stdout.splitlines()
        if line.strip()
    )
    if not changed_files or not diff.strip():
        raise GovernanceError("Engineering task commit contains no verifiable diff")
    return CommitRecord(commit, record.base_commit, record.branch, diff, changed_files)


def _common_git_dir(repository: Path) -> Path:
    raw = _run_git(repository, ["rev-parse", "--git-common-dir"]).stdout.strip()
    path = Path(raw)
    if not path.is_absolute():
        path = repository / path
    return path.resolve()


@contextlib.contextmanager
def repository_lock(repository: str | Path, *, timeout_seconds: int = 30) -> Iterator[None]:
    """Serialize merges for one repository across local worker processes."""
    try:
        import fcntl
    except ImportError as exc:  # pragma: no cover - Amaura targets macOS/Linux
        raise GovernanceError("Repository locking requires a POSIX runtime") from exc
    root = _repository_root(repository)
    lock_path = _common_git_dir(root) / "amaura-merge.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        deadline = time.monotonic() + max(1, timeout_seconds)
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise GovernanceError("Timed out waiting for the repository merge lock")
                time.sleep(0.1)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _validation_tokens(command: str) -> list[str]:
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        raise GovernanceError("Invalid post-merge validation command") from exc
    if not tokens:
        return []
    if not any(tuple(tokens[: len(prefix)]) == prefix for prefix in _SAFE_VALIDATION_PREFIXES):
        raise GovernanceError("Post-merge validation command is not in the safe command allowlist")
    return tokens


def _run_validation(repository: Path, command: str) -> None:
    tokens = _validation_tokens(command)
    if not tokens:
        return
    try:
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        existing_pytest_options = environment.get("PYTEST_ADDOPTS", "").strip()
        if "pytest" in tokens:
            environment["PYTEST_ADDOPTS"] = (
                f"{existing_pytest_options} -p no:cacheprovider".strip()
            )
        completed = subprocess.run(
            tokens,
            cwd=repository,
            capture_output=True,
            text=True,
            env=environment,
            timeout=max(30, int(os.environ.get("AMAURA_POST_MERGE_TIMEOUT", "600"))),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GovernanceError(f"Post-merge validation could not run: {command}") from exc
    if completed.returncode != 0:
        output = (completed.stdout + "\n" + completed.stderr).strip()
        raise GovernanceError(f"Post-merge validation failed: {command}\n{output[-4000:]}")


def merge_approved_task(task: dict[str, Any], *, cleanup: bool = True) -> MergeRecord:
    """Merge the exact reviewed commit into the exact recorded base head, then validate."""
    metadata = dict(task.get("metadata") or {})
    repository = Path(str(metadata.get("git_repository_root") or metadata.get("workspace") or "")).expanduser().resolve()
    branch = str(metadata.get("git_branch", ""))
    base_branch = str(metadata.get("git_base_branch", ""))
    base_commit = str(metadata.get("git_base_commit", ""))
    approved_commit = str(metadata.get("git_commit", ""))
    worktree_path = str(metadata.get("git_worktree_path", ""))
    if not all((repository, branch, base_branch, base_commit, approved_commit, worktree_path)):
        raise GovernanceError("Engineering task is missing immutable Git execution metadata")

    validation_command = str(
        metadata.get("post_merge_validation")
        or os.environ.get("AMAURA_POST_MERGE_COMMAND", "")
    ).strip()
    with repository_lock(repository):
        status = _run_git(repository, ["status", "--porcelain"]).stdout.strip()
        if status:
            raise GovernanceError("Target repository changed locally; automatic merge is blocked")
        current_branch = _run_git(repository, ["symbolic-ref", "--quiet", "--short", "HEAD"]).stdout.strip()
        if current_branch != base_branch:
            raise GovernanceError(
                f"Target branch changed from '{base_branch}' to '{current_branch}'; automatic merge is blocked"
            )
        current_head = _run_git(repository, ["rev-parse", "HEAD"]).stdout.strip()
        if current_head != base_commit:
            raise GovernanceError(
                "Target repository advanced after task creation. Rebase and re-review the task before merging."
            )
        branch_head = _run_git(repository, ["rev-parse", branch]).stdout.strip()
        if branch_head != approved_commit:
            raise GovernanceError("Task branch changed after evidence/review; approval is invalid")

        previous_head = current_head
        _run_git(
            repository,
            [
                "-c",
                f"user.name={os.environ.get('AMAURA_GIT_AUTHOR_NAME', 'Amaura Agent')}",
                "-c",
                f"user.email={os.environ.get('AMAURA_GIT_AUTHOR_EMAIL', 'amaura@local.invalid')}",
                "merge",
                "--no-ff",
                branch,
                "-m",
                f"Merge Amaura task {task['id']}",
            ],
            timeout=120,
        )
        candidate_head = _run_git(repository, ["rev-parse", "HEAD"]).stdout.strip()
        try:
            _run_validation(repository, validation_command)
        except Exception:
            _run_git(repository, ["reset", "--hard", previous_head])
            _run_git(repository, ["clean", "-fd"], allow_failure=True)
            raise
        # Validation tools may generate caches or alter tracked fixtures. Restore
        # the exact reviewed merge candidate before exposing it as complete.
        _run_git(repository, ["reset", "--hard", candidate_head])
        _run_git(repository, ["clean", "-fd"], allow_failure=True)
        if _run_git(repository, ["status", "--porcelain"]).stdout.strip():
            _run_git(repository, ["reset", "--hard", previous_head])
            raise GovernanceError("Post-merge validation left the target repository dirty")
        merged_head = candidate_head

    record = MergeRecord(str(repository), branch, previous_head, merged_head, validation_command)
    if cleanup:
        cleanup_task_worktree(task, require_clean=False)
    return record


def rollback_approved_merge(task: dict[str, Any], merge: MergeRecord) -> None:
    """Compensate a Git merge when durable completion cannot be committed."""

    metadata = dict(task.get("metadata") or {})
    repository = Path(merge.repository_root).expanduser().resolve()
    expected_branch = str(metadata.get("git_base_branch", ""))
    with repository_lock(repository):
        current_branch = _run_git(
            repository,
            ["symbolic-ref", "--quiet", "--short", "HEAD"],
        ).stdout.strip()
        current_head = _run_git(repository, ["rev-parse", "HEAD"]).stdout.strip()
        if current_branch != expected_branch or current_head != merge.merged_head:
            raise GovernanceError(
                "Cannot compensate merge because the target repository changed after the merge"
            )
        _run_git(repository, ["reset", "--hard", merge.previous_head])
        _run_git(repository, ["clean", "-fd"], allow_failure=True)
        if _run_git(repository, ["status", "--porcelain"]).stdout.strip():
            raise GovernanceError("Compensating merge rollback left the repository dirty")


def cleanup_task_worktree(task: dict[str, Any], *, require_clean: bool = True) -> None:
    metadata = dict(task.get("metadata") or {})
    repository_raw = metadata.get("git_repository_root") or metadata.get("workspace")
    branch = str(metadata.get("git_branch") or _branch_name(str(task.get("id", "task"))))
    worktree_raw = metadata.get("git_worktree_path") or (_worktree_root() / str(task.get("id", "task")))
    if not repository_raw:
        return
    repository = _repository_root(str(repository_raw))
    worktree = Path(str(worktree_raw)).expanduser().resolve()
    if worktree.exists() and require_clean:
        status = _run_git(worktree, ["status", "--porcelain"]).stdout.strip()
        if status:
            raise GovernanceError("Refusing to remove a worktree with uncommitted task changes")
    if worktree.exists():
        _run_git(repository, ["worktree", "remove", "--force", str(worktree)], allow_failure=False)
    _run_git(repository, ["branch", "-D", branch], allow_failure=True)
    _run_git(repository, ["worktree", "prune"], allow_failure=True)


__all__ = [
    "CommitRecord",
    "MergeRecord",
    "WorktreeRecord",
    "cleanup_task_worktree",
    "finalize_task_commit",
    "is_git_repository",
    "is_software_task",
    "merge_approved_task",
    "prepare_task_worktree",
    "repository_lock",
    "rollback_approved_merge",
]
