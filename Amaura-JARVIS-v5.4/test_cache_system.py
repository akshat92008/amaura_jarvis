"""
Comprehensive unit tests for the thread-safe hybrid LRU-LFU in-memory cache system.
"""

from __future__ import annotations

import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed

from cache_system import (
    CacheEntry,
    CacheItem,
    CacheStats,
    CacheSystem,
    EvictionPolicy,
    FloatMetric,
    HybridCache,
    HybridLRULFU,
    IntMetric,
    SizeMetric,
)


class TestBasicOperations(unittest.TestCase):
    """Test standard dictionary-like cache operations, getters, setters, and deletion."""

    def test_put_and_get(self):
        cache = HybridCache(capacity=5)
        cache.put("a", 100)
        cache.put("b", 200)

        self.assertEqual(cache.get("a"), 100)
        self.assertEqual(cache.get("b"), 200)
        self.assertIsNone(cache.get("nonexistent"))
        self.assertEqual(cache.get("nonexistent", "default_val"), "default_val")

    def test_set_alias(self):
        cache = HybridCache(capacity=5)
        cache.set("k1", "v1")
        self.assertEqual(cache.get("k1"), "v1")

    def test_none_as_stored_value(self):
        cache = HybridCache(capacity=5)
        cache.put("nullable", None)

        self.assertTrue(cache.contains("nullable"))
        self.assertIsNone(cache.get("nullable", "fallback"))
        self.assertEqual(cache.hits, 1)
        self.assertEqual(cache.misses, 0)

    def test_overwrite_existing_key(self):
        cache = HybridCache(capacity=5)
        cache.put("k", 1)
        self.assertEqual(cache.get("k"), 1)
        self.assertEqual(cache.get_frequency("k"), 2)  # 1 from put, 1 from get

        cache.put("k", 2)
        self.assertEqual(cache.get("k"), 2)
        self.assertEqual(cache.get_frequency("k"), 4)  # +1 from put overwrite, +1 from get
        self.assertEqual(len(cache), 1)

    def test_delete_and_remove(self):
        cache = HybridCache(capacity=5)
        cache.put("k1", 10)
        cache.put("k2", 20)

        self.assertTrue(cache.delete("k1"))
        self.assertFalse(cache.delete("k1"))
        self.assertIsNone(cache.get("k1"))

        self.assertTrue(cache.remove("k2"))
        self.assertFalse(cache.remove("k2"))
        self.assertEqual(len(cache), 0)

    def test_pop(self):
        cache = HybridCache(capacity=5)
        cache.put("x", 42)

        val = cache.pop("x")
        self.assertEqual(val, 42)
        self.assertFalse(cache.contains("x"))

        self.assertEqual(cache.pop("x", "missing"), "missing")
        with self.assertRaises(KeyError):
            cache.pop("x")

    def test_setdefault(self):
        cache = HybridCache(capacity=5)
        val1 = cache.setdefault("a", 10)
        self.assertEqual(val1, 10)
        self.assertEqual(cache.get("a"), 10)

        val2 = cache.setdefault("a", 999)
        self.assertEqual(val2, 10)
        self.assertEqual(cache.get("a"), 10)

    def test_update(self):
        cache = HybridCache(capacity=5)
        cache.update({"a": 1, "b": 2}, c=3)
        self.assertEqual(cache.get("a"), 1)
        self.assertEqual(cache.get("b"), 2)
        self.assertEqual(cache.get("c"), 3)

        cache.update([("d", 4), ("e", 5)])
        self.assertEqual(cache.get("d"), 4)
        self.assertEqual(cache.get("e"), 5)

    def test_clear(self):
        cache = HybridCache(capacity=5)
        cache.put("a", 1)
        cache.put("b", 2)
        self.assertEqual(len(cache), 2)

        cache.clear()
        self.assertEqual(len(cache), 0)
        self.assertIsNone(cache.get("a"))

    def test_peek(self):
        cache = HybridCache(capacity=5)
        cache.put("a", "alpha")

        initial_freq = cache.get_frequency("a")
        initial_time = cache.get_last_accessed("a")

        val = cache.peek("a")
        self.assertEqual(val, "alpha")
        self.assertEqual(cache.get_frequency("a"), initial_freq)
        self.assertEqual(cache.get_last_accessed("a"), initial_time)
        self.assertEqual(cache.hits, 0)
        self.assertEqual(cache.misses, 0)

        self.assertIsNone(cache.peek("nonexistent"))
        self.assertEqual(cache.peek("nonexistent", "def"), "def")
        self.assertEqual(cache.misses, 0)

    def test_dict_operators(self):
        cache = HybridCache(capacity=3)
        cache["x"] = 10
        self.assertEqual(cache["x"], 10)
        self.assertTrue("x" in cache)
        self.assertFalse("y" in cache)
        self.assertEqual(len(cache), 1)

        del cache["x"]
        self.assertFalse("x" in cache)
        with self.assertRaises(KeyError):
            _ = cache["x"]
        with self.assertRaises(KeyError):
            del cache["x"]

    def test_keys_values_items_and_iter(self):
        cache = HybridCache(capacity=5)
        cache.put("k1", "v1")
        cache.put("k2", "v2")
        cache.put("k3", "v3")

        self.assertEqual(set(cache.keys()), {"k1", "k2", "k3"})
        self.assertEqual(set(cache.values()), {"v1", "v2", "v3"})
        self.assertEqual(set(cache.items()), {("k1", "v1"), ("k2", "v2"), ("k3", "v3")})
        self.assertEqual(set(iter(cache)), {"k1", "k2", "k3"})

    def test_repr_and_str(self):
        cache = HybridCache(capacity=10)
        cache.put("test", 123)
        repr_str = repr(cache)
        self.assertIn("HybridCache", repr_str)
        self.assertIn("capacity=10", repr_str)
        self.assertEqual(str(cache), repr_str)


