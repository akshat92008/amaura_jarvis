import requests
import sys

payload = {
    "message": "open Safari",
    "session_id": "qual_phase2",
    "workspace": "",
    "autonomy": "execute_until_approval",
    "coding_backend": "antigravity"
}
headers = {
    "X-Amaura-Operator-Key": "test_qual_key"
}
try:
    resp = requests.post("http://127.0.0.1:8000/api/chat", json=payload, headers=headers, timeout=30)
    print(resp.status_code)
    print(resp.text)
except Exception as e:
    print(e)
