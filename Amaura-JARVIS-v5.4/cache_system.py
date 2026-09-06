"""
Thread-safe Hybrid LRU-LFU in-memory cache system.

Features:
- Thread-safe operations protected by reentrant locks (RLock).
- Hybrid eviction policy combining Recency (LRU) and Frequency (LFU) with configurable weights.
- Dedicated LRU and LFU eviction modes.
- Per-item and cache-wide TTL (Time-To-Live) expiration.
- Lazy and proactive expired entry cleanup.
- Optional background daemon thread for periodic expired item purging.
- Comprehensive hit, miss, eviction, and expiration statistics tracking.
- Dict-like interface, metric callables, and context manager support.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Mapping,
    Optional,
    Tuple,
    Union,
)


class IntMetric(int):
    """Integer that is also callable returning itself."""
    def __call__(self) -> int:
        return int(self)


class FloatMetric(float):
    """Float that is also callable returning itself."""
    def __call__(self) -> float:
        return float(self)


class SizeMetric(int):
    """Cache size metric that can be used both as an int and as a callable method."""
    def __call__(self) -> int:
        return int(self)


class EvictionPolicy(str, Enum):
    """Eviction policy options for the cache."""
    HYBRID = "hybrid"
    LRU = "lru"
    LFU = "lfu"


@dataclass
class CacheEntry:
    """Represents an entry stored in the cache."""
    key: Any
    value: Any
    created_at: float
    last_accessed: float
    frequency: int = 1
    ttl: Optional[float] = None
    insertion_order: int = 0

    @property
    def expires_at(self) -> Optional[float]:
        """Timestamp when this entry expires, or None if no TTL."""
        if self.ttl is None:
            return None
        return self.created_at + self.ttl

    def is_expired(self, current_time: Optional[float] = None) -> bool:
        """Check if entry has expired relative to current_time."""
        if self.ttl is None:
            return False
        now = time.time() if current_time is None else current_time
        return now >= (self.created_at + self.ttl)

    def remaining_ttl(self, current_time: Optional[float] = None) -> Optional[float]:
        """Remaining TTL in seconds, or None if no TTL."""
        if self.ttl is None:
            return None
        now = time.time() if current_time is None else current_time
        rem = (self.created_at + self.ttl) - now
        return max(0.0, rem)


class CacheStats:
    """Tracks hit/miss, eviction, and expiration statistics."""
    def __init__(
        self,
        hits: int = 0,
        misses: int = 0,
        evictions: int = 0,
        expirations: int = 0,
        capacity: int = 0,
        size: int = 0,
    ) -> None:
        self.hits = hits
        self.misses = misses
        self.evictions = evictions
        self.expirations = expirations
        self.capacity = capacity
        self.size = size

    @property
    def total_requests(self) -> int:
        """Total get requests (hits + misses)."""
        return self.hits + self.misses

    @property
    def hit_ratio(self) -> float:
        """Ratio of hits to total requests (0.0 if no requests)."""
        total = self.total_requests
        return self.hits / total if total > 0 else 0.0

    @property
    def hit_rate(self) -> float:
        """Alias for hit_ratio."""
        return self.hit_ratio

    @property
    def miss_ratio(self) -> float:
        """Ratio of misses to total requests (0.0 if no requests)."""
        total = self.total_requests
        return self.misses / total if total > 0 else 0.0

    @property
    def miss_rate(self) -> float:
        """Alias for miss_ratio."""
        return self.miss_ratio

    def reset(self) -> None:
        """Reset hit, miss, eviction, and expiration counters."""
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.expirations = 0

    def to_dict(self) -> Dict[str, Any]:
        """Export statistics as a dictionary."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "expirations": self.expirations,
            "capacity": self.capacity,
            "size": self.size,
            "total_requests": self.total_requests,
            "hit_ratio": self.hit_ratio,
            "miss_ratio": self.miss_ratio,
            "hit_rate": self.hit_rate,
            "miss_rate": self.miss_rate,
        }

    def __getitem__(self, item: str) -> Any:
        d = self.to_dict()
        if item in d:
            return d[item]
        raise KeyError(item)

    def get(self, item: str, default: Any = None) -> Any:
        return self.to_dict().get(item, default)

    def __contains__(self, item: str) -> bool:
        return item in self.to_dict()

    def keys(self):
        return self.to_dict().keys()

    def values(self):
        return self.to_dict().values()

    def items(self):
        return self.to_dict().items()

    def __repr__(self) -> str:
        return (
            f"CacheStats(hits={self.hits}, misses={self.misses}, "
            f"evictions={self.evictions}, expirations={self.expirations}, "
            f"hit_ratio={self.hit_ratio:.4f}, size={self.size}/{self.capacity})"
        )

    def __copy__(self) -> CacheStats:
        return CacheStats(
            hits=self.hits,
            misses=self.misses,
            evictions=self.evictions,
            expirations=self.expirations,
            capacity=self.capacity,
            size=self.size,
        )


