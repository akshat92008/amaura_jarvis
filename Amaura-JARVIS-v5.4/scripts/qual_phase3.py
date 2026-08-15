import os
import sys
import time
import json
import subprocess
import requests
from pathlib import Path

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = ROOT_DIR / "qualification_evidence" / "20260812_193925"

def send_chat_request(text):
    payload = {
        "message": text,
        "session_id": "qual_phase3",
        "workspace": "",
        "autonomy": "execute_until_approval",
        "coding_backend": "antigravity"
    }
    headers = {
        "X-Amaura-Operator-Key": "test_qual_key",
        "X-Jarvis-Key": "test_jarvis_key"
    }
    print(f"\n[JARVIS Request] {text}")
    resp = requests.post("http://127.0.0.1:8000/api/chat", json=payload, headers=headers, timeout=30)
    data = resp.json()
    print(f"[JARVIS Response] Intent: {data.get('intent', data.get('executive', {}).get('intent'))}")
    msg = data.get('message', data.get('response'))
    print(f"[JARVIS Message] {msg}")
    return data, msg

def main():
    print("=== Phase 3: Negative macOS Tests ===")
    
    evidence_file = EVIDENCE_DIR / "E-MAC-003_negative_tests.json"
    
    print("Starting backend...")
    env = os.environ.copy()
    env["AMAURA_OPERATOR_KEY"] = "test_qual_key"
    env["JARVIS_API_KEY"] = "test_jarvis_key"
    
    server = subprocess.Popen(
        [sys.executable, "-m", "jarvis.server"],
        cwd=ROOT_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
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
        tests = [
            "open malware_app",
            "open Safari; touch /tmp/pwned",
        ]
        
        for text in tests:
            print(f"\n--- Test: {text} ---")
            data, msg = send_chat_request(text)
            
            # Verify failure (should not be "Successfully opened")
            success = "✅" not in msg and ("Failed" in msg or "Error" in msg or "not in the strict allowlist" in msg)
            print(f"Test Passed: {success}")
            
            evidence_records.append({
                "test": text,
                "jarvis_response": data,
                "msg": msg,
                "success": success
            })
            
        with open(evidence_file, "w") as f:
            json.dump(evidence_records, f, indent=2)
            
        print(f"\nEvidence saved to {evidence_file}")
        
    finally:
        print("\nShutting down backend...")
        server.terminate()
        server.wait()

if __name__ == "__main__":
    main()
