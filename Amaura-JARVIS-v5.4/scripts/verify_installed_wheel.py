#!/usr/bin/env python3
"""Verify a built Amaura wheel through an actual package installer.

The release builder also performs structural smoke checks. This qualification
step intentionally installs the wheel into an empty target directory first so
invalid wheel metadata/RECORD/install semantics cannot pass merely because a
wheel is a readable ZIP archive.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _install_wheel(wheel: Path, target: Path) -> None:
    uv = shutil.which("uv")
    if uv:
        command = [uv, "pip", "install", "--target", str(target), "--no-deps", "--reinstall", str(wheel)]
    else:
        command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--target",
            str(target),
            "--no-deps",
            "--force-reinstall",
            str(wheel),
        ]
    subprocess.run(command, check=True, timeout=120, capture_output=True, text=True)


def verify(wheel: Path) -> dict[str, object]:
    wheel = wheel.expanduser().resolve()
    if not wheel.is_file() or wheel.suffix != ".whl":
        raise FileNotFoundError(f"Wheel does not exist: {wheel}")

    with tempfile.TemporaryDirectory(prefix="amaura-installed-wheel-") as tmp:
        target = Path(tmp) / "site"
        target.mkdir(parents=True)
        _install_wheel(wheel, target)

        code = r'''
import importlib.metadata as metadata
import json
from pathlib import Path
import jarvis
from jarvis.server import STATIC_DIR
from jarvis.amaura.prompts import load_prompt_catalogue

target = Path(__import__("os").environ["AMAURA_WHEEL_TARGET"]).resolve()
module_path = Path(jarvis.__file__).resolve()
if target not in module_path.parents:
    raise AssertionError(f"jarvis imported outside installed target: {module_path}")

dist = metadata.distribution("jarvis")
dist_root = Path(dist.locate_file("")).resolve()
if target != dist_root and target not in dist_root.parents and dist_root not in target.parents:
    raise AssertionError(f"distribution metadata outside installed target: {dist_root}")

version = metadata.version("jarvis")
if jarvis.__version__ != version:
    raise AssertionError(f"package version mismatch: module={jarvis.__version__!r} metadata={version!r}")

entry_points = {ep.name for ep in dist.entry_points if ep.group == "console_scripts"}
required = {"jarvis", "nexus", "amaura", "amaura-worker"}
missing = sorted(required - entry_points)
if missing:
    raise AssertionError(f"missing console entry points: {missing}")

for name in ("index.html", "app.js", "styles.css"):
    if not (Path(STATIC_DIR) / name).is_file():
        raise AssertionError(f"missing packaged static asset: {name}")
profiles = load_prompt_catalogue()
if len(profiles) < 57:
    raise AssertionError(f"prompt catalogue incomplete: {len(profiles)}")

print(json.dumps({
    "version": version,
    "module_path": str(module_path),
    "entry_points": sorted(entry_points),
    "profiles": len(profiles),
}))
'''
        env = dict(os.environ)
        env["PYTHONPATH"] = str(target)
        env["PYTHONNOUSERSITE"] = "1"
        env["AMAURA_WHEEL_TARGET"] = str(target)
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=tmp,
            env=env,
            check=True,
            timeout=60,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout.strip().splitlines()[-1])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.wheel), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
