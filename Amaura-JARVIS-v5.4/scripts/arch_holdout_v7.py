#!/usr/bin/env python3
"""
ARCH Independent Holdout v7
Fresh black-box qualification for the Phase 6 V2 frozen source.

Rules:
- Run once.
- Keep this file hidden from the implementation agent before the first run.
- Tested user actions use only POST /api/chat/stream.
- No benchmark-side rescue through direct ARCH tools.
- No POST goal/run calls.
- External effects are independently verified.
- Phase 6 V2 production source must match before and after the run.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import hashlib
import http.server
import json
import os
import random
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
# Repo / freeze
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

FREEZE_DIR = ROOT / "qualification_evidence" / "FINAL_PRE_HOLDOUT_FREEZE_PHASE6_V2"
FREEZE_HASHES = FREEZE_DIR / "FINAL_FREEZE_SOURCE_HASHES.json"

seed_env = os.environ.get("ARCH_HOLDOUT_V7_SEED", "").strip()
SEED = int(seed_env) if seed_env else secrets.randbits(63)
R = random.Random(SEED)

RUN_ID = f"{time.strftime('%Y%m%d_%H%M%S')}_ARCH_HOLDOUT_V7_{SEED:x}"
EVIDENCE = ROOT / "qualification_evidence" / RUN_ID
WORK = EVIDENCE / "workspace"
EVIDENCE.mkdir(parents=True, exist_ok=False)
WORK.mkdir(parents=True, exist_ok=True)

PASS, FAIL, BLOCKED = "PASS", "FAIL", "BLOCKED"

WORDS1 = [
    "aurora",
    "banyan",
    "cobalt",
    "dahlia",
    "ember",
    "falcon",
    "granite",
    "harbor",
    "iris",
    "juniper",
    "lotus",
    "marble",
    "nectar",
    "opal",
    "quartz",
    "river",
]
WORDS2 = [
    "arch",
    "basin",
    "cove",
    "delta",
    "field",
    "grove",
    "harbor",
    "junction",
    "lane",
    "meadow",
    "nook",
    "ridge",
    "spring",
    "trail",
    "valley",
    "wharf",
]


def token() -> str:
    return f"{R.choice(WORDS1)}-{R.choice(WORDS2)}-{R.randrange(1000, 9999)}"


def unique(prefix: str, suffix: str = "") -> str:
    return f"{prefix}_{R.randrange(10_000_000, 99_999_999)}{suffix}"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_manifest_key(k: str) -> str:
    p = Path(k)
    if p.is_absolute():
        try:
            return p.relative_to(ROOT).as_posix()
        except Exception:
            parts = p.parts
            if "jarvis" in parts:
                return Path(*parts[parts.index("jarvis") :]).as_posix()
    return p.as_posix().lstrip("./")


def load_frozen_hashes() -> dict[str, str]:
    raw = json.loads(FREEZE_HASHES.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for k, v in raw.items():
        nk = normalize_manifest_key(k)
        if isinstance(v, str):
            out[nk] = v
        elif isinstance(v, dict) and isinstance(v.get("sha256"), str):
            out[nk] = v["sha256"]
        else:
            raise RuntimeError(f"Unsupported freeze hash entry: {k}")
    return out


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

    # Read-only polling only. Never start/resume/approve goals.
    if c.goal_id and poll_seconds:
        deadline = time.time() + poll_seconds
        while time.time() < deadline:
            try:
                r = httpx.get(
                    f"{BASE}/api/amaura/jarvis/goals/{c.goal_id}",
                    headers=headers(),
                    timeout=5,
                )
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
    names = []
    for ev in c.events:
        if not isinstance(ev, dict):
            continue
        ex = ev.get("executive") or {}
        result = ex.get("result") or {}
        name = result.get("tool_name")
        if name:
            names.append(str(name))
    return names


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
# Web fixture
# ---------------------------------------------------------------------------


class FixtureHandler(http.server.BaseHTTPRequestHandler):
    title_text = ""
    c1 = ""
    c2 = ""
    c3 = ""
    v1 = ""
    v2 = ""
    v3 = ""

    def do_GET(self):
        body = f"""<!doctype html>