class TestEvictionPolicies(unittest.TestCase):
    """Test LRU, LFU, and Hybrid eviction policies and callbacks."""

    def test_lru_eviction(self):
        current_time = 100.0

        def mock_time():
            return current_time

        cache = HybridCache(capacity=3, policy=EvictionPolicy.LRU, time_fn=mock_time)

        current_time = 101.0
        cache.put("a", 1)
        current_time = 102.0
        cache.put("b", 2)
        current_time = 103.0
        cache.put("c", 3)

        # Access "a" and "b", leaving "c" as least recently used
        current_time = 104.0
        cache.get("a")
        current_time = 105.0
        cache.get("b")

        # Put "d", should evict "c"
        current_time = 106.0
        cache.put("d", 4)

        self.assertIsNone(cache.get("c"))
        self.assertEqual(cache.get("a"), 1)
        self.assertEqual(cache.get("b"), 2)
        self.assertEqual(cache.get("d"), 4)
        self.assertEqual(cache.evictions, 1)

    def test_lfu_eviction(self):
        current_time = 100.0

        def mock_time():
            return current_time

        cache = HybridCache(capacity=3, policy=EvictionPolicy.LFU, time_fn=mock_time)

        current_time = 101.0
        cache.put("a", 1)
        current_time = 102.0
        cache.put("b", 2)
        current_time = 103.0
        cache.put("c", 3)

        # "a" accessed 3 times -> freq = 1 + 3 = 4
        cache.get("a")
        cache.get("a")
        cache.get("a")

        # "b" accessed 2 times -> freq = 1 + 2 = 3
        cache.get("b")
        cache.get("b")

        # "c" accessed 0 times -> freq = 1

        # Put "d", should evict "c" because it has the lowest frequency
        current_time = 104.0
        cache.put("d", 4)

        self.assertIsNone(cache.get("c"))
        self.assertEqual(cache.get("a"), 1)
        self.assertEqual(cache.get("b"), 2)
        self.assertEqual(cache.get("d"), 4)

    def test_lfu_tie_breaker_uses_lru(self):
        current_time = 100.0

        def mock_time():
            return current_time

        cache = HybridCache(capacity=3, policy="lfu", time_fn=mock_time)

        current_time = 101.0
        cache.put("a", 1)  # accessed at 101, freq 1
        current_time = 102.0
        cache.put("b", 2)  # accessed at 102, freq 1
        current_time = 103.0
        cache.put("c", 3)  # accessed at 103, freq 1

        # Boost "c" to freq 2
        current_time = 104.0
        cache.get("c")

        # Now "a" and "b" tie with frequency 1.
        # "a" was accessed at 101, "b" at 102. "a" is older -> LRU tie-breaker evicts "a".
        current_time = 105.0
        cache.put("d", 4)

        self.assertIsNone(cache.get("a"))
        self.assertEqual(cache.get("b"), 2)
        self.assertEqual(cache.get("c"), 3)
        self.assertEqual(cache.get("d"), 4)

    def test_hybrid_eviction(self):
        current_time = 100.0

        def mock_time():
            return current_time

        cache = HybridCache(
            capacity=3,
            policy=EvictionPolicy.HYBRID,
            lru_weight=0.5,
            lfu_weight=0.5,
            time_fn=mock_time,
        )

        current_time = 101.0
        cache.put("old_popular", "A")
        # Give old_popular high frequency
        for _ in range(5):
            cache.get("old_popular")

        current_time = 110.0
        cache.put("old_unpopular", "C")

        current_time = 111.0
        cache.put("recent_unpopular", "B")

        # old_unpopular has low frequency and was accessed before recent_unpopular
        # Let's verify old_unpopular gets the lowest hybrid score
        current_time = 115.0
        cache.put("new_item", "D")

        self.assertIsNone(cache.get("old_unpopular"))
        self.assertEqual(cache.get("old_popular"), "A")
        self.assertEqual(cache.get("recent_unpopular"), "B")
        self.assertEqual(cache.get("new_item"), "D")

    def test_custom_score_function(self):
        # Custom score function evicting highest number first
        cache = HybridCache(
            capacity=2,
            score_fn=lambda entry: -entry.value,  # lowest return value evicted first
        )
        cache.put("small", 10)
        cache.put("large", 1000)

        # "large" has score -1000, which is smaller than -10, so "large" gets evicted
        cache.put("medium", 50)
        self.assertIsNone(cache.get("large"))
        self.assertEqual(cache.get("small"), 10)
        self.assertEqual(cache.get("medium"), 50)

    def test_manual_evict(self):
        cache = HybridCache(capacity=5)
        self.assertIsNone(cache.evict())

        cache.put("k1", "v1")
        cache.put("k2", "v2")
        evicted = cache.evict()
        self.assertIsNotNone(evicted)
        self.assertEqual(len(cache), 1)
        self.assertEqual(cache.evictions, 1)

    def test_eviction_callback(self):
        evicted_items = []

        def on_evict(key, val):
            evicted_items.append((key, val))

        cache = HybridCache(capacity=2, policy="lru", on_evict=on_evict)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)

        self.assertEqual(len(evicted_items), 1)
        self.assertEqual(evicted_items[0], ("a", 1))

    def test_dynamic_capacity_resizing(self):
        cache = HybridCache(capacity=4, policy="lru")
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)
        cache.put("d", 4)
        self.assertEqual(len(cache), 4)

        # Shrink capacity to 2 -> should evict 2 oldest entries ("a" and "b")
        cache.capacity = 2
        self.assertEqual(len(cache), 2)
        self.assertIsNone(cache.get("a"))
        self.assertIsNone(cache.get("b"))
        self.assertEqual(cache.get("c"), 3)
        self.assertEqual(cache.get("d"), 4)
        self.assertEqual(cache.evictions, 2)


