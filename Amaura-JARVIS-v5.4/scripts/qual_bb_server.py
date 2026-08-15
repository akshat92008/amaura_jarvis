#!/usr/bin/env python3
"""
Phase 3 — JARVIS Server lifecycle helper.
Starts server, waits for /api/health, returns the process + API key.
"""
import os, sys, subprocess, time, json, signal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from jarvis.amaura.runtime import load_amaura_env
load_amaura_env()

JARVIS_HOST = os.environ.get("JARVIS_HOST", "127.0.0.1")
JARVIS_PORT = int(os.environ.get("JARVIS_PORT", "8000"))
BASE_URL = f"http://{JARVIS_HOST}:{JARVIS_PORT}"

def get_api_key():
    """Read API key from .amaura-data or env."""
    # Try env first
    k = os.environ.get("JARVIS_API_KEY", "")
    if k:
        return k
    # Try .amaura-data
    data_dir = Path(__file__).parent.parent / ".amaura-data"
    for fname in ["api_key.txt", "authority.json", "jarvis_api_key.txt"]:
        p = data_dir / fname
        if p.exists():
            content = p.read_text().strip()
            try:
                return json.loads(content).get("api_key", content)
            except Exception:
                return content
    return ""

def is_server_up():
    try:
        import httpx
        r = httpx.get(f"{BASE_URL}/api/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False

def start_server(env_dir: Path, timeout: int = 30):
    """Start JARVIS server process, return (proc, api_key, base_url)."""
    if is_server_up():
        print(f"  Server already up at {BASE_URL}")
        return None, get_api_key(), BASE_URL

    venv_python = env_dir / ".venv" / "bin" / "python"
    cmd = [str(venv_python), "-m", "jarvis.server"]
    env = os.environ.copy()
    
    proc = subprocess.Popen(
        cmd,
        cwd=str(env_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_server_up():
            print(f"  Server started (pid={proc.pid}) at {BASE_URL}")
            return proc, get_api_key(), BASE_URL
        if proc.poll() is not None:
            out = proc.stdout.read() if proc.stdout else ""
            err = proc.stderr.read() if proc.stderr else ""
            print(f"  Server exited early: stdout={out[:500]} stderr={err[:500]}")
            return None, "", ""
        time.sleep(0.5)
    
    proc.terminate()
    print(f"  Server did not start within {timeout}s")
    return None, "", ""

def stop_server(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        print(f"  Server stopped (pid={proc.pid})")

if __name__ == "__main__":
    project_dir = Path(__file__).parent.parent
    proc, api_key, base_url = start_server(project_dir)
    if proc or is_server_up():
        print(f"SERVER_OK base_url={base_url} api_key_len={len(api_key)}")
    else:
        print("SERVER_FAIL")
    if proc:
        stop_server(proc)
