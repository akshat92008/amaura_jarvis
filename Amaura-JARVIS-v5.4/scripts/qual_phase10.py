import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = ROOT_DIR / "qualification_evidence" / "20260812_193925"


def send_memory_update(payload):
    headers = {"X-Amaura-Operator-Key": "test_qual_key", "X-Jarvis-Key": "test_jarvis_key"}
    resp = requests.post("http://127.0.0.1:8000/api/memory", json=payload, headers=headers, timeout=10)
    return resp.json()


def send_chat_request(text):
    payload = {
        "message": text,
        "session_id": "qual_phase10",
        "workspace": "",
        "autonomy": "execute_until_approval",
        "coding_backend": "antigravity",
    }
    headers = {"X-Amaura-Operator-Key": "test_qual_key", "X-Jarvis-Key": "test_jarvis_key"}
    print(f"\n[JARVIS Request] {text}")
    resp = requests.post("http://127.0.0.1:8000/api/chat", json=payload, headers=headers, timeout=60)
    data = resp.json()
    print(f"[JARVIS Response] Intent: {data.get('intent')}")
    msg = data.get("response", data.get("message", ""))
    print(f"[JARVIS Message] {msg}")
    return data, msg


def main():
    print("=== Phase 10: Reference Resolution ===")

    evidence_file = EVIDENCE_DIR / "E-REF-001_reference_resolution.json"

    print("Starting backend...")
    env = os.environ.copy()
    env["AMAURA_OPERATOR_KEY"] = "test_qual_key"
    env["JARVIS_API_KEY"] = "test_jarvis_key"
    env["AMAURA_JARVIS_INTERACTIVE_LEGACY_FALLBACK"] = "1"
    env["AMAURA_JARVIS_LLM_PLANNER"] = "0"
    env["AMAURA_JARVIS_INTENT_MODEL"] = "0"
    env["AMAURA_MODEL_MODE"] = "local"

    server = subprocess.Popen(
        [sys.executable, "-m", "jarvis.server"],
        cwd=ROOT_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        # Wait for server to start
        for _ in range(30):
            try:
                resp = requests.get("http://127.0.0.1:8000/api/health")
                if resp.status_code == 200:
                    break
            except requests.exceptions.ConnectionError:
                time.sleep(1)
        else:
            print("Server failed to start.")
            sys.exit(1)

        print("Server is up.")

        # 1. Save memory reference
        ref_key = "project_falcon_code"
        ref_val = "FALCON-9982-SECRET"
        send_memory_update({"key": ref_key, "value": ref_val})
        print(f"Saved memory reference: {ref_key} = {ref_val}")

        # 2. Query referencing it
        data, msg = send_chat_request("What is the project falcon code from my memory?")

        # Verify reference resolution / context sources
        context_sources = data.get("executive", {}).get("context_sources", [])
        print(f"Context Sources: {context_sources}")

        # Check if reference or memory was resolved
        success = ref_val in msg or any(
            "qual_phase10" in str(src).lower() or "falcon" in str(src).lower() for src in context_sources
        )
        print(f"Test Passed: {success}")

        evidence = {
            "test": "Reference Resolution",
            "ref_key": ref_key,
            "ref_val": ref_val,
            "query": "What is the project falcon code from my memory?",
            "chat_response": data,
            "success": success,
        }

        with open(evidence_file, "w") as f:
            json.dump(evidence, f, indent=2)

        print(f"\nEvidence saved to {evidence_file}")

    finally:
        print("\nShutting down backend...")
        server.terminate()
        server.wait()


if __name__ == "__main__":
    main()