class TestTTLExpiration(unittest.TestCase):
    """Test TTL expiration, lazy expiration, active cleanup, and callbacks."""

    def test_per_item_ttl(self):
        current_time = 1000.0

        def mock_time():
            return current_time

        cache = HybridCache(capacity=5, time_fn=mock_time)
        cache.put("short", "lived", ttl=10.0)
        cache.put("persistent", "forever", ttl=None)

        self.assertEqual(cache.get("short"), "lived")
        self.assertEqual(cache.get_ttl("short"), 10.0)
        self.assertEqual(cache.get_ttl("persistent"), float("inf"))

        # Advance time by 5s
        current_time = 1005.0
        self.assertEqual(cache.get("short"), "lived")
        self.assertEqual(cache.get_ttl("short"), 5.0)

        # Advance time past TTL (11s elapsed)
        current_time = 1011.0
        self.assertIsNone(cache.get("short"))
        self.assertFalse(cache.contains("short"))
        self.assertEqual(cache.get("persistent"), "forever")
        self.assertEqual(cache.expirations, 1)

    def test_default_ttl(self):
        current_time = 500.0

        def mock_time():
            return current_time

        cache = HybridCache(capacity=5, default_ttl=20.0, time_fn=mock_time)
        cache.put("item1", "val1")  # uses default TTL 20.0
        cache.put("item2", "val2", ttl=5.0)  # overrides with 5.0

        current_time = 506.0
        self.assertIsNone(cache.get("item2"))  # expired
        self.assertEqual(cache.get("item1"), "val1")  # still active

        current_time = 521.0
        self.assertIsNone(cache.get("item1"))  # expired
        self.assertEqual(cache.expirations, 2)

    def test_zero_ttl_expires_immediately(self):
        current_time = 100.0

        def mock_time():
            return current_time

        cache = HybridCache(capacity=5, time_fn=mock_time)
        cache.put("zero_ttl", 999, ttl=0.0)

        self.assertFalse(cache.contains("zero_ttl"))
        self.assertIsNone(cache.get("zero_ttl"))
        self.assertEqual(cache.expirations, 1)

    def test_lazy_cleanup_on_contains_and_len(self):
        current_time = 100.0

        def mock_time():
            return current_time

        cache = HybridCache(capacity=5, time_fn=mock_time)
        cache.put("a", 1, ttl=5.0)
        cache.put("b", 2, ttl=15.0)
        self.assertEqual(len(cache), 2)

        current_time = 106.0
        self.assertFalse("a" in cache)
        self.assertEqual(len(cache), 1)
        self.assertEqual(cache.keys(), ["b"])

    def test_manual_cleanup_expired(self):
        current_time = 200.0

        def mock_time():
            return current_time

        cache = HybridCache(capacity=10, time_fn=mock_time)
        cache.put("k1", 1, ttl=5.0)
        cache.put("k2", 2, ttl=5.0)
        cache.put("k3", 3, ttl=50.0)

        current_time = 210.0
        purged = cache.cleanup_expired()
        self.assertEqual(purged, 2)
        self.assertEqual(len(cache), 1)
        self.assertEqual(cache.keys(), ["k3"])

    def test_expired_cleaned_before_eviction(self):
        current_time = 10.0

        def mock_time():
            return current_time

        cache = HybridCache(capacity=2, policy="lru", time_fn=mock_time)
        cache.put("expiring", "value", ttl=5.0)
        cache.put("active", "safe", ttl=None)

        current_time = 20.0  # "expiring" is now expired
        # Inserting 3rd item when capacity is 2
        # It should clean "expiring" first and avoid evicting "active"
        cache.put("new_entry", "added")

        self.assertEqual(len(cache), 2)
        self.assertIsNone(cache.get("expiring"))
        self.assertEqual(cache.get("active"), "safe")
        self.assertEqual(cache.get("new_entry"), "added")
        self.assertEqual(cache.evictions, 0)
        self.assertEqual(cache.expirations, 1)

    def test_expiration_callback(self):
        expired_items = []

        def on_expire(k, v):
            expired_items.append((k, v))

        current_time = 100.0

        def mock_time():
            return current_time

        cache = HybridCache(capacity=5, on_expire=on_expire, time_fn=mock_time)
        cache.put("temp", "secret", ttl=2.0)

        current_time = 105.0
        self.assertIsNone(cache.get("temp"))
        self.assertEqual(expired_items, [("temp", "secret")])

    def test_background_cleanup_thread(self):
        cache = HybridCache(capacity=5, cleanup_interval=0.03)
        try:
            cache.put("temp_thread", 42, ttl=0.02)
            self.assertEqual(len(cache), 1)
            time.sleep(0.08)
            # Background thread should have automatically purged it
            self.assertEqual(cache.expirations, 1)
            self.assertEqual(len(cache), 0)
        finally:
            cache.close()


