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


def send_chat_request(text):
    payload = {
        "message": text,
        "session_id": "qual_phase7",
        "workspace": "",
        "autonomy": "execute_until_approval",
        "coding_backend": "antigravity",
    }
    headers = {"X-Amaura-Operator-Key": "test_qual_key", "X-Jarvis-Key": "test_jarvis_key"}
    print(f"\n[JARVIS Request] {text}")
    resp = requests.post("http://127.0.0.1:8000/api/chat", json=payload, headers=headers, timeout=30)
    data = resp.json()
    print(f"[JARVIS Response] Intent: {data.get('intent', data.get('executive', {}).get('intent'))}")
    msg = data.get("message", data.get("response"))
    print(f"[JARVIS Message] {msg}")
    return data, msg


def main():
    print("=== Phase 7: Core Chat E2E ===")

    evidence_file = EVIDENCE_DIR / "E-CHAT-001_core_chat.json"

    print("Starting backend...")
    env = os.environ.copy()
    env["AMAURA_OPERATOR_KEY"] = "test_qual_key"
    env["JARVIS_API_KEY"] = "test_jarvis_key"

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

        data, msg = send_chat_request("Hello JARVIS. Can you confirm your version and capabilities for qualification?")

        # Verify latency metrics exist
        latency = data.get("model_latency_ms")
        ttft = data.get("model_ttft_ms")
        intent = data.get("intent")

        success = latency is not None and ttft is not None and isinstance(msg, str) and len(msg) > 0

        print(f"\nLatency: {latency}ms")
        print(f"TTFT: {ttft}ms")
        print(f"Intent: {intent}")
        print(f"Test Passed: {success}")

        evidence = {
            "test": "Core Chat E2E",
            "request": "Hello JARVIS. Can you confirm your version and capabilities for qualification?",
            "response": data,
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
