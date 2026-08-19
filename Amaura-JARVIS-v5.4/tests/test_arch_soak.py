from __future__ import annotations

from scripts.run_arch_soak import sample_failures


def test_sample_failures_accepts_single_bounded_arch_and_records_swap_growth():
    sample = {
        "arch_count": 1,
        "arch_pids": [4242],
        "launchd_pid": 4242,
        "legacy_pids": [],
        "aggregate_rss_mb": 900.0,
        "child_count": 4,
        "swap_used_mb": 125.0,
    }

    failures = sample_failures(
        sample,
        baseline_swap_mb=100.0,
        max_rss_mb=2048.0,
        max_swap_growth_mb=192.0,
        max_child_count=32,
    )

    assert failures == []
    assert sample["swap_growth_mb"] == 25.0


def test_sample_failures_rejects_split_runtime_resource_overflow_and_swap_growth():
    sample = {
        "arch_count": 2,
        "arch_pids": [4242, 4343],
        "launchd_pid": 4242,
        "legacy_pids": [5151],
        "aggregate_rss_mb": 2300.0,
        "child_count": 40,
        "swap_used_mb": 350.0,
    }

    failures = sample_failures(
        sample,
        baseline_swap_mb=100.0,
        max_rss_mb=2048.0,
        max_swap_growth_mb=192.0,
        max_child_count=32,
    )

    joined = "\n".join(failures)
    assert "exactly one ARCH" in joined
    assert "legacy split-runtime" in joined
    assert "RSS" in joined
    assert "child count" in joined
    assert "swap grew" in joined


def test_sample_failures_requires_launchd_to_own_the_arch_pid():
    sample = {
        "arch_count": 1,
        "arch_pids": [4242],
        "launchd_pid": 9999,
        "legacy_pids": [],
        "aggregate_rss_mb": 500.0,
        "child_count": 2,
        "swap_used_mb": None,
    }

    failures = sample_failures(
        sample,
        baseline_swap_mb=None,
        max_rss_mb=2048.0,
        max_swap_growth_mb=192.0,
        max_child_count=32,
    )

    assert len(failures) == 1
    assert "launchd pid" in failures[0]
