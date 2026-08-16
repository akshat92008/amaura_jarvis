#!/usr/bin/env python3
"""
Black-Box E2E Harness
Submits natural-language requests to JARVIS REST API and records:
- request / response
- tool calls (from SSE events)
- latency metrics
- classification

The harness NEVER decides which tool to call — it only submits text and observes.
"""

import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from jarvis.amaura.runtime import load_amaura_env

load_amaura_env()

try:
    import httpx
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "httpx", "-q"])
    import httpx

JARVIS_HOST = os.environ.get("JARVIS_HOST", "127.0.0.1")
JARVIS_PORT = int(os.environ.get("JARVIS_PORT", "8000"))
BASE_URL = f"http://{JARVIS_HOST}:{JARVIS_PORT}"

_server_proc = None


def get_api_key() -> str:
    """Read JARVIS API key from env (loaded from .env.amaura)."""
    from jarvis.amaura.runtime import load_amaura_env

    load_amaura_env()
    key = os.environ.get("JARVIS_API_KEY", "").strip()
    return key


def get_operator_key() -> str:
    """Read Amaura operator key for mission execution."""
    from jarvis.amaura.runtime import load_amaura_env

    load_amaura_env()
    return os.environ.get("AMAURA_OPERATOR_KEY", "").strip()