class TestStatisticsTracking(unittest.TestCase):
    """Test hits, misses, hit ratio, miss ratio, evictions, expirations, and metric objects."""

    def test_hits_and_misses_count(self):
        cache = HybridCache(capacity=5)
        cache.put("key1", 1)

        self.assertEqual(cache.get("key1"), 1)  # hit 1
        self.assertEqual(cache.get("key1"), 1)  # hit 2
        self.assertIsNone(cache.get("unknown"))  # miss 1
        self.assertIsNone(cache.get("unknown2"))  # miss 2

        self.assertEqual(cache.hits, 2)
        self.assertEqual(cache.misses, 2)
        self.assertAlmostEqual(cache.hit_ratio, 0.5)
        self.assertAlmostEqual(cache.miss_ratio, 0.5)
        self.assertAlmostEqual(cache.hit_rate, 0.5)
        self.assertAlmostEqual(cache.miss_rate, 0.5)

    def test_empty_cache_ratios(self):
        cache = HybridCache(capacity=5)
        self.assertEqual(cache.hit_ratio, 0.0)
        self.assertEqual(cache.miss_ratio, 0.0)

    def test_stats_reset(self):
        cache = HybridCache(capacity=5)
        cache.put("a", 1)
        cache.get("a")
        cache.get("missing")
        self.assertEqual(cache.hits, 1)
        self.assertEqual(cache.misses, 1)

        cache.reset_stats()
        self.assertEqual(cache.hits, 0)
        self.assertEqual(cache.misses, 0)
        self.assertEqual(cache.evictions, 0)
        self.assertEqual(cache.expirations, 0)

    def test_stats_object_and_dict_access(self):
        cache = HybridCache(capacity=10)
        cache.put("x", 1)
        cache.get("x")
        cache.get("y")

        stats = cache.get_stats()
        self.assertIsInstance(stats, CacheStats)
        self.assertEqual(stats.hits, 1)
        self.assertEqual(stats.misses, 1)
        self.assertEqual(stats.total_requests, 2)
        self.assertEqual(stats.capacity, 10)
        self.assertEqual(stats.size, 1)

        # Dictionary access
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)
        self.assertIn("hit_ratio", stats)
        d = stats.to_dict()
        self.assertEqual(d["hits"], 1)

        # Repr
        self.assertIn("CacheStats", repr(stats))

    def test_callable_metric_properties(self):
        cache = HybridCache(capacity=5)
        cache.put("k", "v")
        cache.get("k")

        # Can be evaluated as primitive values
        self.assertEqual(cache.hits, 1)
        self.assertEqual(cache.size, 1)
        self.assertAlmostEqual(cache.hit_ratio, 1.0)

        # Can also be called like methods
        self.assertEqual(cache.hits(), 1)
        self.assertEqual(cache.size(), 1)
        self.assertAlmostEqual(cache.hit_ratio(), 1.0)
        self.assertEqual(cache.misses(), 0)
        self.assertEqual(cache.evictions(), 0)
        self.assertEqual(cache.expirations(), 0)


