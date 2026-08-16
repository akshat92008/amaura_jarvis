import os
import subprocess
import time

import requests

RUN_ID = "20260812_193925"
EVIDENCE_DIR = os.path.join(os.getcwd(), f"qualification_evidence/{RUN_ID}/phase_1")
os.makedirs(EVIDENCE_DIR, exist_ok=True)


def write_ev(name, content):
    with open(os.path.join(EVIDENCE_DIR, name), "w") as f:
        f.write(content)


def get_health():
    try:
        return requests.get("http://127.0.0.1:8000/api/health").json()
    except Exception as e:
        return {"error": str(e)}


def run_phase1():
    print("Starting backend A...")
    backend = subprocess.Popen([".venv/bin/python", "-m", "uvicorn", "jarvis.server:app", "--port", "8000"])
    time.sleep(3)  # Wait for startup

    health_a = get_health()
    build_id_a = health_a.get("build_id")
    print(f"Backend A Build ID: {build_id_a}")

    write_ev(
        "E-BUILD-001.txt",
        f"EVIDENCE ID: E-BUILD-001\nCLAIM: Record build ID A\nBUILD_ID: {build_id_a}\nJSON: {health_a}",
    )

    print("Changing source identity (making a temporary commit)...")
    # Make a temporary commit to change HEAD^{tree}
    with open("SuperMario.py", "a") as f:
        f.write("\n# qualification touch")
    subprocess.run(["git", "add", "SuperMario.py"])
    subprocess.run(["git", "commit", "-m", "temp: qualification phase 1"])

    new_tree = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], capture_output=True, text=True).stdout.strip()
    print(f"New Git Tree Hash: {new_tree}")

    print("Checking old backend...")
    health_a2 = get_health()
    build_id_a2 = health_a2.get("build_id")
    print(f"Old Backend still reports: {build_id_a2}")

    write_ev(
        "E-BUILD-002.txt",
        f"EVIDENCE ID: E-BUILD-002\nCLAIM: Old backend still reports A\nEXPECTED: {build_id_a}\nACTUAL: {build_id_a2}\nJSON: {health_a2}",
    )

    print("Restarting backend...")
    backend.terminate()
    backend.wait()

    backend_b = subprocess.Popen([".venv/bin/python", "-m", "uvicorn", "jarvis.server:app", "--port", "8000"])
    time.sleep(3)

    health_b = get_health()
    build_id_b = health_b.get("build_id")
    print(f"Backend B Build ID: {build_id_b}")

    write_ev(
        "E-BUILD-003.txt",
        f"EVIDENCE ID: E-BUILD-003\nCLAIM: New backend reports B\nEXPECTED: {new_tree}\nACTUAL: {build_id_b}\nJSON: {health_b}",
    )

    backend_b.terminate()
    backend_b.wait()

    # Revert the temporary commit
    subprocess.run(["git", "reset", "--hard", "HEAD~1"])


if __name__ == "__main__":
    run_phase1()
