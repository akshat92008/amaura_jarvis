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


def main():
    print("=== Phase 5: Capability Self-Awareness ===")

    evidence_file = EVIDENCE_DIR / "E-CAP-001_self_awareness.json"

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

        headers = {"X-Amaura-Operator-Key": "test_qual_key", "X-Jarvis-Key": "test_jarvis_key"}

        resp = requests.get("http://127.0.0.1:8000/api/amaura/capabilities/status", headers=headers, timeout=10)
        data = resp.json()

        capabilities = data.get("capabilities", [])

        # Verify macos_app is in capabilities
        macos_app = next((c for c in capabilities if c.get("key") == "macos_app"), None)
        success = macos_app is not None

        print(f"\nmacos_app capability present: {success}")
        if success:
            print(f"macos_app availability: {macos_app.get('available')}")

        evidence = {
            "test": "Capability Self-Awareness",
            "endpoint": "/api/amaura/capabilities/status",
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
