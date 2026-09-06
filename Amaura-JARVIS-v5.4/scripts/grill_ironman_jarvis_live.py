"""
Iron Man JARVIS — Real-World Live Grilling & Automation Verification Suite.

ZERO-FAKING COMMITMENT:
All operations are executed live by the real JarvisAgent, real tools, real system APIs,
and real LLM reasoning passes. The script itself NEVER writes the solution files;
JARVIS itself must autonomously invoke tools (web_search, run_command, write_file, etc.)
to achieve the goals.
"""

from __future__ import annotations

import json
import os
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
from jarvis.fleet import house_party_protocol
from jarvis.knowledge_graph import get_knowledge_graph
from jarvis.morning_briefing import compose_morning_briefing
from jarvis.personality import get_personality
from jarvis.awareness import get_awareness


def log(msg: str) -> None:
    print(msg, flush=True)


def test_realworld_web_intelligence(agent: JarvisAgent) -> dict:
    log("\n" + "=" * 75)
    log("▶ REAL-WORLD GRILL 1: Live Web Search & Technical Briefing Generation")
    log("=" * 75)
    agent.messages.clear()

    target_doc = PROJECT_ROOT / "CLAUDE_3_7_ANALYSIS.md"
    if target_doc.exists():
        target_doc.unlink()

    prompt = (
        "Execute a live web search using web_search for 'Claude 3.7 Sonnet hybrid reasoning'. "
        "Extract key architectural details: hybrid thinking model, token budgets, and coding benchmarks. "
        "Then use write_file to save a comprehensive technical report into 'CLAUDE_3_7_ANALYSIS.md' "
        "in the current workspace. Ensure the file contains at least 300 words of technical synthesis."
    )

    t0 = time.time()
    response = agent.run(prompt)
    elapsed = round(time.time() - t0, 2)

    doc_exists = target_doc.exists()
    doc_size = target_doc.stat().st_size if doc_exists else 0
    passed = doc_exists and doc_size > 500

    log(f"Response preview:\n{response[:300]}...")
    log(f"File status: exists={doc_exists}, size={doc_size} bytes, elapsed={elapsed}s")
    log(f"Result: {'✅ PASSED' if passed else '❌ FAILED'}")

    return {
        "name": "Live Web Intelligence (Claude 3.7)",
        "passed": passed,
        "elapsed_sec": elapsed,
        "file_created": doc_exists,
        "file_bytes": doc_size,
    }


def test_realworld_system_telemetry(agent: JarvisAgent) -> dict:
    log("\n" + "=" * 75)
    log("▶ REAL-WORLD GRILL 2: Live Mac Hardware & Telemetry Extraction")
    log("=" * 75)
    agent.messages.clear()

    target_json = PROJECT_ROOT / "MAC_TELEMETRY.json"
    if target_json.exists():
        target_json.unlink()

    prompt = (
        "Inspect the host Mac system: run terminal commands or system tools using run_command "
        "to check top CPU processes (e.g. ps -arcwwwxo pid,%cpu,comm | head -n 6), "
        "disk space (df -h /), and current memory. "
        "Then write the parsed data as valid JSON into 'MAC_TELEMETRY.json' with keys: "
        "'timestamp', 'top_processes', 'disk_free', and 'system_platform'. "
        "Make sure MAC_TELEMETRY.json is written to disk."
    )

    t0 = time.time()
    response = agent.run(prompt)
    elapsed = round(time.time() - t0, 2)

    json_exists = target_json.exists()
    is_valid_json = False
    parsed_data = {}
    if json_exists:
        try:
            parsed_data = json.loads(target_json.read_text(encoding="utf-8"))
            is_valid_json = isinstance(parsed_data, dict) and "top_processes" in parsed_data
        except Exception as exc:
            log(f"JSON validation error: {exc}")

    passed = json_exists and is_valid_json
    log(f"File status: exists={json_exists}, valid_json={is_valid_json}, elapsed={elapsed}s")
    log(f"Result: {'✅ PASSED' if passed else '❌ FAILED'}")

    return {
        "name": "Live Mac Hardware Telemetry",
        "passed": passed,
        "elapsed_sec": elapsed,
        "json_valid": is_valid_json,
    }


