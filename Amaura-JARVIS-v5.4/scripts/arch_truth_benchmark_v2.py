#!/usr/bin/env python3
"""ARCH Truth v2: strict composite real-machine qualification.

V2 deliberately reuses the mature randomized 26-case ARCH Holdout V9 rather
than cloning that logic. It then adds the missing cross-session durable-memory
proof that the earlier 10-case truth benchmark did not establish.

Rules:
- user work is exercised only through POST /api/chat/stream;
- the V9 holdout independently verifies filesystem/browser/repo/concurrency
  effects and hashes production Python source before and after;
- V2 requires every V9 case to PASS (BLOCKED is not green here);
- cross-session memory must return the exact hidden value from a third session
  and expose the exact durable project-memory source in recall context;
- tracked source and HEAD must remain unchanged throughout;
- automated PASS is provisional until raw evidence is independently audited.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
V9 = REPO_ROOT / "scripts" / "arch_holdout_v9.py"
PASS = "PASS"
FAIL = "FAIL"
BENCHMARK_VERSION = 2

sys.path.insert(0, str(REPO_ROOT))
try:
    from jarvis.amaura.runtime import load_amaura_env

    load_amaura_env()
except Exception as exc:
    print(f"WARNING: could not load Amaura env: {exc}", file=sys.stderr)


@dataclass
class Chat:
    prompt: str
    session_id: str
    http_status: int | None = None
    response_text: str = ""
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SupplementResult:
    test_id: str
    status: str
    capability_correct: bool
    instruction_compliant: bool
    reason: str
    verification: dict[str, Any]
    chats: list[dict[str, Any]]


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=30, check=False
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git failed").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout.strip()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_hashes() -> dict[str, str]:
    return {
        path.relative_to(REPO_ROOT).as_posix(): _file_sha256(path)
        for path in sorted((REPO_ROOT / "jarvis").rglob("*.py"))
        if "__pycache__" not in path.parts
    }


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("JARVIS_API_KEY", "").strip()
    operator_key = os.environ.get("AMAURA_OPERATOR_KEY", "").strip()
    if api_key:
        headers["X-Jarvis-Key"] = api_key
    if operator_key:
        headers["X-Amaura-Operator-Key"] = operator_key
    return headers


def _healthy(base_url: str) -> bool:
    try:
        return httpx.get(f"{base_url}/api/health", timeout=3).status_code == 200
    except Exception:
        return False


def _start_server(base_url: str, port: int, log_path: Path) -> subprocess.Popen[str]:
    python = REPO_ROOT / ".venv" / "bin" / "python"
    if not python.exists():
        raise RuntimeError(f"Missing virtualenv Python: {python}")
    env = os.environ.copy()
    env["JARVIS_HOST"] = "127.0.0.1"
    env["JARVIS_PORT"] = str(port)
    log = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [str(python), "-m", "jarvis.server"],
        cwd=REPO_ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.time() + 60
    while time.time() < deadline:
        if _healthy(base_url):
            return process
        if process.poll() is not None:
            raise RuntimeError("JARVIS server exited during V2 memory supplement startup")
        time.sleep(0.4)
    process.terminate()
    raise RuntimeError("JARVIS server startup timeout during V2 memory supplement")


def _chat(base_url: str, prompt: str, session_id: str, timeout: int = 90) -> Chat:
    result = Chat(prompt=prompt, session_id=session_id)
    try:
        with httpx.Client(timeout=timeout) as client:
            with client.stream(
                "POST",
                f"{base_url}/api/chat/stream",
                json={"message": prompt, "stream": True, "session_id": session_id},
                headers=_headers(),
            ) as response:
                result.http_status = response.status_code
                if response.status_code != 200:
                    result.error = response.read().decode(errors="replace")[:1200]
                    return result
                for line in response.iter_lines():
                    raw = line.strip()
                    if raw.startswith("data:"):
                        raw = raw[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        result.events.append({"raw": raw})
                        continue
                    result.events.append(event)
                    event_type = event.get("type", "")
                    if event_type in ("token", "content"):
                        result.response_text += str(event.get("content", ""))
                    elif event_type == "complete" and not result.response_text:
                        result.response_text = str(event.get("response", ""))
                    elif event_type == "error":
                        result.error = str(event.get("error", ""))
    except Exception as exc:
        result.error = repr(exc)
    return result


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _project_memory_source(chat: Chat, marker: str) -> str:
    """Return the exact project-memory source ref that stored ``marker``."""
    for node in _walk_dicts(chat.events):
        memory = node.get("memory")
        if not isinstance(memory, dict):
            continue
        namespace = str(memory.get("namespace", ""))
        key = str(memory.get("key", ""))
        value = memory.get("value")
        serialized = json.dumps(value, sort_keys=True, default=str) if value is not None else ""
        if namespace.startswith("jarvis.memory.project") and key and marker in serialized:
            return f"{namespace}:{key}"
    return ""


def _project_memory_retrieved(chat: Chat, source_ref: str, marker: str) -> bool:
    """Accept explicit internal-memory telemetry or the exact recalled context source."""
    for node in _walk_dicts(chat.events):
        context_sources = node.get("context_sources")
        if source_ref and isinstance(context_sources, list) and source_ref in [str(item) for item in context_sources]:
            return True

        provider = str(node.get("provider", "")).lower()
        execution_type = str(node.get("execution_type", "")).lower()
        tool_name = str(node.get("tool_name", "")).lower()
        value = node.get("value")
        serialized = json.dumps(value, sort_keys=True, default=str) if value is not None else ""
        if marker not in serialized:
            continue
        if provider == "internal-memory" or execution_type == "memory_retrieval" or tool_name == "memory_retrieval":
            return True
    return False


def _cross_session_memory(evidence: Path) -> SupplementResult:
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    process = _start_server(base_url, port, evidence / "memory_server.log")
    entity = f"ARCH-V2-PROJECT-{uuid.uuid4().hex[:12].upper()}"
    marker = f"ARCH-V2-VALUE-{uuid.uuid4().hex[:16].upper()}"
    distractor_entity = f"ARCH-V2-PROJECT-{uuid.uuid4().hex[:12].upper()}"
    distractor = f"ARCH-V2-VALUE-{uuid.uuid4().hex[:16].upper()}"
    session_store = f"v2-store-{uuid.uuid4()}"
    session_distractor = f"v2-distractor-{uuid.uuid4()}"
    session_recall = f"v2-recall-{uuid.uuid4()}"
    try:
        store = _chat(
            base_url,
            f"Remember this durable project fact: the release marker for {entity} is {marker}. Confirm only after storing it in project memory.",
            session_store,
        )
        other = _chat(
            base_url,
            f"Remember this durable project fact: the release marker for {distractor_entity} is {distractor}. Confirm only after storing it in project memory.",
            session_distractor,
        )
        recall = _chat(
            base_url,
            f"What release marker did I previously tell you for {entity}? Reply with the marker only and nothing else.",
            session_recall,
        )
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    store_source = _project_memory_source(store, marker)
    store_provenance = bool(store_source)
    recall_provenance = _project_memory_retrieved(recall, store_source, marker)
    exact = recall.response_text.strip() == marker
    no_distractor = distractor not in recall.response_text
    distinct_sessions = len({session_store, session_distractor, session_recall}) == 3
    service_ok = all(chat.http_status == 200 and not chat.error for chat in (store, other, recall))
    capability = bool(store_provenance and recall_provenance and marker in recall.response_text and no_distractor and service_ok)
    instruction = bool(exact and distinct_sessions)
    status = PASS if capability and instruction else FAIL
    return SupplementResult(
        test_id="v2_cross_session_durable_memory",
        status=status,
        capability_correct=capability,
        instruction_compliant=instruction,
        reason=(
            "PASS requires durable project-memory storage, the exact stored project-memory source in third-session recall context, "
            "no distractor leakage, and exact value-only output."
        ),
        verification={
            "entity": entity,
            "marker": marker,
            "distractor_entity": distractor_entity,
            "sessions_distinct": distinct_sessions,
            "store_session": session_store,
            "distractor_session": session_distractor,
            "recall_session": session_recall,
            "stored_project_memory_source": store_source,
            "store_project_memory_provenance": store_provenance,
            "recall_internal_memory_provenance": recall_provenance,
            "exact_response": exact,
            "no_distractor_leakage": no_distractor,
            "service_ok": service_ok,
        },
        chats=[asdict(store), asdict(other), asdict(recall)],
    )


def _v9_runs() -> set[Path]:
    root = REPO_ROOT / "qualification_evidence"
    if not root.exists():
        return set()
    return {path.resolve() for path in root.glob("*_ARCH_HOLDOUT_V9_*") if path.is_dir()}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _audit_checklist(evidence: Path, v9_dir: Path, supplement: SupplementResult) -> None:
    lines = [
        "# ARCH Truth v2 — Raw Evidence Audit Checklist",
        "",
        "Automated PASS is provisional. Do not call this release-qualified until every item below is manually audited.",
        "",
        f"- [ ] Review V9 raw result: `{v9_dir / 'HOLDOUT_V9_RESULTS.json'}`",
        "- [ ] Confirm every V9 PASS is supported by independent artifact/effect verification, not response text alone.",
        "- [ ] Spot-check exact-response cases for instruction compliance, especially browser/exact-literal cases.",
        "- [ ] Inspect randomized repo-diagnosis cases and confirm source fixtures do not reveal the answer in comments.",
        "- [ ] Inspect mixed-concurrency evidence for request/session/action isolation.",
        "- [ ] Confirm V9 source-integrity report is green and no tracked JARVIS source changed.",
        f"- [ ] Review cross-session memory result: `{evidence / 'cross_session_memory.json'}`",
        "- [ ] Confirm memory store and recall use three distinct session IDs.",
        "- [ ] Confirm recall context contains the exact project-memory source created by the store request.",
        "- [ ] Confirm recall response equals the marker exactly and excludes the distractor.",
        "- [ ] Confirm V7_EXACT_SHA_BINDING.json matches the candidate SHA and benchmark hashes.",
        "",
        f"Supplement automated status: **{supplement.status}**",
        "",
        "Final manual audit verdict: `PENDING`",
    ]
    (evidence / "EVIDENCE_AUDIT_CHECKLIST.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    run_id = time.strftime("%Y%m%d_%H%M%S") + "_ARCH_TRUTH_V2_BENCHMARK"
    evidence = REPO_ROOT / "qualification_evidence" / run_id
    evidence.mkdir(parents=True, exist_ok=False)

    head_before = _git("rev-parse", "HEAD")
    tracked_before = _git("status", "--porcelain", "--untracked-files=no")
    source_before = _source_hashes()
    v9_sha_before = _file_sha256(V9)
    if tracked_before:
        raise RuntimeError("ARCH Truth v2 requires a clean tracked worktree")

    before_runs = _v9_runs()
    print("ARCH Truth v2: running strict randomized Holdout V9 (26 cases)...", flush=True)
    v9_run = subprocess.run([sys.executable, str(V9)], cwd=REPO_ROOT, env=os.environ.copy(), check=False)
    created = _v9_runs() - before_runs
    v9_dir = max(created, key=lambda path: path.stat().st_mtime) if created else None
    if v9_dir is None:
        print("ERROR: V9 evidence directory was not discovered", file=sys.stderr)
        return 2
    v9_results = _read_json(v9_dir / "HOLDOUT_V9_RESULTS.json")
    counts = v9_results.get("counts") if isinstance(v9_results.get("counts"), dict) else {}
    v9_pass_count = int(counts.get("PASS", 0))
    v9_all_pass = (
        v9_run.returncode == 0
        and int(counts.get("FAIL", 0)) == 0
        and int(counts.get("BLOCKED", 0)) == 0
        and v9_pass_count == 26
        and bool(v9_results.get("qualification_valid"))
    )

    print("ARCH Truth v2: running cross-session durable-memory supplement...", flush=True)
    supplement = _cross_session_memory(evidence)
    (evidence / "cross_session_memory.json").write_text(json.dumps(asdict(supplement), indent=2), encoding="utf-8")

    head_after = _git("rev-parse", "HEAD")
    tracked_after = _git("status", "--porcelain", "--untracked-files=no")
    source_after = _source_hashes()
    v9_sha_after = _file_sha256(V9)
    source_integrity = head_after == head_before and not tracked_after and source_after == source_before
    v9_unchanged = v9_sha_after == v9_sha_before
    automated_gate_pass = bool(v9_all_pass and supplement.status == PASS and source_integrity and v9_unchanged)
    total_pass_count = v9_pass_count + (1 if supplement.status == PASS else 0)

    summary = {
        "benchmark_version": BENCHMARK_VERSION,
        "run_id": run_id,
        "head_before": head_before,
        "head_after": head_after,
        "tracked_worktree_clean_before": not bool(tracked_before),
        "tracked_worktree_clean_after": not bool(tracked_after),
        "source_integrity": source_integrity,
        "v9_benchmark_sha256_before": v9_sha_before,
        "v9_benchmark_sha256_after": v9_sha_after,
        "v9_benchmark_unchanged": v9_unchanged,
        "v9_evidence_dir": str(v9_dir),
        "v9_exit_code": v9_run.returncode,
        "v9_counts": counts,
        "v9_qualification_valid": bool(v9_results.get("qualification_valid")),
        "v9_all_26_pass": v9_all_pass,
        "supplement": asdict(supplement),
        "score": f"{total_pass_count}/27",
        "automated_gate_pass": automated_gate_pass,
        "evidence_audit_required": True,
        "evidence_audit_status": "PENDING",
        "release_qualified": False,
    }
    result_path = evidence / "TRUTH_V2_RESULTS.json"
    result_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _audit_checklist(evidence, v9_dir, supplement)

    print("\n" + "=" * 78)
    print(f"ARCH TRUTH V2 AUTOMATED: {'PASS' if automated_gate_pass else 'FAIL'} | score {summary['score']}")
    print(f"V9: {counts.get('PASS', 0)}/26 PASS | {counts.get('FAIL', 0)} FAIL | {counts.get('BLOCKED', 0)} BLOCKED")
    print(f"Cross-session memory: {supplement.status}")
    print(f"Results: {result_path}")
    print(f"Audit checklist: {evidence / 'EVIDENCE_AUDIT_CHECKLIST.md'}")
    print("Automated PASS is PROVISIONAL until raw evidence audit is completed.")
    print("=" * 78)
    return 0 if automated_gate_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
