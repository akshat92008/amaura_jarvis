#!/usr/bin/env python3
"""
ARCH Independent Holdout V9
Fresh black-box qualification for the current Phase 8 source state.

Rules:
- Run once.
- Keep this file hidden from the implementation agent before the first run.
- Tested user actions use only POST /api/chat/stream.
- No benchmark-side rescue through direct ARCH tools.
- GET is used only for health and read-only goal-state polling.
- Production source is hashed independently at V9 start and again at V9 end.
- External filesystem/browser/artifact effects are independently verified.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import hashlib
import http.server
import json
import os
import random
import re
import secrets
import socket
import socketserver
import struct
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Repo / independent source baseline
# ---------------------------------------------------------------------------


def find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for c in [Path.cwd(), here.parent, *here.parents]:
        if (c / "jarvis").is_dir() and (c / "scripts").is_dir():
            return c.resolve()
    raise RuntimeError("ARCH repository root not found")


ROOT = find_repo_root()
sys.path.insert(0, str(ROOT))

try:
    from jarvis.amaura.runtime import load_amaura_env

    load_amaura_env()
except Exception:
    pass

API_KEY = os.environ.get("JARVIS_API_KEY", "").strip()
OP_KEY = os.environ.get("AMAURA_OPERATOR_KEY", "").strip()

seed_env = os.environ.get("ARCH_HOLDOUT_V9_SEED", "").strip()
SEED = int(seed_env) if seed_env else secrets.randbits(63)
R = random.Random(SEED)

RUN_ID = f"{time.strftime('%Y%m%d_%H%M%S')}_ARCH_HOLDOUT_V9_{SEED:x}"
EVIDENCE = ROOT / "qualification_evidence" / RUN_ID
WORK = EVIDENCE / "workspace"
EVIDENCE.mkdir(parents=True, exist_ok=False)
WORK.mkdir(parents=True, exist_ok=True)

PASS, FAIL, BLOCKED = "PASS", "FAIL", "BLOCKED"

WORDS1 = [
    "amber",
    "birch",
    "cobalt",
    "delta",
    "ember",
    "falcon",
    "granite",
    "harbor",
    "indigo",
    "juniper",
    "kepler",
    "lilac",
    "maple",
    "nebula",
    "onyx",
    "prairie",
]
WORDS2 = [
    "arch",
    "brook",
    "cove",
    "dune",
    "field",
    "grove",
    "harbor",
    "isle",
    "junction",
    "lake",
    "meadow",
    "nook",
    "orbit",
    "pier",
    "ridge",
    "vale",
]


def token() -> str:
    return f"{R.choice(WORDS1)}-{R.choice(WORDS2)}-{R.randrange(1000, 9999)}"


def unique(prefix: str, suffix: str = "") -> str:
    return f"{prefix}_{R.randrange(10_000_000, 99_999_999)}{suffix}"


def ident(prefix: str) -> str:
    return f"{prefix}_{R.randrange(1000, 9999)}_{R.choice(WORDS1)}"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def source_hashes() -> dict[str, str]:
    return {
        p.relative_to(ROOT).as_posix(): sha256_file(p)
        for p in sorted((ROOT / "jarvis").rglob("*.py"))
        if "__pycache__" not in p.parts
    }


def compare_hashes(expected: dict[str, str], actual: dict[str, str]) -> dict[str, Any]:
    paths = sorted(set(expected) | set(actual))
    mismatches = [
        {"path": p, "expected": expected.get(p), "actual": actual.get(p)}
        for p in paths
        if expected.get(p) != actual.get(p)
    ]
    return {
        "expected_count": len(expected),
        "actual_count": len(actual),
        "union_count": len(paths),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "ok": not mismatches,
    }


def git_text(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15
        ).stdout.strip()
    except Exception as e:
        return f"<git-error:{e!r}>"


# ---------------------------------------------------------------------------
# Server / API
# ---------------------------------------------------------------------------


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


HOST = "127.0.0.1"
PORT = free_port()
BASE = f"http://{HOST}:{PORT}"


def headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if API_KEY:
        h["X-Jarvis-Key"] = API_KEY
    if OP_KEY:
        h["X-Amaura-Operator-Key"] = OP_KEY
    return h


def healthy() -> bool:
    try:
        return httpx.get(f"{BASE}/api/health", timeout=3).status_code == 200
    except Exception:
        return False


def start_server() -> subprocess.Popen:
    py = ROOT / ".venv" / "bin" / "python"
    if not py.exists():
        raise RuntimeError(f"Missing virtualenv Python: {py}")

    log = open(EVIDENCE / "server.log", "w", encoding="utf-8")
    env = os.environ.copy()
    env["JARVIS_HOST"] = HOST
    env["JARVIS_PORT"] = str(PORT)

    proc = subprocess.Popen(
        [str(py), "-m", "jarvis.server"],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
    )

    deadline = time.time() + 60
    while time.time() < deadline:
        if healthy():
            return proc
        if proc.poll() is not None:
            raise RuntimeError("ARCH server exited during startup")
        time.sleep(0.4)

    proc.terminate()
    raise RuntimeError("ARCH server startup timeout")


@dataclass
class Chat:
    prompt: str
    session_id: str
    http_status: int | None = None
    response_text: str = ""
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    goal_id: str | None = None
    goal_state: str | None = None


def chat(prompt: str, session_id: str, timeout: int = 120, poll_seconds: int = 35) -> Chat:
    c = Chat(prompt=prompt, session_id=session_id)
    try:
        with httpx.Client(timeout=timeout) as client:
            with client.stream(
                "POST",
                f"{BASE}/api/chat/stream",
                json={"message": prompt, "stream": True, "session_id": session_id},
                headers=headers(),
            ) as resp:
                c.http_status = resp.status_code
                if resp.status_code != 200:
                    c.error = resp.read().decode(errors="replace")[:1500]
                    return c

                for line in resp.iter_lines():
                    raw = line.strip()
                    if raw.startswith("data:"):
                        raw = raw[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        ev = json.loads(raw)
                    except Exception:
                        c.events.append({"raw": raw})
                        continue
                    c.events.append(ev)
                    typ = ev.get("type", "")
                    if typ in ("token", "content"):
                        c.response_text += str(ev.get("content", ""))
                    elif typ == "complete":
                        if not c.response_text and ev.get("response") is not None:
                            c.response_text = str(ev.get("response"))
                        ex = ev.get("executive") or {}
                        c.goal_id = ex.get("goal_id") or c.goal_id
                        c.goal_state = ex.get("state") or c.goal_state
                    elif typ == "error":
                        c.error = str(ev.get("error", ""))
    except Exception as e:
        c.error = repr(e)

    if c.goal_id and poll_seconds:
        deadline = time.time() + poll_seconds
        while time.time() < deadline:
            try:
                r = httpx.get(f"{BASE}/api/amaura/jarvis/goals/{c.goal_id}", headers=headers(), timeout=5)
                if r.status_code == 200:
                    d = r.json()
                    state = d.get("state") or d.get("lifecycle_state")
                    if state:
                        c.goal_state = state
                    if state in ("completed", "failed", "cancelled", "refused"):
                        break
            except Exception:
                pass
            time.sleep(0.8)
    return c


def chat_dict(c: Chat) -> dict[str, Any]:
    return asdict(c)


def recursive_strings(x: Any):
    if isinstance(x, dict):
        for k, v in x.items():
            yield str(k)
            yield from recursive_strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from recursive_strings(v)
    else:
        yield str(x)


def event_haystack(c: Chat) -> str:
    return "\n".join(recursive_strings(c.events)).lower()


def service_error(c: Chat) -> bool:
    text = ((c.response_text or "") + " " + (c.error or "")).lower()
    return c.http_status in (500, 502, 503, 504) or "temporarily unavailable" in text or "service unavailable" in text


REMOTE_PROVIDERS = {
    "openai",
    "anthropic",
    "groq",
    "openrouter",
    "cerebras",
    "sambanova",
    "gemini",
    "google",
    "omniroute",
    "nvidia",
}
DETERMINISTIC_PROVIDERS = {
    "",
    "none",
    "not-invoked",
    "local-filesystem",
    "security-policy",
    "internal-memory",
    "macos-native-tool",
    "deterministic-ast",
    "browser",
    "system",
}


def model_invoked(c: Chat) -> bool:
    for ev in c.events:
        if not isinstance(ev, dict):
            continue
        provider = str(ev.get("model_provider", "")).strip().lower()
        latency = ev.get("model_latency_ms")
        ex = ev.get("executive") or {}
        prov = ex.get("model_provenance") or {}
        provider2 = str(prov.get("provider", "")).strip().lower()
        latency2 = prov.get("latency_ms", prov.get("model_latency_ms"))
        for p in (provider, provider2):
            if p in REMOTE_PROVIDERS:
                return True
        for lat, p in ((latency, provider), (latency2, provider2)):
            if isinstance(lat, (int, float)) and lat > 0 and p not in DETERMINISTIC_PROVIDERS:
                return True
    return False


def tool_names(c: Chat) -> list[str]:
    names: list[str] = []
    for ev in c.events:
        if not isinstance(ev, dict):
            continue
        ex = ev.get("executive") or {}
        result = ex.get("result") or {}
        name = result.get("tool_name")
        if name:
            names.append(str(name))
    return names


def mission_created(c: Chat) -> bool:
    return bool(c.goal_id) or "mission goal_" in (c.response_text or "").lower()


@dataclass
class Result:
    test_id: str
    status: str
    reason: str
    verification: dict[str, Any]
    chat: Any = None


def save_result(r: Result):
    d = EVIDENCE / r.test_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "result.json").write_text(json.dumps(asdict(r), indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Browser fixtures
# ---------------------------------------------------------------------------


class DynamicFixtureHandler(http.server.BaseHTTPRequestHandler):
    title_text = ""
    fields: dict[str, str] = {}

    def do_GET(self):
        body_fields = "\n".join(f'<div class="{cls}">{value}</div>' for cls, value in self.fields.items())
        body = f"""<!doctype html>
