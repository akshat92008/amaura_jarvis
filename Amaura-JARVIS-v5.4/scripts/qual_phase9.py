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

def send_memory_update(payload):
    headers = {
        "X-Amaura-Operator-Key": "test_qual_key",
        "X-Jarvis-Key": "test_jarvis_key"
    }
    resp = requests.post("http://127.0.0.1:8000/api/memory", json=payload, headers=headers, timeout=10)
    data = resp.json()
    return data

def get_memory():
    headers = {
        "X-Jarvis-Key": "test_jarvis_key"
    }
    resp = requests.get("http://127.0.0.1:8000/api/memory", headers=headers, timeout=10)
    data = resp.json()
    return data

def main():
    print("=== Phase 9: Memory Operations ===")
    
    evidence_file = EVIDENCE_DIR / "E-MEM-001_memory_operations.json"
    
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
        
        # Test 1: Add fact
        unique_fact = f"My favorite color is qualification_blue_{int(time.time())}"
        res1 = send_memory_update({"fact": unique_fact})
        print(f"Fact added: {res1.get('status') == 'added'}")
        
        # Test 2: Add key/value
        unique_key = f"qual_test_key_{int(time.time())}"
        unique_val = "qual_test_val"
        res2 = send_memory_update({"key": unique_key, "value": unique_val})
        print(f"KV added: {res2.get('status') == 'updated'}")
        
        # Test 3: Get memory and verify deduplication/isolation
        mem_data = get_memory()
        facts = mem_data.get("facts", [])
        
        fact_found = False
        kv_found = False
        for f in facts:
            if isinstance(f, dict):
                content = f.get("content", "")
                if unique_fact in content or content == unique_fact:
                    fact_found = True
                if unique_val in content or content == unique_val:
                    kv_found = True
            elif isinstance(f, str):
                if unique_fact in f or f == unique_fact:
                    fact_found = True
                if unique_val in f or f == unique_val:
                    kv_found = True
                
        # Also check items
        for item in mem_data.get("items", []):
            val = item.get("value", {})
            if isinstance(val, dict):
                if item.get("key") == unique_key and val.get("content") == unique_val:
                    kv_found = True
            elif isinstance(val, str):
                if item.get("key") == unique_key and val == unique_val:
                    kv_found = True
        
        print(f"Fact found in get_memory: {fact_found}")
        print(f"KV found in get_memory: {kv_found}")
        
        success = fact_found and kv_found
        
        print(f"\nTest Passed: {success}")
        
        evidence = {
            "test": "Memory Operations",
            "fact_request": {"fact": unique_fact},
            "kv_request": {"key": unique_key, "value": unique_val},
            "fact_response": res1,
            "kv_response": res2,
            "memory_state": mem_data,
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
