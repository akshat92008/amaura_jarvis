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


def send_chat_stream_request(text):
    payload = {
        "message": text,
        "session_id": "qual_phase8",
        "workspace": "",
        "autonomy": "execute_until_approval",
        "coding_backend": "antigravity",
    }
    headers = {"X-Amaura-Operator-Key": "test_qual_key", "X-Jarvis-Key": "test_jarvis_key"}
    print(f"\n[JARVIS Stream Request] {text}")

    start_time = time.time()

    with requests.post(
        "http://127.0.0.1:8000/api/chat/stream", json=payload, headers=headers, timeout=30, stream=True
    ) as resp:
        resp.raise_for_status()

        chunks = []
        for line in resp.iter_lines():
            if line:
                chunk_time = time.time()
                data = json.loads(line)
                chunks.append({"timestamp": chunk_time - start_time, "data": data})

                if data.get("type") == "token":
                    print(data.get("content", ""), end="", flush=True)
                elif data.get("type") == "metadata":
                    print(f"\n[Metadata] {data}")
        print()
    return chunks


def main():
    print("=== Phase 8: True Streaming Proof ===")

    evidence_file = EVIDENCE_DIR / "E-STRM-001_true_streaming.json"

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

        chunks = send_chat_stream_request("Count from 1 to 5 slowly.")

        # Verify streaming (we got multiple token chunks)
        token_chunks = [c for c in chunks if c["data"].get("type") == "token"]

        success = len(token_chunks) > 5

        print(f"\nReceived {len(token_chunks)} token chunks.")
        print(f"Test Passed: {success}")

        evidence = {
            "test": "True Streaming Proof",
            "request": "Count from 1 to 5 slowly.",
            "chunks": chunks,
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
