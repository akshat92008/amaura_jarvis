#!/usr/bin/env python3
"""Install/check Amaura's optional OSS capability groups.

Nothing here runs automatically at Amaura startup. The script is an explicit
founder/operator action so an 8 GB machine never downloads or starts heavy
stacks unexpectedly.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GROUPS = {
    "browser": ["playwright>=1.50.0", "crawl4ai>=0.6.0", "browser-use>=0.4.0"],
    "documents": ["docling>=2.0.0", "PyMuPDF>=1.24.0", "paddleocr>=3.0.0"],
    "memory": ["llama-index-core>=0.12.0", "qdrant-client[fastembed]>=1.12.0"],
    "media": ["faster-whisper>=1.1.0", "kokoro>=0.9.4", "soundfile>=0.12.1", "yt-dlp[default]>=2025.1.0"],
    "observability": ["langfuse>=4.0.0", "mcp>=1.0.0"],
}

BREW_PACKAGES = {
    "media-system": ["ffmpeg", "imagemagick", "vips", "espeak-ng", "node"],
}


def run(argv: list[str]) -> None:
    print("+", " ".join(argv))
    subprocess.run(argv, check=True, cwd=ROOT)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("groups", nargs="*", choices=sorted([*GROUPS, *BREW_PACKAGES, "all"]))
    parser.add_argument("--check", action="store_true", help="Only print current capability health")
    parser.add_argument("--deep-check", action="store_true", help="Run explicit non-destructive execution smoke probes")
    parser.add_argument("--skip-browser-binary", action="store_true")
    args = parser.parse_args()

    if args.check or args.deep_check:
        from jarvis.amaura.capability_runtime import CapabilityRuntime
        for row in CapabilityRuntime().inventory(deep=bool(args.deep_check)):
            state = "READY" if row["execution_ready"] else "CONF" if row["configured"] else "MISS"
            print(f"{row['key']:<20} {state:<5} installed={row['installed']} configured={row['configured']} ready={row['execution_ready']} {row['reason']}")
        return 0

    groups = args.groups or ["browser", "memory", "media", "observability"]
    if "all" in groups:
        groups = [*GROUPS, *BREW_PACKAGES]

    for group in groups:
        if group in GROUPS:
            run([sys.executable, "-m", "pip", "install", *GROUPS[group]])
        elif group in BREW_PACKAGES:
            if sys.platform != "darwin":
                print(f"Skipping Homebrew group '{group}' outside macOS")
                continue
            brew = shutil.which("brew")
            if not brew:
                raise SystemExit("Homebrew is required for system media packages: https://brew.sh")
            run([brew, "install", *BREW_PACKAGES[group]])

    if "browser" in groups and not args.skip_browser_binary:
        run([sys.executable, "-m", "playwright", "install", "chromium"])

    # Crawl4AI has its own optional post-install setup. Do not fail the whole
    # install if an older/newer release does not expose this command.
    if "browser" in groups:
        command = shutil.which("crawl4ai-setup")
        if command:
            try:
                run([command])
            except subprocess.CalledProcessError:
                print("crawl4ai-setup failed; the core adapter remains installed and will report health explicitly")

    if sys.platform == "darwin" and os.uname().machine == "arm64" and "documents" in groups:
        print("NOTE: PaddleOCR/Paddle inference support varies by release on Apple Silicon. Amaura will fall back to Docling/PyMuPDF if PaddleOCR is unavailable.")

    from jarvis.amaura.capability_runtime import CapabilityRuntime
    print("\nCapability health:")
    for row in CapabilityRuntime().inventory():
        state = "READY" if row["execution_ready"] else "CONF" if row["configured"] else "MISS"
        print(f"{row['key']:<20} {state:<5} {row['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
