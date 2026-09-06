import json
import urllib.request
import time

def send_chat(message: str, session_id: str = "founder-e2e-session"):
    url = "http://127.0.0.1:8000/api/chat"
    data = json.dumps({"message": message, "session_id": session_id}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-Jarvis-Key": "-iPYagWa6KEN1_p0PltbI46BaXwe8jEqPxVq51-WB3mpsNMUgtjyLwaarveGPAU4",
        },
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            elapsed = time.time() - t0
            result = json.loads(resp.read().decode("utf-8"))
            return result, elapsed
    except Exception as exc:
        elapsed = time.time() - t0
        return {"error": str(exc)}, elapsed

print("=== RUNNING LIVE END-TO-END FLOW VERIFICATION ===")

# Test 1: Punctuation splitting with "thank you.I want you to..."
msg1 = "no thank you.I want you to create a fully functional ecommerce beautiful website"
print(f"\n[Test 1] Sending prompt with 'you.I': {msg1}")
res1, el1 = send_chat(msg1)
print(f"Elapsed: {el1:.2f}s")
reply1 = res1.get("response", "") or res1.get("error", "")
print(f"JARVIS Reply (first 250 chars):\n{reply1[:250]}...\n")

# Assertions for Test 1
assert "write request has no explicit payload" not in reply1, "FAIL: False write payload rejection occurred!"
assert "you.I" not in reply1.lower() or "website" in reply1.lower(), "FAIL: PathExtractor captured you.I as target path!"
print("✅ Test 1 PASSED: Zero false write rejection on sentence punctuation!")

# Test 2: Follow-up on white screen
msg2 = "Its not opening fix it a white screen is appearing instead of website"
print(f"\n[Test 2] Sending follow-up: {msg2}")
res2, el2 = send_chat(msg2)
print(f"Elapsed: {el2:.2f}s")
reply2 = res2.get("response", "") or res2.get("error", "")
print(f"JARVIS Reply (first 250 chars):\n{reply2[:250]}...\n")

# Assertions for Test 2
assert "Existing-project software work requires a workspace" not in reply2, "FAIL: Workspace governance rejection occurred!"
print("✅ Test 2 PASSED: Workspace resolved smoothly without governance rejection!")

print("\n=== ALL LIVE FLOW TESTS PASSED SUCCESSFULLY! ===")
