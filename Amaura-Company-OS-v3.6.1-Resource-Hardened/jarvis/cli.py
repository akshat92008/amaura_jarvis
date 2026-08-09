#!/usr/bin/env python3
"""
J.A.R.V.I.S. — Interactive CLI

Usage:
    jarvis                          Start interactive mode
    jarvis --model kimi             Start with a specific model
    jarvis "build a flask app"      Run a single prompt and exit
    jarvis --voice                  Start in voice mode
    jarvis --telegram               Start the Telegram bot
    jarvis --list-models            Show all available models
"""

from __future__ import annotations

import argparse
import os
import sys

from jarvis.models import resolve_model, DEFAULT_MODEL, list_models
from jarvis import ui


def parse_args():
    parser = argparse.ArgumentParser(
        prog="jarvis",
        description="J.A.R.V.I.S. — Just A Rather Very Intelligent System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  jarvis                              Interactive mode (default model)
  jarvis --model kimi-k3              Use Kimi K3
  jarvis --voice                      Start in voice mode
  jarvis "create a REST API"          Single prompt mode
  jarvis --list-models                List all available models
  jarvis --telegram                   Start Telegram bot

Environment:
  NVIDIA_API_KEY                      Your NVIDIA API key (from build.nvidia.com)
  TELEGRAM_BOT_TOKEN                  Telegram bot token (from @BotFather)
  TELEGRAM_USER_ID                    Your Telegram user ID (for security)
        """,
    )
    parser.add_argument("prompt", nargs="?", help="Single prompt to run")
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL, help=f"Model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--api-key", "-k", help="NVIDIA API key")
    parser.add_argument("--working-dir", "-d", help="Working directory")
    parser.add_argument("--voice", "-v", action="store_true", help="Enable voice mode")
    parser.add_argument("--web", "-w", action="store_true", help="Launch JARVIS Web Interface (HUD)")
    parser.add_argument("--no-web", action="store_true", help="Disable automatic launch of JARVIS Web Interface")
    parser.add_argument("--telegram", "-t", action="store_true", help="Start Telegram bot")
    parser.add_argument("--amaura", action="store_true", help="Start the Amaura Autonomous Workforce Daemon")
    parser.add_argument("--fable", "-f", action="store_true", help="Execute Claude Fable 5 Mythos CoT reasoning planning engine")
    parser.add_argument("--list-models", action="store_true", help="List available models")
    return parser.parse_args()


def handle_slash_command(cmd: str, agent: JarvisAgent, voice_engine: VoiceEngine) -> bool:
    """Handle slash commands. Returns True if handled."""
    parts = cmd.strip().split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if command in ("/exit", "/quit", "/q"):
        ui.print_goodbye()
        sys.exit(0)

    elif command == "/help":
        ui.print_help()
        return True

    elif command == "/fable":
        if not arg:
            ui.print_info("Usage: /fable <task request>")
            return True
        agent.run_fable_reasoning(arg)
        return True

    elif command == "/voice":
        new_state = voice_engine.toggle()
        agent.voice_mode = new_state
        if new_state:
            ui.print_success("Voice mode enabled. I'm listening, sir.")
            voice_engine.speak("Voice mode activated. I'm listening, sir.")
        else:
            ui.print_info("Voice mode disabled. Text input only.")
        return True

    elif command == "/models":
        models = list_models()
        ui.print_models(models, agent.model_key)
        return True

    elif command == "/model":
        if not arg:
            ui.print_info(f"Current model: {agent.model_cfg['name']} ({agent.model_key})")
            return True
        if agent.set_model(arg):
            ui.print_success(f"Switched to {agent.model_cfg['name']}")
        else:
            ui.print_error(f"Unknown model: {arg}. Use /models to see options.")
        return True

    elif command == "/clear":
        agent.clear_history()
        ui.print_success("Conversation cleared. Fresh start, sir.")
        return True

    elif command == "/compact":
        removed = agent.compact_conversation()
        ui.print_success(f"Compacted conversation. Removed {removed} messages.")
        return True

    elif command == "/memory":
        summary = agent.user_mem.get_summary()
        ui.console.print(summary)
        return True

    elif command == "/remember":
        if arg:
            agent.user_mem.add_fact(arg)
            ui.print_success(f"Noted and remembered: \"{arg}\"")
        else:
            ui.print_info("Usage: /remember <fact about you>")
        return True

    elif command == "/forget":
        agent.user_mem.reset()
        ui.print_success("Personal memory cleared.")
        return True

    elif command == "/history":
        from jarvis.memory import ConversationMemory

        mem = ConversationMemory()
        convs = mem.list_conversations(limit=10)
        if not convs:
            ui.print_info("No conversation history yet.")
        else:
            for c in convs:
                ui.console.print(f"  [{ui.DIM}]{c['created_at'][:19]}[/] [{ui.WHITE}]{c['preview']}[/]")
        return True

    elif command == "/save":
        path = arg or f"~/Desktop/jarvis_conversation_{agent.conversation_id}.json"
        agent.save_conversation(path)
        return True

    elif command == "/undo":
        from jarvis.history import get_history
        success, msg = get_history().undo_last_change()
        if success:
            ui.print_success(msg)
        else:
            ui.print_error(msg)
        return True

    elif command == "/changes":
        from jarvis.history import get_history
        summary = get_history().get_change_summary()
        ui.console.print(summary)
        return True

    elif command == "/status":
        from jarvis.tools.desktop import tool_get_system_info
        info = tool_get_system_info()
        ui.console.print(info)
        return True

    elif command in ("/company", "/briefing", "/approvals"):
        import json
        from jarvis.tools.amaura import get_control_plane
        control = get_control_plane()
        if command == "/company":
            result = control.dashboard()
        elif command == "/briefing":
            result = control.daily_briefing()
        else:
            result = {"pending_approvals": control.store.list_approvals("pending")}
        ui.console.print_json(json.dumps(result, default=str))
        return True

    elif command == "/telegram":
        ui.print_info("Starting Telegram bot...")
        try:
            from jarvis.telegram.bot import start_telegram_bot
            start_telegram_bot(agent)
        except ImportError:
            ui.print_error("Telegram bot dependencies not installed. Run: pip install python-telegram-bot")
        except Exception as e:
            ui.print_error(f"Telegram error: {e}")
        return True

    elif command == "/desktop":
        ui.console.print(f"\n  [{ui.GOLD}]Desktop Commands:[/]")
        ui.console.print(f"    [{ui.WHITE}]Just ask naturally:[/]")
        ui.console.print(f"    [{ui.DIM}]• \"Open Safari\"[/]")
        ui.console.print(f"    [{ui.DIM}]• \"Set volume to 50\"[/]")
        ui.console.print(f"    [{ui.DIM}]• \"Take a screenshot\"[/]")
        ui.console.print(f"    [{ui.DIM}]• \"What apps are running?\"[/]")
        ui.console.print(f"    [{ui.DIM}]• \"Lock my screen\"[/]")
        ui.console.print(f"    [{ui.DIM}]• \"Show system status\"[/]")
        ui.console.print()
        return True

    elif command == "/agents":
        from jarvis.tools.agent_factory import tool_list_agents
        result = tool_list_agents()
        ui.console.print(result)
        return True

    elif command == "/spawn":
        if not arg:
            ui.print_info("Usage: /spawn <task description>")
            ui.print_info("Creates a quick agent and runs it on the task.")
            return True
        # Quick-spawn: create a temporary agent and run it
        agent.run(f"Create a temporary AI agent to handle this task, then run it: {arg}")
        return True

    elif command == "/tools":
        from jarvis.tools.registry import get_tool_count
        counts = get_tool_count()
        ui.console.print(f"\n  [{ui.GOLD}]⚡ J.A.R.V.I.S. Tool Arsenal[/]")
        ui.console.print(f"    [{ui.CYAN}]Core Coding:[/]      [{ui.WHITE}]{counts.get('coding', 0)} tools[/]")
        ui.console.print(f"    [{ui.CYAN}]Advanced Coding:[/]  [{ui.WHITE}]{counts.get('advanced_coding', 0)} tools[/]")
        ui.console.print(f"    [{ui.CYAN}]Agent Factory:[/]    [{ui.WHITE}]{counts.get('agent_factory', 0)} tools[/]")
        ui.console.print(f"    [{ui.CYAN}]Desktop Control:[/]  [{ui.WHITE}]{counts.get('desktop', 0)} tools[/]")
        ui.console.print(f"    [{ui.CYAN}]Research:[/]         [{ui.WHITE}]{counts.get('research', 0)} tools[/]")
        ui.console.print(f"    [{ui.CYAN}]Documents:[/]        [{ui.WHITE}]{counts.get('documents', 0)} tools[/]")
        ui.console.print(f"    [{ui.CYAN}]Communication:[/]    [{ui.WHITE}]{counts.get('communication', 0)} tools[/]")
        ui.console.print(f"    [{ui.GOLD}]{'─' * 30}[/]")
        ui.console.print(f"    [{ui.GOLD}]Total:[/]            [{ui.WHITE}]{counts.get('total', 0)} tools[/]")
        ui.console.print()
        return True

    elif command == "/project":
        if not arg:
            ui.print_info("Usage: /project <template> <name>")
            ui.print_info("Templates: python-cli, python-api, flask, react, nextjs, vue, express, go, rust, django, fullstack")
            return True
        agent.run(f"Generate a project using the generate_project tool: {arg}")
        return True

    return False


def handle_natural_or_slash_command(user_input: str, agent: JarvisAgent, voice_engine: VoiceEngine) -> bool:
    """
    Normalizes natural language queries and slash commands so the user never has to type slash commands.
    Returns True if handled locally, False if it should be passed to the LLM agent.
    """
    clean = user_input.strip().lower()
    
    # Direct slash commands
    if user_input.startswith("/"):
        return handle_slash_command(user_input, agent, voice_engine)
    
    # Natural language shortcuts mapping to commands
    natural_mappings = {
        "tools": "/tools",
        "show tools": "/tools",
        "list tools": "/tools",
        "what tools do you have": "/tools",
        "what tools do you have?": "/tools",
        "tool list": "/tools",
        "my tools": "/tools",
        "help": "/help",
        "commands": "/help",
        "show commands": "/help",
        "how to use": "/help",
        "what can you do": "/help",
        "what can you do?": "/help",
        "undo": "/undo",
        "undo change": "/undo",
        "undo changes": "/undo",
        "undo last change": "/undo",
        "undo last edit": "/undo",
        "revert": "/undo",
        "clear": "/clear",
        "reset": "/clear",
        "clear conversation": "/clear",
        "clear history": "/clear",
        "status": "/status",
        "system status": "/status",
        "system info": "/status",
        "show status": "/status",
        "models": "/models",
        "list models": "/models",
        "show models": "/models",
        "history": "/history",
        "show history": "/history",
        "memory": "/memory",
        "show memory": "/memory",
        "changes": "/changes",
        "show changes": "/changes",
        "exit": "/exit",
        "quit": "/exit",
        "bye": "/exit",
        "voice": "/voice",
        "toggle voice": "/voice",
        "desktop": "/desktop",
        "desktop commands": "/desktop",
        "agents": "/agents",
        "list agents": "/agents",
        "show agents": "/agents",
    }
    
    if clean in natural_mappings:
        return handle_slash_command(natural_mappings[clean], agent, voice_engine)
    
    # Handle natural "switch to model <X>" or "use model <X>"
    if clean.startswith("switch model to ") or clean.startswith("use model "):
        model_arg = clean.replace("switch model to ", "").replace("use model ", "").strip()
        return handle_slash_command(f"/model {model_arg}", agent, voice_engine)
    
    # Handle natural "remember that <X>" or "remember <X>"
    if clean.startswith("remember that ") or clean.startswith("remember "):
        fact_arg = user_input.strip()[len("remember "):].strip()
        if fact_arg.lower().startswith("that "):
            fact_arg = fact_arg[5:].strip()
        return handle_slash_command(f"/remember {fact_arg}", agent, voice_engine)
        
    return False


def run_interactive(agent: JarvisAgent, voice_engine: VoiceEngine):
    """Run the interactive CLI loop."""
    while True:
        try:
            # Voice input mode
            if voice_engine.enabled:
                ui.print_voice_listening()
                text = voice_engine.listen_once(timeout=15)
                if text:
                    ui.print_voice_transcription(text)
                    user_input = text
                else:
                    ui.print_info("Didn't catch that. Try again, or type your request.")
                    continue
            else:
                # Text input mode
                try:
                    user_input = input("\033[1;36m◈ JARVIS › \033[0m").strip()
                except (EOFError, KeyboardInterrupt):
                    ui.console.print()
                    ui.print_goodbye()
                    break

            if not user_input:
                continue

            # Check natural language shortcuts & slash commands
            if handle_natural_or_slash_command(user_input, agent, voice_engine):
                continue

            # Run the agent
            response = agent.run(user_input)

            # Voice output
            if voice_engine.enabled and response:
                voice_engine.speak(response)

        except KeyboardInterrupt:
            ui.console.print()
            ui.print_goodbye()
            break
        except EOFError:
            ui.print_goodbye()
            break


def _run_web_server(host: str, port: int) -> None:
    """Run the primary authenticated server using the exact validated bind."""
    import uvicorn

    os.environ["JARVIS_EFFECTIVE_BIND_HOST"] = host
    uvicorn.run(
        "jarvis.server:app",
        host=host,
        port=port,
        log_level="warning",
    )


def launch_background_web(open_browser_flag: bool = True) -> str:
    """Launch the authenticated HUD asynchronously on a validated network bind."""
    import threading

    from jarvis.network_security import browser_host, validate_bind_security

    port = int(os.environ.get("JARVIS_PORT", "8000"))
    host = os.environ.get("JARVIS_HOST", "127.0.0.1").strip() or "127.0.0.1"
    validate_bind_security(host)
    os.environ["JARVIS_EFFECTIVE_BIND_HOST"] = host
    url_host = browser_host(host)
    url = f"http://{url_host}:{port}"
    api_key = os.environ.get("JARVIS_API_KEY", "").strip()
    browser_url = f"{url}/#api_key={api_key}" if api_key else url

    def _async_launcher() -> None:
        import socket
        import time
        import webbrowser

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                is_running = sock.connect_ex((url_host, port)) == 0
        except OSError:
            is_running = False

        if not is_running:
            _run_web_server(host, port)
            return

        if open_browser_flag:
            webbrowser.open(browser_url, new=2)

    def _open_when_ready() -> None:
        if not open_browser_flag:
            return
        import socket
        import time
        import webbrowser

        for _ in range(40):
            try:
                with socket.create_connection((url_host, port), timeout=0.25):
                    webbrowser.open(browser_url, new=2)
                    return
            except OSError:
                time.sleep(0.1)

    threading.Thread(target=_async_launcher, daemon=True, name="jarvis-web-server").start()
    if open_browser_flag:
        threading.Thread(target=_open_when_ready, daemon=True, name="jarvis-web-browser").start()
    return url


def main():
    """Main entry point."""
    args = parse_args()

    # Amaura has its own fail-closed operator CLI. Route before resolving or
    # instantiating the general JARVIS assistant so workforce operation never
    # depends on an NVIDIA key or interactive-agent startup.
    if args.amaura:
        from jarvis.amaura.cli import main as amaura_main

        return amaura_main(["worker"])

    # List models
    if args.list_models:
        models = list_models()
        ui.print_models(models)
        return

    # Resolve model
    model_key = args.model
    model_cfg = resolve_model(model_key)
    if not model_cfg:
        ui.print_error(f"Unknown model: {model_key}")
        ui.print_info("Use --list-models to see available models.")
        sys.exit(1)

    # Set working directory
    working_dir = args.working_dir or os.getcwd()

    # Print boot banner IMMEDIATELY for instant terminal feedback
    ui.print_boot_sequence(model_cfg["name"], working_dir)

    # Create the general assistant only after Amaura and listing routes exit.
    from jarvis.agent import JarvisAgent

    try:
        agent = JarvisAgent(
            api_key=args.api_key,
            model_key=model_key,
            working_dir=working_dir,
        )
    except ValueError as e:
        ui.print_error(str(e))
        sys.exit(1)

    # Voice engine
    from jarvis.voice.engine import VoiceEngine

    voice_engine = VoiceEngine()
    if args.voice:
        if voice_engine.available:
            voice_engine.enable()
            agent.voice_mode = True
        else:
            ui.print_warning("Voice dependencies not available. Install: pip install SpeechRecognition PyAudio")

    # Web Mode explicitly requested
    if args.web:
        ui.print_info("Launching JARVIS Web Interface...")
        url = launch_background_web(open_browser_flag=True)
        ui.print_success(f"JARVIS Web Interface running at {url}")
        from jarvis.server import main as start_server
        start_server()
        return

    # Telegram mode
    if args.telegram:
        ui.print_info("Starting Telegram bot mode...")
        try:
            from jarvis.telegram.bot import start_telegram_bot
            start_telegram_bot(agent)
        except ImportError:
            ui.print_error("Install python-telegram-bot: pip install python-telegram-bot")
        except Exception as e:
            ui.print_error(f"Telegram error: {e}")
        return

    # Single prompt mode with Fable-5 Reasoning
    if args.fable:
        prompt = args.prompt or "scaffold complete production ready python web application with tests"
        agent.run_fable_reasoning(prompt)
        return

    # Single prompt mode
    if args.prompt:
        agent.run(args.prompt)
        return

    # Interactive mode — automatically launches Web HUD alongside CLI
    if not args.no_web:
        web_url = launch_background_web(open_browser_flag=True)
        ui.print_success(f"JARVIS Web Interface HUD live at {web_url}")

    if voice_engine.enabled:
        ui.print_success("Voice mode active. Speak your commands.")
        voice_engine.greet()

    run_interactive(agent, voice_engine)


if __name__ == "__main__":
    main()
