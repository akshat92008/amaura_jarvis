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
        git_toplevel = Path(_git(root, "rev-parse", "--show-toplevel")).resolve()
    except Exception:
        return {
            "ready": False,
            "error": "source_checkout_required",
            "repository_root": str(root),
        }
    if root != git_toplevel and git_toplevel not in root.parents:
        return {
            "ready": False,
            "error": "source_checkout_required",
            "repository_root": str(root),
            "git_toplevel": str(git_toplevel),
        }

    provenance: dict[str, Any] = {
        "git_toplevel": str(git_toplevel),
        "head": "",
        "origin_main": "",
        "head_matches_origin_main": False,
        "worktree_clean": False,
        "fetch_ok": False,
    }
    try:
        _git(root, "fetch", "--quiet", "origin", "main")
        provenance["fetch_ok"] = True
        provenance["head"] = _git(root, "rev-parse", "HEAD")
        provenance["origin_main"] = _git(root, "rev-parse", "origin/main")
        provenance["head_matches_origin_main"] = provenance["head"] == provenance["origin_main"]
        provenance["worktree_clean"] = not bool(_git(root, "status", "--porcelain"))
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
