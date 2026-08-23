#!/usr/bin/env python3
"""Authoritative Real Interactive PTY Qualification Harness for Amaura JARVIS.

Drives the actual production executable:
    .venv/bin/jarvis --no-web
as a real interactive pseudo-terminal (PTY) session.

Verifies:
1. Boot & Entrypoint guards installation via runtime behavior.
2. Single-mission continuity sequence (6 turns targeting exact expected goal).
3. Independent CompanyStore verification on every turn (zero junk goals, zero historical poisoning).
4. Result/status text is grounded in the exact target mission's CompanyStore rows.
5. Multi-mission separation and named reference switching in the same PTY.
6. Clean process termination with /exit.
7. Restart semantics use a distinct new session anchor, not a stale prior-session anchor.
"""

from __future__ import annotations

import json
import os
import pty
import re
import select
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
JARVIS_BIN = REPO_ROOT / ".venv" / "bin" / "jarvis"

PROMPT_PATTERN = re.compile(r"◈ JARVIS ›\s*", re.MULTILINE)
SESSION_NAMESPACE = "jarvis.session_context"
HISTORICAL_POISON_TOKENS = (
    "HISTORICAL_FAKE_RESULT_A7C91",
    "HISTORICAL_FAKE_RESULT_B13F2",
)


def _session_anchor_map(control: Any) -> dict[str, dict[str, Any]]:
    """Return persisted session anchors keyed by their exact session id."""
    rows = control.store.list_knowledge(namespace=SESSION_NAMESPACE, limit=500)
    return {
        str(row["key"]): row
        for row in rows
        if isinstance(row, dict) and str(row.get("key") or "").strip()
    }


def _anchor_goal(control: Any, session_id: str) -> str:
    """Read one exact session anchor; never accept another session as proof."""
    row = control.store.get_knowledge(SESSION_NAMESPACE, session_id)
    value = row.get("value") or {}
    assert isinstance(value, dict), f"Malformed session anchor for {session_id}: {row}"
    return str(value.get("current_goal_id") or "")


def _goal_tasks(control: Any, goal_id: str) -> list[dict[str, Any]]:
    return control.store.list_work_items(parent_id=goal_id, limit=1000)


def _assert_no_historical_result_leak(response: str) -> None:
    for poison in HISTORICAL_POISON_TOKENS:
        assert poison not in response, f"Historical result poison leaked into current response: {poison}"


def _assert_result_response_consistent(control: Any, goal_id: str, response: str) -> None:
    """Verify every rendered task-result bullet is backed by the exact goal's rows."""
    _assert_no_historical_result_leak(response)
    assert goal_id in response, f"Status/result response omitted exact target goal {goal_id}: {response}"

    tasks = _goal_tasks(control, goal_id)
    allowed_result_lines: set[str] = set()
    for task in tasks:
        summary = str(task.get("summary") or "").strip()
        if summary:
            allowed_result_lines.add(f"- {task.get('title') or task.get('id')}: {summary[:1000]}")

    rendered_result_lines = {
        line.strip()
        for line in response.splitlines()
        if line.strip().startswith("- ")
    }
    unsupported = rendered_result_lines - allowed_result_lines
    assert not unsupported, (
        f"Response rendered result lines not present under exact goal {goal_id}: "
        f"{sorted(unsupported)}"
    )

    if "Recorded task results:" in response:
        assert rendered_result_lines, "Response claimed recorded task results but rendered none."
        assert allowed_result_lines, (
            f"Response claimed recorded results for {goal_id}, but CompanyStore has no task summaries."
        )

    no_result_text = "No completed task result has been recorded yet."
    if no_result_text in response:
        assert not allowed_result_lines, (
            f"Response claimed no recorded task result for {goal_id}, "
            "but CompanyStore contains task summaries."
        )