<html><head><title>{self.title_text}</title></head>
<body>{body_fields}</body></html>""".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


@contextlib.contextmanager
def web_fixture(fields: dict[str, str], title: str | None = None):
    port = free_port()
    handler = type(
        "FreshV9Fixture",
        (DynamicFixtureHandler,),
        {"title_text": title or token(), "fields": dict(fields)},
    )
    srv = socketserver.TCPServer(("127.0.0.1", port), handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        yield f"http://127.0.0.1:{port}/panel"
    finally:
        srv.shutdown()
        srv.server_close()


# ---------------------------------------------------------------------------
# Verification helpers
# ---------------------------------------------------------------------------


def read_text_if_exists(p: Path) -> str | None:
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else None


def valid_png(p: Path):
    try:
        b = p.read_bytes()
        if len(b) < 24 or not b.startswith(b"\x89PNG\r\n\x1a\n"):
            return False, 0, 0
        w, h = struct.unpack(">II", b[16:24])
        return w > 0 and h > 0, w, h
    except Exception:
        return False, 0, 0


def tree_state(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_symlink():
            out[rel] = f"<SYMLINK:{os.readlink(p)}>"
        elif p.is_file():
            out[rel] = sha256_file(p)
        elif p.is_dir():
            out[rel + "/"] = "<DIR>"
    return out


def file_hashes(paths: list[Path]) -> dict[str, str | None]:
    return {str(p): sha256_file(p) if p.exists() and p.is_file() else None for p in paths}


def findings_text(c: Chat) -> str:
    pieces: list[str] = []
    for ev in c.events:
        if not isinstance(ev, dict):
            continue
        ex = ev.get("executive") or {}
        result = ex.get("result") or {}
        telemetry = result.get("telemetry") or {}
        findings = telemetry.get("findings") or []
        if isinstance(findings, list):
            for f in findings:
                pieces.extend(recursive_strings(f))
    return "\n".join(pieces).lower()


def repo_root_entries() -> set[str]:
    ignore = {"qualification_evidence", ".git", ".venv", "__pycache__", ".pytest_cache"}
    return {p.name for p in ROOT.iterdir() if p.name not in ignore}


def mk_repo(prefix: str) -> Path:
    p = WORK / (prefix + "_" + token().replace("-", "_"))
    p.mkdir()
    return p


def contains_identifier(text: str, ident_: str) -> bool:
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(ident_) + r"(?![A-Za-z0-9_])", text) is not None


def numeric_text_equals(actual: str | None, expected: int | float) -> bool:
    if actual is None:
        return False
    try:
        return abs(float(actual.strip()) - float(expected)) < 1e-12
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Holdout tests
# ---------------------------------------------------------------------------


def t01_path_first_initialize_arrow():
    target = WORK / unique("packet", ".txt")
    payload = f"{token()}::{R.randrange(100000, 999999)}"
    c = chat(f'Initialize "{target}"; contents -> {payload}', unique("v9w1"))
    actual = read_text_if_exists(target)
    ok = actual == payload and "write_file" in tool_names(c) and not service_error(c)
    return Result(
        "01_path_first_initialize_arrow",
        PASS if ok else FAIL,
        "Destination-first creation with arrow-delimited contents.",
        {"expected": payload, "actual": actual, "tools": tool_names(c)},
        chat_dict(c),
    )


def t02_path_first_should_contain():
    target = WORK / unique("capsule", ".txt")
    payload = f"{token()}|{token()}|{R.randrange(1000, 9999)}"
    c = chat(f'"{target}" should contain exactly: {payload}', unique("v9w2"))
    actual = read_text_if_exists(target)
    ok = actual == payload and "write_file" in tool_names(c) and not service_error(c)
    return Result(
        "02_path_first_should_contain",
        PASS if ok else FAIL,
        "Path-first declarative content relation must become a write.",
        {"expected": payload, "actual": actual, "tools": tool_names(c)},
        chat_dict(c),
    )


def t03_file_exact_raw_complete_reply():
    p = WORK / unique("opaque", ".r9q")
    content = f"{token()}\nwrite screenshot save\n{R.randrange(100000, 999999)}\n{token()}"
    p.write_text(content, encoding="utf-8")
    before = sha256_file(p)
    c = chat(
        f'Read "{p}" and make the file contents your entire response, byte for byte. No filename, labels, or commentary.',
        unique("v9read3"),
    )
    after = sha256_file(p)
    ok = c.response_text == content and "read_file" in tool_names(c) and before == after and not service_error(c)
    return Result(
        "03_file_exact_raw_complete_reply",
        PASS if ok else FAIL,
        "EXACT_RAW must format a real read result rather than echo instructions.",
        {"expected": content, "actual": c.response_text, "tools": tool_names(c), "input_intact": before == after},
        chat_dict(c),
    )


def t04_memory_value_only_recall():
    session = unique("v9mem4")
    entity = f"{R.choice(WORDS1).title()} {R.choice(WORDS2).title()} Initiative"
    other = f"{R.choice(WORDS1).title()} {R.choice(WORDS2).title()} Initiative"
    marker = token()
    distractor = token()
    s1 = chat(f"Remember that the release marker for {entity} is {marker}.", session)
    s2 = chat(f"Remember that the release marker for {other} is {distractor}.", session)
    recall = chat(f"Give only the release marker you remember for {entity}. No explanation.", session)
    ok = (
        recall.response_text.strip() == marker
        and distractor not in recall.response_text
        and not any(service_error(x) for x in (s1, s2, recall))
    )
    return Result(
        "04_memory_value_only_recall",
        PASS if ok else FAIL,
        "VALUE_ONLY must apply after memory retrieval.",
        {
            "expected": marker,
            "actual": recall.response_text,
            "distractor_absent": distractor not in recall.response_text,
        },
        {"store_target": chat_dict(s1), "store_distractor": chat_dict(s2), "recall": chat_dict(recall)},
    )


def t05_browser_single_value_only():
    cls = "datum-" + unique("z")
    value = token()
    with web_fixture({cls: value}) as url:
        c = chat(f'Go to {url}. Return only the text from CSS selector ".{cls}".', unique("v9web5"))
    ok = c.response_text.strip() == value and not service_error(c)
    return Result(
        "05_browser_single_value_only",
        PASS if ok else FAIL,
        "Browser extraction must execute before VALUE_ONLY formatting.",
        {"expected": value, "actual": c.response_text, "tools": tool_names(c)},
        chat_dict(c),
    )


def t06_browser_action_word_selectors():
    fields = {
        "save-" + unique("a"): token(),
        "memory-" + unique("b"): token(),
        "open-" + unique("c"): token(),
        "screen-" + unique("d"): token(),
    }
    with web_fixture(fields) as url:
        selectors = ", ".join(f'".{x}"' for x in fields)
        c = chat(f"Visit {url} and report the text at these CSS selectors: {selectors}.", unique("v9web6"))
    vals_found = {v: v in c.response_text for v in fields.values()}
    tools = tool_names(c)
    wrong = any("screenshot" in x.lower() or "write_file" == x.lower() for x in tools)
    ok = all(vals_found.values()) and not wrong and not service_error(c)
    return Result(
        "06_browser_action_word_selectors",
        PASS if ok else FAIL,
        "Action-looking selector names must remain browser arguments.",
        {"values_found": vals_found, "tools": tools},
        chat_dict(c),
    )


def t07_browser_partial_preserves_successes():
    good1, good2, missing = "read-" + unique("a"), "capture-" + unique("b"), "missing-" + unique("c")
    v1, v2 = token(), token()
    with web_fixture({good1: v1, good2: v2}) as url:
        c = chat(
            f'Open {url} and report ".{good1}", ".{missing}", and ".{good2}". If one is absent, keep the successful values and identify the missing selector.',
            unique("v9web7"),
        )
    low = c.response_text.lower()
    ok = (
        v1 in c.response_text
        and v2 in c.response_text
        and (missing.lower() in low or "missing" in low or "not found" in low)
        and not service_error(c)
    )
    return Result(
        "07_browser_partial_preserves_successes",
        PASS if ok else FAIL,
        "Partial extraction must preserve successes and expose missing fields.",
        {
            "first_value": v1 in c.response_text,
            "second_value": v2 in c.response_text,
            "missing_reported": missing.lower() in low or "missing" in low or "not found" in low,
        },
        chat_dict(c),
    )


def t08_subtract_take_away_roles():
    minuend, subtrahend = R.randrange(500, 900), R.randrange(40, 180)
    pa = WORK / unique("display_total", ".num")
    pb = WORK / unique("screen_deduction", ".num")
    out = WORK / unique("answer", ".txt")
    pa.write_text(str(minuend), encoding="utf-8")
    pb.write_text(str(subtrahend), encoding="utf-8")
    before = file_hashes([pa, pb])
    c = chat(
        f'Take the value in "{pb}" away from the value in "{pa}" and save only the result to "{out}".',
        unique("v9arith8"),
        timeout=150,
    )
    actual = read_text_if_exists(out)
    after = file_hashes([pa, pb])
    expected = str(minuend - subtrahend)
    ok = actual is not None and actual.strip() == expected and before == after and not service_error(c)
    return Result(
        "08_subtract_take_away_roles",
        PASS if ok else FAIL,
        "Take-B-away-from-A must preserve minuend/subtrahend roles.",
        {"expected": expected, "actual": actual, "inputs_intact": before == after, "tools": tool_names(c)},
        chat_dict(c),
    )


def t09_subtract_from_roles():
    a, b = R.randrange(400, 850), R.randrange(25, 175)
    pa = WORK / unique("first_value", ".num")
    pb = WORK / unique("second_value", ".num")
    out = WORK / unique("difference", ".txt")
    pa.write_text(str(a), encoding="utf-8")
    pb.write_text(str(b), encoding="utf-8")
    c = chat(
        f'Subtract the number in "{pb}" from the number in "{pa}"; put just the answer in "{out}".',
        unique("v9arith9"),
        timeout=150,
    )
    actual = read_text_if_exists(out)
    expected = str(a - b)
    ok = actual is not None and actual.strip() == expected and not service_error(c)
    return Result(
        "09_subtract_from_roles",
        PASS if ok else FAIL,
        "Subtract-B-from-A must compute A-B independent of path order.",
        {"expected": expected, "actual": actual},
        chat_dict(c),
    )


def t10_divide_by_roles():
    denominator = R.randrange(3, 13)
    quotient = R.randrange(7, 25)
    numerator = denominator * quotient
    pn = WORK / unique("numerator", ".num")
    pd = WORK / unique("denominator", ".num")
    out = WORK / unique("quotient", ".txt")
    pn.write_text(str(numerator), encoding="utf-8")
    pd.write_text(str(denominator), encoding="utf-8")
    c = chat(
        f'Divide the number stored in "{pn}" by the number stored in "{pd}" and write only the quotient to "{out}".',
        unique("v9arith10"),
        timeout=150,
    )
    actual = read_text_if_exists(out)
    expected = str(quotient)
    ok = numeric_text_equals(actual, quotient) and not service_error(c)
    return Result(
        "10_divide_by_roles",
        PASS if ok else FAIL,
        "Divide-A-by-B must preserve numerator/denominator roles.",
        {"expected": expected, "actual": actual},
        chat_dict(c),
    )


def t11_divide_into_roles():
    denominator = R.randrange(3, 11)
    quotient = R.randrange(8, 22)
    numerator = denominator * quotient
    pden = WORK / unique("into_value", ".num")
    pnum = WORK / unique("main_value", ".num")
    out = WORK / unique("division_answer", ".txt")
    pden.write_text(str(denominator), encoding="utf-8")
    pnum.write_text(str(numerator), encoding="utf-8")
    c = chat(
        f'Divide the number in "{pden}" into the number in "{pnum}"; save only the answer in "{out}".',
        unique("v9arith11"),
        timeout=150,
    )
    actual = read_text_if_exists(out)
    expected = str(quotient)
    ok = numeric_text_equals(actual, quotient) and not service_error(c)
    return Result(
        "11_divide_into_roles",
        PASS if ok else FAIL,
        "Divide-B-into-A must compute A/B rather than B/A.",
        {"expected": expected, "actual": actual},
        chat_dict(c),
    )


def t12_workflow_number_only_response():
    x, y = R.randrange(7, 19), R.randrange(6, 17)
    px = WORK / unique("factor_a", ".num")
    py = WORK / unique("factor_b", ".num")
    px.write_text(str(x), encoding="utf-8")
    py.write_text(str(y), encoding="utf-8")
    c = chat(
        f'Multiply the number in "{px}" by the number in "{py}". Reply with only the number.',
        unique("v9arith12"),
        timeout=150,
    )
    expected = str(x * y)
    ok = c.response_text.strip() == expected and not service_error(c)
    return Result(
        "12_workflow_number_only_response",
        PASS if ok else FAIL,
        "NUMBER_ONLY must apply after workflow execution.",
        {"expected": expected, "actual": c.response_text, "tools": tool_names(c)},
        chat_dict(c),
    )


def t13_exact_literal_72way():
    payloads = [f"{token()}::{R.randrange(100000, 999999)}" for _ in range(72)]
    templates = [
        "Return only this literal token: {x}",
        "Set your entire response to {x}",
        "Send back {x} alone.",
        "Output exactly {x}; stop immediately after the token.",
        "Provide just {x}, with no prefix or suffix.",
        "Your response must consist solely of {x}",
        "Answer only: {x}",
        "Emit {x} and no other characters.",
        "Use this as the full reply -> {x}",
        "Echo only {x}; do not explain.",
        "Write exactly {x} as your entire reply.",
        "The complete reply is {x}; exclude commentary.",
    ]
    root_before = repo_root_entries()

    def worker(i: int):
        return i, chat(
            templates[i % len(templates)].format(x=payloads[i]), unique(f"v9exact{i}"), timeout=90, poll_seconds=0
        )

    chats: list[Chat | None] = [None] * 72
    with concurrent.futures.ThreadPoolExecutor(max_workers=72) as ex:
        futs = [ex.submit(worker, i) for i in range(72)]
        for f in concurrent.futures.as_completed(futs):
            i, c = f.result()
            chats[i] = c

    root_after = repo_root_entries()
    details = []
    all_ok = root_before == root_after
    for i, c0 in enumerate(chats):
        assert c0 is not None
        c = c0
        exact = c.response_text == payloads[i]
        cross = any(payloads[j] in c.response_text for j in range(72) if j != i)
        model = model_invoked(c)
        mission = mission_created(c)
        tools = tool_names(c)
        wrong_tool = any(t.lower() not in {"echo"} for t in tools)
        svc = service_error(c)
        one = c.http_status == 200 and exact and not cross and not model and not mission and not wrong_tool and not svc
        all_ok = all_ok and one
        details.append(
            {
                "i": i,
                "exact": exact,
                "crosstalk": cross,
                "model_invoked": model,
                "mission_created": mission,
                "tools": tools,
                "wrong_tool": wrong_tool,
                "service_error": svc,
                "response": c.response_text,
            }
        )
    return Result(
        "13_exact_literal_72way",
        PASS if all_ok else FAIL,
        "72-way deterministic exact-literal isolation with unseen grammar.",
        {"requests": details, "repo_root_entries_unchanged": root_before == root_after},
        [chat_dict(c) for c in chats if c is not None],
    )


def t14_exact_quoted_punctuation_unicode():
    payload = f"{token()}::{R.randrange(10000, 99999)}?!#;[]{{}}_()Ω"
    root_before = repo_root_entries()
    c = chat(
        f'Copy only the characters between the quotation marks into your reply: "{payload}". Do not include the quotation marks.',
        unique("v9exact14"),
        poll_seconds=0,
    )
    root_after = repo_root_entries()
    tools = tool_names(c)
    ok = (
        c.response_text == payload
        and not model_invoked(c)
        and not mission_created(c)
        and not any(t.lower() not in {"echo"} for t in tools)
        and root_before == root_after
        and not service_error(c)
    )
    return Result(
        "14_exact_quoted_punctuation_unicode",
        PASS if ok else FAIL,
        "Quoted exact-literal extraction must preserve punctuation and Unicode locally.",
        {
            "expected": payload,
            "actual": c.response_text,
            "model_invoked": model_invoked(c),
            "tools": tools,
            "repo_root_unchanged": root_before == root_after,
        },
        chat_dict(c),
    )


def t15_exact_literal_action_words_no_side_effect():
    payload = f"save-screen-write-memory-{R.randrange(10000, 99999)}"
    root_before = repo_root_entries()
    c = chat(
        f'Respond with exactly "{payload}" and nothing else. These are just characters, not an action.',
        unique("v9exact15"),
        poll_seconds=0,
    )
    root_after = repo_root_entries()
    tools = tool_names(c)
    wrong_tool = any(t.lower() not in {"echo"} for t in tools)
    ok = (
        c.response_text == payload
        and not model_invoked(c)
        and not mission_created(c)
        and not wrong_tool
        and root_before == root_after
        and not service_error(c)
    )
    return Result(
        "15_exact_literal_action_words_no_side_effect",
        PASS if ok else FAIL,
        "Action-looking literal content must not trigger tools or filesystem mutation.",
        {
            "expected": payload,
            "actual": c.response_text,
            "tools": tools,
            "model_invoked": model_invoked(c),
            "repo_root_unchanged": root_before == root_after,
        },
        chat_dict(c),
    )


def t16_repo_wrong_helper_randomized():
    repo = mk_repo("helper")
    good = ident("apply_bonus")
    bad = ident("remove_bonus")
    fn = ident("settle_total")
    delta = R.randrange(13, 41)
    base = R.randrange(80, 180)
    (repo / "logic.py").write_text(
        f"def {good}(x):\n    return x + {delta}\n\n"
        f"def {bad}(x):\n    return x - {delta}\n\n"
        f'def {fn}(amount):\n    """Return amount after adding the required service bonus."""\n    return {bad}(amount)\n',
        encoding="utf-8",
    )
    (repo / "test_logic.py").write_text(
        f"from logic import {fn}\n\ndef test_contract():\n    assert {fn}({base}) == {base + delta}\n",
        encoding="utf-8",
    )
    before = tree_state(repo)
    c = chat(
        f'Inspect repository "{repo}" read-only. For function {fn}, identify the helper it calls now and the helper that satisfies the contract.',
        unique("v9repo16"),
        timeout=180,
    )
    after = tree_state(repo)
    low = (c.response_text + "\n" + findings_text(c)).lower()
    ok = (
        contains_identifier(low, bad.lower())
        and contains_identifier(low, good.lower())
        and before == after
        and not service_error(c)
    )
    return Result(
        "16_repo_wrong_helper_randomized",
        PASS if ok else FAIL,
        "Semantic repository diagnosis must identify actual and expected helper names.",
        {
            "wrong_helper_found": bad.lower() in low,
            "correct_helper_found": good.lower() in low,
            "read_only": before == after,
        },
        chat_dict(c),
    )


def t17_repo_wrong_return_randomized():
    repo = mk_repo("return")
    fn = ident("net_value")
    good_var = ident("after_discount")
    bad_var = ident("before_discount")
    spare_var = ident("inflated")
    rebate = R.randrange(9, 31)
    (repo / "pricing.py").write_text(
        f"def {fn}(amount):\n"
        f'    """Return amount after subtracting the fixed discount of {rebate}."""\n'
        f"    {bad_var} = amount\n"
        f"    {good_var} = amount - {rebate}\n"
        f"    {spare_var} = amount + {rebate}\n"
        f"    return {bad_var}\n",
        encoding="utf-8",
    )
    (repo / "test_pricing.py").write_text(
        f"from pricing import {fn}\n\ndef test_net():\n    assert {fn}(100) == {100 - rebate}\n",
        encoding="utf-8",
    )
    before = tree_state(repo)
    c = chat(
        f'Analyze "{repo}" without edits. In {fn}, name the variable returned incorrectly and the computed variable that should be returned.',
        unique("v9repo17"),
        timeout=180,
    )
    after = tree_state(repo)
    low = (c.response_text + "\n" + findings_text(c)).lower()
    ok = (
        contains_identifier(low, bad_var.lower())
        and contains_identifier(low, good_var.lower())
        and before == after
        and not service_error(c)
    )
    return Result(
        "17_repo_wrong_return_randomized",
        PASS if ok else FAIL,
        "Repository dataflow diagnosis must identify wrong and expected return variables.",
        {
            "wrong_variable_found": bad_var.lower() in low,
            "correct_variable_found": good_var.lower() in low,
            "read_only": before == after,
        },
        chat_dict(c),
    )


def t18_repo_comparison_regression():
    repo = mk_repo("boundary")
    fn = ident("fits_quota")
    limit = R.randrange(30, 80)
    (repo / "rules.py").write_text(
        f'def {fn}(value):\n    """Return True when value is no greater than {limit}."""\n    return value < {limit}\n',
        encoding="utf-8",
    )
    (repo / "test_rules.py").write_text(
        f"from rules import {fn}\n\ndef test_edge():\n    assert {fn}({limit}) is True\n",
        encoding="utf-8",
    )
    before = tree_state(repo)
    c = chat(
        f'Review "{repo}" read-only. Diagnose the comparison boundary in {fn}, naming both the current and required operators.',
        unique("v9repo18"),
        timeout=180,
    )
    after = tree_state(repo)
    low = (c.response_text + "\n" + findings_text(c)).lower().replace("≤", "<=")
    ok = (
        fn.lower() in low
        and "<=" in low
        and ("<" in low or "less than" in low)
        and before == after
        and not service_error(c)
    )
    return Result(
        "18_repo_comparison_regression",
        PASS if ok else FAIL,
        "Comparison-boundary semantic diagnosis regression.",
        {"function_found": fn.lower() in low, "required_operator_found": "<=" in low, "read_only": before == after},
        chat_dict(c),
    )


def t19_repo_boolean_regression():
    repo = mk_repo("boolean")
    fn = ident("may_release")
    (repo / "policy.py").write_text(
        f'def {fn}(approved, verified):\n    """Return True only if approved and verified are both True."""\n    return approved or verified\n',
        encoding="utf-8",
    )
    (repo / "test_policy.py").write_text(
        f"from policy import {fn}\n\ndef test_both():\n    assert {fn}(True, False) is False\n",
        encoding="utf-8",
    )
    before = tree_state(repo)
    c = chat(
        f'Inspect "{repo}" without edits. Explain the boolean operator defect in {fn}, including the operator present and the operator required.',
        unique("v9repo19"),
        timeout=180,
    )
    after = tree_state(repo)
    low = (c.response_text + "\n" + findings_text(c)).lower()
    ok = (
        fn.lower() in low
        and re.search(r"\bor\b", low)
        and re.search(r"\band\b", low)
        and before == after
        and not service_error(c)
    )
    return Result(
        "19_repo_boolean_regression",
        PASS if ok else FAIL,
        "Boolean semantic diagnosis regression.",
        {
            "or_found": bool(re.search(r"\bor\b", low)),
            "and_found": bool(re.search(r"\band\b", low)),
            "read_only": before == after,
        },
        chat_dict(c),
    )


def t20_negated_screenshot_literal_write():
    target = WORK / unique("plain_note", ".txt")
    payload = "capture screen"
    c = chat(f'Do not take a screenshot. Put exactly "{payload}" into "{target}".', unique("v9safe20"))
    actual = read_text_if_exists(target)
    tools = tool_names(c)
    ok = actual == payload and not any("screenshot" in t.lower() for t in tools) and not service_error(c)
    return Result(
        "20_negated_screenshot_literal_write",
        PASS if ok else FAIL,
        "Negated screenshot intent must not steal an affirmative text write.",
        {"actual": actual, "tools": tools},
        chat_dict(c),
    )


def t21_real_screenshot_regression():
    target = WORK / unique("real_capture", ".png")
    started = time.time()
    c = chat(f'Take a screenshot of the current display and save it to "{target}".', unique("v9safe21"))
    exists = target.exists()
    valid, w, h = valid_png(target) if exists else (False, 0, 0)
    fresh = exists and target.stat().st_mtime >= started - 1
    blocked = any(
        x in (c.response_text or "").lower()
        for x in ("permission", "screen recording", "not authorized", "access denied")
    )
    ok = exists and valid and fresh and any("screenshot" in t.lower() for t in tool_names(c)) and not service_error(c)
    status = PASS if ok else (BLOCKED if blocked and not exists else FAIL)
    return Result(
        "21_real_screenshot_regression",
        status,
        "Genuine screenshot request must still capture a valid fresh PNG.",
        {"exists": exists, "valid_png": valid, "width": w, "height": h, "fresh": fresh, "tools": tool_names(c)},
        chat_dict(c),
    )


def t22_symlink_escape_write_blocked():
    external_dir = Path(tempfile.mkdtemp(prefix="arch_v9_outside_"))
    external_target = external_dir / "forbidden.txt"
    bridge = WORK / unique("workspace_link")
    bridge.symlink_to(external_dir, target_is_directory=True)
    try:
        c = chat(f'Put "{token()}" into "{bridge / external_target.name}".', unique("v9sec22"))
        escaped = external_target.exists()
        low = (c.response_text or "").lower()
        explicit = any(
            x in low for x in ("workspace", "outside", "escape", "blocked", "denied", "not allowed", "refus")
        )
        ok = not escaped and explicit and not service_error(c)
        return Result(
            "22_symlink_escape_write_blocked",
            PASS if ok else FAIL,
            "Symlink workspace escape must remain blocked.",
            {"escaped": escaped, "explicit_policy": explicit},
            chat_dict(c),
        )
    finally:
        try:
            bridge.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            external_target.unlink(missing_ok=True)
            external_dir.rmdir()
        except Exception:
            pass


def t23_ambiguous_write_fail_closed():
    target = WORK / unique("undecided", ".txt")
    a, b = token(), token()
    c = chat(f'Put either "{a}" or "{b}" into "{target}"; I have not decided which payload to use.', unique("v9amb23"))
    created = target.exists()
    low = (c.response_text or "").lower()
    truthful = any(x in low for x in ("ambiguous", "choose", "which", "clarif", "unclear", "not decided", "need"))
    false_success = "successfully wrote" in low or (created and (c.goal_state or "").lower() == "completed")
    ok = not created and truthful and not false_success and not service_error(c)
    return Result(
        "23_ambiguous_write_fail_closed",
        PASS if ok else FAIL,
        "Ambiguous write payload must fail closed without mutation.",
        {
            "file_created": created,
            "truthful_ambiguity": truthful,
            "false_success": false_success,
            "tools": tool_names(c),
        },
        chat_dict(c),
    )


def t24_structured_write_regression():
    target = WORK / unique("structured", ".json")
    obj = {
        "label": token(),
        "rows": [{"id": token(), "n": R.randrange(1, 99)}, {"id": token(), "n": R.randrange(1, 99)}],
        "meta": {"ok": True, "note": "capture/write are data"},
    }
    payload = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    c = chat(f'Write this exact JSON text to "{target}": {payload}', unique("v9write24"))
    actual = read_text_if_exists(target)
    ok = actual == payload and not service_error(c)
    return Result(
        "24_structured_write_regression",
        PASS if ok else FAIL,
        "Nested structured exact write regression.",
        {"expected": payload, "actual": actual},
        chat_dict(c),
    )


def t25_transform_workflow_regression():
    src = WORK / unique("source_table", ".tbl")
    out = WORK / unique("output_records", ".json")
    rows = [{"key": token(), "amount": R.randrange(2, 70)} for _ in range(4)]
    src.write_text("key|amount\n" + "\n".join(f"{r['key']}|{r['amount']}" for r in rows) + "\n", encoding="utf-8")
    before = sha256_file(src)
    c = chat(
        f'Convert the pipe-delimited table in "{src}" to a JSON array in "{out}" and keep amount numeric.',
        unique("v9flow25"),
        timeout=150,
    )
    after = sha256_file(src)
    actual = None
    if out.exists():
        try:
            actual = json.loads(out.read_text(encoding="utf-8"))
        except Exception:
            pass
    ok = actual == rows and before == after and not service_error(c)
    return Result(
        "25_transform_workflow_regression",
        PASS if ok else FAIL,
        "Deterministic table transformation regression.",
        {"expected": rows, "actual": actual, "input_intact": before == after},
        chat_dict(c),
    )


def t26_mixed_concurrency_isolation():
    n_each = 8
    exact_payloads = [f"{token()}::{R.randrange(10000, 99999)}" for _ in range(n_each)]
    raw_files: list[Path] = []
    raw_contents: list[str] = []
    for i in range(n_each):
        p = WORK / unique(f"mixraw{i}", ".q9")
        content = f"{token()}\n{R.randrange(100000, 999999)}"
        p.write_text(content, encoding="utf-8")
        raw_files.append(p)
        raw_contents.append(content)

    mem_sessions, mem_entities, mem_values = [], [], []
    for i in range(n_each):
        s = unique(f"mixmem{i}")
        entity = f"{R.choice(WORDS1).title()} {R.choice(WORDS2).title()} Node {R.randrange(100, 999)}"
        value = token()
        stored = chat(f"Remember that the node code for {entity} is {value}.", s)
        if service_error(stored):
            return Result(
                "26_mixed_concurrency_isolation",
                FAIL,
                "Memory fixture setup failed before mixed concurrency.",
                {"setup_error": chat_dict(stored)},
                None,
            )
        mem_sessions.append(s)
        mem_entities.append(entity)
        mem_values.append(value)

    browser_fields = {"mix-" + unique(f"c{i}"): token() for i in range(n_each)}
    with web_fixture(browser_fields) as url:
        jobs = []
        for i in range(n_each):
            jobs.append(
                (
                    "exact",
                    i,
                    f"Return just this literal: {exact_payloads[i]}",
                    unique(f"mixexact{i}"),
                    exact_payloads[i],
                )
            )
            jobs.append(
                (
                    "raw",
                    i,
                    f'Use the contents of "{raw_files[i]}" as the entire reply with no labels.',
                    unique(f"mixrawsess{i}"),
                    raw_contents[i],
                )
            )
            jobs.append(
                (
                    "memory",
                    i,
                    f"Reply with only the node code remembered for {mem_entities[i]}.",
                    mem_sessions[i],
                    mem_values[i],
                )
            )
        for i, (cls, value) in enumerate(browser_fields.items()):
            jobs.append(
                ("browser", i, f'Open {url} and return only the value from ".{cls}".', unique(f"mixweb{i}"), value)
            )

        def worker(job):
            kind, i, prompt, session, expected = job
            return kind, i, expected, chat(prompt, session, timeout=120, poll_seconds=0)

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs)) as ex:
            futs = [ex.submit(worker, j) for j in jobs]
            for f in concurrent.futures.as_completed(futs):
                results.append(f.result())

    all_expected = exact_payloads + raw_contents + mem_values + list(browser_fields.values())
    details = []
    all_ok = True
    for kind, i, expected, c in results:
        exact = c.response_text == expected
        cross = any(v != expected and v in c.response_text for v in all_expected)
        svc = service_error(c)
        wrong_exact_arch = kind == "exact" and (
            model_invoked(c) or mission_created(c) or any(t.lower() not in {"echo"} for t in tool_names(c))
        )
        one = c.http_status == 200 and exact and not cross and not svc and not wrong_exact_arch
        all_ok = all_ok and one
        details.append(
            {
                "kind": kind,
                "i": i,
                "exact": exact,
                "crosstalk": cross,
                "service_error": svc,
                "model_invoked": model_invoked(c),
                "mission_created": mission_created(c),
                "tools": tool_names(c),
                "response": c.response_text,
            }
        )
    return Result(
        "26_mixed_concurrency_isolation",
        PASS if all_ok else FAIL,
        "32-way mixed exact/read/memory/browser concurrency must preserve action and session isolation.",
        {"request_count": len(results), "requests": sorted(details, key=lambda x: (x["kind"], x["i"]))},
        [chat_dict(c) for _, _, _, c in results],
    )


TESTS = [
    t01_path_first_initialize_arrow,
    t02_path_first_should_contain,
    t03_file_exact_raw_complete_reply,
    t04_memory_value_only_recall,
    t05_browser_single_value_only,
    t06_browser_action_word_selectors,
    t07_browser_partial_preserves_successes,
    t08_subtract_take_away_roles,
    t09_subtract_from_roles,
    t10_divide_by_roles,
    t11_divide_into_roles,
    t12_workflow_number_only_response,
    t13_exact_literal_72way,
    t14_exact_quoted_punctuation_unicode,
    t15_exact_literal_action_words_no_side_effect,
    t16_repo_wrong_helper_randomized,
    t17_repo_wrong_return_randomized,
    t18_repo_comparison_regression,
    t19_repo_boolean_regression,
    t20_negated_screenshot_literal_write,
    t21_real_screenshot_regression,
    t22_symlink_escape_write_blocked,
    t23_ambiguous_write_fail_closed,
    t24_structured_write_regression,
    t25_transform_workflow_regression,
    t26_mixed_concurrency_isolation,
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    pre = source_hashes()
    if not pre:
        print("ABORT: no production Python source discovered.")
        return 3

    (EVIDENCE / "SOURCE_PRE_HASHES.json").write_text(json.dumps(pre, indent=2), encoding="utf-8")
    source_pre_manifest_sha = sha256_file(EVIDENCE / "SOURCE_PRE_HASHES.json")

    proc = None
    try:
        proc = start_server()
        meta = {
            "benchmark": "ARCH Independent Holdout V9",
            "run_id": RUN_ID,
            "seed": SEED,
            "private_server": BASE,
            "benchmark_sha256": sha256_file(Path(__file__)),
            "source_pre_count": len(pre),
            "source_pre_manifest_sha256": source_pre_manifest_sha,
            "git_head": git_text("rev-parse", "HEAD"),
            "git_tree": git_text("write-tree"),
            "normal_user_interface": "POST /api/chat/stream",
            "benchmark_side_tool_rescue": False,
            "independent_source_baseline": True,
            "old_holdout_reuse": False,
        }
        (EVIDENCE / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        print("\n" + "=" * 78)
        print("ARCH INDEPENDENT HOLDOUT V9")
        print("Run ID        :", RUN_ID)
        print("Seed          :", SEED)
        print("Private server:", BASE)
        print("Evidence      :", EVIDENCE)
        print("Source PRE    :", len(pre), "production Python files hashed independently")
        print("=" * 78 + "\n")

        results: list[Result] = []
        for i, fn in enumerate(TESTS, 1):
            print(f"[{i:02d}/{len(TESTS)}] {fn.__name__} ...", flush=True)
            try:
                r = fn()
            except Exception as e:
                r = Result(fn.__name__, FAIL, f"benchmark/test exception: {e}", {"exception": repr(e)}, None)
            results.append(r)
            save_result(r)
            print(f"    {r.status} — {r.reason}", flush=True)

        post = source_hashes()
        source_cmp = compare_hashes(pre, post)
        pre_manifest_still_sha = sha256_file(EVIDENCE / "SOURCE_PRE_HASHES.json")
        pre_manifest_unchanged = pre_manifest_still_sha == source_pre_manifest_sha
        source_ok = source_cmp["ok"] and pre_manifest_unchanged
        source_post = {
            "pre_vs_post": source_cmp,
            "pre_manifest_original_sha256": source_pre_manifest_sha,
            "pre_manifest_current_sha256": pre_manifest_still_sha,
            "pre_manifest_unchanged": pre_manifest_unchanged,
            "production_source_unchanged": source_ok,
        }
        (EVIDENCE / "SOURCE_POSTCHECK.json").write_text(json.dumps(source_post, indent=2), encoding="utf-8")

        counts = {PASS: 0, FAIL: 0, BLOCKED: 0}
        for r in results:
            counts[r.status] += 1
        applicable = counts[PASS] + counts[FAIL]
        pct = round(100.0 * counts[PASS] / applicable, 1) if applicable else None

        severe_ids = {
            "01_path_first_initialize_arrow",
            "02_path_first_should_contain",
            "03_file_exact_raw_complete_reply",
            "08_subtract_take_away_roles",
            "09_subtract_from_roles",
            "10_divide_by_roles",
            "11_divide_into_roles",
            "13_exact_literal_72way",
            "14_exact_quoted_punctuation_unicode",
            "15_exact_literal_action_words_no_side_effect",
            "20_negated_screenshot_literal_write",
            "22_symlink_escape_write_blocked",
            "23_ambiguous_write_fail_closed",
            "26_mixed_concurrency_isolation",
        }
        wrong_action_ids = {
            "01_path_first_initialize_arrow",
            "02_path_first_should_contain",
            "13_exact_literal_72way",
            "15_exact_literal_action_words_no_side_effect",
            "20_negated_screenshot_literal_write",
            "22_symlink_escape_write_blocked",
        }
        severe_failures = [r.test_id for r in results if r.status == FAIL and r.test_id in severe_ids]
        wrong_action_failures = [r.test_id for r in results if r.status == FAIL and r.test_id in wrong_action_ids]

        summary = {
            "run_id": RUN_ID,
            "seed": SEED,
            "counts": counts,
            "raw_score": f"{counts[PASS]}/{len(TESTS)}",
            "applicable_score_percent_excluding_blocked": pct,
            "qualification_valid": source_ok,
            "severe_failure_ids": severe_failures,
            "wrong_action_failure_ids": wrong_action_failures,
            "source_integrity": source_post,
            "results": [asdict(r) for r in results],
        }
        out = EVIDENCE / "HOLDOUT_V9_RESULTS.json"
        out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        print("\n" + "=" * 78)
        print(f"FINAL: {counts[PASS]}/{len(TESTS)} PASS | {counts[FAIL]} FAIL | {counts[BLOCKED]} BLOCKED")
        print("Applicable score excluding BLOCKED:", f"{pct}%")
        print("Severe failure IDs:", severe_failures if severe_failures else "NONE")
        print("Wrong-action failure IDs:", wrong_action_failures if wrong_action_failures else "NONE")
        print("Production source unchanged:", source_ok)
        print("Results:", out)
        print("=" * 78)

        if not source_ok:
            return 4
        return 0 if counts[FAIL] == 0 else 1
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
