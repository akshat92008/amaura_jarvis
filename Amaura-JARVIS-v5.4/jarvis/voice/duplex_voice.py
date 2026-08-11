"""Continuous voice session for Amaura JARVIS.

This module deliberately does not claim token-level streaming STT.  It provides
real continuous utterance recognition when SpeechRecognition/PyAudio are
available, wake-word gating, actual routing into JARVIS cognition, interruptible
TTS, and push-to-talk through the exact same cognition path.

Mission execution is not implicitly authorised by voice. The safe default
handler can converse but sets ``allow_missions=False``. A trusted authenticated
host may inject a handler after it has independently validated operator authority.
"""
from __future__ import annotations

import threading
import time
from enum import Enum
from typing import Callable, Dict, List, Optional

from jarvis.voice.listener import is_available as stt_available, listen_continuous
from jarvis.voice.speaker import Speaker, get_speaker


class VoiceState(str, Enum):
    IDLE = "IDLE"
    WAKE_WORD_WAIT = "WAKE_WORD_WAIT"
    LISTENING = "LISTENING"
    PROCESSING = "PROCESSING"
    SPEAKING = "SPEAKING"
    INTERRUPTED = "INTERRUPTED"
    ERROR = "ERROR"


VOICE_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "start_duplex_voice_session",
            "description": "Start a hands-free JARVIS voice session with wake-word detection and interruptible speech.",
            "parameters": {
                "type": "object",
                "properties": {
                    "wake_word": {
                        "type": "string",
                        "description": "Wake-word trigger phrase such as 'Hey JARVIS'.",
                        "default": "Hey JARVIS",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_duplex_voice_session",
            "description": "Stop the active JARVIS voice session.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trigger_barge_in",
            "description": "Immediately stop JARVIS speech output so the user can interrupt.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "push_to_talk_command",
            "description": "Send transcribed push-to-talk text through the same JARVIS cognition path as voice.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Transcribed user utterance."}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_voice_session_status",
            "description": "Get measured status for the current voice session.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


CommandHandler = Callable[[str], str]

_default_agent = None
_default_control = None
_default_lock = threading.Lock()


def _default_command_handler(text: str) -> str:
    """Safely route voice into JARVIS cognition without execution authority."""
    from jarvis.agent import JarvisAgent
    from jarvis.amaura.control_plane import AmauraControlPlane

    agent = JarvisAgent()
    control = AmauraControlPlane()
    result = agent.run_executive(
        text,
        control=control,
        session_id="voice-default",
        workspace="",
        autonomy="execute_until_approval",
        coding_backend="antigravity",
        allow_missions=False,
        allow_memory_mutation=False,
    )
    return str(result.get("message") or "").strip()


class DuplexVoiceEngine:
    """Wake-word voice loop with real cognition and barge-in support."""

    def __init__(
        self,
        wake_word: str = "Hey JARVIS",
        *,
        command_handler: CommandHandler | None = None,
        speaker: Speaker | None = None,
    ) -> None:
        self.wake_word = wake_word.strip() or "Hey JARVIS"
        self.state = VoiceState.IDLE
        self.speaker = speaker or get_speaker()
        self.command_handler = command_handler or _default_command_handler
        self._session_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self.last_latency_ms: float | None = None
        self.last_error = ""
        self.history: List[Dict[str, str]] = []

    def set_command_handler(self, handler: CommandHandler | None) -> None:
        """Install a host-authorised handler, or restore the safe default."""
        with self._lock:
            self.command_handler = handler or _default_command_handler

    def detect_wake_word(self, text: str) -> bool:
        if not text:
            return False
        clean = " ".join(text.lower().strip().split())
        candidates = {
            " ".join(self.wake_word.lower().split()),
            "jarvis",
            "hey jarvis",
            "ok jarvis",
        }
        return any(candidate and candidate in clean for candidate in candidates)

    def _strip_wake_word(self, text: str) -> str:
        lowered = text.lower()
        candidates = [self.wake_word, "hey jarvis", "ok jarvis", "jarvis"]
        for candidate in sorted(candidates, key=len, reverse=True):
            index = lowered.find(candidate.lower())
            if index >= 0:
                return (text[:index] + text[index + len(candidate):]).strip(" ,:;.!?-")
        return text.strip()

    def _listen_loop(self) -> None:
        try:
            listen_continuous(self._on_utterance, self._stop_event)
        except Exception as exc:
            with self._lock:
                if not self._stop_event.is_set():
                    self.state = VoiceState.ERROR
                    self.last_error = str(exc)[:500]

    def start_session(self, wake_word: str = "Hey JARVIS") -> str:
        with self._lock:
            if self._session_thread and self._session_thread.is_alive():
                return self.get_status()
            self.wake_word = wake_word.strip() or "Hey JARVIS"
            self._stop_event.clear()
            self.last_error = ""
            if stt_available():
                self.state = VoiceState.WAKE_WORD_WAIT
                self._session_thread = threading.Thread(
                    target=self._listen_loop,
                    daemon=True,
                    name="jarvis-continuous-listener",
                )
                self._session_thread.start()
                mode = "continuous utterance STT + interruptible TTS"
            else:
                # Preserve the session state contract even when microphone
                # dependencies are unavailable; status truthfully reports that
                # no continuous listener thread is running.
                self.state = VoiceState.WAKE_WORD_WAIT
                mode = "push-to-talk text only (microphone STT unavailable)"
        return (
            "🎙️ **Duplex Live Voice Session Active**\n"
            f"- **State:** `{self.state.value}`\n"
            f"- **Wake Word:** `{self.wake_word}`\n"
            f"- **Mode:** {mode}\n"
            "- **Barge-In:** enabled\n"
            "- **Cognition:** routed through JARVIS (no canned acknowledgement)"
        )

    def stop_session(self) -> str:
        with self._lock:
            self._stop_event.set()
            self.speaker.stop()
            thread = self._session_thread
            self._session_thread = None
            self.state = VoiceState.IDLE
        if thread and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        return "🎙️ **Duplex Live Voice Session Terminated.**"

    def handle_barge_in(self) -> str:
        with self._lock:
            active = self.speaker.is_speaking() or self.state == VoiceState.SPEAKING
            if active:
                self.speaker.stop()
                self.state = VoiceState.INTERRUPTED
                return "⚡ **Barge-In:** JARVIS speech stopped; listening to the interruption."
        return "🎙️ **Barge-In:** No active JARVIS speech to interrupt."

    def _on_utterance(self, text: str) -> None:
        text = str(text or "").strip()
        if not text or self._stop_event.is_set():
            return
        if self.speaker.is_speaking():
            self.handle_barge_in()

        with self._lock:
            state = self.state
        if state == VoiceState.WAKE_WORD_WAIT:
            if not self.detect_wake_word(text):
                return
            remaining = self._strip_wake_word(text)
            if not remaining:
                with self._lock:
                    self.state = VoiceState.LISTENING
                return
            self._process_command(remaining, speak=True)
            return
        if state in {VoiceState.LISTENING, VoiceState.INTERRUPTED, VoiceState.IDLE}:
            self._process_command(text, speak=True)

    def _process_command(self, text: str, *, speak: bool) -> tuple[str, float]:
        clean = str(text or "").strip()
        if not clean:
            raise ValueError("Voice command cannot be empty")
        if self.speaker.is_speaking():
            self.handle_barge_in()
        with self._lock:
            self.state = VoiceState.PROCESSING
        start = time.perf_counter()
        try:
            response = str(self.command_handler(clean) or "").strip()
            if not response:
                response = "I could not produce a response for that request."
            elapsed = (time.perf_counter() - start) * 1000.0
            with self._lock:
                self.last_latency_ms = elapsed
                self.history.append(
                    {
                        "user": clean,
                        "assistant": response,
                        "timestamp": time.strftime("%H:%M:%S"),
                    }
                )
                self.history[:] = self.history[-100:]
                self.state = VoiceState.SPEAKING if speak else VoiceState.WAKE_WORD_WAIT
            if speak:
                worker = self.speaker.speak_async(response)

                def restore_state() -> None:
                    worker.join()
                    with self._lock:
                        if not self._stop_event.is_set() and self.state == VoiceState.SPEAKING:
                            self.state = VoiceState.WAKE_WORD_WAIT if stt_available() else VoiceState.IDLE

                threading.Thread(target=restore_state, daemon=True, name="jarvis-voice-state").start()
            return response, elapsed
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000.0
            with self._lock:
                self.last_latency_ms = elapsed
                self.last_error = str(exc)[:500]
                self.state = VoiceState.ERROR
            raise

    def push_to_talk(self, text: str) -> str:
        """Route PTT text through actual JARVIS cognition and speak the result."""
        try:
            response, elapsed = self._process_command(text, speak=True)
            return (
                f"🎙️ **Push-to-Talk Processed ({elapsed:.1f} ms cognition latency)**\n"
                f"- **User:** {text}\n"
                f"- **JARVIS:** {response}\n"
                f"- **State:** `{self.state.value}`"
            )
        except Exception as exc:
            return f"🎙️ **Voice command failed closed:** {exc}"

    def get_status(self) -> str:
        latency = "not measured" if self.last_latency_ms is None else f"{self.last_latency_ms:.1f} ms"
        thread_live = bool(self._session_thread and self._session_thread.is_alive())
        return (
            "🎙️ **JARVIS Duplex Voice Session Status**\n"
            f"- **State:** `{self.state.value}`\n"
            f"- **Wake Word:** `{self.wake_word}`\n"
            f"- **Continuous Listener:** `{'Yes' if thread_live else 'No'}`\n"
            f"- **STT Available:** `{'Yes' if stt_available() else 'No'}`\n"
            f"- **Is Speaking:** `{'Yes' if self.speaker.is_speaking() else 'No'}`\n"
            f"- **Measured Cognition Latency:** `{latency}`\n"
            f"- **Processed Utterances:** `{len(self.history)}`\n"
            f"- **Last Error:** `{self.last_error or 'none'}`"
        )


_voice_engine = DuplexVoiceEngine()


def configure_voice_command_handler(handler: CommandHandler | None) -> None:
    """Trusted host hook for routing authorised voice commands."""
    _voice_engine.set_command_handler(handler)


def start_duplex_voice_session(wake_word: str = "Hey JARVIS") -> str:
    return _voice_engine.start_session(wake_word)


def stop_duplex_voice_session() -> str:
    return _voice_engine.stop_session()


def trigger_barge_in() -> str:
    return _voice_engine.handle_barge_in()


def push_to_talk_command(text: str) -> str:
    return _voice_engine.push_to_talk(text)


def get_voice_session_status() -> str:
    return _voice_engine.get_status()


VOICE_DISPATCH = {
    "start_duplex_voice_session": start_duplex_voice_session,
    "stop_duplex_voice_session": stop_duplex_voice_session,
    "trigger_barge_in": trigger_barge_in,
    "push_to_talk_command": push_to_talk_command,
    "get_voice_session_status": get_voice_session_status,
}

__all__ = [
    "DuplexVoiceEngine",
    "VoiceState",
    "VOICE_TOOL_DEFINITIONS",
    "VOICE_DISPATCH",
    "configure_voice_command_handler",
    "start_duplex_voice_session",
    "stop_duplex_voice_session",
    "trigger_barge_in",
    "push_to_talk_command",
    "get_voice_session_status",
]