_SENTINEL = object()


class HybridCache:
    """
    Thread-safe hybrid LRU-LFU in-memory cache system.
    Supports TTL expiration, concurrency locks, hit/miss statistics,
    and configurable eviction policies (HYBRID, LRU, LFU).
    """

    def __init__(
        self,
        capacity: int,
        policy: Union[str, EvictionPolicy] = EvictionPolicy.HYBRID,
        default_ttl: Optional[float] = None,
        lru_weight: float = 0.5,
        lfu_weight: float = 0.5,
        cleanup_interval: Optional[float] = None,
        on_evict: Optional[Callable[[Any, Any], None]] = None,
        on_expire: Optional[Callable[[Any, Any], None]] = None,
        score_fn: Optional[Callable[[CacheEntry], float]] = None,
        time_fn: Callable[[], float] = time.time,
    ) -> None:
        """
        Initialize the HybridCache.

        :param capacity: Maximum number of entries allowed in the cache.
        :param policy: Eviction policy ('hybrid', 'lru', 'lfu').
        :param default_ttl: Default TTL in seconds for entries without explicit TTL.
        :param lru_weight: Relative weight for recency in hybrid eviction scoring.
        :param lfu_weight: Relative weight for frequency in hybrid eviction scoring.
        :param cleanup_interval: Interval in seconds for background cleanup daemon thread.
        :param on_evict: Callback invoked on eviction: fn(key, value).
        :param on_expire: Callback invoked on TTL expiration: fn(key, value).
        :param score_fn: Optional custom scoring function for eviction: fn(entry) -> float.
        :param time_fn: Function providing current timestamp (default time.time).
        """
        if isinstance(capacity, bool) or not isinstance(capacity, int):
            raise TypeError(f"Capacity must be an integer, got: {type(capacity).__name__}")
        if capacity <= 0:
            raise ValueError(f"Capacity must be a positive integer, got: {capacity}")

        if default_ttl is not None and default_ttl < 0:
            raise ValueError(f"default_ttl must be non-negative, got: {default_ttl}")

        if lru_weight < 0 or lfu_weight < 0:
            raise ValueError("Weights must be non-negative")
        total_w = lru_weight + lfu_weight
        if total_w <= 0:
            raise ValueError("At least one weight (lru_weight or lfu_weight) must be positive")

        self._capacity = capacity
        self._default_ttl = default_ttl
        self._lru_weight = lru_weight / total_w
        self._lfu_weight = lfu_weight / total_w
        self._on_evict = on_evict
        self._on_expire = on_expire
        self._score_fn = score_fn
        self._time_fn = time_fn

        self._entries: Dict[Any, CacheEntry] = {}
        self._stats = CacheStats(capacity=capacity)
        self._counter = 0
        self._lock = threading.RLock()

        self._policy = self._parse_policy(policy)

        # Background cleanup thread configuration
        self._cleanup_interval = cleanup_interval
        self._cleanup_stop_event = threading.Event()
        self._cleanup_thread: Optional[threading.Thread] = None

        if self._cleanup_interval is not None and self._cleanup_interval > 0:
            self.start_cleanup_thread(self._cleanup_interval)

    @staticmethod
    def _parse_policy(policy: Union[str, EvictionPolicy]) -> EvictionPolicy:
        if isinstance(policy, EvictionPolicy):
            return policy
        if isinstance(policy, str):
            try:
                return EvictionPolicy(policy.lower())
            except ValueError:
                raise ValueError(
                    f"Unknown eviction policy: '{policy}'. "
                    f"Supported: {[p.value for p in EvictionPolicy]}"
                )
        raise TypeError(f"Invalid policy type: {type(policy).__name__}")

    # -------------------------------------------------------------------------
    # Context Manager & Lock
    # -------------------------------------------------------------------------

    def __enter__(self) -> HybridCache:
        self._lock.acquire()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self._lock.release()

    @property
    def lock(self) -> threading.RLock:
        """Expose the reentrant lock for explicit synchronized blocks."""
        return self._lock

    # -------------------------------------------------------------------------
    # Core Cache Operations
    # -------------------------------------------------------------------------

    def put(self, key: Any, value: Any, ttl: Optional[float] = None) -> None:
        """
        Store key-value pair in cache.
        If key exists, updates value, access time, and increments frequency.
        If cache is full, purges expired items, then evicts an item using the eviction policy.
        """
        if ttl is not None and ttl < 0:
            raise ValueError(f"TTL must be non-negative, got: {ttl}")

        with self._lock:
            now = self._time_fn()

            # Check if key exists but is already expired
            if key in self._entries and self._entries[key].is_expired(now):
                self._del_entry_locked(key, expired=True)

            if key in self._entries:
                entry = self._entries[key]
                entry.value = value
                entry.last_accessed = now
                entry.frequency += 1
                effective_ttl = ttl if ttl is not None else self._default_ttl
                if effective_ttl is not None:
                    entry.created_at = now
                    entry.ttl = effective_ttl
                else:
                    entry.ttl = None
                return

            # Clean up expired items to free space
            self._cleanup_expired_locked()

            # Evict if capacity exceeded
            while len(self._entries) >= self._capacity:
                self._evict_one_locked()

            self._counter += 1
            effective_ttl = ttl if ttl is not None else self._default_ttl
            entry = CacheEntry(
                key=key,
                value=value,
                created_at=now,
                last_accessed=now,
                frequency=1,
                ttl=effective_ttl,
                insertion_order=self._counter,
            )
            self._entries[key] = entry

    def set(self, key: Any, value: Any, ttl: Optional[float] = None) -> None:
        """Alias for put."""
        self.put(key, value, ttl=ttl)

    def get(self, key: Any, default: Any = None) -> Any:
        """
        Retrieve value for key.
        Updates access time, frequency, and hit/miss statistics.
        Returns default if key does not exist or has expired.
        """
        with self._lock:
            now = self._time_fn()
            if key not in self._entries:
                self._stats.misses += 1
                return default

            entry = self._entries[key]
            if entry.is_expired(now):
                self._del_entry_locked(key, expired=True)
                self._stats.misses += 1
                return default

            entry.last_accessed = now
            entry.frequency += 1
            self._stats.hits += 1
            return entry.value

    def peek(self, key: Any, default: Any = None) -> Any:
        """
        Retrieve value without updating recency, frequency, or hit/miss statistics.
        Returns default if key does not exist or has expired.
        """
        with self._lock:
            now = self._time_fn()
            if key not in self._entries:
                return default

            entry = self._entries[key]
            if entry.is_expired(now):
                self._del_entry_locked(key, expired=True)
                return default

            return entry.value

    def delete(self, key: Any) -> bool:
        """
        Remove key from cache.
        Returns True if key was present and active, False otherwise.
        """
        with self._lock:
            now = self._time_fn()
            if key not in self._entries:
                return False

            entry = self._entries.pop(key)
            if entry.is_expired(now):
                self._stats.expirations += 1
                if self._on_expire:
                    try:
                        self._on_expire(entry.key, entry.value)
                    except Exception:
                        pass
                return False
            return True

    def remove(self, key: Any) -> bool:
        """Alias for delete."""
        return self.delete(key)

    def pop(self, key: Any, default: Any = _SENTINEL) -> Any:
        """
        Remove key and return its value.
        If key not found and default provided, returns default; else raises KeyError.
        """
        with self._lock:
            now = self._time_fn()
            if key not in self._entries:
                if default is not _SENTINEL:
                    return default
                raise KeyError(key)

            entry = self._entries.pop(key)
            if entry.is_expired(now):
                self._stats.expirations += 1
                if self._on_expire:
                    try:
                        self._on_expire(entry.key, entry.value)
                    except Exception:
                        pass
                if default is not _SENTINEL:
                    return default
                raise KeyError(key)
            return entry.value

    def contains(self, key: Any) -> bool:
        """Check if key exists and is not expired."""
        with self._lock:
            now = self._time_fn()
            if key not in self._entries:
                return False
            entry = self._entries[key]
            if entry.is_expired(now):
                self._del_entry_locked(key, expired=True)
                return False
            return True

    def __contains__(self, key: Any) -> bool:
        return self.contains(key)

    def __getitem__(self, key: Any) -> Any:
        with self._lock:
            val = self.get(key, default=_SENTINEL)
            if val is _SENTINEL:
                raise KeyError(key)
            return val

    def __setitem__(self, key: Any, value: Any) -> None:
        self.put(key, value)

    def __delitem__(self, key: Any) -> None:
        with self._lock:
            if not self.delete(key):
                raise KeyError(key)

    def __len__(self) -> int:
        with self._lock:
            self._cleanup_expired_locked()
            return len(self._entries)

    def __iter__(self) -> Iterator[Any]:
        with self._lock:
            self._cleanup_expired_locked()
            snapshot = list(self._entries.keys())
        return iter(snapshot)

    def setdefault(self, key: Any, default: Any = None, ttl: Optional[float] = None) -> Any:
        """Return value for key if present; else insert key with default and return default."""
        with self._lock:
            val = self.get(key, default=_SENTINEL)
            if val is not _SENTINEL:
                return val
            self.put(key, default, ttl=ttl)
            return default

    def update(self, *args: Any, ttl: Optional[float] = None, **kwargs: Any) -> None:
        """Update cache with key-value pairs from mapping/iterable and kwargs."""
        with self._lock:
            if args:
                if len(args) > 1:
                    raise TypeError(f"update expected at most 1 arguments, got {len(args)}")
                other = args[0]
                if isinstance(other, Mapping) or hasattr(other, "items"):
                    for k, v in other.items():
                        self.put(k, v, ttl=ttl)
                elif hasattr(other, "keys"):
                    for k in other.keys():
                        self.put(k, other[k], ttl=ttl)
                else:
                    for k, v in other:
                        self.put(k, v, ttl=ttl)
            for k, v in kwargs.items():
                self.put(k, v, ttl=ttl)

    def clear(self) -> None:
        """Clear all entries from the cache."""
        with self._lock:
            self._entries.clear()

    # -------------------------------------------------------------------------
    # Inspection & Collections
    # -------------------------------------------------------------------------

    def keys(self) -> List[Any]:
        """Return a snapshot list of active keys."""
        with self._lock:
            self._cleanup_expired_locked()
            return list(self._entries.keys())

    def values(self) -> List[Any]:
        """Return a snapshot list of active values."""
        with self._lock:
            self._cleanup_expired_locked()
            return [entry.value for entry in self._entries.values()]

    def items(self) -> List[Tuple[Any, Any]]:
        """Return a snapshot list of active (key, value) pairs."""
        with self._lock:
            self._cleanup_expired_locked()
            return [(k, entry.value) for k, entry in self._entries.items()]

    def get_ttl(self, key: Any) -> Optional[float]:
        """
        Return remaining TTL in seconds for key.
        Returns float('inf') if key exists without TTL.
        Returns None if key does not exist or has expired.
        """
        with self._lock:
            now = self._time_fn()
            if key not in self._entries:
                return None
            entry = self._entries[key]
            if entry.is_expired(now):
                self._del_entry_locked(key, expired=True)
                return None
            if entry.ttl is None:
                return float("inf")
            return max(0.0, (entry.created_at + entry.ttl) - now)

    def ttl(self, key: Any) -> Optional[float]:
        """Alias for get_ttl."""
        return self.get_ttl(key)

    def has_ttl(self, key: Any) -> bool:
        """Return True if key has an expiration TTL configured."""
        with self._lock:
            now = self._time_fn()
            if key not in self._entries:
                return False
            entry = self._entries[key]
            if entry.is_expired(now):
                self._del_entry_locked(key, expired=True)
                return False
            return entry.ttl is not None

    def get_frequency(self, key: Any) -> Optional[int]:
        """Return access frequency of key, or None if not found/expired."""
        with self._lock:
            now = self._time_fn()
            if key not in self._entries:
                return None
            entry = self._entries[key]
            if entry.is_expired(now):
                self._del_entry_locked(key, expired=True)
                return None
            return entry.frequency

    def get_last_accessed(self, key: Any) -> Optional[float]:
        """Return timestamp when key was last accessed, or None if not found/expired."""
        with self._lock:
            now = self._time_fn()
            if key not in self._entries:
                return None
            entry = self._entries[key]
            if entry.is_expired(now):
                self._del_entry_locked(key, expired=True)
                return None
            return entry.last_accessed

    # -------------------------------------------------------------------------
    # Eviction & Expiration Logic
    # -------------------------------------------------------------------------

    def _del_entry_locked(self, key: Any, expired: bool = False) -> None:
        if key in self._entries:
            entry = self._entries.pop(key)
            if expired:
                self._stats.expirations += 1
                if self._on_expire:
                    try:
                        self._on_expire(entry.key, entry.value)
                    except Exception:
                        pass

    def _cleanup_expired_locked(self) -> int:
        now = self._time_fn()
        expired_keys = [k for k, entry in self._entries.items() if entry.is_expired(now)]
        for k in expired_keys:
            self._del_entry_locked(k, expired=True)
        return len(expired_keys)

    def cleanup_expired(self) -> int:
        """Scan and purge all expired entries. Returns count of purged entries."""
        with self._lock:
            return self._cleanup_expired_locked()

    def _select_victim_locked(self) -> Any:
        if not self._entries:
            raise KeyError("Cannot evict from empty cache")

        if self._score_fn is not None:
            return min(
                self._entries.keys(),
                key=lambda k: (
                    self._score_fn(self._entries[k]),
                    self._entries[k].last_accessed,
                    self._entries[k].frequency,
                    self._entries[k].insertion_order,
                ),
            )

        if self._policy == EvictionPolicy.LRU:
            return min(
                self._entries.keys(),
                key=lambda k: (
                    self._entries[k].last_accessed,
                    self._entries[k].frequency,
                    self._entries[k].insertion_order,
                ),
            )

        elif self._policy == EvictionPolicy.LFU:
            return min(
                self._entries.keys(),
                key=lambda k: (
                    self._entries[k].frequency,
                    self._entries[k].last_accessed,
                    self._entries[k].insertion_order,
                ),
            )

        else:  # EvictionPolicy.HYBRID
            entries = list(self._entries.values())
            if len(entries) == 1:
                return entries[0].key

            f_min = min(e.frequency for e in entries)
            f_max = max(e.frequency for e in entries)
            t_min = min(e.last_accessed for e in entries)
            t_max = max(e.last_accessed for e in entries)

            f_range = f_max - f_min
            t_range = t_max - t_min

            scores: Dict[Any, float] = {}
            for entry in entries:
                norm_f = (entry.frequency - f_min) / f_range if f_range > 0 else 0.0
                norm_t = (entry.last_accessed - t_min) / t_range if t_range > 0 else 0.0
                score = (self._lfu_weight * norm_f) + (self._lru_weight * norm_t)
                scores[entry.key] = score

            return min(
                self._entries.keys(),
                key=lambda k: (
                    scores[k],
                    self._entries[k].last_accessed,
                    self._entries[k].frequency,
                    self._entries[k].insertion_order,
                ),
            )

    def _evict_one_locked(self) -> Optional[Tuple[Any, Any]]:
        if not self._entries:
            return None

        victim_key = self._select_victim_locked()
        victim_entry = self._entries.pop(victim_key)
        self._stats.evictions += 1

        if self._on_evict is not None:
            try:
                self._on_evict(victim_entry.key, victim_entry.value)
            except Exception:
                pass

        return (victim_entry.key, victim_entry.value)

    def evict(self) -> Optional[Tuple[Any, Any]]:
        """Manually evict the next candidate entry according to policy."""
        with self._lock:
            return self._evict_one_locked()

    # -------------------------------------------------------------------------
    # Background Cleanup Daemon Thread
    # -------------------------------------------------------------------------

    def start_cleanup_thread(self, interval: Optional[float] = None) -> None:
        """Start a background daemon thread that periodically purges expired items."""
        with self._lock:
            if self._cleanup_thread is not None and self._cleanup_thread.is_alive():
                return
            if interval is not None:
                if interval <= 0:
                    raise ValueError("Cleanup interval must be positive")
                self._cleanup_interval = interval
            if self._cleanup_interval is None or self._cleanup_interval <= 0:
                raise ValueError("Cleanup interval must be set and positive")

            self._cleanup_stop_event.clear()
            self._cleanup_thread = threading.Thread(
                target=self._background_cleanup_loop,
                daemon=True,
                name="HybridCache-CleanupThread",
            )
            self._cleanup_thread.start()

    def _background_cleanup_loop(self) -> None:
        while not self._cleanup_stop_event.wait(timeout=self._cleanup_interval):
            try:
                self.cleanup_expired()
            except Exception:
                pass

    def stop_cleanup_thread(self, timeout: Optional[float] = 2.0) -> None:
        """Signal and stop the background cleanup thread."""
        if self._cleanup_thread is not None and self._cleanup_thread.is_alive():
            self._cleanup_stop_event.set()
            self._cleanup_thread.join(timeout=timeout)

    def close(self) -> None:
        """Cleanly shut down resources including background threads."""
        self.stop_cleanup_thread()

    def __del__(self) -> None:
        try:
            self.stop_cleanup_thread(timeout=0.2)
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Statistics & Metrics
    # -------------------------------------------------------------------------

    def get_stats(self) -> CacheStats:
        """Return a snapshot of current cache statistics."""
        with self._lock:
            return CacheStats(
                hits=self._stats.hits,
                misses=self._stats.misses,
                evictions=self._stats.evictions,
                expirations=self._stats.expirations,
                capacity=self._capacity,
                size=len(self._entries),
            )

    @property
    def stats(self) -> CacheStats:
        """Property returning cache statistics snapshot."""
        return self.get_stats()

    def reset_stats(self) -> None:
        """Reset hit, miss, eviction, and expiration counters."""
        with self._lock:
            self._stats.reset()

    @property
    def hits(self) -> IntMetric:
        """Number of cache hits (usable as int or callable)."""
        with self._lock:
            return IntMetric(self._stats.hits)

    @property
    def misses(self) -> IntMetric:
        """Number of cache misses (usable as int or callable)."""
        with self._lock:
            return IntMetric(self._stats.misses)

    @property
    def evictions(self) -> IntMetric:
        """Number of capacity evictions (usable as int or callable)."""
        with self._lock:
            return IntMetric(self._stats.evictions)

    @property
    def expirations(self) -> IntMetric:
        """Number of TTL expirations (usable as int or callable)."""
        with self._lock:
            return IntMetric(self._stats.expirations)

    @property
    def hit_ratio(self) -> FloatMetric:
        """Hit ratio as float or callable."""
        with self._lock:
            return FloatMetric(self.get_stats().hit_ratio)

    @property
    def hit_rate(self) -> FloatMetric:
        """Alias for hit_ratio."""
        return self.hit_ratio

    @property
    def miss_ratio(self) -> FloatMetric:
        """Miss ratio as float or callable."""
        with self._lock:
            return FloatMetric(self.get_stats().miss_ratio)

    @property
    def miss_rate(self) -> FloatMetric:
        """Alias for miss_ratio."""
        return self.miss_ratio

    @property
    def size(self) -> SizeMetric:
        """Current number of active entries (usable as int or callable size())."""
        with self._lock:
            self._cleanup_expired_locked()
            return SizeMetric(len(self._entries))

    # -------------------------------------------------------------------------
    # Configuration Properties
    # -------------------------------------------------------------------------

    @property
    def capacity(self) -> int:
        return self._capacity

    @capacity.setter
    def capacity(self, new_capacity: int) -> None:
        with self._lock:
            if isinstance(new_capacity, bool) or not isinstance(new_capacity, int):
                raise TypeError("Capacity must be an integer")
            if new_capacity <= 0:
                raise ValueError(f"Capacity must be a positive integer, got: {new_capacity}")
            self._capacity = new_capacity
            self._cleanup_expired_locked()
            while len(self._entries) > self._capacity:
                self._evict_one_locked()

    @property
    def policy(self) -> EvictionPolicy:
        return self._policy

    @policy.setter
    def policy(self, value: Union[str, EvictionPolicy]) -> None:
        with self._lock:
            self._policy = self._parse_policy(value)

    @property
    def default_ttl(self) -> Optional[float]:
        return self._default_ttl

    @default_ttl.setter
    def default_ttl(self, value: Optional[float]) -> None:
        with self._lock:
            if value is not None and value < 0:
                raise ValueError(f"default_ttl must be non-negative, got: {value}")
            self._default_ttl = value

    @property
    def lru_weight(self) -> float:
        return self._lru_weight

    @lru_weight.setter
    def lru_weight(self, value: float) -> None:
        with self._lock:
            if value < 0:
                raise ValueError("lru_weight must be non-negative")
            total = value + self._lfu_weight
            if total <= 0:
                raise ValueError("Total weights must be positive")
            self._lru_weight = value / total
            self._lfu_weight = self._lfu_weight / total

    @property
    def lfu_weight(self) -> float:
        return self._lfu_weight

    @lfu_weight.setter
    def lfu_weight(self, value: float) -> None:
        with self._lock:
            if value < 0:
                raise ValueError("lfu_weight must be non-negative")
            total = self._lru_weight + value
            if total <= 0:
                raise ValueError("Total weights must be positive")
            self._lfu_weight = value / total
            self._lru_weight = self._lru_weight / total

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"HybridCache(capacity={self._capacity}, size={len(self._entries)}, "
                f"policy='{self._policy.value}', hits={self._stats.hits}, misses={self._stats.misses})"
            )

    def __str__(self) -> str:
        return repr(self)


# Aliases for compatibility and convenience
CacheSystem = HybridCache
HybridLRULFU = HybridCache
CacheItem = CacheEntry