def test_realworld_software_engineering(agent: JarvisAgent) -> dict:
    log("\n" + "=" * 75)
    log("▶ REAL-WORLD GRILL 3: Autonomous Software Engineering & Pytest Verification")
    log("=" * 75)
    agent.messages.clear()

    util_file = PROJECT_ROOT / "markdown_table_formatter.py"
    test_file = PROJECT_ROOT / "test_markdown_table_formatter.py"

    if util_file.exists():
        util_file.unlink()
    if test_file.exists():
        test_file.unlink()

    prompt = (
        "You are tasked with building a real-world software utility. "
        "Create 'markdown_table_formatter.py' with a function:\n"
        "  `format_markdown_table(text: str) -> str`\n"
        "Requirements:\n"
        "- Parses pipe-delimited markdown tables in `text`.\n"
        "- Computes maximum column widths for each column (the width of the longest cell in that column, minimum 3 for '---').\n"
        "- Normalizes each row so cells are padded with spaces to match column widths.\n"
        "- Preserves alignment indicators in delimiter rows (e.g. :--- for left, :---: for center, ---: for right).\n"
        "- Leaves non-table lines completely untouched.\n\n"
        "Next, create 'test_markdown_table_formatter.py' with at least 4 pytest test cases:\n"
        "1. test_basic_table: verifies formatting a simple 2x2 table.\n"
        "2. test_alignments: verifies left (:---), center (:---:), and right (---:) alignment preservation.\n"
        "3. test_text_without_tables: returns regular prose unmodified.\n"
        "4. test_multiline_mixed_content: handles a mix of regular text and an embedded table.\n\n"
        "IMPORTANT: Ensure test expectations match your format_markdown_table output (expected strings must have the exact padded column widths!). Use write_file to save both files.\n"
        "Then execute `pytest test_markdown_table_formatter.py -v` using `run_command`. If any test fails, use write_file to rewrite the file with fixes until all tests pass."
    )

    t0 = time.time()
    response = agent.run(prompt)
    elapsed = round(time.time() - t0, 2)

    util_exists = util_file.exists()
    test_exists = test_file.exists()
    pytest_passed = False

    if util_exists and test_exists:
        try:
            res = subprocess.run(
                [sys.executable, "-m", "pytest", str(test_file), "-v"],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=str(PROJECT_ROOT),
            )
            pytest_passed = res.returncode == 0
            log(f"Independent Pytest Run:\n{res.stdout.strip()}")
            if res.stderr:
                log(f"Pytest stderr:\n{res.stderr.strip()}")
        except Exception as exc:
            log(f"Pytest run exception: {exc}")

    passed = util_exists and test_exists and pytest_passed
    log(f"Engineering outcome: util={util_exists}, test={test_exists}, pytest_passed={pytest_passed}, elapsed={elapsed}s")
    log(f"Result: {'✅ PASSED' if passed else '❌ FAILED'}")

    return {
        "name": "Autonomous Software Engineering (Markdown Formatter)",
        "passed": passed,
        "elapsed_sec": elapsed,
        "util_exists": util_exists,
        "test_exists": test_exists,
        "pytest_passed": pytest_passed,
    }


def test_fleet_house_party() -> dict:
    log("\n" + "=" * 75)
    log("▶ REAL-WORLD GRILL 4: Iron Man Fleet Swarm (House Party Protocol)")
    log("=" * 75)

    t0 = time.time()
    objective = "Execute security, performance, dependency, and architecture sweep of current repo"
    report = house_party_protocol(objective)
    elapsed = round(time.time() - t0, 2)

    suits = ["MARK_42", "HEARTBREAKER", "SILVER_CENTURION", "IGOR", "VERONICA"]
    suits_present = all(suit in report for suit in suits)
    has_protocol_ack = "HOUSE PARTY PROTOCOL ENGAGED" in report and "All suits reporting in" in report

    passed = suits_present and has_protocol_ack and elapsed < 10.0
    log(f"Fleet Protocol Report:\n{report[:400]}...")
    log(f"Suits present: {suits_present}, has_protocol_ack: {has_protocol_ack}, elapsed={elapsed}s")
    log(f"Result: {'✅ PASSED' if passed else '❌ FAILED'}")

    return {
        "name": "House Party Protocol Fleet Swarm",
        "passed": passed,
        "elapsed_sec": elapsed,
        "suits_verified": suits_present,
    }


def main():
    log("╔══════════════════════════════════════════════════════════════════════════════╗")
    log("║      IRON MAN JARVIS — LIVE REAL-WORLD CAPABILITY & STRESS GRILL             ║")
    log("╚══════════════════════════════════════════════════════════════════════════════╝")

    t_start = time.time()
    agent = JarvisAgent(working_dir=str(PROJECT_ROOT))
    log(f"JarvisAgent initialized with model: {agent.model_key} | provider: {agent.provider}")

    results = []

    # Test 1: Real-Time Web Intelligence
    r1 = test_realworld_web_intelligence(agent)
    results.append(r1)
    time.sleep(3)

    # Test 2: Real-Time Hardware & Process Telemetry
    r2 = test_realworld_system_telemetry(agent)
    results.append(r2)
    time.sleep(3)

    # Test 3: Autonomous Software Engineering & Verification
    r3 = test_realworld_software_engineering(agent)
    results.append(r3)
    time.sleep(3)

    # Test 4: Multi-Suit Fleet Swarm
    r4 = test_fleet_house_party()
    results.append(r4)

    total_elapsed = round(time.time() - t_start, 2)
    all_passed = all(r["passed"] for r in results)

    summary = {
        "timestamp": time.time(),
        "total_elapsed_sec": total_elapsed,
        "all_passed": all_passed,
        "results": results,
    }

    results_file = PROJECT_ROOT / "grill_live_results.json"
    results_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    log("\n" + "=" * 75)
    log("GRILL EXECUTION SUMMARY")
    log("=" * 75)
    for r in results:
        status_sym = "✅ PASSED" if r["passed"] else "❌ FAILED"
        log(f"• {r['name']:<50} {status_sym} ({r['elapsed_sec']}s)")
    log(f"\nOVERALL STATUS: {'ALL TESTS PASSED 🚀' if all_passed else 'SOME TESTS FAILED ⚠️'} in {total_elapsed}s")
    log(f"Saved results to: {results_file.name}")


if __name__ == "__main__":
    main()
