"""Unified ARCH runtime entrypoint.

ARCH is the single founder-facing process. It owns the interactive executive,
web HUD, mission runner, proactive cognition, and company autopilot while
preserving the existing governed authority boundaries.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from jarvis.amaura.runtime import load_amaura_env


def _positive_int(raw: str, default: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, value)


def _cap_int_env(name: str, *, default: int, maximum: int) -> None:
    current = _positive_int(os.environ.get(name, str(default)), default)
    os.environ[name] = str(min(current, maximum))


def configure_arch_runtime() -> None:
    """Enable the canonical unified runtime with conservative 8 GB defaults."""
    os.environ["ARCH_RUNTIME"] = "1"

    # ARCH owns these loops. The generic server keeps them off by default so it
    # can still be used as a control surface in compatibility deployments.
    os.environ["AMAURA_JARVIS_PROACTIVE"] = "1"
    os.environ["AMAURA_JARVIS_MISSION_RUNNER"] = "1"
    os.environ["AMAURA_COMPANY_AUTOPILOT_RUNTIME"] = "1"

    # The supported target is an 8 GB MacBook. Keep heavyweight execution
    # serialized and bound the local resource envelope even if an older env
    # file contains more aggressive defaults.
    os.environ.setdefault("AMAURA_RESOURCE_PROFILE", "macbook-8gb")
    _cap_int_env("AMAURA_COMPANY_AUTOPILOT_WORK_UNITS", default=1, maximum=1)
    _cap_int_env("AMAURA_AUTOPILOT_MAX_WORK_UNITS", default=1, maximum=1)
    _cap_int_env("AMAURA_RAM_NORMAL_TARGET_MB", default=768, maximum=768)
    _cap_int_env("AMAURA_RAM_BURST_LIMIT_MB", default=1536, maximum=1536)
    _cap_int_env("AMAURA_RAM_ABSOLUTE_LIMIT_MB", default=2048, maximum=2048)
    _cap_int_env("AMAURA_RAM_PRESSURE_LIMIT_MB", default=768, maximum=768)
    _cap_int_env("AMAURA_ANTIGRAVITY_RESERVATION_MB", default=768, maximum=768)
    _cap_int_env("AMAURA_ANTIGRAVITY_MAX_RSS_MB", default=1536, maximum=1536)
    _cap_int_env("AMAURA_SWAP_GROWTH_ABORT_MB", default=192, maximum=192)


def _parse_arch_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        prog="arch",
        description="ARCH — unified autonomous executive runtime",
        add_help=False,
    )
    parser.add_argument("--env-file", default=os.environ.get("AMAURA_ENV_FILE", ""))
    args, remaining = parser.parse_known_args(argv)
    return args, remaining


def main(argv: list[str] | None = None) -> None:
    """Load one trusted environment, configure ARCH, then start JARVIS once."""
    original_argv = list(sys.argv)
    raw_args = list(sys.argv[1:] if argv is None else argv)
    args, remaining = _parse_arch_args(raw_args)

    explicit_env = Path(args.env_file).expanduser() if args.env_file else None
    if explicit_env is not None:
        loaded = load_amaura_env(explicit_env, require_private_permissions=True)
    else:
        loaded = load_amaura_env(require_private_permissions=True)

    if loaded is not None:
        os.environ["AMAURA_ENV_FILE"] = str(loaded)

    configure_arch_runtime()

    # Reuse the already-qualified natural-language front door rather than
    # creating a second assistant implementation.
    from jarvis.cli import main as jarvis_main

    try:
        sys.argv = [original_argv[0], *remaining]
        jarvis_main()
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    main()
