import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

from jarvis.amaura.antigravity_bridge import AntigravityDeliveryAdapter, AntigravityResultContract

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = ROOT_DIR / "qualification_evidence" / "20260812_193925"


def main():
    print("=== Phase 12-14: Antigravity & Approvals Subsystem ===")

    ev_12 = EVIDENCE_DIR / "E-AGY-001_contract_valid.json"
    ev_13 = EVIDENCE_DIR / "E-AGY-002_contract_rejection.json"
    ev_14 = EVIDENCE_DIR / "E-APP-001_approvals.json"

    # ── Phase 12: Clean Antigravity Contract Qualification ────────────────────
    valid_payload = json.dumps(
        {
            "schema": "amaura.antigravity-result.v1",
            "success": True,
            "summary": "Implemented feature cleanly.",
            "changed_files": ["src/app.py"],
            "verification_commands": ["python -m unittest"],
        }
    )

    try:
        contract_dict = AntigravityDeliveryAdapter._extract_contract(valid_payload)
        contract = AntigravityResultContract.model_validate(contract_dict)
        p12_passed = contract.success is True and len(contract.changed_files) == 1
    except Exception as exc:
        print(f"P12 failed: {exc}")
        p12_passed = False

    print(f"Phase 12 (Antigravity Valid Contract): {p12_passed}")
    with open(ev_12, "w") as f:
        json.dump({"test": "Clean Antigravity Contract", "payload": valid_payload, "success": p12_passed}, f, indent=2)

    # ── Phase 13: Antigravity Failure Path (Rejection) ────────────────────────
    invalid_payload = json.dumps(
        {
            "schema": "amaura.antigravity-result.v1",
            "success": True,
            "summary": "Bad path traversal",
            "changed_files": ["../../etc/passwd"],
            "verification_commands": ["python -m unittest"],
        }
    )

    p13_passed = False
    try:
        contract_dict = AntigravityDeliveryAdapter._extract_contract(invalid_payload)
        AntigravityResultContract.model_validate(contract_dict)
    except Exception as exc:
        print(f"P13 caught expected validation/governance rejection: {exc}")
        p13_passed = True

    print(f"Phase 13 (Antigravity Failure Path Rejection): {p13_passed}")
    with open(ev_13, "w") as f:
        json.dump({"test": "Antigravity Failure Path", "payload": invalid_payload, "success": p13_passed}, f, indent=2)

    # ── Phase 14: Approvals Subsystem E2E ─────────────────────────────────────
    print("\nStarting backend for Phase 14...")
    env = os.environ.copy()
    env["AMAURA_APPROVAL_KEY"] = "test_approval_key"
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

        headers = {
            "X-Amaura-Operator-Key": "test_qual_key",
            "X-Amaura-Approval-Key": "test_approval_key",
            "X-Jarvis-Key": "test_jarvis_key",
        }

        # Query approvals endpoint
        resp = requests.get("http://127.0.0.1:8000/api/amaura/approvals", headers=headers, timeout=10)
        data = resp.json()
        print(f"Approvals response status: {resp.status_code}")

        p14_passed = resp.status_code == 200 and "approvals" in data
        print(f"Phase 14 (Approvals Subsystem): {p14_passed}")

        with open(ev_14, "w") as f:
            json.dump({"test": "Approvals Subsystem", "response": data, "success": p14_passed}, f, indent=2)

    finally:
        print("Shutting down backend...")
        server.terminate()
        server.wait()


if __name__ == "__main__":
    main()
