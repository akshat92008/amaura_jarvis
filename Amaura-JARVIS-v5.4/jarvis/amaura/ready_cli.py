"""Founder-facing one-command certification and launch for Amaura JARVIS."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = REPOSITORY_ROOT / ".env.amaura"


def _emit(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def _build_jarvis_argv(args: argparse.Namespace) -> list[str]:
    argv = [sys.executable, "-m", "jarvis.runtime_entry"]
    argv.append("--web" if args.web else "--no-web")
    if args.voice:
        argv.append("--voice")
    if args.telegram:
        argv.append("--telegram")
    if args.model:
        argv.extend(["--model", args.model])
    if args.working_dir:
        argv.extend(["--working-dir", str(Path(args.working_dir).expanduser().resolve())])
    if args.prompt:
        argv.append(args.prompt)
    return argv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jarvis-ready",
        description="Certify the exact local Amaura JARVIS checkout and launch it only when production-ready.",
    )
    parser.add_argument("prompt", nargs="?", help="Optional single prompt to run after certification")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="Private Amaura environment file")
    parser.add_argument("--check-only", action="store_true", help="Certify readiness without launching JARVIS")
    parser.add_argument("--web", action="store_true", help="Launch the JARVIS web interface instead of CLI-only mode")
    parser.add_argument("--voice", action="store_true", help="Enable voice mode")
    parser.add_argument("--telegram", action="store_true", help="Start Telegram mode")
    parser.add_argument("--model", default="", help="Override the configured interactive model")
    parser.add_argument("--working-dir", default="", help="Founder working directory for the session")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env_path = Path(args.env_file).expanduser().resolve()
    if not env_path.is_file():
        _emit(
            {
                "ready": False,
                "verdict": "NOT_READY_FOR_DAILY_USE",
                "error": "amaura_environment_missing",
                "env_file": str(env_path),
                "next": "Run: amaura init --build-sandbox",
            }
        )
        return 2

    try:
        from jarvis.amaura.runtime import load_amaura_env

        loaded = load_amaura_env(env_path, override=True, require_private_permissions=True)
        if loaded is None:
            raise RuntimeError(f"Could not load Amaura environment: {env_path}")

        from jarvis.amaura.local_certification import certify_local_runtime

        report = certify_local_runtime(REPOSITORY_ROOT)
    except Exception as exc:
        _emit(
            {
                "ready": False,
                "verdict": "NOT_READY_FOR_DAILY_USE",
                "error": type(exc).__name__,
                "message": str(exc),
            }
        )
        return 1

    _emit(report)
    if report.get("ready") is not True:
        return 1
    if args.check_only:
        return 0

    jarvis_argv = _build_jarvis_argv(args)
    os.execv(sys.executable, jarvis_argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
