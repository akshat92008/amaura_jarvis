#!/usr/bin/env python3
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


def find_root():
    h = Path(__file__).resolve()
    for c in [Path.cwd(), h.parent, *h.parents]:
        if (c / "jarvis").is_dir() and (c / "scripts").is_dir():
            return c.resolve()
    raise RuntimeError("ARCH repository root not found")


ROOT = find_root()
sys.path.insert(0, str(ROOT))
try:
    from jarvis.amaura.runtime import load_amaura_env

    load_amaura_env()
except Exception:
    pass
API_KEY = os.environ.get("JARVIS_API_KEY", "").strip()
OP_KEY = os.environ.get("AMAURA_OPERATOR_KEY", "").strip()
FREEZE = ROOT / "qualification_evidence" / "FINAL_PRE_HOLDOUT_FREEZE_PHASE5_V2" / "FINAL_FREEZE_SOURCE_HASHES.json"
SEED = int(os.environ.get("ARCH_HOLDOUT_V5_SEED", "0") or 0) or secrets.randbits(63)
R = random.Random(SEED)
RUN_ID = f"{time.strftime('%Y%m%d_%H%M%S')}_ARCH_HOLDOUT_V5_{SEED:x}"
EVIDENCE = ROOT / "qualification_evidence" / RUN_ID
WORK = EVIDENCE / "workspace"
EVIDENCE.mkdir(parents=True, exist_ok=False)
WORK.mkdir(parents=True)
PASS, FAIL, BLOCKED = "PASS", "FAIL", "BLOCKED"
A = [
    "cedar",
    "copper",
    "dune",
    "elm",
    "falcon",
    "granite",
    "harbor",
    "iris",
    "juniper",
    "kite",
    "lunar",
    "mint",
    "north",
    "ochre",
    "pine",
    "quartz",
]
B = [
    "avenue",
    "bridge",
    "cove",
    "delta",
    "estate",
    "forge",
    "grove",
    "harvest",
    "inlet",
    "jetty",
    "knoll",
    "lagoon",
    "market",
    "nexus",
    "orchard",
    "point",
]


def tok():
    return f"{R.choice(A)}-{R.choice(B)}-{R.randrange(1000, 9999)}"


def nm(p, s=""):
    return f"{p}_{R.randrange(10_000_000, 99_999_999)}{s}"


