import os
import json
import subprocess
import time
import hashlib
from datetime import datetime

RUN_ID = "20260812_193925"
EVIDENCE_DIR = os.path.join(os.getcwd(), f"qualification_evidence/{RUN_ID}")

def run_cmd(cmd, cwd=None):
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
        return res.stdout.strip(), res.stderr.strip(), res.returncode
    except Exception as e:
        return "", str(e), -1

def write_evidence(name, content):
    path = os.path.join(EVIDENCE_DIR, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return path

def hash_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def phase_0():
    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    
    # 1. Gather baseline commands
    commands = {
        "git_status.txt": "git status",
        "git_diff.txt": "git diff",
        "git_rev_parse_HEAD.txt": "git rev-parse HEAD",
        "git_rev_parse_tree.txt": "git rev-parse HEAD^{tree}",
        "git_ls_files.txt": "git ls-files",
        "python_version.txt": "python --version",
        "agy_version.txt": "agy --version",
        "sw_vers.txt": "sw_vers",
        "uname.txt": "uname -a",
        "ps_backend.txt": "ps aux | grep -i jarvis | grep -v grep",
        "lsof_port.txt": "lsof -i -P -n | grep LISTEN"
    }
    
    evidence_manifest = {}
    
    for filename, cmd in commands.items():
        out, err, code = run_cmd(cmd)
        content = f"COMMAND: {cmd}\nEXIT_CODE: {code}\n\nSTDOUT:\n{out}\n\nSTDERR:\n{err}\n"
        path = write_evidence(f"phase_0/{filename}", content)
        evidence_manifest[filename] = {"cmd": cmd, "code": code, "stdout": out}
    
    # Analyze Backend PIDs
    ps_out = evidence_manifest["ps_backend.txt"]["stdout"]
    lines = ps_out.split('\n')
    backend_pids = []
    for line in lines:
        if "jarvis" in line.lower() and not line.isspace() and "qual_harness" not in line:
            parts = line.split()
            if len(parts) > 1:
                backend_pids.append(parts[1])
    
    # Create manifest.json
    manifest = {
        "run_id": RUN_ID,
        "start_time": datetime.utcnow().isoformat() + "Z",
        "machine": "MacBook Air M3, 8 GB RAM",
        "macOS version": evidence_manifest["sw_vers.txt"]["stdout"].replace('\n', ' '),
        "Python version": evidence_manifest["python_version.txt"]["stdout"],
        "Amaura version": "5.4.1",
        "Git commit": evidence_manifest["git_rev_parse_HEAD.txt"]["stdout"],
        "Git tree hash": evidence_manifest["git_rev_parse_tree.txt"]["stdout"],
        "initial git status": evidence_manifest["git_status.txt"]["stdout"],
        "backend PIDs": backend_pids,
        "backend count": len(backend_pids),
        "backend start time": "N/A - extract manually or from ps",
        "backend build ID": "N/A - fixing in Phase 1",
        "agy version": evidence_manifest["agy_version.txt"]["stdout"]
    }
    
    write_evidence("manifest.json", json.dumps(manifest, indent=2))
    
    # Generate E-BASE-001
    ebase_content = f"EVIDENCE ID: E-BASE-001\n"
    ebase_content += f"CLAIM: Baseline state frozen and backend evaluated.\n"
    ebase_content += f"BACKEND COUNT: {len(backend_pids)}\n"
    ebase_content += f"PIDS: {', '.join(backend_pids)}\n"
    write_evidence("phase_0/E-BASE-001.txt", ebase_content)

    print(f"Phase 0 completed. Found {len(backend_pids)} backends.")
    print("PIDs:", backend_pids)

if __name__ == "__main__":
    phase_0()