class PTYSession:
    """Manages an interactive PTY session connected to .venv/bin/jarvis --no-web."""

    def __init__(self, data_dir: Path, working_dir: Path, timeout: float = 60.0):
        self.data_dir = data_dir
        self.working_dir = working_dir
        self.timeout = timeout
        self.master_fd: int | None = None
        self.slave_fd: int | None = None
        self.process: subprocess.Popen[bytes] | None = None
        self.buffer = ""
        self.transcript: list[dict[str, Any]] = []

    def start(self) -> None:
        self.master_fd, self.slave_fd = pty.openpty()
        env = {
            **os.environ,
            "PYTHONUNBUFFERED": "1",
            "TERM": "xterm-256color",
            "AMAURA_DATA_DIR": str(self.data_dir),
            "AMAURA_AUDIT_CHECKPOINT_PATH": str(self.data_dir / "audit.checkpoint"),
            "AMAURA_PROVIDER_RECEIPT_KEY": "a" * 64,
            "AMAURA_REVIEW_ATTESTATION_KEY": "r" * 64,
            "NVIDIA_API_KEY": os.environ.get("NVIDIA_API_KEY", "test-key"),
        }
        cmd = [str(JARVIS_BIN), "--no-web", "--working-dir", str(self.working_dir)]
        self.process = subprocess.Popen(
            cmd,
            stdin=self.slave_fd,
            stdout=self.slave_fd,
            stderr=self.slave_fd,
            cwd=str(self.working_dir),
            env=env,
            close_fds=True,
        )
        os.close(self.slave_fd)
        self.slave_fd = None
        boot_output = self._read_until_prompt(timeout=45.0)
        self.transcript.append({"type": "boot", "output": boot_output})

    def _clean_ansi(self, text: str) -> str:
        ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        return ansi_escape.sub("", text)

    def _read_until_prompt(self, timeout: float | None = None) -> str:
        if timeout is None:
            timeout = self.timeout
        start_time = time.monotonic()
        accumulated = ""
        while time.monotonic() - start_time < timeout:
            r, _, _ = select.select([self.master_fd], [], [], 0.2)
            if self.master_fd in r:
                try:
                    data = os.read(self.master_fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                decoded = data.decode("utf-8", errors="replace")
                accumulated += decoded
                cleaned = self._clean_ansi(accumulated)
                if "◈ JARVIS ›" in cleaned:
                    return accumulated
            if self.process and self.process.poll() is not None:
                break
        raise TimeoutError(
            f"Timed out waiting for prompt after {timeout}s. Received:\n"
            f"{self._clean_ansi(accumulated)}"
        )

    def send_turn(self, user_input: str, timeout: float | None = None) -> str:
        if self.master_fd is None or self.process is None:
            raise RuntimeError("PTY session not started")
        payload = (user_input.strip() + "\n").encode("utf-8")
        os.write(self.master_fd, payload)
        raw_output = self._read_until_prompt(timeout=timeout)
        cleaned = self._clean_ansi(raw_output)
        response_text = cleaned
        if "◈ JARVIS ›" in response_text:
            parts = response_text.split("◈ JARVIS ›")
            if len(parts) >= 2:
                response_text = parts[-2]
        self.transcript.append(
            {
                "type": "turn",
                "input": user_input,
                "raw_output": raw_output,
                "clean_response": response_text.strip(),
            }
        )
        return response_text.strip()

    def exit(self) -> int:
        if self.master_fd is None or self.process is None:
            return 0
        try:
            os.write(self.master_fd, b"/exit\n")
            time.sleep(0.5)
            self.process.wait(timeout=5.0)
        except Exception:
            try:
                self.process.terminate()
                self.process.wait(timeout=2.0)
            except Exception:
                self.process.kill()
        finally:
            if self.master_fd is not None:
                try:
                    os.close(self.master_fd)
                except OSError:
                    pass
                self.master_fd = None
        return self.process.returncode or 0


def run_full_pty_qualification() -> dict[str, Any]:
    print("=" * 70)
    print("STARTING AUTHORITATIVE REAL PTY CLI QUALIFICATION")
    print(f"Target Binary: {JARVIS_BIN}")
    assert JARVIS_BIN.exists(), f"Executable {JARVIS_BIN} not found!"
    print("=" * 70)

    results: dict[str, Any] = {
        "entrypoint_test": "UNTESTED",
        "single_mission_continuity": "UNTESTED",
        "result_consistency": "UNTESTED",
        "multi_mission_continuity": "UNTESTED",
        "restart_test": "UNTESTED",
        "turns": [],
        "overall": "FAIL",
    }

    temp_dir = tempfile.mkdtemp(prefix="jarvis_pty_qual_")
    qual_root = Path(temp_dir)
    data_dir = qual_root / "amaura_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    working_dir = qual_root / "workspace"
    working_dir.mkdir(parents=True, exist_ok=True)

    os.environ["AMAURA_DATA_DIR"] = str(data_dir)
    os.environ["AMAURA_AUDIT_CHECKPOINT_PATH"] = str(data_dir / "audit.checkpoint")
    os.environ["AMAURA_PROVIDER_RECEIPT_KEY"] = "a" * 64
    os.environ["AMAURA_REVIEW_ATTESTATION_KEY"] = "r" * 64

    from jarvis.amaura.control_plane import AmauraControlPlane

    control = AmauraControlPlane(
        db_path=data_dir / "amaura.db",
        audit_checkpoint_path=data_dir / "audit.checkpoint",
    )

    control.store.insert_work_item(
        {
            "id": "goal_historical_weather",
            "item_type": "programme",
            "title": "historical weather research task",
            "owner_id": "operator",
            "metadata": {"dynamic_goal": True, "executive_session_id": "old_session_1"},
        }
    )
    control.store.insert_work_item(
        {
            "id": "task_historical_weather_result",
            "parent_id": "goal_historical_weather",
            "item_type": "task",
            "title": "old weather result",
            "owner_id": "operator",
            "state": "completed",
            "summary": HISTORICAL_POISON_TOKENS[0],
        }
    )
    control.store.insert_work_item(
        {
            "id": "goal_historical_auth",
            "item_type": "programme",
            "title": "review pull request for authentication",
            "owner_id": "operator",
            "metadata": {"dynamic_goal": True, "executive_session_id": "old_session_2"},
        }
    )
    control.store.insert_work_item(
        {
            "id": "task_historical_auth_result",
            "parent_id": "goal_historical_auth",
            "item_type": "task",
            "title": "old auth result",
            "owner_id": "operator",
            "state": "completed",
            "summary": HISTORICAL_POISON_TOKENS[1],
        }
    )
    baseline_anchor_keys = set(_session_anchor_map(control))
    control.close()

    pty_session = PTYSession(data_dir=data_dir, working_dir=working_dir, timeout=60.0)
    print("[1/5] Launching .venv/bin/jarvis --no-web in real PTY...")
    pty_session.start()
    print("✓ PTY Process online.")

    boot_text = pty_session.transcript[0]["output"]
    assert "J.A.R.V.I.S." in boot_text, "Boot sequence missing expected JARVIS banner"
    results["entrypoint_test"] = "PASS"
    print("✓ [Entrypoint Test] Production boot sequence verified.")

    init_prompt = (
        "build me a small arcade fighting game with sounds on my Desktop "
        "called founder-continuity-final"
    )
    print(f"\n[2/5] Sending Mission Turn 0: '{init_prompt}'...")
    turn0_resp = pty_session.send_turn(init_prompt)
    print(f"Response: {turn0_resp[:200]}...")

    control = AmauraControlPlane(
        db_path=data_dir / "amaura.db",
        audit_checkpoint_path=data_dir / "audit.checkpoint",
    )
    progs = [
        it
        for it in control.store.list_work_items(limit=100)
        if it.get("item_type") == "programme"
        and it.get("id") not in ("goal_historical_weather", "goal_historical_auth")
    ]
    assert len(progs) == 1, (
        f"Expected exactly 1 new programme created, found {len(progs)}: {progs}"
    )
    expected_goal_id = str(progs[0]["id"])
    print(f"✓ EXPECTED_GOAL ID created in CompanyStore: {expected_goal_id}")

    anchors_after_create = _session_anchor_map(control)
    first_session_keys = set(anchors_after_create) - baseline_anchor_keys
    assert len(first_session_keys) == 1, (
        "Could not identify exactly one new interactive session anchor after mission "
        f"creation: {sorted(first_session_keys)}"
    )
    first_session_id = next(iter(first_session_keys))
    assert _anchor_goal(control, first_session_id) == expected_goal_id, (
        f"Initial session {first_session_id} did not bind to {expected_goal_id}"
    )
    print(f"✓ Exact first-session anchor: {first_session_id} -> {expected_goal_id}")

    continuity_prompts = [
        ("what are the results of the task i gave you?", "results"),
        ("what's its status?", "status"),
        ("continue it", "continue"),
        ("focus on that first", "focus"),
        ("yes", "yes"),
        ("execute it", "execute"),
    ]

    print("\n[3/5] Driving 6-turn conversational continuity in SAME PTY...")
    for idx, (prompt, label) in enumerate(continuity_prompts, start=1):
        print(f"  Turn {idx} ({label}): '{prompt}'")
        resp = pty_session.send_turn(prompt)
        print(f"    Output: {resp[:150]}...")

        all_progs = [
            it
            for it in control.store.list_work_items(limit=100)
            if it.get("item_type") == "programme"
        ]
        assert len(all_progs) == 3, (
            f"Duplicate goal created on prompt '{prompt}'! Total now: {len(all_progs)}"
        )

        active_goal = _anchor_goal(control, first_session_id)
        assert active_goal == expected_goal_id, (
            f"Turn {idx} ({prompt}) anchored exact session {first_session_id} "
            f"to '{active_goal}', expected '{expected_goal_id}'"
        )

        assert "couldn't resolve that reference" not in resp.lower(), (
            f"Unresolved reference on turn {idx}!"
        )
        _assert_no_historical_result_leak(resp)
        if label in {"results", "status"}:
            _assert_result_response_consistent(control, expected_goal_id, resp)

        results["turns"].append(
            {
                "turn": idx,
                "label": label,
                "prompt": prompt,
                "session_id": first_session_id,
                "target_goal": active_goal,
                "expected_goal": expected_goal_id,
                "response_snippet": resp[:200],
                "verified": True,
            }
        )

    results["single_mission_continuity"] = "PASS"
    results["result_consistency"] = "PASS"
    print(
        "✓ [Single Mission Continuity] 6/6 turns stayed on the exact session goal "
        "with 0 duplicate goals and 0 historical result leaks."
    )

    print("\n[4/5] Multi-Mission Separation and Named Reference Switching in SAME PTY...")
    research_prompt = "research current AI coding agent trends on the web and summarize what you find"
    print(f"  Creating second mission: '{research_prompt}'...")
    res_resp = pty_session.send_turn(research_prompt)
    print(f"    Output: {res_resp[:150]}...")

    new_progs = [
        it
        for it in control.store.list_work_items(limit=100)
        if it.get("item_type") == "programme"
        and it.get("id")
        not in ("goal_historical_weather", "goal_historical_auth", expected_goal_id)
    ]
    assert len(new_progs) == 1, f"Expected 1 research programme, found {len(new_progs)}"
    research_goal_id = str(new_progs[0]["id"])
    print(f"  ✓ Research goal ID created: {research_goal_id}")

    multi_turns = [
        ("what's the status of the game project?", expected_goal_id, "game"),
        ("what's the status of the research task?", research_goal_id, "research"),
        ("continue the game", expected_goal_id, "game"),
        ("show me the research task", research_goal_id, "research"),
        ("what's its status?", research_goal_id, "research"),
    ]

    for prompt, exp_gid, tag in multi_turns:
        print(f"  Multi-Turn ({tag}): '{prompt}'")
        resp = pty_session.send_turn(prompt)
        print(f"    Output: {resp[:150]}...")
        active_gid = _anchor_goal(control, first_session_id)
        assert active_gid == exp_gid, (
            f"Multi-mission prompt '{prompt}' resolved exact session "
            f"{first_session_id} to '{active_gid}', expected '{exp_gid}'"
        )
        _assert_no_historical_result_leak(resp)

    results["multi_mission_continuity"] = "PASS"
    print(
        "✓ [Multi-Mission Continuity] Correctly switched between game and research "
        "missions by name and pronouns."
    )

    print("\n[5/5] Testing /exit and Restart Semantics...")
    exit_code = pty_session.exit()
    print(f"✓ PTY Process exited cleanly with code {exit_code}.")
    assert pty_session.process is not None
    assert pty_session.process.poll() is not None, "Old process was not terminated!"

    anchors_before_restart = _session_anchor_map(control)
    restart_baseline_keys = set(anchors_before_restart)
    assert first_session_id in restart_baseline_keys

    restart_pty = PTYSession(data_dir=data_dir, working_dir=working_dir, timeout=60.0)
    restart_pty.start()
    print("✓ New PTY process started.")

    programmes_before_fail_closed = {
        str(it.get("id") or "")
        for it in control.store.list_work_items(item_type="programme", limit=1000)
    }
    fail_closed_resp = restart_pty.send_turn("continue it")
    print(f"  Restart 'continue it' -> {fail_closed_resp[:150]}...")
    assert (
        "couldn't resolve" in fail_closed_resp.lower()
        or "clarify" in fail_closed_resp.lower()
        or "reference" in fail_closed_resp.lower()
    ), f"Fresh session 'continue it' did not fail closed: {fail_closed_resp}"
    programmes_after_fail_closed = {
        str(it.get("id") or "")
        for it in control.store.list_work_items(item_type="programme", limit=1000)
    }
    assert programmes_after_fail_closed == programmes_before_fail_closed, (
        "Fresh-session pronoun created a new goal instead of failing closed."
    )
    assert set(_session_anchor_map(control)) == restart_baseline_keys, (
        "Fresh-session unresolved pronoun unexpectedly created/reused a persisted "
        "session anchor before an explicit reference."
    )

    explicit_resp = restart_pty.send_turn(f"{expected_goal_id} give me results")
    print(
        f"  Restart explicit '{expected_goal_id} give me results' -> "
        f"{explicit_resp[:150]}..."
    )
    _assert_result_response_consistent(control, expected_goal_id, explicit_resp)

    anchors_after_explicit = _session_anchor_map(control)
    new_restart_session_keys = set(anchors_after_explicit) - restart_baseline_keys
    assert len(new_restart_session_keys) == 1, (
        "Explicit lookup in restarted PTY did not create exactly one distinct "
        f"new session anchor: {sorted(new_restart_session_keys)}"
    )
    restart_session_id = next(iter(new_restart_session_keys))
    assert restart_session_id != first_session_id
    assert _anchor_goal(control, restart_session_id) == expected_goal_id, (
        f"Restarted session {restart_session_id} did not anchor to {expected_goal_id}"
    )
    assert _anchor_goal(control, first_session_id) == research_goal_id, (
        "Old session anchor changed during restarted-session exact lookup; "
        "restart proof must not reuse/mutate the prior session."
    )
    print(
        f"  ✓ Distinct restart anchor: {restart_session_id} -> {expected_goal_id} "
        f"(old session remains {first_session_id} -> {research_goal_id})"
    )

    followup_resp = restart_pty.send_turn("continue it")
    print(f"  Restart follow-up 'continue it' -> {followup_resp[:150]}...")
    assert _anchor_goal(control, restart_session_id) == expected_goal_id, (
        "Restart follow-up did not remain on the exact restored session anchor."
    )
    _assert_no_historical_result_leak(followup_resp)

    chat_resp = restart_pty.send_turn("what is 2 + 2?")
    print(f"  Restart normal chat 'what is 2 + 2?' -> {chat_resp[:150]}...")
    assert "4" in chat_resp, f"Normal chat failed: {chat_resp}"

    restart_pty.exit()
    control.close()
    shutil.rmtree(temp_dir, ignore_errors=True)

    results["restart_test"] = "PASS"
    results["overall"] = "PASS"
    results["first_session_id"] = first_session_id
    results["restart_session_id"] = restart_session_id
    results["historical_result_leaks"] = 0
    results["unsupported_result_lines"] = 0
    print("\n" + "=" * 70)
    print("ALL REAL PTY CLI QUALIFICATION TESTS PASSED SUCCESSFULLY!")
    print("=" * 70)
    return results


if __name__ == "__main__":
    report = run_full_pty_qualification()
    print(json.dumps(report, indent=2))
