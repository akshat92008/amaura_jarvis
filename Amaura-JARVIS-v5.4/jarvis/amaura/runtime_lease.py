"""Canonical company-runtime leadership lease.

Amaura v7 has one company-level scheduling authority. Task leases in
``CompanyStore`` remain the final execution guard, but all long-running company
loops share this process lease so the autopilot and compatibility mission runner
cannot independently advance the same portfolio.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

COMPANY_RUNTIME_LOCK_SUFFIX = ".amaura-company-runtime.lock"


@contextmanager
def company_runtime_leader_lock(control: Any) -> Iterator[bool]:
    """Acquire the canonical company-runtime leader lease without blocking."""
    if os.name != "posix":
        yield True
        return

    import fcntl

    lock_path = control.store.db_path.with_suffix(COMPANY_RUNTIME_LOCK_SUFFIX)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


__all__ = ["COMPANY_RUNTIME_LOCK_SUFFIX", "company_runtime_leader_lock"]
