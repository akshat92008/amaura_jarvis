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


def verify_app_running(app_name):
    """Check if a macOS app is running using osascript."""
    cmd = f'osascript -e \'tell application "System Events" to (name of processes) contains "{app_name}"\''
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return "true" in result.stdout.strip().lower()


def control_app(app_name, action):
    """Force an app to a specific state to prepare for test."""
    if action == "quit":
        subprocess.run(f"osascript -e 'tell application \"{app_name}\" to quit'", shell=True)
        time.sleep(2)
        if verify_app_running(app_name):
            subprocess.run(["pkill", "-f", app_name])
            time.sleep(1)
    elif action == "open":
        subprocess.run(f"osascript -e 'tell application \"{app_name}\" to activate'", shell=True)
        time.sleep(2)


def send_chat_request(text):
    payload = {
        "message": text,
        "session_id": "qual_phase2",
        "workspace": "",
        "autonomy": "execute_until_approval",
        "coding_backend": "antigravity",
    }
    headers = {"X-Amaura-Operator-Key": "test_qual_key", "X-Jarvis-Key": "test_jarvis_key"}
    print(f"\n[JARVIS Request] {text}")
    resp = requests.post("http://127.0.0.1:8000/api/chat", json=payload, headers=headers, timeout=30)
    print(f"DEBUG: status_code={resp.status_code}, response_text={resp.text}")
    try:
        data = resp.json()
    except Exception as e:
        print(f"DEBUG JSON ERROR: {e}")
        data = {}
    print(f"[JARVIS Response] Intent: {data.get('intent')} | Message: {data.get('message')}")
    return data


def main():
    print("=== Phase 2: macOS Action Path E2E Tests ===")

    evidence_file = EVIDENCE_DIR / "E-MAC-001_safari_open.json"
    evidence_file2 = EVIDENCE_DIR / "E-MAC-002_other_actions.json"

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
        server.terminate()
        sys.exit(1)

    print("Server is up.")
    evidence_records = []

    try:
        # TEST 1: open Safari (Prove not running, invoke JARVIS, prove running)
        print("\n--- Test 1: open Safari ---")
        control_app("Safari", "quit")
        is_running_before = verify_app_running("Safari")
        print(f"Safari running before: {is_running_before}")

        response = send_chat_request("open Safari")

        time.sleep(3)  # Wait for OS to launch app
        is_running_after = verify_app_running("Safari")
        print(f"Safari running after: {is_running_after}")

        evidence_records.append(
            {
                "test": "open Safari",
                "is_running_before": is_running_before,
                "jarvis_response": response,
                "is_running_after": is_running_after,
                "success": not is_running_before and is_running_after and "✅" in response.get("message", ""),
            }
        )

        # Output evidence 1
        with open(evidence_file, "w") as f:
            json.dump(evidence_records[0], f, indent=2)

        print(f"Test 1 evidence saved to {evidence_file}")

        # OTHER TESTS
        other_actions = [
            ("launch Safari", "Safari"),
            ("activate Safari", "Safari"),
            ("focus Safari", "Safari"),
            ("show Safari", "Safari"),
            ("open Notes", "Notes"),
            ("close Notes", "Notes"),
            ("quit Notes", "Notes"),
        ]

        other_evidence = []
        for text, app in other_actions:
            print(f"\n--- Test: {text} ---")
            # If closing, ensure it's open first
            if "close" in text or "quit" in text:
                control_app(app, "open")
                time.sleep(1)

            res = send_chat_request(text)
            time.sleep(2)

            is_running_after = verify_app_running(app)
            print(f"{app} running after {text}: {is_running_after}")

            other_evidence.append({"test": text, "jarvis_response": res, "is_running_after": is_running_after})

        with open(evidence_file2, "w") as f:
            json.dump(other_evidence, f, indent=2)

        print(f"\nOther tests evidence saved to {evidence_file2}")

    finally:
        print("\nShutting down backend...")
        server.terminate()
        server.wait()


if __name__ == "__main__":
    main()