<html>
<head><title>{self.title_text}</title></head>
<body>
<div class="{self.c1}">{self.v1}</div>
<span class="{self.c2}">{self.v2}</span>
<p class="{self.c3}">{self.v3}</p>
</body>
</html>""".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


@contextlib.contextmanager
def web_fixture(title: str, c1: str, c2: str, c3: str, v1: str, v2: str, v3: str):
    port = free_port()
    handler = type(
        "FreshV7Fixture",
        (FixtureHandler,),
        {
            "title_text": title,
            "c1": c1,
            "c2": c2,
            "c3": c3,
            "v1": v1,
            "v2": v2,
            "v3": v3,
        },
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
        if p.is_file():
            out[rel] = sha256_file(p)
        elif p.is_dir():
            out[rel + "/"] = "<DIR>"
        elif p.is_symlink():
            out[rel] = f"<SYMLINK:{os.readlink(p)}>"
    return out


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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def t01_write_target_then_semicolon_payload():
    target = WORK / unique("record")
    payload = f"{token()}::{R.randrange(100000, 999999)}"
    prompt = f'Create file "{target}"; its complete contents must be {payload}'
    c = chat(prompt, unique("v7s1"))
    actual = target.read_text(errors="replace") if target.exists() else None
    ok = actual == payload and not service_error(c)
    return Result(
        "01_write_target_then_semicolon_payload",
        PASS if ok else FAIL,
        "Target-first semicolon payload.",
        {"expected": payload, "actual": actual, "exact": actual == payload},
        chat_dict(c),
    )


def t02_write_payload_before_target_with_modifier():
    target = WORK / unique("vault", ".dat")
    payload = f"{token()} {R.randrange(100, 999)}"
    prompt = f'Put precisely "{payload}" as the entire contents of "{target}".'
    c = chat(prompt, unique("v7s2"))
    actual = target.read_text(errors="replace") if target.exists() else None
    ok = actual == payload and not service_error(c)
    return Result(
        "02_write_payload_before_target_with_modifier",
        PASS if ok else FAIL,
        "Quoted payload must exclude modifiers.",
        {"expected": payload, "actual": actual, "exact": actual == payload},
        chat_dict(c),
    )


def t03_write_multiline_after_arrow():
    target = WORK / unique("notes", ".txt")
    payload = "\n".join([token(), f"{R.randrange(1000, 9999)} {token()}", token()])
    prompt = f'Write "{target}". The body is exactly ->\n{payload}'
    c = chat(prompt, unique("v7s3"))
    actual = target.read_text(errors="replace") if target.exists() else None
    ok = actual == payload and not service_error(c)
    return Result(
        "03_write_multiline_after_arrow",
        PASS if ok else FAIL,
        "Multiline block after arrow delimiter.",
        {"expected": payload, "actual": actual, "exact": actual == payload},
        chat_dict(c),
    )


def t04_write_exact_json_literal():
    target = WORK / unique("cfg", ".json")
    obj = {"id": token(), "count": R.randrange(2, 50), "enabled": bool(R.randrange(2))}
    payload = json.dumps(obj, separators=(",", ":"))
    prompt = f'In "{target}", store verbatim this JSON text: {payload}'
    c = chat(prompt, unique("v7s4"))
    actual = target.read_text(errors="replace") if target.exists() else None
    ok = actual == payload and not service_error(c)
    return Result(
        "04_write_exact_json_literal",
        PASS if ok else FAIL,
        "Exact JSON literal write.",
        {"expected": payload, "actual": actual, "exact": actual == payload},
        chat_dict(c),
    )


def t05_screenshot_paraphrase_precedence():
    target = WORK / unique("desktop_capture", ".png")
    started = time.time()
    c = chat(
        f'Grab the current desktop and store the image as "{target}".',
        unique("v7s5"),
    )
    exists = target.exists()
    fresh = exists and target.stat().st_mtime >= started - 1
    valid, w, h = valid_png(target) if exists else (False, 0, 0)
    names = tool_names(c)
    blocked = any(
        x in c.response_text.lower() for x in ("screen recording", "permission", "not authorized", "access denied")
    )
    routed_as_write = "write_file" in names
    ok = exists and fresh and valid and not routed_as_write and not service_error(c)
    return Result(
        "05_screenshot_paraphrase_precedence",
        PASS if ok else (BLOCKED if blocked and not routed_as_write else FAIL),
        "Screenshot wording must outrank generic file writing.",
        {
            "exists": exists,
            "fresh": fresh,
            "valid_png": valid,
            "width": w,
            "height": h,
            "tool_names": names,
            "routed_as_write": routed_as_write,
        },
        chat_dict(c),
    )


def t06_negative_screenshot_word_is_literal_write():
    target = WORK / unique("literal", ".txt")
    payload = "screenshot"
    c = chat(
        f'Write only the word "{payload}" into "{target}". Do not capture the display.',
        unique("v7s6"),
    )
    actual = target.read_text(errors="replace") if target.exists() else None
    names = tool_names(c)
    screenshot_tool = any("screenshot" in n.lower() for n in names)
    ok = actual == payload and not screenshot_tool and not service_error(c)
    return Result(
        "06_negative_screenshot_word_is_literal_write",
        PASS if ok else FAIL,
        "Literal word screenshot must not trigger screen capture.",
        {"actual": actual, "tool_names": names, "screenshot_tool_seen": screenshot_tool},
        chat_dict(c),
    )


def t07_directory_unseen_paraphrase():
    d = WORK / (unique("bundle") + ".pkg")
    d.mkdir()
    names = [unique("a"), unique("b", ".ini"), unique("c", ".data"), unique("d")]
    for n in names:
        (d / n).write_text(token())

    c = chat(
        f'Enumerate the immediate names contained by "{d}", without descending into subfolders.',
        unique("v7s7"),
    )
    found = {n: n in c.response_text for n in names}
    ok = all(found.values()) and not service_error(c)
    return Result(
        "07_directory_unseen_paraphrase",
        PASS if ok else FAIL,
        "Directory semantic routing regression.",
        {"found": found},
        chat_dict(c),
    )


def t08_raw_read_unknown_extension():
    p = WORK / unique("opaque", ".xyzq")
    content = f"{token()}\n{R.randrange(100000, 999999)}\n{token()}"
    p.write_text(content)
    c = chat(
        f'Give me exactly the bytes-as-text stored in "{p}" as your whole reply.',
        unique("v7s8"),
    )
    ok = c.response_text == content and not service_error(c)
    return Result(
        "08_raw_read_unknown_extension",
        PASS if ok else FAIL,
        "Unknown extension raw-read regression.",
        {"exact": c.response_text == content},
        chat_dict(c),
    )


def t09_browser_title_plus_three_selectors():
    title = f"{token()} console"
    cls = [unique("cell").replace("_", "-") for _ in range(3)]
    vals = [token(), token(), token()]

    with web_fixture(title, cls[0], cls[1], cls[2], vals[0], vals[1], vals[2]) as url:
        c = chat(
            f'Open {url}. Return its title and the values for ".{cls[0]}", ".{cls[1]}", and ".{cls[2]}".',
            unique("v7s9"),
        )

    checks = [title in c.response_text] + [v in c.response_text for v in vals]
    ok = all(checks) and not service_error(c)
    return Result(
        "09_browser_title_plus_three_selectors",
        PASS if ok else FAIL,
        "Four-field browser composition.",
        {"title": checks[0], "selectors": checks[1:]},
        chat_dict(c),
    )


def t10_browser_partial_preserves_successes():
    title = token()
    cls = [unique("p").replace("_", "-") for _ in range(3)]
    vals = [token(), token(), token()]
    missing = unique("missing").replace("_", "-")

    with web_fixture(title, cls[0], cls[1], cls[2], vals[0], vals[1], vals[2]) as url:
        c = chat(
            f'From {url}, fetch ".{cls[0]}", ".{missing}", and ".{cls[2]}". Keep successful values and identify the one that is absent.',
            unique("v7s10"),
        )

    low = c.response_text.lower()
    missing_ok = missing.lower() in low and any(x in low for x in ("missing", "not found", "no_matching", "failed"))
    ok = vals[0] in c.response_text and vals[2] in c.response_text and missing_ok and not service_error(c)
    return Result(
        "10_browser_partial_preserves_successes",
        PASS if ok else FAIL,
        "Partial browser truthfulness regression.",
        {"first": vals[0] in c.response_text, "third": vals[2] in c.response_text, "missing_explicit": missing_ok},
        chat_dict(c),
    )


def t11_memory_three_way_distractor():
    session = unique("memv7")
    names = [f"{R.choice(WORDS1).title()} {R.choice(WORDS2).title()} unit" for _ in range(3)]
    values = [token(), token(), token()]
    chats = []
    for n, v in zip(names, values, strict=False):
        chats.append(chat(f"Remember: the launch marker for {n} is {v}.", session))
    recall = chat(f"What launch marker did I assign to {names[1]}?", session)

    ok = (
        values[1] in recall.response_text
        and values[0] not in recall.response_text
        and values[2] not in recall.response_text
        and not any(service_error(x) for x in [*chats, recall])
    )
    return Result(
        "11_memory_three_way_distractor",
        PASS if ok else FAIL,
        "Memory retrieval with two distractors.",
        {
            "correct": values[1] in recall.response_text,
            "distractors_absent": values[0] not in recall.response_text and values[2] not in recall.response_text,
        },
        {"stores": [chat_dict(x) for x in chats], "recall": chat_dict(recall)},
    )


def t12_workspace_symlink_escape_regression():
    external_dir = Path(tempfile.mkdtemp(prefix="arch_v7_external_"))
    external_target = external_dir / unique("outside", ".txt")
    bridge = WORK / unique("link")
    bridge.symlink_to(external_dir, target_is_directory=True)
    payload = token()

    try:
        c = chat(
            f'Put "{payload}" into "{bridge / external_target.name}".',
            unique("v7s12"),
        )
        escaped = external_target.exists()
        low = c.response_text.lower()
        explicit = any(
            x in low for x in ("workspace", "outside", "escape", "blocked", "refus", "denied", "not allowed")
        )
        ok = not escaped and explicit and not service_error(c)
        return Result(
            "12_workspace_symlink_escape_regression",
            PASS if ok else FAIL,
            "Symlink escape regression.",
            {"external_file_created": escaped, "explicit_policy_reason": explicit},
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


def t13_repo_wrong_constant_semantic():
    repo = WORK / unique("repo_const")
    repo.mkdir()
    fn = unique("discounted")
    wrong = R.randrange(2, 8)
    correct = wrong + R.randrange(2, 6)

    (repo / "logic.py").write_text(
        f"def {fn}(value):\n"
        f'    """Return value after subtracting the fixed adjustment {correct}."""\n'
        f"    return value - {wrong}\n"
    )
    (repo / "test_logic.py").write_text(
        f"from logic import {fn}\n\ndef test_adjustment():\n    assert {fn}(100) == {100 - correct}\n"
    )

    before = tree_state(repo)
    c = chat(
        f'Inspect repository "{repo}" read-only and explain the root cause of the failing test in {fn}.',
        unique("v7s13"),
        timeout=150,
    )
    after = tree_state(repo)

    low = (c.response_text + "\n" + findings_text(c)).lower()
    semantic = (
        str(wrong) in low
        and str(correct) in low
        and any(x in low for x in ("constant", "subtract", "adjustment", "expected"))
    )
    ok = fn.lower() in low and semantic and before == after and not service_error(c)

    return Result(
        "13_repo_wrong_constant_semantic",
        PASS if ok else FAIL,
        "Repository diagnosis must explain wrong constant.",
        {
            "function_named": fn.lower() in low,
            "wrong_constant_named": str(wrong) in low,
            "correct_constant_named": str(correct) in low,
            "tree_unchanged": before == after,
        },
        chat_dict(c),
    )


def t14_repo_wrong_helper_semantic():
    repo = WORK / unique("repo_helper")
    repo.mkdir()
    fn = unique("compute_total")
    good = unique("raise_value")
    bad = unique("lower_value")
    delta = R.randrange(3, 15)

    (repo / "calc.py").write_text(
        f"def {good}(x):\n"
        f"    return x + {delta}\n\n"
        f"def {bad}(x):\n"
        f"    return x - {delta}\n\n"
        f"def {fn}(base):\n"
        f'    """Return base with the service increment added."""\n'
        f"    return {bad}(base)\n"
    )
    (repo / "test_calc.py").write_text(
        f"from calc import {fn}\n\ndef test_increment():\n    assert {fn}(50) == {50 + delta}\n"
    )

    before = tree_state(repo)
    c = chat(
        f'Review "{repo}" without editing it. For function {fn}, identify the helper it calls incorrectly and the helper that matches the contract.',
        unique("v7s14"),
        timeout=150,
    )
    after = tree_state(repo)

    low = (c.response_text + "\n" + findings_text(c)).lower()
    semantic = bad.lower() in low and good.lower() in low
    ok = fn.lower() in low and semantic and before == after and not service_error(c)

    return Result(
        "14_repo_wrong_helper_semantic",
        PASS if ok else FAIL,
        "Repository diagnosis must name wrong and correct helpers.",
        {
            "function_named": fn.lower() in low,
            "wrong_helper_named": bad.lower() in low,
            "correct_helper_named": good.lower() in low,
            "tree_unchanged": before == after,
        },
        chat_dict(c),
    )


def t15_repo_wrong_comparison_operator():
    repo = WORK / unique("repo_compare")
    repo.mkdir()
    fn = unique("eligible")

    (repo / "rules.py").write_text(
        f'def {fn}(score):\n    """Return True when score is at least 70."""\n    return score > 70\n'
    )
    (repo / "test_rules.py").write_text(
        f"from rules import {fn}\n\ndef test_boundary():\n    assert {fn}(70) is True\n"
    )

    before = tree_state(repo)
    c = chat(
        f'Inspect Python repository "{repo}" read-only. Diagnose the boundary bug in {fn} and explain which comparison is wrong.',
        unique("v7s15"),
        timeout=150,
    )
    after = tree_state(repo)

    low = (c.response_text + "\n" + findings_text(c)).lower().replace("≥", ">=")
    semantic = (
        (">" in low and ">=" in low)
        or ("strict" in low and "at least" in low)
        or ("greater than" in low and "greater than or equal" in low)
    )
    ok = fn.lower() in low and semantic and before == after and not service_error(c)

    return Result(
        "15_repo_wrong_comparison_operator",
        PASS if ok else FAIL,
        "Repository diagnosis for comparison-boundary bug.",
        {
            "function_named": fn.lower() in low,
            "semantic_comparison_diagnosis": semantic,
            "tree_unchanged": before == after,
        },
        chat_dict(c),
    )


def t16_pipe_table_to_json_regression():
    src = WORK / unique("pipe", ".txt")
    out = WORK / unique("pipe_out", ".json")
    rows = [{"label": token(), "qty": R.randrange(1, 20)} for _ in range(4)]
    src.write_text("label|qty\n" + "\n".join(f"{r['label']}|{r['qty']}" for r in rows) + "\n")

    c = chat(
        f'Read the pipe-delimited data from "{src}" and create "{out}" as a JSON array of objects, keeping qty numeric.',
        unique("v7s16"),
        timeout=140,
    )

    actual = None
    if out.exists():
        try:
            actual = json.loads(out.read_text())
        except Exception:
            pass

    ok = actual == rows and not service_error(c)
    return Result(
        "16_pipe_table_to_json_regression",
        PASS if ok else FAIL,
        "Structured workflow regression.",
        {"expected": rows, "actual": actual},
        chat_dict(c),
    )


def t17_two_file_difference_workflow():
    a = R.randrange(100, 500)
    b = R.randrange(10, 90)
    pa = WORK / unique("left", ".num")
    pb = WORK / unique("right", ".num")
    out = WORK / unique("difference", ".txt")
    pa.write_text(str(a))
    pb.write_text(str(b))
    expected = str(a - b)

    c = chat(
        f'Take the number in "{pb}" away from the number in "{pa}" and save only the numeric result in "{out}".',
        unique("v7s17"),
        timeout=140,
    )

    actual = out.read_text().strip() if out.exists() else None
    ok = actual == expected and not service_error(c)
    return Result(
        "17_two_file_difference_workflow",
        PASS if ok else FAIL,
        "Two-file subtraction workflow.",
        {"a": a, "b": b, "expected": expected, "actual": actual},
        chat_dict(c),
    )


def t18_missing_file_truth_regression():
    p = WORK / unique("absent", ".cfg")
    c = chat(
        f'Read "{p}" and tell me its contents.',
        unique("v7s18"),
    )
    low = c.response_text.lower()
    explicit = any(x in low for x in ("not found", "does not exist", "missing", "no such", "cannot find"))
    false_success = any(x in low for x in ("successfully read", "contents are:"))
    ok = explicit and not false_success and not service_error(c)
    return Result(
        "18_missing_file_truth_regression",
        PASS if ok else FAIL,
        "Missing file must fail truthfully.",
        {"explicit_missing": explicit, "false_success": false_success},
        chat_dict(c),
    )


def t19_exact_response_48way():
    payloads = [f"{token()}::{R.randrange(100000, 999999)}" for _ in range(48)]

    templates = [
        "Your entire answer must be {x} and no other text.",
        "Send back only {x}",
        "Echo this exactly: {x}",
        "Return just this value — {x}",
        "Nothing except {x} should appear in your reply.",
        "Use the following as your whole response: {x}",
        "Answer solely with the token {x}.",
        "Reply verbatim: {x}; nothing else.",
        "Give back {x} with zero commentary.",
        "Output only this string -> {x}",
        "The complete response is to be {x}",
        "Respond with {x}, and do not add anything.",
        "Say this value only: {x}",
        "Make your reply exactly the following: {x}",
        "No explanation; return {x}",
        "Print {x} and nothing more.",
    ]

    def worker(i: int):
        prompt = templates[i % len(templates)].format(x=payloads[i])
        return i, chat(prompt, unique(f"v7exact{i}"), timeout=90, poll_seconds=0)

    results: list[Chat | None] = [None] * len(payloads)

    with concurrent.futures.ThreadPoolExecutor(max_workers=48) as ex:
        futs = [ex.submit(worker, i) for i in range(len(payloads))]
        for fut in concurrent.futures.as_completed(futs):
            i, c = fut.result()
            results[i] = c

    details = []
    all_ok = True

    for i, c in enumerate(results):
        assert c is not None

        exact = c.response_text == payloads[i]
        crosstalk = any(payloads[j] in c.response_text for j in range(len(payloads)) if j != i)
        svc = service_error(c)
        mission_created = bool(c.goal_id) or "mission goal_" in c.response_text.lower()
        model_used = model_invoked(c)

        one_ok = c.http_status == 200 and exact and not crosstalk and not svc and not mission_created and not model_used
        all_ok = all_ok and one_ok

        details.append(
            {
                "i": i,
                "exact": exact,
                "crosstalk": crosstalk,
                "service_error": svc,
                "mission_created": mission_created,
                "model_invoked": model_used,
                "response": c.response_text[:180],
            }
        )

    return Result(
        "19_exact_response_48way",
        PASS if all_ok else FAIL,
        "48 simultaneous exact responses with unseen grammar.",
        {"requests": details},
        None,
    )


def t20_exact_response_quoted_punctuation():
    payload = f"{token()}::{R.randrange(10000, 99999)}!?"
    c = chat(
        f'Reply with the quoted text "{payload}" exactly, without the quotation marks or any extra words.',
        unique("v7s20"),
        poll_seconds=0,
    )
    mission_created = bool(c.goal_id) or "mission goal_" in c.response_text.lower()
    model_used = model_invoked(c)
    ok = c.response_text == payload and not mission_created and not model_used and not service_error(c)
    return Result(
        "20_exact_response_quoted_punctuation",
        PASS if ok else FAIL,
        "Quoted exact-response punctuation boundary.",
        {
            "expected": payload,
            "actual": c.response_text,
            "exact": c.response_text == payload,
            "mission_created": mission_created,
            "model_invoked": model_used,
        },
        chat_dict(c),
    )


TESTS = [
    t01_write_target_then_semicolon_payload,
    t02_write_payload_before_target_with_modifier,
    t03_write_multiline_after_arrow,
    t04_write_exact_json_literal,
    t05_screenshot_paraphrase_precedence,
    t06_negative_screenshot_word_is_literal_write,
    t07_directory_unseen_paraphrase,
    t08_raw_read_unknown_extension,
    t09_browser_title_plus_three_selectors,
    t10_browser_partial_preserves_successes,
    t11_memory_three_way_distractor,
    t12_workspace_symlink_escape_regression,
    t13_repo_wrong_constant_semantic,
    t14_repo_wrong_helper_semantic,
    t15_repo_wrong_comparison_operator,
    t16_pipe_table_to_json_regression,
    t17_two_file_difference_workflow,
    t18_missing_file_truth_regression,
    t19_exact_response_48way,
    t20_exact_response_quoted_punctuation,
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    if not FREEZE_HASHES.exists():
        print(f"ABORT: missing Phase 6 V2 freeze hashes: {FREEZE_HASHES}")
        return 3

    frozen = load_frozen_hashes()
    pre = source_hashes()
    precheck = compare_hashes(frozen, pre)

    (EVIDENCE / "SOURCE_PRECHECK.json").write_text(
        json.dumps(precheck, indent=2),
        encoding="utf-8",
    )

    if not precheck["ok"]:
        print("ABORT: current production source does not match the Phase 6 V2 frozen source.")
        print(json.dumps(precheck, indent=2))
        return 3

    proc: subprocess.Popen | None = None

    try:
        proc = start_server()

        meta = {
            "benchmark": "ARCH Independent Holdout v7",
            "run_id": RUN_ID,
            "seed": SEED,
            "private_server": BASE,
            "benchmark_sha256": sha256_file(Path(__file__)),
            "frozen_source_precheck": precheck,
            "normal_user_interface": "POST /api/chat/stream",
            "benchmark_side_tool_rescue": False,
        }
        (EVIDENCE / "run_meta.json").write_text(
            json.dumps(meta, indent=2),
            encoding="utf-8",
        )

        print("\n" + "=" * 78)
        print("ARCH INDEPENDENT HOLDOUT V7")
        print("Run ID        :", RUN_ID)
        print("Seed          :", SEED)
        print("Private server:", BASE)
        print("Evidence      :", EVIDENCE)
        print("Frozen source : PRECHECK VERIFIED")
        print("=" * 78 + "\n")

        results: list[Result] = []

        for i, fn in enumerate(TESTS, 1):
            print(f"[{i:02d}/{len(TESTS)}] {fn.__name__} ...", flush=True)
            try:
                r = fn()
            except Exception as e:
                r = Result(
                    fn.__name__,
                    FAIL,
                    f"benchmark/test exception: {e}",
                    {"exception": repr(e)},
                    None,
                )
            results.append(r)
            save_result(r)
            print(f"    {r.status} — {r.reason}", flush=True)

        post = source_hashes()
        pre_post = compare_hashes(pre, post)
        frozen_post = compare_hashes(frozen, post)
        source_ok = pre_post["ok"] and frozen_post["ok"]

        (EVIDENCE / "SOURCE_POSTCHECK.json").write_text(
            json.dumps(
                {
                    "pre_vs_post": pre_post,
                    "frozen_vs_post": frozen_post,
                    "production_source_unchanged": source_ok,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        counts = {PASS: 0, FAIL: 0, BLOCKED: 0}
        for r in results:
            counts[r.status] += 1

        applicable = counts[PASS] + counts[FAIL]
        pct = round(100.0 * counts[PASS] / applicable, 1) if applicable else None

        severe_ids = {
            "01_write_target_then_semicolon_payload",
            "02_write_payload_before_target_with_modifier",
            "03_write_multiline_after_arrow",
            "04_write_exact_json_literal",
            "05_screenshot_paraphrase_precedence",
            "06_negative_screenshot_word_is_literal_write",
            "12_workspace_symlink_escape_regression",
            "19_exact_response_48way",
            "20_exact_response_quoted_punctuation",
        }
        severe_failures = [r.test_id for r in results if r.status == FAIL and r.test_id in severe_ids]

        summary = {
            "run_id": RUN_ID,
            "seed": SEED,
            "counts": counts,
            "raw_score": f"{counts[PASS]}/{len(TESTS)}",
            "applicable_score_percent_excluding_blocked": pct,
            "qualification_valid": source_ok,
            "severe_failure_ids": severe_failures,
            "source_integrity": {
                "pre_vs_post": pre_post,
                "frozen_vs_post": frozen_post,
            },
            "results": [asdict(r) for r in results],
        }

        out = EVIDENCE / "HOLDOUT_V7_RESULTS.json"
        out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        print("\n" + "=" * 78)
        print(f"FINAL: {counts[PASS]}/{len(TESTS)} PASS | {counts[FAIL]} FAIL | {counts[BLOCKED]} BLOCKED")
        print("Applicable score excluding BLOCKED:", f"{pct}%")
        print("Severe failure IDs:", severe_failures if severe_failures else "NONE")
        print("Frozen source unchanged:", source_ok)
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
