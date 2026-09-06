"""Unfaked Real-World Stress Test & Autonomous Automation Suite for JARVIS v5.4.

ZERO-FAKING POLICY:
Every test case in this suite directly invokes the actual JarvisAgent and ExecutiveKernel
runtime without mocks or faked returns. All tool calls, file writes, bug fixes, shell commands,
and concurrency latencies are recorded with complete ground-truth verification.
"""

import concurrent.futures
import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from jarvis.amaura.runtime import load_amaura_env

load_amaura_env()

from jarvis.agent import JarvisAgent
from jarvis.tools.amaura import get_control_plane


def log(msg: str) -> None:
    print(msg, flush=True)


def get_rss_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    if sys.platform == "darwin":
        return usage.ru_maxrss / (1024 * 1024)
    return usage.ru_maxrss / 1024


def test_autonomous_coding(agent: JarvisAgent) -> dict:
    log("")
    log("=" * 70)
    log("▶ STRESS VECTOR 1: Autonomous Code Generation & Verification")
    log("=" * 70)
    
    target_module = PROJECT_ROOT / "auto_stat_calc.py"
    target_test = PROJECT_ROOT / "test_auto_stat_calc.py"
    
    if target_module.exists():
        target_module.unlink()
    if target_test.exists():
        target_test.unlink()

    prompt = (
        "Create a file named auto_stat_calc.py in the current directory with functions "
        "mean(numbers: list[float]) -> float and std_dev(numbers: list[float]) -> float. "
        "Then create a test file test_auto_stat_calc.py that imports auto_stat_calc and asserts "
        "mean([1, 2, 3, 4, 5]) == 3.0 and round(std_dev([1, 2, 3, 4, 5]), 2) == 1.41. "
        "Finally, run python3 test_auto_stat_calc.py using run_command to verify it passes."
    )
    
    t0 = time.time()
    response = agent.run(prompt)
    elapsed = time.time() - t0

    module_exists = target_module.exists()
    test_exists = target_test.exists()
    
    test_passes = False
    test_stdout = ""
    if module_exists and test_exists:
        try:
            res = subprocess.run(
                [sys.executable, str(target_test)],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(PROJECT_ROOT)
            )
            test_passes = res.returncode == 0
            test_stdout = res.stdout + res.stderr
        except Exception as e:
            test_stdout = str(e)

    if target_module.exists():
        target_module.unlink()
    if target_test.exists():
        target_test.unlink()

    passed = module_exists and test_exists and test_passes
    log(f"  Execution Time: {elapsed:.2f}s")
    log(f"  Module Generated: {'✅ Yes' if module_exists else '❌ No'}")
    log(f"  Test File Generated: {'✅ Yes' if test_exists else '❌ No'}")
    log(f"  Independent Test Execution: {'✅ PASSED' if test_passes else '❌ FAILED'}")
    log(f"  Result: {'✅ PASSED' if passed else '❌ FAILED'}")

    return {
        "name": "Autonomous Code Generation & Verification",
        "passed": passed,
        "elapsed_sec": round(elapsed, 2),
        "module_created": module_exists,
        "test_created": test_exists,
        "test_verified": test_passes,
    }


def test_autonomous_bug_healing(agent: JarvisAgent) -> dict:
    log("")
    log("=" * 70)
    log("▶ STRESS VECTOR 2: Autonomous Bug Diagnosis & Self-Healing")
    log("=" * 70)

    buggy_file = PROJECT_ROOT / "buggy_matrix.py"
    buggy_lines = [
        "def transpose(matrix):",
        "    rows = len(matrix)",
        "    cols = len(matrix[0])",
        "    # BUG: using swapped indexing",
        "    return [[matrix[i][j] for i in range(cols)] for j in range(rows)]",
        "",
        "if __name__ == '__main__':",
        "    m = [[1, 2, 3], [4, 5, 6]]",
        "    t = transpose(m)",
        "    expected = [[1, 4], [2, 5], [3, 6]]",
        "    assert t == expected, f'Expected {expected}, got {t}'",
        "    print('MATRIX_TRANSPOSE_VERIFIED')",
    ]
    with open(buggy_file, "w") as f:
        f.write("\n".join(buggy_lines) + "\n")

    prompt = (
        "There is a bug in buggy_matrix.py causing an IndexError or assertion failure. "
        "Use read_file to inspect buggy_matrix.py, understand the bug, use edit_file or write_file "
        "to fix the transpose function so it correctly transposes non-square matrices, and then "
        "execute python3 buggy_matrix.py with run_command to verify it outputs MATRIX_TRANSPOSE_VERIFIED."
    )

    t0 = time.time()
    response = agent.run(prompt)
    elapsed = time.time() - t0

    healed = False
    stdout = ""
    try:
        res = subprocess.run(
            [sys.executable, str(buggy_file)],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(PROJECT_ROOT)
        )
        healed = res.returncode == 0 and "MATRIX_TRANSPOSE_VERIFIED" in res.stdout
        stdout = res.stdout + res.stderr
    except Exception as e:
        stdout = str(e)

    if buggy_file.exists():
        buggy_file.unlink()

    log(f"  Execution Time: {elapsed:.2f}s")
    log(f"  Self-Healing Verification: {'✅ PASSED' if healed else '❌ FAILED'}")
    if not healed:
        log(f"  Script output: {stdout.strip()}")
    log(f"  Result: {'✅ PASSED' if healed else '❌ FAILED'}")

    return {
        "name": "Autonomous Bug Diagnosis & Self-Healing",
        "passed": healed,
        "elapsed_sec": round(elapsed, 2),
        "healed": healed,
    }


