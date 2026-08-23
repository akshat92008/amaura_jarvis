"""Fail-closed local runtime certification for Amaura JARVIS.

This combines repository provenance, the live production doctor, and the
founder-facing real PTY qualification into one machine-readable verdict.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from typing import Any

_HISTORICAL_POISON_TOKENS = (
    "HISTORICAL_FAKE_RESULT_A7C91",
    "HISTORICAL_FAKE_RESULT_B13F2",
)


def _normalize_text(value: str) -> str:
    return " ".join(str(value).split())


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed with exit {completed.returncode}: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    return completed.stdout.strip()


def _resolve_git_checkout_root(root: Path) -> Path:
    """Resolve the enclosing Git checkout for a package nested below repo root."""

    top_level = _git(root, "rev-parse", "--show-toplevel")
    checkout_root = Path(top_level).expanduser().resolve()
    if not checkout_root.is_dir():
        raise RuntimeError(f"Git reported an invalid checkout root: {checkout_root}")
    return checkout_root


def _porcelain_paths(entry: str) -> tuple[str, ...]:
    """Return paths represented by a git status --porcelain entry."""

    payload = entry[3:].strip() if len(entry) >= 4 else entry.strip()
    if " -> " in payload:
        before, after = payload.split(" -> ", 1)
        return before.strip('"'), after.strip('"')
    return (payload.strip('"'),)


def runtime_worktree_status(repository_root: str | Path) -> dict[str, Any]:
    """Report dirtiness that can actually affect the certified runtime tree.

    The installable product may live below the Git checkout root. Untracked or
    modified sibling files outside that package cannot affect imports or the
    local runtime and therefore remain advisory rather than blocking startup.
    Any change inside the certified runtime package still fails closed.
    """

    root = Path(repository_root).expanduser().resolve()
    checkout_root = _resolve_git_checkout_root(root)
    try:
        relative_root = root.relative_to(checkout_root)
    except ValueError as exc:
        raise RuntimeError(f"Runtime root {root} is outside Git checkout {checkout_root}") from exc

    raw_status = _git(checkout_root, "status", "--porcelain")
    checkout_entries = [line for line in raw_status.splitlines() if line.strip()]
    prefix = "" if relative_root == Path(".") else relative_root.as_posix().rstrip("/")

    if not prefix:
        runtime_entries = list(checkout_entries)
    else:
        runtime_entries = []
        for entry in checkout_entries:
            paths = _porcelain_paths(entry)
            if any(path == prefix or path.startswith(prefix + "/") for path in paths):
                runtime_entries.append(entry)

    return {
        "checkout_root": str(checkout_root),
        "runtime_root": str(root),
        "runtime_relative_path": prefix or ".",
        "worktree_clean": not runtime_entries,
        "runtime_dirty_entries": runtime_entries,
        "checkout_dirty_entries": checkout_entries,
        "outside_runtime_dirty_entries": [entry for entry in checkout_entries if entry not in runtime_entries],
    }


def _rendered_result_bullets(response: str) -> list[str]:
    marker = "Recorded task results:"
    if marker not in response:
        return []
    section = response.split(marker, 1)[1]
    if "Pending founder approvals:" in section:
        section = section.split("Pending founder approvals:", 1)[0]
    bullets: list[str] = []
    current = ""
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("- "):
            if current:
                bullets.append(_normalize_text(current))
            current = line[2:].strip()
        elif current:
            current = f"{current} {line}"
    if current:
        bullets.append(_normalize_text(current))
    return bullets


def _assert_authoritative_result_response(control: Any, goal_id: str, response: str) -> None:
    """Cross-check rendered status/results against the exact CompanyStore mission."""

    normalized = _normalize_text(response)
    normalized_lower = normalized.lower()
    for poison in _HISTORICAL_POISON_TOKENS:
        assert poison not in response, f"Historical result poison leaked into current response: {poison}"

    goal = control.store.get_work_item(goal_id)
    title = _normalize_text(str(goal.get("title") or ""))
    assert goal_id in response or (title and title in normalized), (
        f"Status/result response did not identify exact target mission {goal_id}: {response}"
    )

    from jarvis.amaura.cognition import ExecutiveKernel

    mission = ExecutiveKernel(control).brain.status(goal_id)
    authoritative_state = str(mission.get("state") or goal.get("state") or "unknown").lower()
    assert authoritative_state in normalized_lower, (
        f"Response state disagrees with authoritative mission {goal_id}: "
        f"expected {authoritative_state!r}, response={response!r}"
    )

    tasks = mission.get("active_tasks") or mission.get("tasks") or []
    allowed_bullets: list[str] = []
    for task in tasks:
        summary = str(task.get("summary") or "").strip()
        if summary:
            allowed_bullets.append(_normalize_text(f"{task.get('title') or task.get('id')}: {summary[:1000]}"))

    rendered_bullets = _rendered_result_bullets(response)
    if "Recorded task results:" in response:
        assert allowed_bullets, (
            f"Response claimed recorded results for {goal_id}, but CompanyStore has no task summaries."
        )
        assert rendered_bullets, "Response claimed recorded task results but rendered none."
        unsupported = [bullet for bullet in rendered_bullets if bullet not in allowed_bullets]
        assert not unsupported, (
            f"Response rendered result content not persisted under exact goal {goal_id}: {unsupported}"
        )

    no_result_text = "No completed task result has been recorded yet."
    if no_result_text in response:
        assert not allowed_bullets, (
            f"Response claimed no recorded result for {goal_id}, but CompanyStore contains task summaries."
        )


def _load_pty_qualifier(root: Path) -> Any:
    path = root / "scripts" / "qualify_real_cli_pty.py"
    if not path.is_file():
        raise RuntimeError(f"Missing PTY qualification harness: {path}")
    spec = importlib.util.spec_from_file_location("amaura_local_pty_qualifier", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load PTY qualification harness: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.__dict__["_assert_result_response_consistent"] = _assert_authoritative_result_response
    qualifier = getattr(module, "run_full_pty_qualification", None)
    if not callable(qualifier):
        raise RuntimeError("PTY qualification harness does not expose run_full_pty_qualification()")
    return qualifier


def run_authoritative_pty_qualification(repository_root: str | Path) -> dict[str, Any]:
    root = Path(repository_root).expanduser().resolve()
    return _load_pty_qualifier(root)()


def certify_local_runtime(repository_root: str | Path) -> dict[str, Any]:
    """Return a fail-closed daily-use verdict for the exact local checkout."""

    root = Path(repository_root).expanduser().resolve()
    try:
        worktree = runtime_worktree_status(root)
        checkout_root = Path(str(worktree["checkout_root"]))
    except Exception as exc:
        return {
            "ready": False,
            "error": "source_checkout_required",
            "repository_root": str(root),
            "message": f"{type(exc).__name__}: {exc}",
        }

    provenance: dict[str, Any] = {
        **worktree,
        "head": "",
        "origin_main": "",
        "head_matches_origin_main": False,
        "fetch_ok": False,
    }
    try:
        _git(checkout_root, "fetch", "--quiet", "origin", "main")
        provenance["fetch_ok"] = True
        provenance["head"] = _git(checkout_root, "rev-parse", "HEAD")
        provenance["origin_main"] = _git(checkout_root, "rev-parse", "origin/main")
        provenance["head_matches_origin_main"] = provenance["head"] == provenance["origin_main"]
    except Exception as exc:
        provenance["error"] = f"{type(exc).__name__}: {exc}"

    from jarvis.amaura.doctor import certify_release

    try:
        doctor = certify_release(repository_root=root, static_only=False)
    except Exception as exc:
        doctor = {
            "ready": False,
            "source_certified": False,
            "production_ready": False,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }

    try:
        pty_report = run_authoritative_pty_qualification(root)
    except Exception as exc:
        pty_report = {
            "overall": "FAIL",
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }

    ready = bool(
        provenance.get("fetch_ok")
        and provenance.get("head_matches_origin_main")
        and provenance.get("worktree_clean")
        and doctor.get("production_ready") is True
        and doctor.get("ready") is True
        and pty_report.get("overall") == "PASS"
        and pty_report.get("single_mission_continuity") == "PASS"
        and pty_report.get("result_consistency") == "PASS"
        and pty_report.get("multi_mission_continuity") == "PASS"
        and pty_report.get("restart_test") == "PASS"
    )

    return {
        "ready": ready,
        "verdict": "READY_FOR_DAILY_USE" if ready else "NOT_READY_FOR_DAILY_USE",
        "repository_root": str(root),
        "provenance": provenance,
        "production_gate": doctor,
        "real_pty": pty_report,
    }
