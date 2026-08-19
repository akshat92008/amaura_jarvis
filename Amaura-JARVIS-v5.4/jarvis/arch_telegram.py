"""Telegram surface for the unified ARCH runtime.

The legacy Telegram bot is retained as the transport/UI implementation, but
normal text and voice requests are routed back through the same authenticated
ARCH ExecutiveKernel instead of the legacy free-form agent loop.
"""

from __future__ import annotations

import asyncio
import os
import threading
from typing import Any


class ArchTelegramAgentProxy:
    """Adapt the existing Telegram transport to the unified ExecutiveKernel."""

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    def __getattr__(self, name: str) -> Any:
        return getattr(self._agent, name)

    def run_non_interactive(self, text: str) -> str:
        from jarvis.tools.amaura import get_control_plane

        result = self._agent.run_executive(
            text,
            control=get_control_plane(),
            session_id="arch-telegram",
            workspace=str(getattr(self._agent, "working_dir", "") or os.getcwd()),
            autonomy="execute_until_approval",
            coding_backend="antigravity",
            allow_missions=True,
            allow_memory_mutation=True,
        )
        return str(result.get("message") or "")


def telegram_configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() and os.environ.get("TELEGRAM_USER_ID", "").strip())


def start_arch_telegram(agent: Any) -> threading.Thread | None:
    """Start Telegram as an internal ARCH surface when credentials exist.

    python-telegram-bot normally installs process signal handlers, which is only
    legal on the main thread. ARCH owns the process, so the internal transport
    runs on its own event-loop thread with signal handling disabled; Ctrl-C and
    shutdown remain owned by ARCH itself.
    """
    if not telegram_configured():
        return None

    proxy = ArchTelegramAgentProxy(agent)

    def runner() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            from telegram.ext import Application

            original_run_polling = Application.run_polling

            def run_polling_without_signals(self, *args, **kwargs):
                kwargs["stop_signals"] = None
                return original_run_polling(self, *args, **kwargs)

            Application.run_polling = run_polling_without_signals
            try:
                from jarvis.telegram.bot import start_telegram_bot

                start_telegram_bot(proxy)
            finally:
                Application.run_polling = original_run_polling
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            loop.close()

    thread = threading.Thread(target=runner, name="arch-telegram", daemon=True)
    thread.start()
    return thread


__all__ = ["ArchTelegramAgentProxy", "start_arch_telegram", "telegram_configured"]
