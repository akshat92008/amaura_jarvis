"""Canonical company-runtime leadership lease for Amaura v7.

The public lock context remains boolean-compatible with historical callers, but
a successful ``True`` is not authority. Internally an opaque LeaderLease is
registered and bound to the exact process, thread, store, and active OS lock;
leader-owned execution must resolve and validate that capability.
"""

from __future__ import annotations

import os
import secrets
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

COMPANY_RUNTIME_LOCK_SUFFIX = ".amaura-company-runtime.lock"
_registry_lock = threading.RLock()
_active_leases: dict[str, "LeaderLease"] = {}


@dataclass(frozen=True, slots=True)
class LeaderLease:
    """Opaque proof of an active company-runtime leadership acquisition."""

    pid: int
    thread_id: int
    lock_path: str
    store_identity: str
    nonce: str


def _store_identity(control: Any) -> str:
    return str(Path(control.store.db_path).expanduser().resolve())


def company_runtime_lock_path(control: Any) -> Path:
    """Return the single user-level scheduler lock, independent of DB filename."""
    override = os.environ.get("AMAURA_COMPANY_RUNTIME_LOCK_PATH", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".amaura" / COMPANY_RUNTIME_LOCK_SUFFIX).resolve()


def _issue_lease(control: Any, lock_path: Path) -> LeaderLease:
    lease = LeaderLease(
        pid=os.getpid(),
        thread_id=threading.get_ident(),
        lock_path=str(lock_path.resolve()),
        store_identity=_store_identity(control),
        nonce=secrets.token_hex(24),
    )
    with _registry_lock:
        _active_leases[lease.nonce] = lease
    return lease


def _retire_lease(lease: LeaderLease) -> None:
    with _registry_lock:
        if _active_leases.get(lease.nonce) is lease:
            _active_leases.pop(lease.nonce, None)


def validate_company_runtime_lease(control: Any, lease: LeaderLease | None) -> bool:
    if not isinstance(lease, LeaderLease):
        return False
    with _registry_lock:
        if _active_leases.get(lease.nonce) is not lease:
            return False
    return (
        lease.pid == os.getpid()
        and lease.thread_id == threading.get_ident()
        and lease.lock_path == str(company_runtime_lock_path(control).resolve())
        and lease.store_identity == _store_identity(control)
    )


def current_company_runtime_lease(control: Any) -> LeaderLease | None:
    """Return the active capability for this store on this thread, if one exists."""
    pid = os.getpid()
    thread_id = threading.get_ident()
    store_identity = _store_identity(control)
    with _registry_lock:
        candidates = tuple(_active_leases.values())
    for lease in candidates:
        if lease.pid == pid and lease.thread_id == thread_id and lease.store_identity == store_identity:
            if validate_company_runtime_lease(control, lease):
                return lease
    return None


@contextmanager
def company_runtime_leader_lock(control: Any) -> Iterator[bool]:
    """Acquire leadership; expose only compatibility boolean, never the capability."""
    lock_path = company_runtime_lock_path(control)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if os.name != "posix":
        lease = _issue_lease(control, lock_path)
        try:
            yield True
        finally:
            _retire_lease(lease)
        return

    import fcntl

    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        lease = _issue_lease(control, lock_path)
        try:
            yield True
        finally:
            _retire_lease(lease)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


__all__ = [
    "COMPANY_RUNTIME_LOCK_SUFFIX",
    "LeaderLease",
    "company_runtime_leader_lock",
    "company_runtime_lock_path",
    "current_company_runtime_lease",
    "validate_company_runtime_lease",
]
