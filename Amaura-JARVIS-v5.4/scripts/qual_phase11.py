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

def verify_app_running(app_name):
    cmd = f'osascript -e \'tell application "System Events" to (name of processes) contains "{app_name}"\''
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return res.stdout.strip() == "true"

def send_chat_request(text, autonomy="plan_only"):
    payload = {
        "message": text,
        "session_id": "qual_phase11",
        "workspace": "",
        "autonomy": autonomy,
        "coding_backend": "antigravity"
    }
    headers = {
        "X-Amaura-Operator-Key": "test_qual_key",
        "X-Jarvis-Key": "test_jarvis_key"
    }
    print(f"\n[JARVIS Request (autonomy={autonomy})] {text}")
    resp = requests.post("http://127.0.0.1:8000/api/chat", json=payload, headers=headers, timeout=30)
    data = resp.json()
    print(f"[JARVIS Response] Intent: {data.get('intent')}")
    msg = data.get('response', data.get('message', ''))
    print(f"[JARVIS Message] {msg}")
    return data, msg

def main():
    print("=== Phase 11: Planning Mode Isolation ===")
    
    evidence_file = EVIDENCE_DIR / "E-PLN-001_planning_mode.json"
    
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
        
        # Ensure Safari is not running
        subprocess.run("osascript -e 'tell application \"Safari\" to quit'", shell=True)
        time.sleep(1)
        
        is_running_before = verify_app_running("Safari")
        print(f"Safari running before: {is_running_before}")
        
        data, msg = send_chat_request("open Safari", autonomy="plan_only")
        
        is_running_after = verify_app_running("Safari")
        print(f"Safari running after plan_only: {is_running_after}")
        
        # Verify no side-effects (Safari should NOT have been opened)
        no_side_effects = (not is_running_before) and (not is_running_after)
        
        success = no_side_effects
        print(f"Test Passed: {success}")
        
        evidence = {
            "test": "Planning Mode Isolation",
            "autonomy": "plan_only",
            "is_running_before": is_running_before,
            "is_running_after": is_running_after,
            "chat_response": data,
            "success": success
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