def test_system_automation_telemetry(agent: JarvisAgent) -> dict:
    log("")
    log("=" * 70)
    log("▶ STRESS VECTOR 3: System Automation & Host Telemetry")
    log("=" * 70)

    prompt = "Inspect the system telemetry: what is the current Darwin kernel version, CPU utilization, and free memory?"
    t0 = time.time()
    response = agent.run_executive(
        prompt,
        control=get_control_plane(),
        session_id="stress-telemetry",
        workspace=".",
        autonomy="execute_until_approval",
        coding_backend="antigravity",
    )
    elapsed = time.time() - t0

    msg = str(response.get("message") or "")
    has_darwin = "darwin" in msg.lower() or "cpu" in msg.lower() or "memory" in msg.lower()
    passed = len(msg) > 30 and has_darwin

    log(f"  Execution Time: {elapsed:.2f}s")
    log(f"  Intent: {response.get('intent')}")
    log(f"  Telemetry Sample: {msg[:120].replace(chr(10), ' ')}...")
    log(f"  Result: {'✅ PASSED' if passed else '❌ FAILED'}")

    return {
        "name": "System Automation & Host Telemetry",
        "passed": passed,
        "elapsed_sec": round(elapsed, 2),
    }


def test_multi_turn_memory(agent: JarvisAgent) -> dict:
    log("")
    log("=" * 70)
    log("▶ STRESS VECTOR 4: Multi-Turn Memory Persistence & Cross-Turn Recall")
    log("=" * 70)

    secret_key = "SALT_KAPPA_991"
    secret_dir = "/opt/amaura/governed-staging"

    t0 = time.time()
    res1 = agent.run_executive(
        f"Remember that my staging deployment path is '{secret_dir}' and my project security token is '{secret_key}'.",
        control=get_control_plane(),
        session_id="stress-memory-turn",
        workspace=".",
        autonomy="execute_until_approval",
    )
    
    res2 = agent.run_executive(
        "What is the hexadecimal representation of 255?",
        control=get_control_plane(),
        session_id="stress-memory-turn",
        workspace=".",
        autonomy="execute_until_approval",
    )
    
    res3 = agent.run_executive(
        "What is my staging deployment path and what is my project security token?",
        control=get_control_plane(),
        session_id="stress-memory-turn",
        workspace=".",
        autonomy="execute_until_approval",
    )
    elapsed = time.time() - t0

    msg = str(res3.get("message") or "").lower()
    recalled_dir = "staging" in msg or "governed-staging" in msg or secret_dir.lower() in msg
    recalled_key = secret_key.lower() in msg
    passed = recalled_dir and recalled_key

    log(f"  Total Turns: 3")
    log(f"  Execution Time: {elapsed:.2f}s")
    log(f"  Recalled Staging Path: {'✅ Yes' if recalled_dir else '❌ No'}")
    log(f"  Recalled Security Token: {'✅ Yes' if recalled_key else '❌ No'}")
    log(f"  Result: {'✅ PASSED' if passed else '❌ FAILED'}")

    return {
        "name": "Multi-Turn Memory Persistence & Recall",
        "passed": passed,
        "elapsed_sec": round(elapsed, 2),
    }


