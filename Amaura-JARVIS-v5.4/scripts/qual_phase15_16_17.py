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
    print("=== Phase 15-17: Company OS, Ventures & Financial Trust ===")

    ev_15 = EVIDENCE_DIR / "E-CMP-001_company_os.json"
    ev_16 = EVIDENCE_DIR / "E-VNT-001_ventures.json"
    ev_17 = EVIDENCE_DIR / "E-FIN-001_financial_trust.json"

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

        # ── Phase 15: Company OS Lifecycle ────────────────────────────────────
        resp15 = requests.get("http://127.0.0.1:8000/api/amaura/company/status", headers=headers, timeout=10)
        data15 = resp15.json()
        p15_passed = resp15.status_code == 200 and "bootstrapped" in data15
        print(f"Phase 15 (Company OS Status): {p15_passed}")
        with open(ev_15, "w") as f:
            json.dump({"test": "Company OS Lifecycle", "response": data15, "success": p15_passed}, f, indent=2)

        # ── Phase 16: Amaura Ventures Validation ──────────────────────────────
        resp16 = requests.get("http://127.0.0.1:8000/api/amaura/ventures/status", headers=headers, timeout=10)
        data16 = resp16.json()
        p16_passed = resp16.status_code == 200 and "branch" in data16
        print(f"Phase 16 (Amaura Ventures Status): {p16_passed}")
        with open(ev_16, "w") as f:
            json.dump({"test": "Amaura Ventures Validation", "response": data16, "success": p16_passed}, f, indent=2)

        # ── Phase 17: Financial Trust ─────────────────────────────────────────
        resp17 = requests.get("http://127.0.0.1:8000/api/amaura/ventures/cashflow", headers=headers, timeout=10)
        data17 = resp17.json()
        p17_passed = resp17.status_code == 200 and ("lanes" in data17 or "cashflow" in data17 or "balances" in data17)
        print(f"Phase 17 (Financial Trust Cashflow): {p17_passed}")
        with open(ev_17, "w") as f:
            json.dump({"test": "Financial Trust", "response": data17, "success": p17_passed}, f, indent=2)

    finally:
        print("Shutting down backend...")
        server.terminate()
        server.wait()


if __name__ == "__main__":
    main()
