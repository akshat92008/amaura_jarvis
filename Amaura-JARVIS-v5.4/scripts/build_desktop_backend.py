#!/usr/bin/env python3
"""Build the signed-app backend sidecar consumed by Electron.

The output is a self-contained executable at desktop-app/runtime/amaura-backend.
Electron never relies on a system Python installation in packaged mode.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "desktop-app" / "runtime"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    work = ROOT / "build" / "desktop-backend"
    dist = ROOT / "build" / "desktop-backend-dist"
    for path in (work, dist, output):
        if path.exists():
            shutil.rmtree(path)
    output.mkdir(parents=True, exist_ok=True)

    env = {**os.environ, "PYTHONHASHSEED": "0", "SOURCE_DATE_EPOCH": "1767225600"}
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "amaura-backend",
        "--distpath",
        str(dist),
        "--workpath",
        str(work),
        "--specpath",
        str(work),
        "--collect-submodules",
        "jarvis",
        "--collect-data",
        "jarvis",
        str(ROOT / "jarvis" / "server.py"),
    ]
    subprocess.run(command, cwd=ROOT, env=env, check=True)
    executable = dist / ("amaura-backend.exe" if os.name == "nt" else "amaura-backend")
    if not executable.is_file():
        raise RuntimeError(f"PyInstaller did not produce {executable}")
    target = output / executable.name
    shutil.copy2(executable, target)
    target.chmod(0o755)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