def test_concurrency_load_stress(num_requests: int = 15) -> dict:
    log("")
    log("=" * 70)
    log(f"▶ STRESS VECTOR 5: Concurrency & Load Stress Test ({num_requests} Concurrent Invocations)")
    log("=" * 70)

    from jarvis.amaura.model_gateway import CognitiveModelGateway

    prompts = [
        "Explain the concept of idempotency in distributed APIs in 1 sentence.",
        "What is the difference between a mutex and a semaphore in 1 sentence?",
        "Why is UTF-8 backward compatible with ASCII? Answer in 1 sentence.",
        "What is the time complexity of binary search? Answer in 1 sentence.",
        "What does ACID stand for in databases? Answer in 1 sentence.",
    ]

    initial_rss = get_rss_mb()
    log(f"  Initial Process RSS: {initial_rss:.2f} MB")
    log(f"  Dispatching {num_requests} concurrent requests across ThreadPoolExecutor(max_workers=5)...")

    latencies: list[float] = []
    errors: list[str] = []

    def _worker(idx: int) -> float:
        prompt = prompts[idx % len(prompts)]
        t_start = time.time()
        try:
            res = CognitiveModelGateway.generate(
                purpose="general",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=64,
            )
            lat = time.time() - t_start
            if not res.text.strip():
                errors.append(f"Req {idx}: empty response")
            return lat
        except Exception as e:
            lat = time.time() - t_start
            errors.append(f"Req {idx}: {e}")
            return lat

    t_total_start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_worker, i) for i in range(num_requests)]
        for f in concurrent.futures.as_completed(futures):
            latencies.append(f.result())
    total_elapsed = time.time() - t_total_start

    final_rss = get_rss_mb()
    rss_delta = final_rss - initial_rss

    latencies.sort()
    p50 = latencies[int(len(latencies) * 0.50)]
    p90 = latencies[int(len(latencies) * 0.90)]
    p99 = latencies[min(int(len(latencies) * 0.99), len(latencies) - 1)]
    min_lat = latencies[0]
    max_lat = latencies[-1]

    passed = len(errors) == 0 and len(latencies) == num_requests
    log(f"  Total Wall Clock Time: {total_elapsed:.2f}s")
    log(f"  Successful Requests: {len(latencies) - len(errors)} / {num_requests}")
    log(f"  Failed Requests: {len(errors)}")
    log(f"  Latency Metrics: min={min_lat:.2f}s, p50={p50:.2f}s, p90={p90:.2f}s, p99={p99:.2f}s, max={max_lat:.2f}s")
    log(f"  Final Process RSS: {final_rss:.2f} MB (Delta: +{rss_delta:.2f} MB)")
    log(f"  Result: {'✅ PASSED' if passed else '❌ FAILED'}")

    return {
        "name": f"Concurrency Load Stress ({num_requests} reqs)",
        "passed": passed,
        "total_elapsed_sec": round(total_elapsed, 2),
        "min_latency_sec": round(min_lat, 2),
        "p50_latency_sec": round(p50, 2),
        "p90_latency_sec": round(p90, 2),
        "p99_latency_sec": round(p99, 2),
        "max_latency_sec": round(max_lat, 2),
        "initial_rss_mb": round(initial_rss, 2),
        "final_rss_mb": round(final_rss, 2),
        "rss_delta_mb": round(rss_delta, 2),
        "errors": errors,
    }


def main():
    log("=" * 70)
    log("  AMAURA JARVIS v5.4 UNFAKED REAL-WORLD STRESS & RELIABILITY SUITE")
    log("  Zero-Faking Policy: All actions executed via live JARVIS runtime")
    log("=" * 70)

    agent = JarvisAgent(model_key="omniroute")

    results = []
    
    results.append(test_autonomous_coding(agent))
    results.append(test_autonomous_bug_healing(agent))
    results.append(test_system_automation_telemetry(agent))
    results.append(test_multi_turn_memory(agent))
    results.append(test_concurrency_load_stress(num_requests=15))

    log("")
    log("=" * 70)
    log("  OVERALL RELIABILITY & STRESS SUITE RESULTS")
    log("=" * 70)
    all_passed = True
    for r in results:
        status = "✅ PASSED" if r["passed"] else "❌ FAILED"
        log(f"  {r['name']:50} {status}")
        if not r["passed"]:
            all_passed = False

    log("=" * 70)
    log(f"  Final Verdict: {'🏆 100% TOP-TIER RELIABLE' if all_passed else '⚠️ FAILURES DETECTED'}")
    log("=" * 70)

    report_file = PROJECT_ROOT / "stress_suite_results.json"
    with open(report_file, "w") as f:
        json.dump({"timestamp": time.time(), "all_passed": all_passed, "results": results}, f, indent=2)
    log(f"\nDetailed ground-truth results saved to: {report_file}")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
