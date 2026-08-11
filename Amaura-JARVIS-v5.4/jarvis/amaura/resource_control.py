"""Cross-process resource control for Amaura's small-Mac execution profile.

This module deliberately separates three ideas that v3.6.0 conflated:

* a *normal target* for ordinary capability work;
* a temporary *burst allowance* for one expensive worker; and
* a hard *absolute ceiling* used to terminate runaway child process trees.

Reservations are persisted in a tiny JSON ledger protected by an OS file lock.
Actual process-tree RSS and host memory/swap pressure are sampled with psutil,
with extra macOS telemetry when the native commands are available.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator

try:  # psutil is a lightweight core dependency in v3.6.1, but fail safely if missing.
    import psutil  # type: ignore
except Exception:  # pragma: no cover - fallback is for damaged/minimal installs.
    psutil = None  # type: ignore

from jarvis.tools.security import workspace_root

_MIB = 1024 * 1024
_LOCAL_LOCK = threading.RLock()
_MAC_PRESSURE_CACHE_LOCK = threading.Lock()
_MAC_PRESSURE_CACHE: tuple[float, float | None] = (0.0, None)
_NATIVE_MEMORY_CACHE_LOCK = threading.Lock()
_NATIVE_MEMORY_CACHE: tuple[float, tuple[int, int, float, int, int, float] | None] = (0.0, None)
_PS_TABLE_CACHE_LOCK = threading.Lock()
_PS_TABLE_CACHE: tuple[float, dict[int, tuple[int, int]]] = (0.0, {})


@dataclass(frozen=True, slots=True)
class MemoryPolicy:
    normal_target_mb: int = 1500
    burst_limit_mb: int = 2500
    absolute_limit_mb: int = 3000
    pressure_limit_mb: int = 1000
    yellow_available_mb: int = 1600
    red_available_mb: int = 800
    yellow_used_percent: float = 82.0
    red_used_percent: float = 92.0
    yellow_swap_percent: float = 30.0
    red_swap_percent: float = 60.0
    swap_growth_abort_mb: int = 192
    stale_reservation_seconds: int = 7200

    @classmethod
    def from_env(cls) -> "MemoryPolicy":
        def _int(name: str, default: int, minimum: int, maximum: int) -> int:
            raw = os.environ.get(name, "").strip()
            if not raw:
                return default
            try:
                return max(minimum, min(int(raw), maximum))
            except ValueError:
                return default

        normal = _int("AMAURA_RAM_NORMAL_TARGET_MB", 1500, 512, 4096)
        burst = _int("AMAURA_RAM_BURST_LIMIT_MB", 2500, normal, 6144)
        absolute = _int("AMAURA_RAM_ABSOLUTE_LIMIT_MB", 3000, burst, 7168)
        pressure = _int("AMAURA_RAM_PRESSURE_LIMIT_MB", 1000, 384, normal)
        return cls(
            normal_target_mb=normal,
            burst_limit_mb=burst,
            absolute_limit_mb=absolute,
            pressure_limit_mb=pressure,
            swap_growth_abort_mb=_int("AMAURA_SWAP_GROWTH_ABORT_MB", 192, 64, 2048),
            stale_reservation_seconds=_int("AMAURA_RESOURCE_LEASE_TTL_SECONDS", 7200, 60, 86400),
        )


@dataclass(frozen=True, slots=True)
class HostMemorySnapshot:
    total_mb: int
    available_mb: int
    used_percent: float
    swap_used_mb: int
    swap_total_mb: int
    swap_percent: float
    mac_free_percent: float | None
    pressure: str
    sampled_at: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _mac_free_percent() -> float | None:
    """Return macOS' native free-memory signal without spawning continuously.

    Heavy workers are sampled several times per second for RSS enforcement. Calling
    ``memory_pressure -Q`` at that cadence would itself create avoidable process
    churn, so the native signal is cached for two seconds. psutil telemetry remains
    live on every scheduler/worker sample.
    """
    global _MAC_PRESSURE_CACHE
    if sys.platform != "darwin":
        return None
    now = time.monotonic()
    with _MAC_PRESSURE_CACHE_LOCK:
        sampled_at, cached = _MAC_PRESSURE_CACHE
        if now - sampled_at < 2.0:
            return cached
        command = shutil_which("memory_pressure")
        if not command:
            _MAC_PRESSURE_CACHE = (now, None)
            return None
        try:
            proc = subprocess.run(
                [command, "-Q"], text=True, capture_output=True, check=False, timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            _MAC_PRESSURE_CACHE = (now, None)
            return None
        text = f"{proc.stdout}\n{proc.stderr}"
        match = re.search(r"System-wide memory free percentage:\s*([0-9.]+)%", text, re.I)
        try:
            value = float(match.group(1)) if match else None
        except ValueError:
            value = None
        _MAC_PRESSURE_CACHE = (now, value)
        return value


def shutil_which(command: str) -> str | None:
    # Local wrapper avoids importing shutil at module import in worker hot paths.
    import shutil

    return shutil.which(command)


def _parse_size_mb(value: str) -> float:
    value = value.strip().upper()
    match = re.match(r"([0-9.]+)\s*([KMGT]?)", value)
    if not match:
        return 0.0
    number = float(match.group(1))
    unit = match.group(2)
    factor = {"": 1 / _MIB, "K": 1 / 1024, "M": 1, "G": 1024, "T": 1024 * 1024}.get(unit, 0)
    return number * factor


def _native_memory_values(policy: MemoryPolicy) -> tuple[int, int, float, int, int, float]:
    """Return total/available/used/swap metrics without third-party packages."""
    global _NATIVE_MEMORY_CACHE
    now = time.monotonic()
    with _NATIVE_MEMORY_CACHE_LOCK:
        sampled_at, cached = _NATIVE_MEMORY_CACHE
        if cached is not None and now - sampled_at < 1.5:
            return cached

        if sys.platform == "darwin":
            total_mb = 0
            sysctl = shutil_which("sysctl")
            if sysctl:
                try:
                    total_proc = subprocess.run(
                        [sysctl, "-n", "hw.memsize"], text=True, capture_output=True, check=False, timeout=2
                    )
                    total_mb = int(int(total_proc.stdout.strip()) / _MIB) if total_proc.returncode == 0 else 0
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    total_mb = 0
            mac_free = _mac_free_percent()
            available_mb = int(total_mb * mac_free / 100.0) if total_mb and mac_free is not None else policy.yellow_available_mb
            used_percent = 100.0 - (available_mb / total_mb * 100.0) if total_mb else policy.yellow_used_percent
            swap_total_mb = 0
            swap_used_mb = 0
            if sysctl:
                try:
                    swap_proc = subprocess.run(
                        [sysctl, "-n", "vm.swapusage"], text=True, capture_output=True, check=False, timeout=2
                    )
                    if swap_proc.returncode == 0:
                        total_match = re.search(r"total\s*=\s*([0-9.]+[KMGT]?)", swap_proc.stdout, re.I)
                        used_match = re.search(r"used\s*=\s*([0-9.]+[KMGT]?)", swap_proc.stdout, re.I)
                        if total_match:
                            swap_total_mb = int(_parse_size_mb(total_match.group(1)))
                        if used_match:
                            swap_used_mb = int(_parse_size_mb(used_match.group(1)))
                except (OSError, subprocess.TimeoutExpired):
                    pass
            swap_percent = (swap_used_mb / swap_total_mb * 100.0) if swap_total_mb else 0.0
            result = (total_mb, available_mb, used_percent, swap_used_mb, swap_total_mb, swap_percent)
        elif Path("/proc/meminfo").is_file():
            values: dict[str, int] = {}
            try:
                for line in Path("/proc/meminfo").read_text(encoding="utf-8", errors="replace").splitlines():
                    key, _, rest = line.partition(":")
                    token = rest.strip().split()[0] if rest.strip() else "0"
                    values[key] = int(token)  # Linux meminfo values are KiB.
            except (OSError, ValueError):
                values = {}
            total_mb = int(values.get("MemTotal", 0) / 1024)
            available_mb = int(values.get("MemAvailable", values.get("MemFree", 0)) / 1024)
            used_percent = 100.0 - (available_mb / total_mb * 100.0) if total_mb else policy.yellow_used_percent
            swap_total_mb = int(values.get("SwapTotal", 0) / 1024)
            swap_free_mb = int(values.get("SwapFree", 0) / 1024)
            swap_used_mb = max(0, swap_total_mb - swap_free_mb)
            swap_percent = (swap_used_mb / swap_total_mb * 100.0) if swap_total_mb else 0.0
            result = (total_mb, available_mb, used_percent, swap_used_mb, swap_total_mb, swap_percent)
        else:
            result = (0, policy.yellow_available_mb, policy.yellow_used_percent, 0, 0, 0.0)

        _NATIVE_MEMORY_CACHE = (now, result)
        return result


def sample_host_memory(policy: MemoryPolicy | None = None) -> HostMemorySnapshot:
    policy = policy or MemoryPolicy.from_env()
    if psutil is not None:
        virtual = psutil.virtual_memory()
        swap = psutil.swap_memory()
        total_mb = int(virtual.total / _MIB)
        available_mb = int(virtual.available / _MIB)
        used_percent = float(virtual.percent)
        swap_used_mb = int(swap.used / _MIB)
        swap_total_mb = int(swap.total / _MIB)
        swap_percent = float(swap.percent)
    else:
        total_mb, available_mb, used_percent, swap_used_mb, swap_total_mb, swap_percent = _native_memory_values(policy)

    mac_free = _mac_free_percent()
    red = (
        available_mb <= policy.red_available_mb
        or used_percent >= policy.red_used_percent
        or swap_percent >= policy.red_swap_percent
        or (mac_free is not None and mac_free <= 8.0)
    )
    yellow = (
        available_mb <= policy.yellow_available_mb
        or used_percent >= policy.yellow_used_percent
        or swap_percent >= policy.yellow_swap_percent
        or (mac_free is not None and mac_free <= 15.0)
    )
    if os.environ.get("AMAURA_IGNORE_RAM_PRESSURE") == "1":
        pressure = "green"
    else:
        pressure = "red" if red else "yellow" if yellow else "green"
    return HostMemorySnapshot(
        total_mb=total_mb,
        available_mb=available_mb,
        used_percent=round(used_percent, 2),
        swap_used_mb=swap_used_mb,
        swap_total_mb=swap_total_mb,
        swap_percent=round(swap_percent, 2),
        mac_free_percent=mac_free,
        pressure=pressure,
        sampled_at=time.time(),
    )


def _posix_process_table() -> dict[int, tuple[int, int]]:
    """Map PID -> (PPID, RSS KiB), cached briefly to keep monitoring cheap."""
    global _PS_TABLE_CACHE
    now = time.monotonic()
    with _PS_TABLE_CACHE_LOCK:
        sampled_at, cached = _PS_TABLE_CACHE
        if cached and now - sampled_at < 0.4:
            return cached
        ps = shutil_which("ps")
        if not ps:
            return {}
        try:
            proc = subprocess.run(
                [ps, "-axo", "pid=,ppid=,rss="], text=True, capture_output=True, check=False, timeout=2
            )
        except (OSError, subprocess.TimeoutExpired):
            return {}
        table: dict[int, tuple[int, int]] = {}
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                parts = line.split()
                if len(parts) != 3:
                    continue
                try:
                    pid, ppid, rss_kib = map(int, parts)
                except ValueError:
                    continue
                table[pid] = (ppid, max(0, rss_kib))
        _PS_TABLE_CACHE = (now, table)
        return table


def process_tree_rss_mb(pid: int) -> int:
    if psutil is not None:
        try:
            root = psutil.Process(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return 0
        seen: set[int] = set()
        total = 0
        candidates = [root]
        try:
            candidates.extend(root.children(recursive=True))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        for process in candidates:
            if process.pid in seen:
                continue
            seen.add(process.pid)
            try:
                total += int(process.memory_info().rss)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return int(total / _MIB)

    if os.name == "posix":
        table = _posix_process_table()
        if pid not in table:
            return 0
        descendants = {pid}
        changed = True
        while changed:
            changed = False
            for child, (parent, _rss) in table.items():
                if child not in descendants and parent in descendants:
                    descendants.add(child)
                    changed = True
        total_kib = sum(table[item][1] for item in descendants if item in table)
        return int(total_kib / 1024)
    return 0


def terminate_process_tree(pid: int, grace_seconds: float = 2.0) -> None:
    if psutil is not None:
        try:
            root = psutil.Process(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return
        try:
            children = root.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            children = []
        processes = [*children, root]
        for process in reversed(processes):
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                process.terminate()
        _, alive = psutil.wait_procs(processes, timeout=max(0.1, grace_seconds))
        for process in alive:
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                process.kill()
        return

    if os.name == "posix":
        # _run() starts capability children in their own session, making PID the
        # process-group ID. Kill the whole group so Chromium/model descendants do
        # not survive their disposable worker. Fall back to the root PID if needed.
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + max(0.1, grace_seconds)
        while time.monotonic() < deadline and _pid_alive(pid):
            time.sleep(0.05)
        if _pid_alive(pid):
            with contextlib.suppress(OSError):
                os.killpg(pid, signal.SIGKILL)
        return

    with contextlib.suppress(OSError):
        os.kill(pid, signal.SIGTERM)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if psutil is not None:
        try:
            return bool(psutil.pid_exists(pid))
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _ledger_path() -> Path:
    raw = os.environ.get("AMAURA_RESOURCE_LEDGER_PATH", "").strip()
    path = Path(raw).expanduser() if raw else workspace_root() / ".amaura-data" / "capability-resource-ledger.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.resolve()


@contextlib.contextmanager
def _locked_ledger_file() -> Iterator[Any]:
    path = _ledger_path()
    handle = path.open("a+", encoding="utf-8")
    with _LOCAL_LOCK:
        locked = False
        if os.name == "posix":
            try:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                locked = True
            except (ImportError, OSError):
                locked = False
        try:
            yield handle
        finally:
            if locked:
                with contextlib.suppress(OSError):
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()


def _read_state(handle: Any) -> dict[str, Any]:
    handle.seek(0)
    raw = handle.read().strip()
    if not raw:
        return {"version": 1, "reservations": []}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"version": 1, "reservations": []}
    if not isinstance(payload, dict) or not isinstance(payload.get("reservations"), list):
        return {"version": 1, "reservations": []}
    return payload


def _write_state(handle: Any, payload: dict[str, Any]) -> None:
    handle.seek(0)
    handle.truncate(0)
    json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
    handle.flush()
    with contextlib.suppress(OSError):
        os.fsync(handle.fileno())


def _prune(payload: dict[str, Any], policy: MemoryPolicy, now: float) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for raw in payload.get("reservations", []):
        if not isinstance(raw, dict):
            continue
        try:
            pid = int(raw.get("pid", 0))
            created = float(raw.get("created_at", 0.0))
        except (TypeError, ValueError):
            continue
        if now - created > policy.stale_reservation_seconds:
            continue
        if not _pid_alive(pid):
            continue
        kept.append(raw)
    return kept


class CrossProcessResourceLedger:
    """Durable admission ledger shared by every Amaura process on one host."""

    def __init__(self, policy: MemoryPolicy | None = None):
        self.policy = policy or MemoryPolicy.from_env()

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        with _locked_ledger_file() as handle:
            payload = _read_state(handle)
            reservations = _prune(payload, self.policy, now)
            if reservations != payload.get("reservations", []):
                payload["reservations"] = reservations
                _write_state(handle, payload)
        return self._summarize(reservations)

    @staticmethod
    def _summarize(reservations: list[dict[str, Any]]) -> dict[str, Any]:
        total = sum(max(0, int(item.get("ram_mb", 0))) for item in reservations)
        heavy = sum(1 for item in reservations if bool(item.get("heavy")))
        return {
            "reserved_mb": total,
            "active_heavy_jobs": heavy,
            "active_jobs": len(reservations),
            "reservations": [
                {
                    "id": str(item.get("id", "")),
                    "pid": int(item.get("pid", 0)),
                    "capability": str(item.get("capability", "")),
                    "ram_mb": int(item.get("ram_mb", 0)),
                    "heavy": bool(item.get("heavy")),
                }
                for item in reservations
            ],
        }

    def try_reserve(self, *, capability: str, ram_mb: int, heavy: bool) -> tuple[str | None, str, dict[str, Any]]:
        policy = self.policy
        host = sample_host_memory(policy)
        current_tree_rss = process_tree_rss_mb(os.getpid())
        now = time.time()
        with _locked_ledger_file() as handle:
            payload = _read_state(handle)
            reservations = _prune(payload, policy, now)
            summary = self._summarize(reservations)

            if host.pressure == "red" and heavy:
                return None, "system memory pressure is red; heavy workers are blocked", {
                    "host": host.to_dict(), **summary, "process_tree_rss_mb": current_tree_rss,
                }
            if host.pressure == "yellow" and heavy:
                return None, "system memory pressure is yellow; no new heavy worker is admitted", {
                    "host": host.to_dict(), **summary, "process_tree_rss_mb": current_tree_rss,
                }

            effective_limit = (
                policy.pressure_limit_mb if host.pressure == "red"
                else policy.burst_limit_mb if heavy
                else policy.normal_target_mb
            )
            projected = int(summary["reserved_mb"]) + max(0, int(ram_mb))
            if bool(summary["active_heavy_jobs"]) and not heavy:
                # During a burst, keep the host quiet rather than stacking ordinary work behind it.
                return None, "a heavy capability is active; ordinary capability admission is paused", {
                    "host": host.to_dict(), **summary, "process_tree_rss_mb": current_tree_rss,
                    "effective_limit_mb": effective_limit,
                }
            if heavy and int(summary["active_heavy_jobs"]) > 0:
                return None, "another heavy capability is already active", {
                    "host": host.to_dict(), **summary, "process_tree_rss_mb": current_tree_rss,
                    "effective_limit_mb": effective_limit,
                }
            if projected > effective_limit:
                return None, f"projected reservation {projected} MB exceeds {effective_limit} MB limit", {
                    "host": host.to_dict(), **summary, "process_tree_rss_mb": current_tree_rss,
                    "effective_limit_mb": effective_limit,
                }
            if current_tree_rss >= policy.absolute_limit_mb:
                return None, f"Amaura process tree already uses {current_tree_rss} MB, above the absolute ceiling", {
                    "host": host.to_dict(), **summary, "process_tree_rss_mb": current_tree_rss,
                    "effective_limit_mb": effective_limit,
                }

            reservation_id = uuid.uuid4().hex
            reservations.append({
                "id": reservation_id,
                "pid": os.getpid(),
                "capability": capability,
                "ram_mb": max(0, int(ram_mb)),
                "heavy": bool(heavy),
                "created_at": now,
            })
            payload = {"version": 1, "updated_at": now, "reservations": reservations}
            _write_state(handle, payload)
            summary = self._summarize(reservations)
            return reservation_id, "reserved", {
                "host": host.to_dict(), **summary, "process_tree_rss_mb": current_tree_rss,
                "effective_limit_mb": effective_limit,
            }

    def release(self, reservation_id: str) -> None:
        if not reservation_id:
            return
        now = time.time()
        with _locked_ledger_file() as handle:
            payload = _read_state(handle)
            reservations = _prune(payload, self.policy, now)
            reservations = [item for item in reservations if str(item.get("id", "")) != reservation_id]
            payload = {"version": 1, "updated_at": now, "reservations": reservations}
            _write_state(handle, payload)


def child_hard_limit_mb(estimated_mb: int, policy: MemoryPolicy | None = None) -> int:
    policy = policy or MemoryPolicy.from_env()
    # Give estimates reasonable headroom while preserving the absolute cap.
    estimated = max(256, int(estimated_mb))
    return min(policy.absolute_limit_mb, max(768, int(estimated * 1.35)))


__all__ = [
    "CrossProcessResourceLedger",
    "HostMemorySnapshot",
    "MemoryPolicy",
    "child_hard_limit_mb",
    "process_tree_rss_mb",
    "sample_host_memory",
    "terminate_process_tree",
]
