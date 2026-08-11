"""Generate a small, syntactically valid example dataset for Fable experiments.

This utility is intentionally separate from the production Amaura workforce.  It
writes one JSONL record and never trains or executes generated code.
"""

from __future__ import annotations

import json
from pathlib import Path

DATASET_FILE = Path(__file__).parent.resolve() / "dataset_fable5.jsonl"

_LRU_SOURCE = '''import threading


class Node:
    def __init__(self, key=0, value=0):
        self.key = key
        self.value = value
        self.prev = None
        self.next = None


class LRUCache:
    def __init__(self, capacity: int):
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self.cache = {}
        self.lock = threading.RLock()
        self.head = Node()
        self.tail = Node()
        self.head.next = self.tail
        self.tail.prev = self.head

    def _remove(self, node: Node) -> None:
        node.prev.next = node.next
        node.next.prev = node.prev

    def _add(self, node: Node) -> None:
        node.prev = self.head
        node.next = self.head.next
        self.head.next.prev = node
        self.head.next = node

    def get(self, key: int) -> int:
        with self.lock:
            node = self.cache.get(key)
            if node is None:
                return -1
            self._remove(node)
            self._add(node)
            return node.value

    def put(self, key: int, value: int) -> None:
        with self.lock:
            if key in self.cache:
                self._remove(self.cache[key])
            node = Node(key, value)
            self.cache[key] = node
            self._add(node)
            if len(self.cache) > self.capacity:
                lru = self.tail.prev
                self._remove(lru)
                del self.cache[lru.key]
'''

_LRU_TEST = '''import unittest

from lru_cache import LRUCache


class TestLRUCache(unittest.TestCase):
    def test_lru_operations(self):
        cache = LRUCache(2)
        cache.put(1, 1)
        cache.put(2, 2)
        self.assertEqual(cache.get(1), 1)
        cache.put(3, 3)
        self.assertEqual(cache.get(2), -1)


if __name__ == "__main__":
    unittest.main()
'''

SAMPLE_TRAINING_EXAMPLES = [
    {
        "instruction": (
            "Build a high-performance LRU Cache in Python with O(1) get and put, "
            "thread safety, and unit tests."
        ),
        "analysis_summary": (
            "Use a hash map plus a doubly linked list, guard mutations with an RLock, "
            "validate capacity, and verify eviction behavior with unit tests."
        ),
        "files": [
            {"path": "lru_cache.py", "content": _LRU_SOURCE},
            {"path": "test_lru_cache.py", "content": _LRU_TEST},
        ],
        "test_command": "python -m unittest test_lru_cache.py",
    }
]


def generate_synthetic_dataset(destination: Path = DATASET_FILE) -> Path:
    """Write deterministic JSONL examples and return the output path."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for example in SAMPLE_TRAINING_EXAMPLES:
            completion = {
                "analysis_summary": example["analysis_summary"],
                "files": example["files"],
                "test_command": example["test_command"],
            }
            record = {
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are an autonomous software engineering model. Return "
                            "structured implementation artifacts and verifiable tests."
                        ),
                    },
                    {"role": "user", "content": example["instruction"]},
                    {"role": "assistant", "content": json.dumps(completion)},
                ]
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return destination


if __name__ == "__main__":
    print(generate_synthetic_dataset())