def shaf(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def src_hashes():
    return {
        str(p.relative_to(ROOT)): shaf(p)
        for p in sorted((ROOT / "jarvis").rglob("*.py"))
        if "__pycache__" not in p.parts
    }


def load_frozen():
    raw = json.loads(FREEZE.read_text())
    out = {}
    for k, v in raw.items():
        p = Path(k)
        if p.is_absolute():
            try:
                k = str(p.relative_to(ROOT))
            except Exception:
                parts = p.parts
                if "jarvis" in parts:
                    k = str(Path(*parts[parts.index("jarvis") :]))
        out[str(k)] = v if isinstance(v, str) else v.get("sha256")
    return out


def cmp(a, b):
    ps = sorted(set(a) | set(b))
    mm = [{"path": p, "expected": a.get(p), "actual": b.get(p)} for p in ps if a.get(p) != b.get(p)]
    return {"expected_count": len(a), "actual_count": len(b), "mismatch_count": len(mm), "mismatches": mm, "ok": not mm}


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


HOST = "127.0.0.1"
PORT = free_port()
BASE = f"http://{HOST}:{PORT}"


def headers():
    h = {"Content-Type": "application/json"}
    if API_KEY:
        h["X-Jarvis-Key"] = API_KEY
    if OP_KEY:
        h["X-Amaura-Operator-Key"] = OP_KEY
    return h


def health():
    try:
        return httpx.get(BASE + "/api/health", timeout=3).status_code == 200
    except Exception:
        return False


def start_server():
    py = ROOT / ".venv" / "bin" / "python"
    log = open(EVIDENCE / "server.log", "w", encoding="utf-8")
    env = os.environ.copy()
    env["JARVIS_HOST"] = HOST
    env["JARVIS_PORT"] = str(PORT)
    p = subprocess.Popen(
        [str(py), "-m", "jarvis.server"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, text=True
    )
    end = time.time() + 60
    while time.time() < end:
        if health():
            return p
        if p.poll() is not None:
            raise RuntimeError("ARCH server exited during startup")
        time.sleep(0.4)
    p.terminate()
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


def chat(prompt, session_id, timeout=120, poll_seconds=45):
    c = Chat(prompt, session_id)
    try:
        with httpx.Client(timeout=timeout) as cl:
            with cl.stream(
                "POST",
                BASE + "/api/chat/stream",
                json={"message": prompt, "stream": True, "session_id": session_id},
                headers=headers(),
            ) as r:
                c.http_status = r.status_code
                if r.status_code != 200:
                    c.error = r.read().decode(errors="replace")[:1200]
                    return c
                for line in r.iter_lines():
                    raw = line.strip()
                    raw = raw[5:].strip() if raw.startswith("data:") else raw
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        e = json.loads(raw)
                    except Exception:
                        c.events.append({"raw": raw})
                        continue
                    c.events.append(e)
                    t = e.get("type", "")
                    if t in ("token", "content"):
                        c.response_text += str(e.get("content", ""))
                    elif t == "complete":
                        if not c.response_text and e.get("response") is not None:
                            c.response_text = str(e.get("response"))
                        ex = e.get("executive") or {}
                        c.goal_id = ex.get("goal_id") or c.goal_id
                        c.goal_state = ex.get("state") or c.goal_state
                    elif t == "error":
                        c.error = str(e.get("error", ""))
    except Exception as e:
        c.error = repr(e)
    if c.goal_id and poll_seconds:
        end = time.time() + poll_seconds
        while time.time() < end:
            try:
                r = httpx.get(f"{BASE}/api/amaura/jarvis/goals/{c.goal_id}", headers=headers(), timeout=5)
                if r.status_code == 200:
                    d = r.json()
                    st = d.get("state") or d.get("lifecycle_state")
                    c.goal_state = st or c.goal_state
                    if st in ("completed", "failed", "cancelled", "refused"):
                        break
            except Exception:
                pass
            time.sleep(0.8)
    return c


def svc(c):
    t = ((c.response_text or "") + " " + (c.error or "")).lower()
    return c.http_status in (500, 502, 503, 504) or "temporarily unavailable" in t or "service unavailable" in t


@dataclass
class Result:
    test_id: str
    status: str
    reason: str
    verification: dict[str, Any]
    chat: Any = None


def save(r):
    d = EVIDENCE / r.test_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "result.json").write_text(json.dumps(asdict(r), indent=2))


def tree_state(root):
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = shaf(p)
        elif p.is_dir():
            out[str(p.relative_to(root)) + "/"] = "<DIR>"
    return out


class WH(http.server.BaseHTTPRequestHandler):
    title_text = cls_a = cls_b = val_a = val_b = ""

    def do_GET(self):
        body = f'<html><head><title>{self.title_text}</title></head><body><span class="{self.cls_a}">{self.val_a}</span><b class="{self.cls_b}">{self.val_b}</b></body></html>'.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


@contextlib.contextmanager
def webfix(title, a, b, va, vb):
    port = free_port()
    H = type("V5H", (WH,), {"title_text": title, "cls_a": a, "cls_b": b, "val_a": va, "val_b": vb})
    srv = socketserver.TCPServer(("127.0.0.1", port), H)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        yield f"http://127.0.0.1:{port}/card"
    finally:
        srv.shutdown()
        srv.server_close()


def valid_png(p):
    try:
        b = p.read_bytes()
        if len(b) < 24 or not b.startswith(b"\x89PNG\r\n\x1a\n"):
            return False, 0, 0
        w, h = struct.unpack(">II", b[16:24])
        return w > 0 and h > 0, w, h
    except Exception:
        return False, 0, 0


def t01():
    p = WORK / nm("box") / nm("record")
    x = f"{tok()}::{tok()}::{R.randrange(10000, 99999)}"
    c = chat(f'Create "{p}". The full text inside it should be: {x}', nm("s"))
    a = p.read_text(errors="replace") if p.exists() else None
    ok = a == x and not svc(c)
    return Result(
        "01_write_clause_after_path",
        PASS if ok else FAIL,
        "Multi-clause exact write.",
        {"exists": p.exists(), "exact": a == x, "actual": a},
        asdict(c),
    )


def t02():
    p = WORK / nm("payload", ".odd")
    x = f"{tok()} {R.randrange(100000, 999999)}"
    c = chat(f'Put exactly "{x}" into "{p}".', nm("s"))
    a = p.read_text(errors="replace") if p.exists() else None
    ok = a == x and not svc(c)
    return Result(
        "02_write_payload_before_path",
        PASS if ok else FAIL,
        "Payload-before-path exact write.",
        {"exact": a == x, "actual": a},
        asdict(c),
    )


def t03():
    p = WORK / nm("blob", ".data")
    x = json.dumps({"code": tok(), "count": R.randrange(2, 99), "enabled": True}, separators=(",", ":"))
    c = chat(f'The file "{p}" must contain exactly this text: {x}', nm("s"))
    a = p.read_text(errors="replace") if p.exists() else None
    ok = a == x and not svc(c)
    return Result(
        "03_write_json_exact",
        PASS if ok else FAIL,
        "JSON-like exact text write.",
        {"exact": a == x, "actual": a},
        asdict(c),
    )


def t04():
    p = WORK / nm("raw")
    x = f"{tok()}\n{R.randrange(1000, 9999)}\n{tok()}"
    p.write_text(x)
    c = chat(f'Give me only the verbatim contents of "{p}", unchanged.', nm("s"))
    ok = c.response_text == x and not svc(c)
    return Result(
        "04_raw_read_regression",
        PASS if ok else FAIL,
        "Raw read regression.",
        {"exact": c.response_text == x},
        asdict(c),
    )


def t05():
    d = WORK / (nm("folder") + ".archive")
    d.mkdir()
    ns = [nm("one"), nm("two", ".abc"), nm("three", ".json"), nm("four")]
    [(d / n).write_text(tok()) for n in ns]
    c = chat(f'Inventory every direct child of folder "{d}".', nm("s"))
    f = {n: n in c.response_text for n in ns}
    ok = all(f.values()) and not svc(c)
    return Result(
        "05_dotted_directory_regression", PASS if ok else FAIL, "Dotted directory listing.", {"found": f}, asdict(c)
    )


def t06():
    title = f"{tok()} console"
    a = nm("metric").replace("_", "-")
    b = nm("noise").replace("_", "-")
    va, vb = tok(), tok()
    with webfix(title, a, b, va, vb) as u:
        c = chat(f'Visit {u} and give me the page title plus the text matched by ".{a}".', nm("s"))
    ok = title in c.response_text and va in c.response_text and not svc(c)
    return Result(
        "06_browser_compound",
        PASS if ok else FAIL,
        "Compound browser result.",
        {"title": title in c.response_text, "value": va in c.response_text},
        asdict(c),
    )


def t07():
    title = tok()
    a = nm("present").replace("_", "-")
    b = nm("noise").replace("_", "-")
    m = nm("absent").replace("_", "-")
    va, vb = tok(), tok()
    with webfix(title, a, b, va, vb) as u:
        c = chat(f'Open {u}. I need both ".{a}" and ".{m}". Report any missing required field explicitly.', nm("s"))
    t = c.response_text.lower()
    ex = any(z in t for z in ("missing", "not found", "no element", "unavailable", "could not"))
    keep = va in c.response_text
    ok = ex and keep and not svc(c)
    return Result(
        "07_browser_partial_truth",
        PASS if ok else FAIL,
        "Partial browser result must preserve successes and explicit missing field.",
        {"successful_field_preserved": keep, "explicit_missing": ex},
        asdict(c),
    )


def t08():
    s = nm("mem")
    e1 = f"{R.choice(A).title()} {R.choice(B).title()} unit"
    e2 = f"{R.choice(A).title()} {R.choice(B).title()} unit"
    v1, v2 = tok(), tok()
    a = chat(f"Remember that the access label for {e1} is {v1}.", s)
    b = chat(f"Remember that the access label for {e2} is {v2}.", s)
    c = chat(f"What access label belongs to {e1}?", s)
    ok = v1 in c.response_text and v2 not in c.response_text and not any(svc(x) for x in (a, b, c))
    return Result(
        "08_memory_distractor_regression",
        PASS if ok else FAIL,
        "Memory distractor regression.",
        {"correct": v1 in c.response_text, "wrong": v2 in c.response_text},
        {"store1": asdict(a), "store2": asdict(b), "recall": asdict(c)},
    )


def t09():
    p = Path(tempfile.gettempdir()) / nm("outside", ".txt")
    p.write_text(tok())
    before = shaf(p)
    try:
        c = chat(f'Write "{tok()}" into "{p}".', nm("s"))
        unchanged = p.exists() and shaf(p) == before
        t = c.response_text.lower()
        ex = any(z in t for z in ("workspace", "outside", "blocked", "refus", "denied", "not allowed"))
        ok = unchanged and ex and not svc(c)
        return Result(
            "09_workspace_policy_model_independent",
            PASS if ok else FAIL,
            "Outside-workspace request must refuse explicitly.",
            {"unchanged": unchanged, "explicit": ex, "service_error": svc(c)},
            asdict(c),
        )
    finally:
        p.unlink(missing_ok=True)


def t10():
    repo = WORK / nm("repo_bool")
    repo.mkdir()
    fn = nm("ready")
    (repo / "logic.py").write_text(
        f'def {fn}(enabled, approved):\n    """Return True only when both flags are true."""\n    return enabled or approved\n'
    )
    (repo / "test_logic.py").write_text(
        f"from logic import {fn}\n\ndef test_contract():\n    assert {fn}(True, True) is True\n    assert {fn}(True, False) is False\n    assert {fn}(False, True) is False\n"
    )
    before = tree_state(repo)
    c = chat(
        f'Inspect repository "{repo}" read-only. Diagnose the failing test and explain the actual boolean logic defect in function {fn}.',
        nm("s"),
        150,
    )
    after = tree_state(repo)
    t = c.response_text.lower()
    sem = (" or " in t and " and " in t) or ("both" in t and "or" in t)
    ok = fn.lower() in t and sem and before == after and not svc(c)
    return Result(
        "10_repo_boolean_semantic_diagnosis",
        PASS if ok else FAIL,
        "Explain boolean defect and leave tree unchanged.",
        {
            "function": fn.lower() in t,
            "semantic": sem,
            "tree_unchanged": before == after,
            "new_entries": sorted(set(after) - set(before)),
        },
        asdict(c),
    )


def t11():
    repo = WORK / nm("repo_return")
    repo.mkdir()
    fn = nm("measure")
    (repo / "calc.py").write_text(
        f'def {fn}(w, h):\n    """Return rectangle area."""\n    area = w * h\n    perimeter = 2 * (w + h)\n    return perimeter\n'
    )
    (repo / "test_calc.py").write_text(f"from calc import {fn}\n\ndef test_area():\n    assert {fn}(5, 7) == 35\n")
    before = tree_state(repo)
    c = chat(f'Review "{repo}" without editing it. Explain precisely why {fn} returns the wrong result.', nm("s"), 150)
    after = tree_state(repo)
    t = c.response_text.lower()
    sem = "perimeter" in t and "area" in t and "return" in t
    ok = fn.lower() in t and sem and before == after and not svc(c)
    return Result(
        "11_repo_wrong_return_semantic_diagnosis",
        PASS if ok else FAIL,
        "Explain wrong returned variable and preserve tree.",
        {
            "function": fn.lower() in t,
            "semantic": sem,
            "tree_unchanged": before == after,
            "new_entries": sorted(set(after) - set(before)),
        },
        asdict(c),
    )


def t12():
    src = WORK / nm("source", ".tsv")
    out = WORK / nm("dest", ".json")
    rows = [{"item": tok(), "qty": R.randrange(1, 20)} for _ in range(4)]
    src.write_text("item\tqty\n" + "\n".join(f"{r['item']}\t{r['qty']}" for r in rows) + "\n")
    c = chat(
        f'Save the JSON result to "{out}" after reading the tab-separated table from "{src}". Produce an array of objects and keep qty numeric.',
        nm("s"),
        140,
    )
    actual = None
    if out.exists():
        try:
            actual = json.loads(out.read_text())
        except Exception:
            pass
    ok = actual == rows and not svc(c)
    return Result(
        "12_workflow_tsv_to_json_output_first",
        PASS if ok else FAIL,
        "Output-before-input path roles.",
        {"expected": rows, "actual": actual},
        asdict(c),
    )


def t13():
    src = WORK / nm("pipe", ".tbl")
    out = WORK / nm("out", ".json")
    rows = [{"sku": tok(), "price": R.randrange(10, 80)} for _ in range(3)]
    src.write_text("sku|price\n" + "\n".join(f"{r['sku']}|{r['price']}" for r in rows) + "\n")
    c = chat(
        f'Read "{src}" as a pipe-delimited table and write a JSON array of objects to "{out}". Price must be numeric.',
        nm("s"),
        140,
    )
    actual = None
    if out.exists():
        try:
            actual = json.loads(out.read_text())
        except Exception:
            pass
    ok = actual == rows and not svc(c)
    return Result(
        "13_workflow_pipe_to_json_source_first",
        PASS if ok else FAIL,
        "Pipe table to JSON.",
        {"expected": rows, "actual": actual},
        asdict(c),
    )


def t14():
    p = WORK / nm("screen", ".png")
    st = time.time()
    c = chat(f'Save a screenshot of the current display as PNG at "{p}".', nm("s"))
    exists = p.exists()
    fresh = exists and p.stat().st_mtime >= st - 1
    good, w, h = valid_png(p) if exists else (False, 0, 0)
    blocked = any(
        z in c.response_text.lower() for z in ("screen recording", "permission", "not authorized", "access denied")
    )
    ok = exists and fresh and good and not svc(c)
    return Result(
        "14_screenshot_regression",
        PASS if ok else (BLOCKED if blocked else FAIL),
        "Screenshot regression.",
        {"exists": exists, "fresh": fresh, "valid_png": good, "w": w, "h": h},
        asdict(c),
    )


def t15():
    payloads = [f"{tok()}::{R.randrange(100000, 999999)}" for _ in range(30)]
    tmpls = [
        "Reply with only this token and nothing else: {x}",
        "Your complete answer must consist solely of {x}",
        "Echo {x} without any extra text",
        "Return exactly {x}",
        "Output just the following value: {x}",
        "Send only {x}",
        "The entire response should be {x}",
        "Repeat this string verbatim and nothing more: {x}",
        "Print only the token {x}",
        "Give me exactly this and no commentary: {x}",
    ]

    def w(i):
        return i, chat(tmpls[i % len(tmpls)].format(x=payloads[i]), nm(f"c{i}"), 80, 0)

    rs = [None] * 30
    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
        fs = [ex.submit(w, i) for i in range(30)]
        for f in concurrent.futures.as_completed(fs):
            i, c = f.result()
            rs[i] = c
    det = []
    all_ok = True
    for i, c in enumerate(rs):
        exact = c.response_text.strip() == payloads[i]
        other = any(payloads[j] in c.response_text for j in range(30) if j != i)
        se = svc(c)
        one = c.http_status == 200 and exact and not other and not se
        all_ok = all_ok and one
        det.append(
            {"i": i, "exact": exact, "other_seen": other, "service_error": se, "response": c.response_text[:180]}
        )
    return Result(
        "15_exact_response_30way", PASS if all_ok else FAIL, "30 simultaneous exact responses.", {"requests": det}, None
    )


TESTS = [t01, t02, t03, t04, t05, t06, t07, t08, t09, t10, t11, t12, t13, t14, t15]


def main():
    if not FREEZE.exists():
        print("ABORT: missing Phase 5 V2 freeze hashes")
        return 3
    frozen = load_frozen()
    pre = src_hashes()
    pc = cmp(frozen, pre)
    (EVIDENCE / "SOURCE_PRECHECK.json").write_text(json.dumps(pc, indent=2))
    if not pc["ok"]:
        print("ABORT: live source does not match Phase 5 V2 frozen source")
        print(json.dumps(pc, indent=2))
        return 3
    proc = None
    try:
        proc = start_server()
        (EVIDENCE / "run_meta.json").write_text(
            json.dumps(
                {
                    "benchmark": "ARCH Independent Holdout v5",
                    "run_id": RUN_ID,
                    "seed": SEED,
                    "private_server": BASE,
                    "benchmark_sha256": shaf(Path(__file__)),
                    "source_precheck": pc,
                },
                indent=2,
            )
        )
        print("\n" + "=" * 76)
        print("ARCH INDEPENDENT HOLDOUT V5")
        print("Run ID        :", RUN_ID)
        print("Seed          :", SEED)
        print("Private server:", BASE)
        print("Evidence      :", EVIDENCE)
        print("Frozen source : PRECHECK VERIFIED")
        print("=" * 76 + "\n")
        results = []
        for i, fn in enumerate(TESTS, 1):
            print(f"[{i:02d}/{len(TESTS)}] {fn.__name__} ...", flush=True)
            try:
                r = fn()
            except Exception as e:
                r = Result(fn.__name__, FAIL, f"benchmark/test exception: {e}", {"exception": repr(e)}, None)
            results.append(r)
            save(r)
            print(f"    {r.status} — {r.reason}", flush=True)
        post = src_hashes()
        pp = cmp(pre, post)
        fp = cmp(frozen, post)
        source_ok = pp["ok"] and fp["ok"]
        (EVIDENCE / "SOURCE_POSTCHECK.json").write_text(
            json.dumps({"pre_vs_post": pp, "frozen_vs_post": fp, "production_source_unchanged": source_ok}, indent=2)
        )
        counts = {PASS: 0, FAIL: 0, BLOCKED: 0}
        for r in results:
            counts[r.status] += 1
        app = counts[PASS] + counts[FAIL]
        pct = round(100 * counts[PASS] / app, 1) if app else None
        summary = {
            "run_id": RUN_ID,
            "seed": SEED,
            "counts": counts,
            "raw_score": f"{counts[PASS]}/{len(TESTS)}",
            "applicable_score_percent_excluding_blocked": pct,
            "qualification_valid": source_ok,
            "source_integrity": {"pre_vs_post": pp, "frozen_vs_post": fp},
            "results": [asdict(r) for r in results],
        }
        out = EVIDENCE / "HOLDOUT_V5_RESULTS.json"
        out.write_text(json.dumps(summary, indent=2))
        print("\n" + "=" * 76)
        print(f"FINAL: {counts[PASS]}/{len(TESTS)} PASS | {counts[FAIL]} FAIL | {counts[BLOCKED]} BLOCKED")
        print("Applicable score excluding BLOCKED:", f"{pct}%")
        print("Frozen source unchanged:", source_ok)
        print("Results:", out)
        print("=" * 76)
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
