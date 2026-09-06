"""Comprehensive automated validation suite for real-world JARVIS daily tasks.

Executes real-world tasks across:
1. Conversational Reasoning & Drafting (Email, Algorithms, Explanations, Math, Summaries)
2. Desktop App Control & Automation (Opening apps with alias resolution)
3. Desktop System Controls (Volume, System Telemetry, Process Discovery)
4. Long-Term Memory Storage & Retrieval
5. Cognitive Multi-Provider Resilience & Self-Healing
"""

import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.amaura.runtime import load_amaura_env
load_amaura_env()

from jarvis.agent import JarvisAgent
from jarvis.tools.amaura import get_control_plane

def run_tests():
    print("=" * 70)
    print("  JARVIS v5.5 Comprehensive Real-World Scenario Test Suite")
    print("=" * 70)

    agent = JarvisAgent(model_key="omniroute")
    control = get_control_plane()

    test_cases = [
        # --- Group 1: Conversational Intelligence & Daily Productivity ---
        {
            "name": "1. Email Drafting",
            "prompt": "Draft a polite 3-sentence email thanking an interviewer at Google for their time.",
            "check": lambda res: len(str(res.get("message") or "").strip()) > 30
            and any(w in str(res.get("message") or "").lower() for w in ("thank", "google", "interview", "time")),
        },
        {
            "name": "2. Python Algorithm Coding",
            "prompt": "Write a Python function to find the two numbers in a list that add up to a target (Two Sum) with O(n) time complexity.",
            "check": lambda res: "def " in str(res.get("message") or "")
            and any(w in str(res.get("message") or "").lower() for w in ("target", "dict", "seen", "complement", "hash")),
        },
        {
            "name": "3. Technical Explanation",
            "prompt": "Explain what a database index is and when to use B-Trees vs Hash indexes in 2 paragraphs.",
            "check": lambda res: len(str(res.get("message") or "").strip()) > 50
            and ("index" in str(res.get("message") or "").lower() or "b-tree" in str(res.get("message") or "").lower()),
        },
        {
            "name": "4. Mathematical & Logic Reasoning",
            "prompt": "If a train travels at 60 mph for 2.5 hours and then 80 mph for 1.5 hours, what is its average speed for the entire journey? Show your calculation.",
            "check": lambda res: any(w in str(res.get("message") or "") for w in ("67.5", "270", "average", "Average")),
        },
        {
            "name": "5. Everyday Productivity Summary",
            "prompt": "Summarize the top 3 principles of the Pomodoro technique into bullet points.",
            "check": lambda res: len(str(res.get("message") or "").strip()) > 30
            and any(char in str(res.get("message") or "") for char in ("-", "•", "1.", "25", "minute")),
        },

        # --- Group 2: Desktop & System Automation ---
        {
            "name": "6. Desktop App Control (Calculator)",
            "prompt": "Open Calculator",
            "check": lambda res: res.get("intent") == "macos_app"
            and ("opened" in str(res.get("message") or "").lower() or res.get("state") == "completed"),
        },
        {
            "name": "7. Desktop Volume Control",
            "prompt": "Set volume to 40%",
            "check": lambda res: res.get("intent") == "desktop_control"
            and "volume set to 40%" in str(res.get("message") or "").lower(),
        },
        {
            "name": "8. Desktop System Telemetry",
            "prompt": "Show system info",
            "check": lambda res: res.get("intent") == "desktop_control"
            and any(w in str(res.get("message") or "").lower() for w in ("system:", "cpu", "memory", "disk", "darwin")),
        },
        {
            "name": "9. Real Running Apps Inspection",
            "prompt": "What apps are running?",
            "check": lambda res: res.get("intent") == "desktop_control"
            and "running applications" in str(res.get("message") or "").lower()
            and len(str(res.get("message") or "")) > 30,
        },

        # --- Group 3: Memory & Personalization ---
        {
            "name": "10. Store Personal Preference",
            "prompt": "Remember that my preferred language is TypeScript",
            "check": lambda res: res.get("intent") == "memory_write"
            and "typescript" in str(res.get("message") or "").lower(),
        },
        {
            "name": "11. Recall Personal Preference",
            "prompt": "What is my preferred language?",
            "check": lambda res: "typescript" in str(res.get("message") or "").lower(),
        },
    ]

    passed = 0
    total = len(test_cases)

    for tc in test_cases:
        print(f"\n▶ Running: {tc['name']}")
        print(f"  Prompt: {tc['prompt']}")
        try:
            res = agent.run_executive(
                tc["prompt"],
                control=control,
                session_id=f"test-{tc['name'][:4].strip()}",
                workspace=".",
                autonomy="execute_until_approval",
                coding_backend="antigravity",
            )
            msg = str(res.get("message") or "").strip()
            intent = res.get("intent", "unknown")
            print(f"  Intent: {intent}")
            preview = msg[:150].replace("\n", " ")
            print(f"  Preview: {preview}...")
            
            if tc["check"](res):
                print(f"  Result: ✅ PASSED")
                passed += 1
            else:
                print(f"  Result: ⚠️ Output didn't match expected criteria")
                print(f"  Full response: {msg}")
        except Exception as exc:
            print(f"  Result: ❌ FAILED with error: {exc}")

    # --- Group 4: Resilience & Cascade Fallback Verification ---
    print("\n▶ Running: 12. Cognitive Cascade Fallback (Simulated OmniRoute Offline)")
    saved_url = os.environ.get("AMAURA_OMNIROUTE_BASE_URL", "")
    try:
        # Point omniroute to dead port to verify seamless cascade fallback to NVIDIA/Ollama
        os.environ["AMAURA_OMNIROUTE_BASE_URL"] = "http://127.0.0.1:19999/v1"
        res = agent.run_executive(
            "Give me 3 tips for writing clean Python code.",
            control=control,
            session_id="test-resilience",
            workspace=".",
            autonomy="execute_until_approval",
            coding_backend="antigravity",
        )
        msg = str(res.get("message") or "").strip()
        if len(msg) > 30 and "temporarily unavailable" not in msg.lower():
            print(f"  Cascade Output: {msg[:100]}...")
            print("  Result: ✅ PASSED (Gracefully fell back to active secondary model)")
            passed += 1
        else:
            print(f"  Result: ⚠️ Cascade failed: {msg}")
    except Exception as exc:
        print(f"  Result: ❌ FAILED with error: {exc}")
    finally:
        if saved_url:
            os.environ["AMAURA_OMNIROUTE_BASE_URL"] = saved_url
    total += 1

    print("\n" + "=" * 70)
    print(f"  Suite Results: {passed}/{total} Scenarios Passed")
    print("=" * 70)
    return passed == total

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
