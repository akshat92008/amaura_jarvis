"""Unified ARCH runtime entrypoint.

ARCH is the single founder-facing process. It owns the interactive executive,
web HUD, mission runner, proactive cognition, and company autopilot while
preserving the existing governed authority boundaries.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from jarvis.amaura.runtime import load_amaura_env
from jarvis.models import DEFAULT_MODEL


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

    # ARCH owns these loops. Generic JARVIS/server compatibility surfaces keep
    # them off by default; the ARCH process explicitly turns them on.
    os.environ["AMAURA_JARVIS_PROACTIVE"] = "1"
    os.environ["AMAURA_JARVIS_MISSION_RUNNER"] = "1"
    os.environ["AMAURA_COMPANY_AUTOPILOT_RUNTIME"] = "1"

    # The supported target is an 8 GB MacBook. Heavy local work stays
    # serialized and the process must degrade under pressure instead of
    # allowing an old config to fan out workers.
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


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="arch", description="ARCH — unified autonomous executive runtime")
    parser.add_argument("prompt", nargs="?", help="Optional one-shot request; omit for interactive ARCH")
    parser.add_argument("--env-file", default=os.environ.get("AMAURA_ENV_FILE", ""))
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL)
    parser.add_argument("--api-key", "-k")
    parser.add_argument("--working-dir", "-d", default="")
    parser.add_argument("--voice", "-v", action="store_true")
    parser.add_argument("--no-web", action="store_true")
    return parser.parse_args(argv)


def _load_runtime_environment(path: str) -> Path | None:
    explicit = Path(path).expanduser() if path else None
    loaded = load_amaura_env(explicit, require_private_permissions=True)
    if loaded is not None:
        os.environ["AMAURA_ENV_FILE"] = str(loaded)
    configure_arch_runtime()
    return loaded


def _authenticate_founder_session(agent) -> None:
    """Attach the configured operator authority to this local ARCH process."""
    operator_key = os.environ.get("AMAURA_OPERATOR_KEY", "").strip()
    if not operator_key:
        raise RuntimeError("ARCH requires AMAURA_OPERATOR_KEY in its private environment")
    agent.set_amaura_session_token(operator_key)


def main(argv: list[str] | None = None) -> None:
    """Start one authenticated ARCH process and all of its internal runtimes."""
    args = _parse_args(argv)
    _load_runtime_environment(args.env_file)

    from jarvis import ui
    from jarvis.agent import JarvisAgent
    from jarvis.cli import launch_background_web, run_interactive
    from jarvis.tools.amaura import get_control_plane
    from jarvis.voice.engine import VoiceEngine

    working_dir = str(Path(args.working_dir or os.getcwd()).resolve())
    agent = JarvisAgent(api_key=args.api_key, model_key=args.model, working_dir=working_dir)
    _authenticate_founder_session(agent)

    voice_engine = VoiceEngine()
    if args.voice:
        if voice_engine.available:
            voice_engine.enable()
            agent.voice_mode = True
        else:
            ui.print_warning("Voice dependencies are not available; continuing with text input")

    if not args.no_web:
        web_url = launch_background_web(open_browser_flag=True)
        ui.print_success(f"ARCH HUD live at {web_url}")

    if args.prompt:
        control = get_control_plane()
        result = agent.run_executive(
            args.prompt,
            control=control,
            session_id=f"arch-{agent.conversation_id}",
            workspace=working_dir,
            autonomy="execute_until_approval",
            coding_backend="antigravity",
        )
        message = str(result.get("message") or "").strip()
        if message:
            ui.console.print(message)
        return

    if voice_engine.enabled:
        ui.print_success("ARCH voice mode active")
        voice_engine.greet()

    run_interactive(agent, voice_engine, working_dir=working_dir)


if __name__ == "__main__":
    main()