def is_server_up() -> bool:
    try:
        r = httpx.get(f"{BASE_URL}/api/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def ensure_server() -> tuple[bool, dict]:
    """Start JARVIS server if not running. Returns (is_up, health_info)."""
    global _server_proc
    if is_server_up():
        try:
            r = httpx.get(f"{BASE_URL}/api/health", timeout=5)
            return True, r.json()
        except Exception:
            return True, {}

    project_dir = Path(__file__).parent.parent
    venv_python = project_dir / ".venv" / "bin" / "python"
    cmd = [str(venv_python), "-m", "jarvis.server"]
    env = os.environ.copy()
    _server_proc = subprocess.Popen(
        cmd, cwd=str(project_dir), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    deadline = time.time() + 45
    while time.time() < deadline:
        if is_server_up():
            try:
                r = httpx.get(f"{BASE_URL}/api/health", timeout=5)
                return True, r.json()
            except Exception:
                return True, {}
        if _server_proc.poll() is not None:
            return False, {"error": "server exited early"}
        time.sleep(0.5)
    return False, {"error": "server startup timeout"}


def stop_server():
    global _server_proc
    if _server_proc and _server_proc.poll() is None:
        _server_proc.terminate()
        try:
            _server_proc.wait(timeout=5)
        except Exception:
            _server_proc.kill()


class BlackBoxResult:
    def __init__(self, test_id: str, prompt: str):
        self.test_id = test_id
        self.prompt = prompt
        self.request_ts = None
        self.first_token_ts = None
        self.first_tool_ts = None
        self.tool_complete_ts = None
        self.final_ts = None
        self.response_text = ""
        self.tool_calls = []  # [{name, args, result, error, status, ts}]
        self.events = []
        self.http_status = None
        self.error = None
        self.goal_id = None
        self.goal_state = None
        self.mission_state_history = []  # [{state, ts}]
        self.classification = "UNVERIFIED"
        self.verification = {}
        self.evidence_dir = None

    def ttft_ms(self) -> float | None:
        if self.request_ts and self.first_token_ts:
            return (self.first_token_ts - self.request_ts) * 1000
        return None

    def total_ms(self) -> float | None:
        if self.request_ts and self.final_ts:
            return (self.final_ts - self.request_ts) * 1000
        return None

    def to_dict(self) -> dict:
        return {
            "test_id": self.test_id,
            "prompt": self.prompt,
            "classification": self.classification,
            "http_status": self.http_status,
            "error": self.error,
            "response_text": self.response_text,
            "response_excerpt": self.response_text[:2000],
            "tool_calls": self.tool_calls,
            "goal_id": self.goal_id,
            "goal_state": self.goal_state,
            "mission_state_history": self.mission_state_history,
            "latency": {
                "ttft_ms": self.ttft_ms(),
                "total_ms": self.total_ms(),
                "request_ts": self.request_ts,
                "final_ts": self.final_ts,
            },
            "verification": self.verification,
        }


def enrich_result_with_mission_evidence(result: BlackBoxResult, timeout: int = 30) -> BlackBoxResult:
    """Poll mission status if goal_id exists to capture state transitions and tool executions."""
    if not result.goal_id:
        return result

    api_key = get_api_key()
    op_key = get_operator_key()
    headers = {}
    if api_key:
        headers["X-Jarvis-Key"] = api_key
    if op_key:
        headers["X-Amaura-Operator-Key"] = op_key

    start_wait = time.time()
    last_state = result.goal_state
    if last_state:
        result.mission_state_history.append({"state": last_state, "ts": time.time()})

    # Trigger goal execution immediately if queued/draft
    try:
        with httpx.Client(timeout=15) as client:
            client.post(
                f"{BASE_URL}/api/amaura/jarvis/goals/{result.goal_id}/run",
                json={"max_ticks": 5, "auto_replan": True},
                headers=headers,
            )
    except Exception:
        pass

    while time.time() - start_wait < timeout:
        try:
            with httpx.Client(timeout=5) as client:
                r = client.get(f"{BASE_URL}/api/amaura/jarvis/goals/{result.goal_id}", headers=headers)
                if r.status_code == 200:
                    status_data = r.json()
                    curr_state = status_data.get("state") or status_data.get("lifecycle_state")
                    if curr_state and curr_state != last_state:
                        last_state = curr_state
                        result.goal_state = curr_state
                        result.mission_state_history.append({"state": curr_state, "ts": time.time()})

                    # Extract tool executions from active and completed tasks
                    tasks = status_data.get("tasks", []) + status_data.get("active_tasks", [])
                    for task in tasks:
                        t_id = task.get("id", "")
                        t_title = task.get("title", "")
                        t_desc = task.get("description", "")
                        t_action = task.get("action_type", "")
                        t_owner = task.get("owner_id", "")
                        t_state = task.get("state", "")
                        t_summary = task.get("summary", "")

                        tool_name = f"task:{t_action or 'action'}:{t_owner or 'agent'}"
                        if not any(tc.get("task_id") == t_id for tc in result.tool_calls):
                            result.tool_calls.append(
                                {
                                    "name": tool_name,
                                    "args": {"task_title": t_title, "description": t_desc, "action_type": t_action},
                                    "result": t_summary or t_desc,
                                    "error": t_summary if t_state == "failed" else None,
                                    "status": t_state,
                                    "task_id": t_id,
                                    "ts": time.time(),
                                }
                            )

                        # Also append detailed task evidence records
                        for ev in task.get("evidence", []):
                            rec_ref = ev.get("reference", "")
                            rec_excerpt = ev.get("excerpt", "")
                            rec_success = ev.get("success", True)
                            if rec_ref and not any(tc.get("reference") == rec_ref for tc in result.tool_calls):
                                result.tool_calls.append(
                                    {
                                        "name": f"evidence:{ev.get('type', 'record')}",
                                        "args": {"task_id": t_id, "reference": rec_ref},
                                        "result": rec_excerpt,
                                        "error": None if rec_success else rec_excerpt,
                                        "status": "completed" if rec_success else "failed",
                                        "reference": rec_ref,
                                        "ts": time.time(),
                                    }
                                )

                    if curr_state in ("completed", "failed", "cancelled"):
                        break
        except Exception:
            pass
        time.sleep(1)

    return result


def submit_chat_stream(prompt: str, test_id: str, timeout: int = 90) -> BlackBoxResult:
    """Submit natural-language prompt to JARVIS streaming chat endpoint."""
    result = BlackBoxResult(test_id, prompt)
    api_key = get_api_key()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-Jarvis-Key"] = api_key
    op_key = get_operator_key()
    if op_key:
        headers["X-Amaura-Operator-Key"] = op_key

    payload = {"message": prompt, "stream": True}
    result.request_ts = time.time()

    try:
        with httpx.Client(timeout=timeout) as client:
            with client.stream("POST", f"{BASE_URL}/api/chat/stream", json=payload, headers=headers) as resp:
                result.http_status = resp.status_code
                if resp.status_code != 200:
                    body = resp.read().decode()
                    result.error = f"HTTP {resp.status_code}: {body[:200]}"
                    if resp.status_code in (500, 502, 503, 504):
                        result.classification = "SERVICE_UNAVAILABLE"
                    else:
                        result.classification = "FAIL"
                    result.final_ts = time.time()
                    return result

                for line in resp.iter_lines():
                    now = time.time()
                    raw = line.strip()
                    if line.startswith("data:"):
                        raw = line[5:].strip()
                    if raw in ("[DONE]", ""):
                        break
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        result.events.append({"raw": raw})
                        continue

                    result.events.append(event)
                    etype = event.get("type", "")

                    if etype in ("token", "content"):
                        token_text = event.get("content", "")
                        result.response_text += token_text
                        if result.first_token_ts is None:
                            result.first_token_ts = now
                    elif etype == "complete":
                        resp_msg = event.get("response", "")
                        if resp_msg and not result.response_text:
                            result.response_text = resp_msg
                        exec_data = event.get("executive", {})
                        if exec_data.get("goal_id"):
                            result.goal_id = exec_data.get("goal_id")
                            result.goal_state = exec_data.get("state")
                    elif etype == "tool_call":
                        if result.first_tool_ts is None:
                            result.first_tool_ts = now
                        tc = event.get("tool_call", event)
                        result.tool_calls.append(
                            {
                                "name": tc.get("function", {}).get("name", tc.get("name", "?")),
                                "args": tc.get("function", {}).get("arguments", tc.get("args", {})),
                                "result": None,
                                "error": None,
                                "status": "invoked",
                                "ts": now,
                            }
                        )
                    elif etype == "tool_result":
                        result.tool_complete_ts = now
                        if result.tool_calls:
                            result.tool_calls[-1]["result"] = event.get("result", event.get("output", ""))
                            result.tool_calls[-1]["status"] = "completed"
                    elif etype == "error":
                        result.error = event.get("error", "Unknown error event")

                    # Also handle OpenAI delta format if present
                    delta = event.get("choices", [{}])[0].get("delta", {})
                    if delta.get("content"):
                        result.response_text += delta["content"]
                        if result.first_token_ts is None:
                            result.first_token_ts = now
                    tool_calls_delta = delta.get("tool_calls", [])
                    for tc in tool_calls_delta:
                        fn = tc.get("function", {})
                        if fn.get("name"):
                            if result.first_tool_ts is None:
                                result.first_tool_ts = now
                            result.tool_calls.append(
                                {
                                    "name": fn["name"],
                                    "args": fn.get("arguments", {}),
                                    "result": None,
                                    "error": None,
                                    "status": "invoked",
                                    "ts": now,
                                }
                            )

    except httpx.TimeoutException as e:
        result.error = f"Timeout after {timeout}s: {e}"
        result.classification = "FAIL"
    except Exception as e:
        result.error = f"Request error: {e}"
        result.classification = "FAIL"
        traceback.print_exc()

    result.final_ts = time.time()
    if result.goal_id:
        enrich_result_with_mission_evidence(result)
    return result


def submit_chat(prompt: str, test_id: str, timeout: int = 90) -> BlackBoxResult:
    """Submit to non-streaming REST endpoint (fallback)."""
    result = BlackBoxResult(test_id, prompt)
    api_key = get_api_key()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-Jarvis-Key"] = api_key
    op_key = get_operator_key()
    if op_key:
        headers["X-Amaura-Operator-Key"] = op_key
    payload = {"message": prompt}
    result.request_ts = time.time()
    try:
        r = httpx.post(f"{BASE_URL}/api/chat", json=payload, headers=headers, timeout=timeout)
        result.http_status = r.status_code
        result.final_ts = time.time()
        if r.status_code == 200:
            data = r.json()
            result.response_text = data.get("response", data.get("message", str(data)))
            raw_tc = data.get("tool_calls", [])
            for tc in raw_tc:
                if isinstance(tc, dict):
                    result.tool_calls.append(
                        {
                            "name": tc.get("name", "?"),
                            "args": tc.get("args", {}),
                            "result": tc.get("result"),
                            "error": tc.get("error"),
                            "status": tc.get("status", "completed"),
                            "ts": result.final_ts,
                        }
                    )
                elif isinstance(tc, str):
                    result.tool_calls.append({"name": tc, "ts": result.final_ts})
            exec_data = data.get("executive", {})
            if exec_data.get("goal_id"):
                result.goal_id = exec_data.get("goal_id")
                result.goal_state = exec_data.get("state")
        else:
            result.error = f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code in (500, 502, 503, 504):
                result.classification = "SERVICE_UNAVAILABLE"
            else:
                result.classification = "FAIL"
    except httpx.TimeoutException:
        result.error = f"Timeout after {timeout}s"
        result.classification = "FAIL"
        result.final_ts = time.time()
    except Exception as e:
        result.error = str(e)
        result.classification = "FAIL"
        result.final_ts = time.time()

    if result.goal_id:
        enrich_result_with_mission_evidence(result)
    return result


def save_result(result: BlackBoxResult, phase_dir: Path):
    """Save all evidence for a test result."""
    test_dir = phase_dir / result.test_id
    test_dir.mkdir(parents=True, exist_ok=True)
    result.evidence_dir = str(test_dir)

    (test_dir / "request.txt").write_text(result.prompt)
    (test_dir / "response.txt").write_text(result.response_text)
    (test_dir / "result.json").write_text(json.dumps(result.to_dict(), indent=2))
    (test_dir / "events.jsonl").write_text("\n".join(json.dumps(e) for e in result.events))
    (test_dir / "tool_calls.json").write_text(json.dumps(result.tool_calls, indent=2))
    (test_dir / "tool_events.jsonl").write_text("\n".join(json.dumps(tc) for tc in result.tool_calls))


if __name__ == "__main__":
    up, health = ensure_server()
    print(f"Server up: {up}, health: {health}")
    if up:
        r = submit_chat("Say hello and tell me today's date.", "test_hello")
        print(f"Response: {r.response_text[:200]}")
        print(f"Tool calls: {r.tool_calls}")
        print(f"Latency: {r.total_ms():.0f}ms")
