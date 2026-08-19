"""Unified ARCH runtime entrypoint.

ARCH is the single founder-facing process. It owns the interactive executive,
web HUD, mission runner, proactive cognition, company autopilot, and configured
remote surfaces while preserving the existing governed authority boundaries.
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import threading
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
    os.environ["AMAURA_JARVIS_PROACTIVE"] = "1"
    os.environ["AMAURA_JARVIS_MISSION_RUNNER"] = "1"
    os.environ["AMAURA_COMPANY_AUTOPILOT_RUNTIME"] = "1"

    os.environ.setdefault("AMAURA_RESOURCE_PROFILE", "macbook-8gb")
    os.environ.setdefault("AMAURA_ARCH_HOSTED_COGNITION_FAILOVER", "1")
    os.environ.setdefault("AMAURA_ARCH_HOSTED_FALLBACK_TIMEOUT_SECONDS", "6")
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
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run the one persistent ARCH runtime without an interactive terminal session.",
    )
    parser.add_argument(
        "--no-web",
        action="store_true",
        help="Do not open the browser HUD; ARCH still runs its internal local server and background loops.",
    )
    args = parser.parse_args(argv)
    if args.headless and args.prompt:
        parser.error("--headless cannot be combined with a one-shot prompt")
    if args.headless and args.voice:
        parser.error("--headless cannot enable local interactive voice mode")
    return args


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


def _assert_arch_port_available() -> None:
    """Refuse to silently attach ARCH to an unrelated/legacy server process."""
    host = os.environ.get("JARVIS_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.environ.get("JARVIS_PORT", "8000"))
    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    try:
        with socket.create_connection((probe_host, port), timeout=0.25):
            raise RuntimeError(
                f"ARCH cannot start because {probe_host}:{port} is already in use. "
                "Stop the old JARVIS/ARCH process instead of running split runtimes."
            )
    except ConnectionRefusedError:
        return
    except TimeoutError:
        return
    except OSError:
        return


def _run_headless_forever() -> None:
    """Keep the canonical ARCH owner process alive until launchd/user shutdown."""
    stop_event = threading.Event()

    def request_stop(_signum, _frame) -> None:
        stop_event.set()

    previous_handlers: dict[int, object] = {}
    for signum in (signal.SIGTERM, signal.SIGINT):
        previous_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, request_stop)
    try:
        while not stop_event.wait(1.0):
            pass
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def main(argv: list[str] | None = None) -> None:
    """Start one authenticated ARCH process and all of its internal runtimes."""
    args = _parse_args(argv)
    _load_runtime_environment(args.env_file)

    from jarvis import ui
    from jarvis.agent import JarvisAgent
    from jarvis.arch_gateway import install_arch_gateway
    from jarvis.arch_grounding import install_arch_grounding
    from jarvis.arch_provider_resilience import install_arch_provider_resilience
    from jarvis.arch_telegram import start_arch_telegram
    from jarvis.cli import launch_background_web, run_interactive
    from jarvis.tools.amaura import get_control_plane
    from jarvis.voice.engine import VoiceEngine

    install_arch_gateway()
    install_arch_grounding()
    install_arch_provider_resilience()
    _assert_arch_port_available()

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

    open_browser = not args.no_web and not args.headless
    web_url = launch_background_web(open_browser_flag=open_browser)
    if open_browser:
        ui.print_success(f"ARCH HUD live at {web_url}")
    else:
        ui.print_success(f"ARCH runtime live at {web_url} (browser HUD not opened)")

    telegram_thread = start_arch_telegram(agent)
    if telegram_thread is not None:
        ui.print_success("ARCH Telegram surface active")

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

    if args.headless:
        ui.print_success("ARCH persistent runtime active")
        _run_headless_forever()
        return

    if voice_engine.enabled:
        ui.print_success("ARCH voice mode active")
        voice_engine.greet()

    run_interactive(agent, voice_engine, working_dir=working_dir)


if __name__ == "__main__":
    main()