class TestThreadSafetyAndConcurrency(unittest.TestCase):
    """Test multi-threaded concurrency safety for puts, gets, expirations, and context manager."""

    def test_concurrent_puts(self):
        cache = HybridCache(capacity=50)
        num_threads = 8
        items_per_thread = 50

        def worker(thread_id):
            for i in range(items_per_thread):
                cache.put(f"t{thread_id}_{i}", i)

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, t) for t in range(num_threads)]
            for f in as_completed(futures):
                f.result()

        self.assertLessEqual(len(cache), 50)
        self.assertLessEqual(cache.size, 50)

    def test_concurrent_reads_and_writes(self):
        cache = HybridCache(capacity=20)
        for i in range(10):
            cache.put(f"seed_{i}", i)

        def reader():
            for _ in range(100):
                for i in range(15):
                    cache.get(f"seed_{i}")

        def writer():
            for i in range(100):
                cache.put(f"dynamic_{i}", i)

        with ThreadPoolExecutor(max_workers=8) as executor:
            f1 = [executor.submit(reader) for _ in range(4)]
            f2 = [executor.submit(writer) for _ in range(4)]
            for f in as_completed(f1 + f2):
                f.result()

        self.assertLessEqual(len(cache), 20)
        self.assertGreater(cache.hits + cache.misses, 0)

    def test_concurrent_ttl_expiration(self):
        cache = HybridCache(capacity=100)

        def worker(idx):
            for i in range(20):
                k = f"k_{idx}_{i}"
                cache.put(k, i, ttl=0.01)
                time.sleep(0.002)
                cache.get(k)
                cache.contains(k)

        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(worker, i) for i in range(6)]
            for f in as_completed(futures):
                f.result()

        self.assertGreaterEqual(cache.expirations, 0)

    def test_context_manager_and_lock_property(self):
        cache = HybridCache(capacity=5)

        with cache:
            cache.put("a", 1)
            cache.put("b", 2)
            self.assertEqual(cache.get("a"), 1)

        with cache.lock:
            cache.put("c", 3)
            self.assertEqual(cache.get("c"), 3)

        self.assertEqual(len(cache), 3)


