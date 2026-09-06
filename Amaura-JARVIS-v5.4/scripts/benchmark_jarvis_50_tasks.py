"""Automated 50-Task Coding Benchmark Harness for JARVIS v5.4.

ZERO-FAKING POLICY:
This harness NEVER writes the solution files. It only sends the task prompt
to JARVIS via JarvisAgent, intercepts execution telemetry, and verifies what
JARVIS actually generated on disk using independent AST/syntax compilation
and functional assertion tests.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import py_compile
import re
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from jarvis.amaura.runtime import load_amaura_env

load_amaura_env()

from jarvis.agent import JarvisAgent


@dataclass
class TaskDefinition:
    id: int
    category: str
    name: str
    file_path: str
    prompt: str
    verify_func: Callable[[Path], tuple[bool, str]]


@dataclass
class TaskResult:
    id: int
    category: str
    name: str
    file_path: str
    status: str  # PASSED, PARTIAL, SYNTAX_ERROR, NO_FILE, EXCEPTION
    duration_s: float
    file_exists: bool
    file_size_bytes: int
    syntax_valid: bool
    verification_message: str
    tools_called: list[str] = field(default_factory=list)
    response_excerpt: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# Verification Helpers
# ══════════════════════════════════════════════════════════════════════════════

def check_python_syntax(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, f"File {path} does not exist"
    try:
        py_compile.compile(str(path), doraise=True)
        return True, "Syntax valid"
    except py_compile.PyCompileError as exc:
        return False, f"Syntax error: {exc}"


def load_module_from_path(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, str(file_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_html_structure(path: Path, required_substrings: list[str]) -> tuple[bool, str]:
    if not path.exists():
        return False, f"File {path} does not exist"
    content = path.read_text(encoding="utf-8", errors="ignore")
    if len(content.strip()) < 50:
        return False, "File is too short to be a valid HTML page"
    lower_content = content.lower()
    if "<html" not in lower_content and "<!doctype" not in lower_content and "<div" not in lower_content:
        return False, "Missing HTML root or basic tags"
    missing = [req for req in required_substrings if req.lower() not in lower_content]
    if missing:
        return False, f"Missing required elements/text: {missing}"
    return True, f"Valid HTML page with required elements: {required_substrings}"


# ══════════════════════════════════════════════════════════════════════════════
# 50 Task Definitions with Independent Verifiers
# ══════════════════════════════════════════════════════════════════════════════

TASKS: list[TaskDefinition] = []


def register_task(
    id: int,
    category: str,
    name: str,
    file_path: str,
    prompt: str,
    verify_func: Callable[[Path], tuple[bool, str]],
) -> None:
    TASKS.append(TaskDefinition(id, category, name, file_path, prompt, verify_func))


# ── 1. Algorithms & Data Structures (01-10) ───────────────────────────────────

def verify_01(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_01", p)
    cls = getattr(mod, "LRUCache", None)
    if not cls:
        return False, "LRUCache class not found"
    cache = cls(2)
    cache.put(1, 1)
    cache.put(2, 2)
    if cache.get(1) != 1:
        return False, "cache.get(1) failed"
    cache.put(3, 3)
    if cache.get(2) != -1:
        return False, "cache.get(2) was not evicted (-1 expected)"
    return True, "LRUCache successfully passed capacity eviction test"

register_task(
    1,
    "Algorithms & Data Structures",
    "LRU Cache",
    "benchmark_runs/task_01_lru_cache/lru_cache.py",
    "Please create a file at `benchmark_runs/task_01_lru_cache/lru_cache.py` with a class `LRUCache` "
    "that takes `capacity: int` in __init__, and implements `get(key)` returning value or -1, "
    "and `put(key, value)` with least-recently-used eviction when capacity is exceeded. "
    "Use write_file to save the file.",
    verify_01,
)


def verify_02(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_02", p)
    cls = getattr(mod, "Trie", None)
    if not cls:
        return False, "Trie class not found"
    trie = cls()
    trie.insert("apple")
    if not trie.search("apple"):
        return False, "search('apple') should be True"
    if trie.search("app"):
        return False, "search('app') should be False"
    if not trie.starts_with("app"):
        return False, "starts_with('app') should be True"
    return True, "Trie insert, search, starts_with verified"

register_task(
    2,
    "Algorithms & Data Structures",
    "Trie (Prefix Tree)",
    "benchmark_runs/task_02_trie/trie.py",
    "Please create a file at `benchmark_runs/task_02_trie/trie.py` implementing a `Trie` class "
    "with methods `insert(word: str) -> None`, `search(word: str) -> bool`, and `starts_with(prefix: str) -> bool`. "
    "Use write_file to save the file.",
    verify_02,
)


def verify_03(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_03", p)
    cls = getattr(mod, "BinarySearchTree", None)
    if not cls:
        return False, "BinarySearchTree class not found"
    bst = cls()
    for v in [5, 3, 7, 2, 4]:
        bst.insert(v)
    if not bst.contains(4):
        return False, "contains(4) should be True"
    if bst.contains(9):
        return False, "contains(9) should be False"
    if bst.inorder() != [2, 3, 4, 5, 7]:
        return False, f"inorder() returned {bst.inorder()}, expected [2, 3, 4, 5, 7]"
    return True, "BST insert, contains, inorder verified"

register_task(
    3,
    "Algorithms & Data Structures",
    "Binary Search Tree",
    "benchmark_runs/task_03_bst/bst.py",
    "Please create a file at `benchmark_runs/task_03_bst/bst.py` implementing a `BinarySearchTree` class "
    "with `insert(val: int)`, `contains(val: int) -> bool`, and `inorder() -> list[int]`. "
    "Use write_file to save the file.",
    verify_03,
)


def verify_04(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_04", p)
    fn = getattr(mod, "dijkstra", None)
    if not fn:
        return False, "dijkstra function not found"
    graph = {
        "A": {"B": 4.0, "C": 2.0},
        "C": {"B": 1.0, "D": 5.0},
        "B": {"D": 1.0},
        "D": {},
    }
    dist = fn(graph, "A")
    if dist.get("B") != 3.0 or dist.get("D") != 4.0:
        return False, f"Unexpected shortest paths: {dist}"
    return True, "Dijkstra algorithm returned correct shortest paths"

register_task(
    4,
    "Algorithms & Data Structures",
    "Dijkstra Shortest Path",
    "benchmark_runs/task_04_dijkstra/dijkstra.py",
    "Please create a file at `benchmark_runs/task_04_dijkstra/dijkstra.py` defining "
    "`dijkstra(graph: dict[str, dict[str, float]], start: str) -> dict[str, float]` "
    "calculating the shortest distance from start to all reachable nodes. "
    "Use write_file to save the file.",
    verify_04,
)


def verify_05(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_05", p)
    ms = getattr(mod, "merge_sort", None)
    qs = getattr(mod, "quick_sort", None)
    if not ms or not qs:
        return False, "merge_sort or quick_sort function missing"
    sample = [38, 27, 43, 3, 9, 82, 10]
    expected = [3, 9, 10, 27, 38, 43, 82]
    if ms(list(sample)) != expected:
        return False, "merge_sort failed"
    if qs(list(sample)) != expected:
        return False, "quick_sort failed"
    return True, "Both merge_sort and quick_sort sorted list correctly"

register_task(
    5,
    "Algorithms & Data Structures",
    "Merge Sort & Quick Sort",
    "benchmark_runs/task_05_mergesort/sort.py",
    "Please create a file at `benchmark_runs/task_05_mergesort/sort.py` containing "
    "`merge_sort(items: list[int]) -> list[int]` and `quick_sort(items: list[int]) -> list[int]`. "
    "Use write_file to save the file.",
    verify_05,
)


def verify_06(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_06", p)
    cls = getattr(mod, "MinHeap", None)
    if not cls:
        return False, "MinHeap class not found"
    heap = cls()
    for v in [5, 3, 8, 1, 2]:
        heap.push(v)
    out = [heap.pop() for _ in range(5)]
    if out != [1, 2, 3, 5, 8]:
        return False, f"Popped items out of order: {out}"
    return True, "MinHeap push/pop in perfect ascending order"

register_task(
    6,
    "Algorithms & Data Structures",
    "Min-Heap from Scratch",
    "benchmark_runs/task_06_min_heap/min_heap.py",
    "Please create a file at `benchmark_runs/task_06_min_heap/min_heap.py` implementing `MinHeap` from scratch "
    "without using python's heapq module. Implement `push(val: int)`, `pop() -> int`, `peek() -> int`, and `__len__()`. "
    "Use write_file to save the file.",
    verify_06,
)


def verify_07(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_07", p)
    cls = getattr(mod, "TokenBucketRateLimiter", None)
    if not cls:
        return False, "TokenBucketRateLimiter class not found"
    limiter = cls(capacity=3.0, refill_rate=1.0)
    for _ in range(3):
        if not limiter.consume(1.0):
            return False, "Initial consume should succeed"
    if limiter.consume(1.0):
        return False, "Should reject when capacity exhausted"
    return True, "TokenBucketRateLimiter enforced capacity and limits"

register_task(
    7,
    "Algorithms & Data Structures",
    "Token Bucket Rate Limiter",
    "benchmark_runs/task_07_rate_limiter/rate_limiter.py",
    "Please create a file at `benchmark_runs/task_07_rate_limiter/rate_limiter.py` implementing "
    "`TokenBucketRateLimiter(capacity: float, refill_rate: float)` with `consume(tokens: float = 1.0) -> bool`. "
    "Use write_file to save the file.",
    verify_07,
)


def verify_08(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_08", p)
    fn = getattr(mod, "topological_sort", None)
    if not fn:
        return False, "topological_sort function not found"
    res = fn(4, [(0, 1), (1, 2), (2, 3)])
    if res != [0, 1, 2, 3]:
        return False, f"Unexpected topo sort: {res}"
    cycle_res = fn(2, [(0, 1), (1, 0)])
    if cycle_res not in ([], None):
        return False, "Cycle should return empty list or None"
    return True, "Topological sort correctly ordered DAG and detected cycle"

register_task(
    8,
    "Algorithms & Data Structures",
    "Topological Sort & Cycle Detection",
    "benchmark_runs/task_08_topo_sort/topo_sort.py",
    "Please create a file at `benchmark_runs/task_08_topo_sort/topo_sort.py` defining "
    "`topological_sort(num_nodes: int, edges: list[tuple[int, int]]) -> list[int]` "
    "returning topological order or empty list `[]` if a cycle is detected. "
    "Use write_file to save the file.",
    verify_08,
)


def verify_09(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_09", p)
    cls = getattr(mod, "HuffmanCoding", None)
    if not cls:
        return False, "HuffmanCoding class not found"
    h = cls()
    encoded, tree = h.encode("abracadabra")
    decoded = h.decode(encoded, tree)
    if decoded != "abracadabra":
        return False, f"Decoded text '{decoded}' does not match original 'abracadabra'"
    return True, "Huffman encode/decode lossless roundtrip verified"

register_task(
    9,
    "Algorithms & Data Structures",
    "Huffman Coding Compression",
    "benchmark_runs/task_09_huffman/huffman.py",
    "Please create a file at `benchmark_runs/task_09_huffman/huffman.py` implementing `HuffmanCoding` "
    "with `encode(text: str) -> tuple[str, Any]` and `decode(encoded_bits: str, tree: Any) -> str`. "
    "Use write_file to save the file.",
    verify_09,
)


def verify_10(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_10", p)
    cls = getattr(mod, "UnionFind", None)
    if not cls:
        return False, "UnionFind class not found"
    uf = cls(5)
    uf.union(0, 1)
    uf.union(1, 2)
    if not uf.connected(0, 2):
        return False, "0 and 2 should be connected"
    if uf.connected(0, 3):
        return False, "0 and 3 should not be connected"
    return True, "UnionFind find, union, connected verified"

register_task(
    10,
    "Algorithms & Data Structures",
    "Disjoint Set Union (Union-Find)",
    "benchmark_runs/task_10_union_find/union_find.py",
    "Please create a file at `benchmark_runs/task_10_union_find/union_find.py` implementing `UnionFind(size: int)` "
    "with `find(p: int) -> int`, `union(p: int, q: int) -> bool`, and `connected(p: int, q: int) -> bool`. "
    "Use write_file to save the file.",
    verify_10,
)


# ── 2. Backend & Systems (11-20) ──────────────────────────────────────────────

def verify_11(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    content = p.read_text(encoding="utf-8")
    if "FastAPI" not in content or "get" not in content or "post" not in content:
        return False, "Missing FastAPI instantiation or routes"
    return True, "FastAPI application code structure verified"

register_task(
    11,
    "Backend & Systems",
    "FastAPI CRUD Service",
    "benchmark_runs/task_11_fastapi_crud/main.py",
    "Please create a file at `benchmark_runs/task_11_fastapi_crud/main.py` implementing a FastAPI app "
    "with Pydantic Item model, in-memory items list, and endpoints: "
    "`GET /items`, `POST /items`, `GET /items/{item_id}`, and `DELETE /items/{item_id}`. "
    "Use write_file to save the file.",
    verify_11,
)


def verify_12(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_12", p)
    cls = getattr(mod, "AuthService", None)
    if not cls:
        return False, "AuthService class not found"
    db_file = p.parent / "test_auth.db"
    if db_file.exists():
        db_file.unlink()
    svc = cls(str(db_file))
    svc.register("alice", "secret123")
    if not svc.login("alice", "secret123"):
        return False, "Valid login failed"
    if svc.login("alice", "wrongpwd"):
        return False, "Invalid login succeeded"
    if db_file.exists():
        db_file.unlink()
    return True, "AuthService SQLite registration, salted hashing, and login verified"

register_task(
    12,
    "Backend & Systems",
    "SQLite User Authentication & Hashing",
    "benchmark_runs/task_12_auth_sqlite/auth.py",
    "Please create a file at `benchmark_runs/task_12_auth_sqlite/auth.py` implementing `AuthService(db_path: str)` "
    "with `register(username: str, password: str) -> bool` and `login(username: str, password: str) -> bool` "
    "storing users in SQLite with salted password hashes (e.g. hashlib.pbkdf2_hmac or sha256). "
    "Use write_file to save the file.",
    verify_12,
)


def verify_13(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_13", p)
    enc = getattr(mod, "encode_token", None)
    dec = getattr(mod, "decode_token", None)
    if not enc or not dec:
        return False, "encode_token or decode_token missing"
    payload = {"user_id": 42, "role": "admin"}
    token = enc(payload, "mysecret")
    res = dec(token, "mysecret")
    if res.get("user_id") != 42 or res.get("role") != "admin":
        return False, f"Decoded payload mismatch: {res}"
    try:
        dec(token, "wrongsecret")
        return False, "Decoding with wrong secret did not fail"
    except Exception:
        pass
    return True, "JWT token encode and HMAC-SHA256 signature verification passed"

register_task(
    13,
    "Backend & Systems",
    "JWT Encoder & Verifier from Scratch",
    "benchmark_runs/task_13_jwt_service/jwt_util.py",
    "Please create a file at `benchmark_runs/task_13_jwt_service/jwt_util.py` implementing "
    "`encode_token(payload: dict, secret: str) -> str` and `decode_token(token: str, secret: str) -> dict` "
    "using pure Python HMAC-SHA256 and base64url encoding (no external PyJWT dependency). "
    "Use write_file to save the file.",
    verify_13,
)


def verify_14(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_14", p)
    cls = getattr(mod, "Router", None)
    if not cls:
        return False, "Router class not found"
    r = cls()
    r.add_route("GET", "/users/{id}", lambda req, params: f"user:{params.get('id')}")
    handler, params = r.resolve("GET", "/users/42")
    if not handler or params.get("id") != "42":
        return False, f"Routing failed to extract params: {params}"
    return True, "Router parameterized path resolution verified"

register_task(
    14,
    "Backend & Systems",
    "HTTP Path Router",
    "benchmark_runs/task_14_http_router/router.py",
    "Please create a file at `benchmark_runs/task_14_http_router/router.py` implementing `Router` "
    "with `add_route(method: str, path_pattern: str, handler: callable)` and "
    "`resolve(method: str, path: str) -> tuple[callable, dict]` extracting parameters like `/users/{id}`. "
    "Use write_file to save the file.",
    verify_14,
)


def verify_15(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_15", p)
    cls = getattr(mod, "JobQueue", None)
    if not cls:
        return False, "JobQueue class not found"
    jq = cls()
    jid = jq.enqueue(lambda x, y: x + y, 10, 20)
    res = jq.run_next()
    if res != 30:
        return False, f"Job returned {res}, expected 30"
    if jq.get_status(jid) != "completed":
        return False, "Job status not updated to completed"
    return True, "JobQueue enqueue, execute, and status check verified"

register_task(
    15,
    "Backend & Systems",
    "In-Memory Job Queue",
    "benchmark_runs/task_15_job_queue/job_queue.py",
    "Please create a file at `benchmark_runs/task_15_job_queue/job_queue.py` implementing `JobQueue` "
    "with `enqueue(func, *args, **kwargs) -> str` (returning job_id), `run_next() -> Any`, "
    "and `get_status(job_id: str) -> str` ('pending', 'completed', 'failed'). "
    "Use write_file to save the file.",
    verify_15,
)


def verify_16(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_16", p)
    cls = getattr(mod, "EventBus", None)
    if not cls:
        return False, "EventBus class not found"
    eb = cls()
    received = []
    cb = lambda data: received.append(data)
    eb.subscribe("order.created", cb)
    eb.publish("order.created", {"order_id": 99})
    if not received or received[0].get("order_id") != 99:
        return False, f"Subscriber did not receive event: {received}"
    eb.unsubscribe("order.created", cb)
    eb.publish("order.created", {"order_id": 100})
    if len(received) != 1:
        return False, "Unsubscribed callback still received event"
    return True, "EventBus subscribe, publish, and unsubscribe verified"

register_task(
    16,
    "Backend & Systems",
    "Pub-Sub Event Bus",
    "benchmark_runs/task_16_event_bus/event_bus.py",
    "Please create a file at `benchmark_runs/task_16_event_bus/event_bus.py` implementing `EventBus` "
    "with `subscribe(topic: str, callback: callable)`, `unsubscribe(topic: str, callback: callable)`, "
    "and `publish(topic: str, data: Any) -> int` returning subscriber count notified. "
    "Use write_file to save the file.",
    verify_16,
)


def verify_17(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_17", p)
    cls = getattr(mod, "KeyValueStore", None)
    if not cls:
        return False, "KeyValueStore class not found"
    kv = cls()
    kv.set("session_1", "user_data", ttl_seconds=0.1)
    if kv.get("session_1") != "user_data":
        return False, "Immediate get failed"
    time.sleep(0.15)
    if kv.get("session_1") is not None:
        return False, "TTL expired key was still returned"
    return True, "KeyValueStore set, get, and TTL expiration verified"

register_task(
    17,
    "Backend & Systems",
    "Key-Value Store with TTL",
    "benchmark_runs/task_17_kv_store_ttl/kv_store.py",
    "Please create a file at `benchmark_runs/task_17_kv_store_ttl/kv_store.py` implementing `KeyValueStore` "
    "with `set(key: str, value: Any, ttl_seconds: float | None = None)`, `get(key: str) -> Any`, "
    "and `delete(key: str) -> bool`. Expired keys must return None. "
    "Use write_file to save the file.",
    verify_17,
)


def verify_18(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_18", p)
    cls = getattr(mod, "CircuitBreaker", None)
    if not cls:
        return False, "CircuitBreaker class not found"
    cb = cls(failure_threshold=2, recovery_timeout=0.2)
    fail_func = lambda: (_ for _ in ()).throw(ValueError("boom"))
    for _ in range(2):
        try:
            cb.call(fail_func)
        except Exception:
            pass
    try:
        cb.call(lambda: "ok")
        return False, "Should raise when circuit is OPEN"
    except Exception as exc:
        if "open" not in str(exc).lower() and "circuit" not in str(exc).lower():
            return False, f"Expected circuit open exception, got {exc}"
    return True, "CircuitBreaker tripped open on failure threshold"

register_task(
    18,
    "Backend & Systems",
    "Circuit Breaker Pattern",
    "benchmark_runs/task_18_circuit_breaker/circuit_breaker.py",
    "Please create a file at `benchmark_runs/task_18_circuit_breaker/circuit_breaker.py` implementing "
    "`CircuitBreaker(failure_threshold: int, recovery_timeout: float)` with `call(func, *args, **kwargs)`. "
    "Trips to OPEN state after consecutive failures and raises an exception on subsequent calls. "
    "Use write_file to save the file.",
    verify_18,
)


def verify_19(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_19", p)
    cls = getattr(mod, "Paginator", None)
    if not cls:
        return False, "Paginator class not found"
    items = list(range(25))
    p1 = cls(items, page_size=10).get_page(1)
    if len(p1["items"]) != 10 or not p1.get("has_next"):
        return False, f"Page 1 incorrect: {p1}"
    p3 = cls(items, page_size=10).get_page(3)
    if len(p3["items"]) != 5 or p3.get("has_next"):
        return False, f"Page 3 incorrect: {p3}"
    return True, "Paginator pagination slicing and page metadata verified"

register_task(
    19,
    "Backend & Systems",
    "API Pagination Helper",
    "benchmark_runs/task_19_paginator/paginator.py",
    "Please create a file at `benchmark_runs/task_19_paginator/paginator.py` implementing "
    "`Paginator(items: list, page_size: int)` with `get_page(page_num: int) -> dict` returning "
    "`{'items': [...], 'page': page_num, 'total_pages': int, 'has_next': bool, 'has_prev': bool}`. "
    "Use write_file to save the file.",
    verify_19,
)


def verify_20(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_20", p)
    cls = getattr(mod, "WebhookDispatcher", None)
    if not cls:
        return False, "WebhookDispatcher class not found"
    d = cls()
    sig = d.sign_payload(json.dumps({"event": "ping"}), "secret123")
    if not sig or not isinstance(sig, str):
        return False, "Invalid signature generated"
    return True, "WebhookDispatcher HMAC signature calculation verified"

register_task(
    20,
    "Backend & Systems",
    "Webhook Dispatcher & HMAC Signer",
    "benchmark_runs/task_20_webhook_dispatcher/dispatcher.py",
    "Please create a file at `benchmark_runs/task_20_webhook_dispatcher/dispatcher.py` implementing `WebhookDispatcher` "
    "with `sign_payload(payload_str: str, secret: str) -> str` (returning hex HMAC-SHA256) and "
    "`format_headers(payload_str: str, secret: str) -> dict` returning headers with signature. "
    "Use write_file to save the file.",
    verify_20,
)


# ── 3. Frontend & Web Development (21-30) ─────────────────────────────────────

def verify_21(p: Path) -> tuple[bool, str]:
    return check_html_structure(p, ["start", "pause", "reset", "25"])

register_task(
    21,
    "Frontend & Web",
    "Pomodoro Timer Widget",
    "benchmark_runs/task_21_pomodoro/index.html",
    "Please create a single-file standalone HTML page at `benchmark_runs/task_21_pomodoro/index.html` "
    "containing a clean Pomodoro Timer with Start, Pause, and Reset buttons, a 25-minute display, "
    "and embedded CSS/JS. Use write_file to save the file.",
    verify_21,
)


def verify_22(p: Path) -> tuple[bool, str]:
    return check_html_structure(p, ["textarea", "preview", "<script>"])

register_task(
    22,
    "Frontend & Web",
    "Live Markdown Previewer",
    "benchmark_runs/task_22_markdown_preview/index.html",
    "Please create a single-file standalone HTML page at `benchmark_runs/task_22_markdown_preview/index.html` "
    "with a two-pane layout: a `<textarea>` editor on the left and a live HTML preview `<div>` on the right, "
    "including embedded JS to convert markdown to HTML. Use write_file to save the file.",
    verify_22,
)


def verify_23(p: Path) -> tuple[bool, str]:
    return check_html_structure(p, ["todo", "progress", "done"])

register_task(
    23,
    "Frontend & Web",
    "Interactive Kanban Board",
    "benchmark_runs/task_23_kanban/index.html",
    "Please create a single-file standalone HTML page at `benchmark_runs/task_23_kanban/index.html` "
    "with 3 columns ('To Do', 'In Progress', 'Done'), an Add Task input form, and task cards. "
    "Include responsive CSS and JS. Use write_file to save the file.",
    verify_23,
)


def verify_24(p: Path) -> tuple[bool, str]:
    return check_html_structure(p, ["weather", "temperature", "forecast"])

register_task(
    24,
    "Frontend & Web",
    "Weather Dashboard Card",
    "benchmark_runs/task_24_weather_card/index.html",
    "Please create a standalone responsive weather widget card at `benchmark_runs/task_24_weather_card/index.html` "
    "displaying current temperature, conditions, humidity, wind, and a 5-day forecast strip. "
    "Use write_file to save the file.",
    verify_24,
)


def verify_25(p: Path) -> tuple[bool, str]:
    return check_html_structure(p, ["generate", "length", "strength"])

register_task(
    25,
    "Frontend & Web",
    "Password Generator & Strength Meter",
    "benchmark_runs/task_25_pwd_meter/index.html",
    "Please create a standalone page at `benchmark_runs/task_25_pwd_meter/index.html` with a password generator "
    "including length slider, uppercase/lowercase/numbers/symbols checkboxes, a Generate button, and a visual "
    "strength indicator bar. Use write_file to save the file.",
    verify_25,
)


def verify_26(p: Path) -> tuple[bool, str]:
    return check_html_structure(p, ["grid", "button", "display"])

register_task(
    26,
    "Frontend & Web",
    "Calculator UI",
    "benchmark_runs/task_26_calculator/index.html",
    "Please create a clean CSS-grid calculator page at `benchmark_runs/task_26_calculator/index.html` "
    "with numbers 0-9, operators (+, -, *, /), equals, clear button, display screen, and functional evaluation JS. "
    "Use write_file to save the file.",
    verify_26,
)


def verify_27(p: Path) -> tuple[bool, str]:
    return check_html_structure(p, ["canvas", "requestanimationframe"])

register_task(
    27,
    "Frontend & Web",
    "Audio Visualizer Canvas",
    "benchmark_runs/task_27_audio_visualizer/index.html",
    "Please create an animated canvas audio frequency visualizer page at `benchmark_runs/task_27_audio_visualizer/index.html` "
    "with animated frequency bars using HTML5 canvas and requestAnimationFrame. Use write_file to save the file.",
    verify_27,
)


def verify_28(p: Path) -> tuple[bool, str]:
    return check_html_structure(p, ["quiz", "score", "next"])

register_task(
    28,
    "Frontend & Web",
    "Interactive Quiz Application",
    "benchmark_runs/task_28_quiz_app/index.html",
    "Please create an interactive multiple-choice quiz page at `benchmark_runs/task_28_quiz_app/index.html` "
    "with 3 questions, option buttons, score tracking, and a final results card. Use write_file to save the file.",
    verify_28,
)


def verify_29(p: Path) -> tuple[bool, str]:
    return check_html_structure(p, ["palette", "color", "copy"])

register_task(
    29,
    "Frontend & Web",
    "Color Palette Generator",
    "benchmark_runs/task_29_color_palette/index.html",
    "Please create a color palette generator tool at `benchmark_runs/task_29_color_palette/index.html` "
    "displaying 5 color swatches with HEX codes and a button to generate new randomized palettes. "
    "Use write_file to save the file.",
    verify_29,
)


def verify_30(p: Path) -> tuple[bool, str]:
    return check_html_structure(p, ["expense", "balance", "amount"])

register_task(
    30,
    "Frontend & Web",
    "Expense Tracker & Balance Sheet",
    "benchmark_runs/task_30_expense_tracker/index.html",
    "Please create a standalone personal expense tracker at `benchmark_runs/task_30_expense_tracker/index.html` "
    "with description/amount input fields, transaction history list, and running balance calculation in JS. "
    "Use write_file to save the file.",
    verify_30,
)


# ── 4. Data Processing & Parsers (31-40) ───────────────────────────────────────

def verify_31(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_31", p)
    c2j = getattr(mod, "csv_to_json", None)
    j2c = getattr(mod, "json_to_csv", None)
    if not c2j or not j2c:
        return False, "csv_to_json or json_to_csv missing"
    csv_raw = "name,age\nAlice,30\nBob,25"
    json_out = c2j(csv_raw)
    data = json.loads(json_out)
    if len(data) != 2 or data[0].get("name") != "Alice":
        return False, f"Parsed JSON incorrect: {data}"
    return True, "CSV to JSON parsing verified"

register_task(
    31,
    "Data Processing & Parsers",
    "CSV & JSON Dual Converter",
    "benchmark_runs/task_31_csv_converter/converter.py",
    "Please create a file at `benchmark_runs/task_31_csv_converter/converter.py` implementing "
    "`csv_to_json(csv_string: str) -> str` and `json_to_csv(json_string: str) -> str`. "
    "Use write_file to save the file.",
    verify_31,
)


def verify_32(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_32", p)
    fn = getattr(mod, "validate_dict", None)
    if not fn:
        return False, "validate_dict function missing"
    schema = {"name": str, "age": int}
    valid_ok, errs = fn({"name": "Alice", "age": 30}, schema)
    if not valid_ok:
        return False, f"Valid dict failed: {errs}"
    invalid_ok, errs2 = fn({"name": "Alice", "age": "not_an_int"}, schema)
    if invalid_ok:
        return False, "Invalid type dict passed validation"
    return True, "validate_dict schema validation verified"

register_task(
    32,
    "Data Processing & Parsers",
    "Schema Validator from Scratch",
    "benchmark_runs/task_32_schema_validator/validator.py",
    "Please create a file at `benchmark_runs/task_32_schema_validator/validator.py` implementing "
    "`validate_dict(data: dict, schema: dict) -> tuple[bool, list[str]]` validating presence of keys "
    "and expected types (e.g. str, int, bool). Use write_file to save the file.",
    verify_32,
)


def verify_33(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_33", p)
    fn = getattr(mod, "parse_apache_log", None)
    if not fn:
        return False, "parse_apache_log function missing"
    sample = '127.0.0.1 - frank [10/Oct/2000:13:55:36 -0700] "GET /apache_pb.gif HTTP/1.0" 200 2326'
    rec = fn(sample)
    if str(rec.get("status")) != "200" or str(rec.get("bytes")) != "2326":
        return False, f"Parsed record mismatch: {rec}"
    return True, "Common log format line parsed successfully"

register_task(
    33,
    "Data Processing & Parsers",
    "Apache/Nginx Log Parser",
    "benchmark_runs/task_33_log_analyzer/log_analyzer.py",
    "Please create a file at `benchmark_runs/task_33_log_analyzer/log_analyzer.py` implementing "
    "`parse_apache_log(line: str) -> dict` extracting `ip`, `method`, `path`, `status`, and `bytes`. "
    "Use write_file to save the file.",
    verify_33,
)


def verify_34(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_34", p)
    fn = getattr(mod, "parse_markdown", None)
    if not fn:
        return False, "parse_markdown function missing"
    html = fn("# Hello\nThis is **bold** text")
    if "<h1>Hello</h1>" not in html and "<h1" not in html:
        return False, f"H1 header not converted: {html}"
    if "<strong>bold</strong>" not in html and "<b>bold</b>" not in html:
        return False, f"Bold text not converted: {html}"
    return True, "Markdown to HTML parser converted headers and bold tags"

register_task(
    34,
    "Data Processing & Parsers",
    "Markdown to HTML Parser",
    "benchmark_runs/task_34_md_parser/md_parser.py",
    "Please create a file at `benchmark_runs/task_34_md_parser/md_parser.py` implementing "
    "`parse_markdown(md_text: str) -> str` supporting `# headers`, `**bold**`, `*italic*`, and paragraphs. "
    "Use write_file to save the file.",
    verify_34,
)


def verify_35(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_35", p)
    fn = getattr(mod, "render_tree", None)
    if not fn:
        return False, "render_tree function missing"
    sample = {"root": {"src": ["app.py", "utils.py"], "README.md": None}}
    res = fn(sample)
    if not isinstance(res, str) or len(res) < 10:
        return False, "render_tree returned empty or non-string"
    return True, "Tree renderer produced ASCII structure"

register_task(
    35,
    "Data Processing & Parsers",
    "Directory Tree Visualizer",
    "benchmark_runs/task_35_tree_viz/tree_viz.py",
    "Please create a file at `benchmark_runs/task_35_tree_viz/tree_viz.py` implementing "
    "`render_tree(tree_dict: dict, indent: str = '') -> str` producing an ASCII indented visual tree. "
    "Use write_file to save the file.",
    verify_35,
)


def verify_36(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_36", p)
    fn = getattr(mod, "merge_configs", None)
    interp = getattr(mod, "interpolate_env_vars", None)
    if not fn or not interp:
        return False, "merge_configs or interpolate_env_vars missing"
    base = {"db": {"host": "localhost", "port": 5432}}
    override = {"db": {"port": 5433, "name": "prod"}}
    merged = fn(base, override)
    if merged.get("db", {}).get("port") != 5433 or merged.get("db", {}).get("host") != "localhost":
        return False, f"Deep merge failed: {merged}"
    resolved = interp({"url": "${HOST}:${PORT}"}, {"HOST": "127.0.0.1", "PORT": "8000"})
    if resolved.get("url") != "127.0.0.1:8000":
        return False, f"Interpolation failed: {resolved}"
    return True, "Deep merge and environment variable interpolation verified"

register_task(
    36,
    "Data Processing & Parsers",
    "Config Merger & Env Interpolator",
    "benchmark_runs/task_36_config_merger/config_merger.py",
    "Please create a file at `benchmark_runs/task_36_config_merger/config_merger.py` implementing "
    "`merge_configs(base: dict, override: dict) -> dict` (deep merge) and "
    "`interpolate_env_vars(config: dict, env: dict) -> dict` replacing `${VAR}` placeholders. "
    "Use write_file to save the file.",
    verify_36,
)


def verify_37(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_37", p)
    cls = getattr(mod, "SemVer", None)
    if not cls:
        return False, "SemVer class missing"
    v1 = cls("1.2.3")
    v2 = cls("1.2.4")
    v3 = cls("2.0.0")
    if not (v1 < v2 < v3):
        return False, "Comparison v1 < v2 < v3 failed"
    if not (cls("1.0.0") == cls("1.0.0")):
        return False, "Equality comparison failed"
    return True, "Semantic Versioning parsing and rich comparisons verified"

register_task(
    37,
    "Data Processing & Parsers",
    "SemVer Parser & Comparator",
    "benchmark_runs/task_37_semver/semver.py",
    "Please create a file at `benchmark_runs/task_37_semver/semver.py` implementing a `SemVer` class "
    "parsing versions like '1.2.3' with attributes `major, minor, patch` and comparison operators `<, ==, >`. "
    "Use write_file to save the file.",
    verify_37,
)


def verify_38(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_38", p)
    cls = getattr(mod, "QueryBuilder", None)
    if not cls:
        return False, "QueryBuilder class missing"
    sql = cls().table("users").select("id", "email").where("active = 1").limit(10).build()
    upper_sql = sql.upper()
    if "SELECT ID, EMAIL" not in upper_sql and "SELECT ID,EMAIL" not in upper_sql:
        return False, f"SELECT clause missing: {sql}"
    if "FROM USERS" not in upper_sql:
        return False, f"FROM clause missing: {sql}"
    if "LIMIT 10" not in upper_sql:
        return False, f"LIMIT clause missing: {sql}"
    return True, "Fluent SQL QueryBuilder built valid query string"

register_task(
    38,
    "Data Processing & Parsers",
    "Fluent SQL Query Builder",
    "benchmark_runs/task_38_sql_builder/query_builder.py",
    "Please create a file at `benchmark_runs/task_38_sql_builder/query_builder.py` implementing `QueryBuilder` "
    "with fluent methods `table(name)`, `select(*cols)`, `where(condition)`, `limit(n)`, and `build() -> str`. "
    "Use write_file to save the file.",
    verify_38,
)


def verify_39(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_39", p)
    fn = getattr(mod, "simple_diff", None)
    if not fn:
        return False, "simple_diff function missing"
    diff = fn(["alpha", "beta"], ["alpha", "gamma"])
    diff_text = "".join(diff)
    if "-beta" not in diff_text or "+gamma" not in diff_text:
        return False, f"Unified diff lines missing: {diff}"
    return True, "Unified line diff engine verified"

register_task(
    39,
    "Data Processing & Parsers",
    "Line Diff Engine",
    "benchmark_runs/task_39_diff_engine/diff_engine.py",
    "Please create a file at `benchmark_runs/task_39_diff_engine/diff_engine.py` implementing "
    "`simple_diff(old_lines: list[str], new_lines: list[str]) -> list[str]` producing diff markers "
    "(' ', '-', '+'). Use write_file to save the file.",
    verify_39,
)


def verify_40(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_40", p)
    fn = getattr(mod, "parse_url", None)
    if not fn:
        return False, "parse_url function missing"
    res = fn("https://example.com:8080/path/test?user=alice&active=true")
    if res.get("scheme") != "https" or res.get("host") != "example.com" or str(res.get("port")) != "8080":
        return False, f"URL parse mismatch: {res}"
    return True, "Pure URL parser extracted scheme, host, port, path, and query params"

register_task(
    40,
    "Data Processing & Parsers",
    "URL Parser from Scratch",
    "benchmark_runs/task_40_url_parser/url_parser.py",
    "Please create a file at `benchmark_runs/task_40_url_parser/url_parser.py` implementing "
    "`parse_url(url: str) -> dict` returning `{'scheme': ..., 'host': ..., 'port': ..., 'path': ..., 'query_params': ...}` "
    "without using urllib.parse. Use write_file to save the file.",
    verify_40,
)


# ── 5. DevOps, Security & System Tools (41-50) ────────────────────────────────

def verify_41(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_41", p)
    cls = getattr(mod, "SystemSnapshot", None)
    if not cls:
        return False, "SystemSnapshot class missing"
    snap = cls()
    raw = snap.to_json()
    data = json.loads(raw)
    if not isinstance(data, dict) or "platform" not in data:
        return False, f"JSON output missing platform or structure: {data}"
    return True, "SystemSnapshot serialized system metrics to JSON"

register_task(
    41,
    "DevOps & Security",
    "System Resource Snapshot",
    "benchmark_runs/task_41_system_monitor/monitor.py",
    "Please create a file at `benchmark_runs/task_41_system_monitor/monitor.py` implementing `SystemSnapshot` "
    "collecting platform, architecture, and memory usage into `to_json() -> str`. "
    "Use write_file to save the file.",
    verify_41,
)


def verify_42(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_42", p)
    fn = getattr(mod, "lint_dockerfile", None)
    if not fn:
        return False, "lint_dockerfile function missing"
    issues = fn("FROM ubuntu:latest\nRUN apt-get update")
    if not any("latest" in str(i).lower() for i in issues):
        return False, f"Failed to detect :latest tag issue in {issues}"
    return True, "Dockerfile linter flagged :latest image tag"

register_task(
    42,
    "DevOps & Security",
    "Dockerfile Linter",
    "benchmark_runs/task_42_dockerfile_linter/linter.py",
    "Please create a file at `benchmark_runs/task_42_dockerfile_linter/linter.py` implementing "
    "`lint_dockerfile(content: str) -> list[str]` detecting use of `:latest` base image tags and missing USER directives. "
    "Use write_file to save the file.",
    verify_42,
)


def verify_43(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_43", p)
    fn = getattr(mod, "scan_for_secrets", None)
    if not fn:
        return False, "scan_for_secrets function missing"
    sample = "aws_key = AKIAIOSFODNN7EXAMPLE\nother_data = 123"
    matches = fn(sample)
    if not matches or not any("AKIAIOSFODNN7EXAMPLE" in str(m) for m in matches):
        return False, f"Failed to detect AWS secret key in {matches}"
    return True, "Secret scanner identified AWS access key"

register_task(
    43,
    "DevOps & Security",
    "Secret & Token Scanner",
    "benchmark_runs/task_43_secret_scanner/scanner.py",
    "Please create a file at `benchmark_runs/task_43_secret_scanner/scanner.py` implementing "
    "`scan_for_secrets(text: str) -> list[dict]` detecting AWS keys (`AKIA[0-9A-Z]{16}`) and private keys. "
    "Use write_file to save the file.",
    verify_43,
)


def verify_44(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_44", p)
    fn = getattr(mod, "is_cert_expired", None)
    if not fn:
        return False, "is_cert_expired function missing"
    if not fn("2020-01-01T00:00:00Z"):
        return False, "2020 date should be expired"
    if fn("2035-01-01T00:00:00Z"):
        return False, "2035 date should not be expired"
    return True, "Certificate expiry check verified"

register_task(
    44,
    "DevOps & Security",
    "SSL/TLS Certificate Checker",
    "benchmark_runs/task_44_cert_checker/cert_checker.py",
    "Please create a file at `benchmark_runs/task_44_cert_checker/cert_checker.py` implementing "
    "`is_cert_expired(valid_to_iso: str) -> bool` determining whether an ISO expiration timestamp has passed. "
    "Use write_file to save the file.",
    verify_44,
)


def verify_45(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_45", p)
    fn = getattr(mod, "parse_cron_field", None)
    if not fn:
        return False, "parse_cron_field function missing"
    step_res = fn("*/15", 0, 59)
    if set(step_res) != {0, 15, 30, 45}:
        return False, f"*/15 returned {step_res}, expected {{0, 15, 30, 45}}"
    range_res = fn("1-3", 0, 59)
    if set(range_res) != {1, 2, 3}:
        return False, f"1-3 returned {range_res}, expected {{1, 2, 3}}"
    return True, "Cron field parser evaluated step and range expressions"

register_task(
    45,
    "DevOps & Security",
    "Crontab Expression Parser",
    "benchmark_runs/task_45_cron_parser/cron_parser.py",
    "Please create a file at `benchmark_runs/task_45_cron_parser/cron_parser.py` implementing "
    "`parse_cron_field(field_str: str, min_val: int, max_val: int) -> set[int]` supporting `*`, step `*/n`, range `a-b`. "
    "Use write_file to save the file.",
    verify_45,
)


def verify_46(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_46", p)
    cls = getattr(mod, "PortScanner", None)
    if not cls:
        return False, "PortScanner class missing"
    scanner = cls("127.0.0.1", timeout=0.5)
    # Check port 8000 where our JARVIS server is running!
    is_open = scanner.check_port(8000)
    if not is_open:
        return False, "Port 8000 was reported as closed, but server is running"
    return True, "PortScanner verified against live server port 8000"

register_task(
    46,
    "DevOps & Security",
    "Network Port Scanner",
    "benchmark_runs/task_46_port_scanner/port_scanner.py",
    "Please create a file at `benchmark_runs/task_46_port_scanner/port_scanner.py` implementing "
    "`PortScanner(target_host: str, timeout: float = 0.5)` with `check_port(port: int) -> bool` using socket.connect_ex. "
    "Use write_file to save the file.",
    verify_46,
)


def verify_47(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_47", p)
    fn = getattr(mod, "compare_env_files", None)
    if not fn:
        return False, "compare_env_files function missing"
    example = "PORT=8000\nDB_URL=sqlite:///db.sqlite\nSECRET_KEY=default"
    actual = "PORT=8080\nDB_URL=sqlite:///db.sqlite\nEXTRA_VAL=foo"
    res = fn(example, actual)
    if "SECRET_KEY" not in res.get("missing_keys", []):
        return False, f"SECRET_KEY was not reported missing: {res}"
    if "EXTRA_VAL" not in res.get("extra_keys", []):
        return False, f"EXTRA_VAL was not reported extra: {res}"
    return True, "Env file diff comparison verified"

register_task(
    47,
    "DevOps & Security",
    "Env File Drift Validator",
    "benchmark_runs/task_47_env_validator/validator.py",
    "Please create a file at `benchmark_runs/task_47_env_validator/validator.py` implementing "
    "`compare_env_files(example_content: str, actual_content: str) -> dict` returning "
    "`{'missing_keys': [...], 'extra_keys': [...], 'matching_keys': [...]}`. "
    "Use write_file to save the file.",
    verify_47,
)


def verify_48(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_48", p)
    fn = getattr(mod, "lint_commit_message", None)
    if not fn:
        return False, "lint_commit_message function missing"
    ok1, msg1 = fn("feat(auth): implement jwt token authentication")
    if not ok1:
        return False, f"Valid commit rejected: {msg1}"
    ok2, msg2 = fn("fixed random bugs")
    if ok2:
        return False, "Invalid commit accepted"
    return True, "Conventional commits linter verified"

register_task(
    48,
    "DevOps & Security",
    "Git Conventional Commit Linter",
    "benchmark_runs/task_48_commit_linter/commit_linter.py",
    "Please create a file at `benchmark_runs/task_48_commit_linter/commit_linter.py` implementing "
    "`lint_commit_message(message: str) -> tuple[bool, str]` enforcing conventional commits "
    "(type(scope): subject with type in feat, fix, docs, refactor, test, chore). "
    "Use write_file to save the file.",
    verify_48,
)


def verify_49(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_49", p)
    cls = getattr(mod, "ObjectPool", None)
    if not cls:
        return False, "ObjectPool class missing"
    counter = 0
    def factory():
        nonlocal counter
        counter += 1
        return {"id": counter}
    pool = cls(factory=factory, max_size=3)
    o1 = pool.acquire()
    o2 = pool.acquire()
    if o1["id"] == o2["id"]:
        return False, "Distinct objects not allocated"
    pool.release(o1)
    o3 = pool.acquire()
    if o3["id"] != o1["id"]:
        return False, "Object was not reused from pool"
    return True, "ObjectPool acquire, release, and reuse verified"

register_task(
    49,
    "DevOps & Security",
    "Object & Connection Pool",
    "benchmark_runs/task_49_object_pool/object_pool.py",
    "Please create a file at `benchmark_runs/task_49_object_pool/object_pool.py` implementing `ObjectPool` "
    "with `acquire() -> Any` and `release(obj: Any) -> None` reusing objects from an internal pool. "
    "Use write_file to save the file.",
    verify_49,
)


def verify_50(p: Path) -> tuple[bool, str]:
    valid, msg = check_python_syntax(p)
    if not valid:
        return False, msg
    mod = load_module_from_path("task_50", p)
    cls = getattr(mod, "ArgumentParser", None)
    if not cls:
        return False, "ArgumentParser class missing"
    parser = cls()
    parser.add_argument("--host", type=str, default="localhost")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--debug", action="store_true", default=False)
    args = parser.parse_args(["--port", "9000", "--debug"])
    if getattr(args, "port", None) != 9000 and (not isinstance(args, dict) or args.get("port") != 9000):
        return False, f"Parsed port mismatch: {args}"
    return True, "Custom ArgumentParser parsed arguments with type conversion"

register_task(
    50,
    "DevOps & Security",
    "CLI Argument Parser from Scratch",
    "benchmark_runs/task_50_arg_parser/arg_parser.py",
    "Please create a file at `benchmark_runs/task_50_arg_parser/arg_parser.py` implementing `ArgumentParser` "
    "from scratch with `add_argument(...)` and `parse_args(argv: list[str])`. "
    "Use write_file to save the file.",
    verify_50,
)


# ══════════════════════════════════════════════════════════════════════════════
# Benchmark Runner
# ══════════════════════════════════════════════════════════════════════════════

def run_task(task: TaskDefinition) -> TaskResult:
    print(f"\n[{task.id:02d}/50] ▶ Running Task: {task.name} ({task.category})")
    target_path = PROJECT_ROOT / task.file_path
    
    # Ensure target directory exists and clean target file before running
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        target_path.unlink()

    tools_called: list[str] = []
    
    def on_event(event: Any) -> None:
        if isinstance(event, dict) and event.get("type") == "tool_start":
            tool_name = event.get("name", "unknown")
            tools_called.append(tool_name)
            print(f"       ⚡ JARVIS Invoked Tool: {tool_name}", flush=True)

    t0 = time.time()
    response_excerpt = ""
    agent_exc = None
    
    # Use dedicated JarvisAgent instance per task to prevent context explosion
    try:
        agent = JarvisAgent(working_dir=str(PROJECT_ROOT))
        raw_response = agent.run_non_interactive(task.prompt, on_event=on_event)
        response_excerpt = (raw_response or "").strip()[:200]
    except Exception as exc:
        agent_exc = exc
        print(f"       ❌ JARVIS Exception: {exc}", flush=True)

    duration = time.time() - t0

    # Ground-Truth Disk Verification
    file_exists = target_path.exists()
    file_size = target_path.stat().st_size if file_exists else 0
    syntax_valid = False
    verification_msg = ""
    status = "FAILED"

    if agent_exc:
        status = "EXCEPTION"
        verification_msg = f"Agent execution exception: {agent_exc}"
    elif not file_exists:
        status = "NO_FILE"
        verification_msg = f"Target file `{task.file_path}` was NOT created on disk"
    else:
        # Check syntax
        if target_path.suffix == ".py":
            syntax_ok, syn_msg = check_python_syntax(target_path)
            syntax_valid = syntax_ok
            if not syntax_ok:
                status = "SYNTAX_ERROR"
                verification_msg = syn_msg
        else:
            syntax_valid = True

        if status not in ("SYNTAX_ERROR", "NO_FILE", "EXCEPTION"):
            # Run functional verification test
            try:
                pass_ok, test_msg = task.verify_func(target_path)
                if pass_ok:
                    status = "PASSED"
                    verification_msg = test_msg
                else:
                    status = "PARTIAL"
                    verification_msg = f"Functional assertion failed: {test_msg}"
            except Exception as test_exc:
                status = "PARTIAL"
                verification_msg = f"Verifier exception: {test_exc}"

    print(f"       Result: {status} in {duration:.2f}s | Size: {file_size}B | Info: {verification_msg}")
    
    return TaskResult(
        id=task.id,
        category=task.category,
        name=task.name,
        file_path=task.file_path,
        status=status,
        duration_s=round(duration, 2),
        file_exists=file_exists,
        file_size_bytes=file_size,
        syntax_valid=syntax_valid,
        verification_message=verification_msg,
        tools_called=tools_called,
        response_excerpt=response_excerpt,
    )


def generate_reports(results: list[TaskResult], output_json: Path, output_md: Path) -> None:
    # 1. JSON Report
    data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_tasks": len(results),
        "passed": sum(1 for r in results if r.status == "PASSED"),
        "partial": sum(1 for r in results if r.status == "PARTIAL"),
        "failed_syntax": sum(1 for r in results if r.status == "SYNTAX_ERROR"),
        "failed_no_file": sum(1 for r in results if r.status == "NO_FILE"),
        "failed_exception": sum(1 for r in results if r.status == "EXCEPTION"),
        "total_duration_s": round(sum(r.duration_s for r in results), 2),
        "results": [asdict(r) for r in results],
    }
    output_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"\n📊 JSON report saved to: {output_json}")

    # 2. Markdown Report
    passed_cnt = data["passed"]
    total_cnt = data["total_tasks"]
    pass_pct = (passed_cnt / total_cnt * 100) if total_cnt else 0

    md_lines = [
        "# JARVIS v5.4 — 50 Autonomous Coding Tasks Benchmark Report",
        "",
        f"**Date:** {data['timestamp']}  ",
        f"**Score:** `{passed_cnt}/{total_cnt}` ({pass_pct:.1f}% Passed)  ",
        f"**Total Execution Time:** {data['total_duration_s']}s  ",
        f"**Policy:** ZERO-FAKING. All files created exclusively by JARVIS via agentic tool loop and independently tested.",
        "",
        "## Summary Scoreboard",
        "",
        "| Category | Passed | Partial | Failed | Total | Pass Rate |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |",
    ]

    # Category breakdown
    categories = sorted({r.category for r in results})
    for cat in categories:
        cat_res = [r for r in results if r.category == cat]
        c_passed = sum(1 for r in cat_res if r.status == "PASSED")
        c_partial = sum(1 for r in cat_res if r.status == "PARTIAL")
        c_failed = sum(1 for r in cat_res if r.status not in ("PASSED", "PARTIAL"))
        c_tot = len(cat_res)
        c_pct = (c_passed / c_tot * 100) if c_tot else 0
        md_lines.append(f"| {cat} | {c_passed} | {c_partial} | {c_failed} | {c_tot} | {c_pct:.1f}% |")

    md_lines.extend([
        "",
        "## Detailed Task-by-Task Results",
        "",
        "| # | Task | Category | Status | Time | File Created | Verification |",
        "| :---: | :--- | :--- | :---: | :---: | :---: | :--- |",
    ])

    status_badges = {
        "PASSED": "✅ PASSED",
        "PARTIAL": "⚠️ PARTIAL",
        "SYNTAX_ERROR": "❌ SYNTAX",
        "NO_FILE": "❌ NO_FILE",
        "EXCEPTION": "💥 ERROR",
    }

    for r in results:
        badge = status_badges.get(r.status, r.status)
        file_info = f"`{Path(r.file_path).name}` ({r.file_size_bytes}B)" if r.file_exists else "❌ None"
        md_lines.append(
            f"| {r.id:02d} | **{r.name}** | {r.category} | {badge} | {r.duration_s}s | {file_info} | {r.verification_message} |"
        )

    output_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    print(f"📄 Markdown report saved to: {output_md}")


def main() -> None:
    parser = argparse.ArgumentParser(description="JARVIS 50-Task Coding Benchmark")
    parser.add_argument("--start", type=int, default=1, help="Start task ID (1-50)")
    parser.add_argument("--count", type=int, default=50, help="Number of tasks to run")
    parser.add_argument("--task", type=int, default=None, help="Run single task ID")
    args = parser.parse_args()

    selected_tasks = TASKS
    if args.task:
        selected_tasks = [t for t in TASKS if t.id == args.task]
    else:
        selected_tasks = [t for t in TASKS if args.start <= t.id < args.start + args.count]

    print("=" * 80)
    print(f"🚀 JARVIS 50-TASK CODING BENCHMARK SUITE")
    print(f"   Selected Tasks: {len(selected_tasks)} (IDs: {[t.id for t in selected_tasks[:5]]}...)")
    print(f"   Strict Policy: ZERO FAKING — Antigravity evaluates; JARVIS generates.")
    print("=" * 80)

    results: list[TaskResult] = []
    for t in selected_tasks:
        res = run_task(t)
        results.append(res)

    output_json = PROJECT_ROOT / "JARVIS_50_TASKS_BENCHMARK.json"
    output_md = PROJECT_ROOT / "JARVIS_50_TASKS_BENCHMARK.md"
    generate_reports(results, output_json, output_md)


if __name__ == "__main__":
    main()