class TestEdgeCasesAndValidation(unittest.TestCase):
    """Test validation errors, invalid inputs, and compatibility aliases."""

    def test_invalid_capacity(self):
        with self.assertRaises(ValueError):
            HybridCache(capacity=0)
        with self.assertRaises(ValueError):
            HybridCache(capacity=-10)
        with self.assertRaises(TypeError):
            HybridCache(capacity="10")
        with self.assertRaises(TypeError):
            HybridCache(capacity=True)  # bool is subclass of int

    def test_invalid_ttl(self):
        with self.assertRaises(ValueError):
            HybridCache(capacity=5, default_ttl=-1.0)

        cache = HybridCache(capacity=5)
        with self.assertRaises(ValueError):
            cache.put("k", 1, ttl=-5.0)

    def test_invalid_weights(self):
        with self.assertRaises(ValueError):
            HybridCache(capacity=5, lru_weight=-1.0)
        with self.assertRaises(ValueError):
            HybridCache(capacity=5, lfu_weight=-1.0)
        with self.assertRaises(ValueError):
            HybridCache(capacity=5, lru_weight=0.0, lfu_weight=0.0)

    def test_invalid_policy(self):
        with self.assertRaises(ValueError):
            HybridCache(capacity=5, policy="unsupported_policy")

    def test_compatibility_aliases(self):
        self.assertIs(CacheSystem, HybridCache)
        self.assertIs(HybridLRULFU, HybridCache)
        self.assertIs(CacheItem, CacheEntry)

        instance = CacheSystem(capacity=5)
        self.assertIsInstance(instance, HybridCache)


if __name__ == "__main__":
    unittest.main()
