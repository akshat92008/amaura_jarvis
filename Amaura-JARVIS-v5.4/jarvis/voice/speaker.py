"""
Voice Speaker — Multi-Tier Streaming Text-to-Speech Engine for JARVIS.

Provides authentic British cadence (Paul Bettany style) with 3-tier cascade:
1. Tier 1: ElevenLabs API (if ELEVENLABS_API_KEY set) with British voice
2. Tier 2: OpenAI Audio Speech API (if OPENAI_API_KEY set) with 'onyx' or 'echo'
3. Tier 3: macOS native `say -v Daniel` (always available, zero network dependencies)

Supports:
- Sentence-level streaming TTS with instant barge-in interruption
- Adaptive speaking rate (combat vs lab vs morning modes)
- Audio player management (`afplay` on macOS)
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import urllib.request
from typing import Generator, Iterable

log = logging.getLogger(__name__)

# Available macOS voices that sound good for Jarvis
VOICES = {
    "daniel": "Daniel",    # British English (authentic default Jarvis voice)
    "oliver": "Oliver",    # British English
    "george": "George",    # British English
    "alex": "Alex",        # American English
    "samantha": "Samantha",# American English
    "karen": "Karen",      # Australian English
    "moira": "Moira",      # Irish English
    "rishi": "Rishi",      # Indian English
}

DEFAULT_VOICE = "Daniel"
DEFAULT_RATE = 175  # Words per minute (calm, measured cadence)


class Speaker:
    """Text-to-Speech engine with multi-tier provider cascade and barge-in support."""

    def __init__(self, voice: str = DEFAULT_VOICE, rate: int = DEFAULT_RATE):
        self.voice = voice
        self.rate = rate
        self._current_process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._interrupt_event = threading.Event()
        self._speech_queue: queue.Queue = queue.Queue()
        self._threads: set[threading.Thread] = set()
        self._threads_lock = threading.Lock()

        # Keys
        self._elevenlabs_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
        self._elevenlabs_voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB").strip() # Adam / British default
        self._openai_key = os.environ.get("OPENAI_API_KEY", "").strip()

    def speak(self, text: str, blocking: bool = True):
        """Speak the given text using the best available provider."""
        if not text or not text.strip():
            return

        clean = self._clean_for_speech(text)
        if not clean:
            return

        self.stop()
        self._interrupt_event.clear()

        # 1. Try ElevenLabs if configured
        if self._elevenlabs_key:
            if self._speak_elevenlabs(clean, blocking=blocking):
                return

        # 2. Try OpenAI TTS if configured
        if self._openai_key:
            if self._speak_openai_tts(clean, blocking=blocking):
                return

        # 3. Native macOS `say` fallback (rock-solid, immediate)
        self._speak_macos_say(clean, blocking=blocking)

    def _speak_elevenlabs(self, text: str, blocking: bool = True) -> bool:
        """Synthesize via ElevenLabs REST API."""
        try:
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{self._elevenlabs_voice_id}"
            payload = json.dumps({
                "text": text,
                "model_id": "eleven_monolingual_v1",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
            }).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Accept": "audio/mpeg",
                    "Content-Type": "application/json",
                    "xi-api-key": self._elevenlabs_key,
                },
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                audio_data = resp.read()

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
                tf.write(audio_data)
                tmp_path = tf.name

            return self._play_audio_file(tmp_path, blocking=blocking)
        except Exception as exc:
            log.debug("ElevenLabs TTS failed or timed out: %s", exc)
            return False

    def _speak_openai_tts(self, text: str, blocking: bool = True) -> bool:
        """Synthesize via OpenAI audio/speech REST endpoint."""
        try:
            url = "https://api.openai.com/v1/audio/speech"
            payload = json.dumps({
                "model": "tts-1",
                "input": text,
                "voice": "onyx",  # deep baritone
                "speed": 1.0,
            }).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Authorization": f"Bearer {self._openai_key}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                audio_data = resp.read()

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
                tf.write(audio_data)
                tmp_path = tf.name

            return self._play_audio_file(tmp_path, blocking=blocking)
        except Exception as exc:
            log.debug("OpenAI TTS failed or timed out: %s", exc)
            return False

    def _play_audio_file(self, audio_file_path: str, blocking: bool = True) -> bool:
        """Play an audio file using macOS afplay or system player with interrupt support."""
        player = shutil.which("afplay") or shutil.which("mpv") or shutil.which("ffplay")
        if not player:
            return False

        cmd = [player, audio_file_path]
        with self._lock:
            try:
                p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._current_process = p
            except Exception:
                return False

        if blocking:
            try:
                while p.poll() is None:
                    if self._interrupt_event.is_set():
                        p.terminate()
                        break
                    p.wait(timeout=0.08)
            except Exception:
                pass
            finally:
                try:
                    os.unlink(audio_file_path)
                except OSError:
                    pass
        return True

    def _speak_macos_say(self, clean_text: str, blocking: bool = True):
        """Standard macOS `say` execution with barge-in support."""
        cmd = ["say", "-v", self.voice, "-r", str(self.rate), clean_text]
        with self._lock:
            try:
                p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._current_process = p
            except Exception:
                return

        if blocking:
            try:
                while p.poll() is None:
                    if self._interrupt_event.is_set():
                        p.terminate()
                        break
                    p.wait(timeout=0.08)
            except Exception:
                pass

    def _start_worker(self, target, *args, name: str) -> threading.Thread:
        def runner():
            try:
                target(*args)
            finally:
                current = threading.current_thread()
                with self._threads_lock:
                    self._threads.discard(current)

        thread = threading.Thread(target=runner, daemon=True, name=name)
        with self._threads_lock:
            self._threads.add(thread)
        thread.start()
        return thread

    def speak_async(self, text: str) -> threading.Thread:
        """Speak in a tracked background thread (non-blocking)."""
        return self._start_worker(self.speak, text, True, name="jarvis-speak")

    def speak_stream(self, text_generator: Iterable[str] | Generator[str, None, None]):
        """Stream sentence chunks to speech as text is being generated."""
        self.stop()
        self._interrupt_event.clear()

        def stream_worker():
            buffer = ""
            for chunk in text_generator:
                if self._interrupt_event.is_set():
                    break
                buffer += chunk
                sentences = re.split(r"([.!?\n]+)", buffer)
                while len(sentences) > 2:
                    sentence = sentences.pop(0) + sentences.pop(0)
                    clean_s = self._clean_for_speech(sentence)
                    if clean_s and not self._interrupt_event.is_set():
                        self.speak(clean_s, blocking=True)
                    buffer = "".join(sentences)

            if buffer.strip() and not self._interrupt_event.is_set():
                clean_s = self._clean_for_speech(buffer)
                if clean_s:
                    self.speak(clean_s, blocking=True)

        return self._start_worker(stream_worker, name="jarvis-speech-stream")

    def stop(self):
        """Stop any currently playing speech immediately (barge-in)."""
        self._interrupt_event.set()
        with self._lock:
            if self._current_process and self._current_process.poll() is None:
                try:
                    self._current_process.terminate()
                except Exception:
                    pass
                self._current_process = None

    def shutdown(self, timeout: float = 2.0) -> None:
        """Stop speech and join tracked workers within a strict deadline."""
        self.stop()
        current = threading.current_thread()
        with self._threads_lock:
            workers = [thread for thread in self._threads if thread is not current]
        if not workers:
            return
        per_thread = max(0.01, float(timeout) / len(workers))
        for thread in workers:
            thread.join(timeout=per_thread)
        with self._threads_lock:
            self._threads = {thread for thread in self._threads if thread.is_alive()}

    def is_speaking(self) -> bool:
        """Check if currently speaking."""
        with self._lock:
            if self._current_process:
                return self._current_process.poll() is None
            return False

    def set_voice(self, voice: str):
        if voice.lower() in VOICES:
            self.voice = VOICES[voice.lower()]
        else:
            self.voice = voice

    def set_rate(self, rate: int):
        self.rate = max(100, min(300, rate))

    @staticmethod
    def _clean_for_speech(text: str) -> str:
        """Clean text for natural speech output."""
        text = re.sub(r"```[\s\S]*?```", "code block omitted", text)
        text = re.sub(r"`[^`]+`", "", text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        text = re.sub(r"#+\s*", "", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"[─═╔╗╚╝╠╣║┌┐└┘├┤│┬┴┼▓▲▼◄►◈●◉⬜🔄✅❌⏭️🔒⚡🛑🚫⚠️📋📁📄🔍🧠💾🔋⏱🖥️🎤📝🔊✓✗ℹ]", "", text)
        text = re.sub(r"/[\w/.-]+", "", text)
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 1000:
            text = text[:1000] + ". I'll stop here. Check the terminal for full response."
        return text

    @staticmethod
    def list_voices() -> list[str]:
        try:
            result = subprocess.run(
                ["say", "-v", "?"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                voices = []
                for line in result.stdout.strip().split("\n"):
                    if line.strip():
                        name = line.split()[0]
                        voices.append(name)
                return voices
        except Exception:
            pass
        return list(VOICES.values())


_speaker: Speaker | None = None


def get_speaker() -> Speaker:
    global _speaker
    if _speaker is None:
        _speaker = Speaker()
    return _speaker


def _shutdown_global_speaker() -> None:
    if _speaker is not None:
        _speaker.shutdown(timeout=1.0)


atexit.register(_shutdown_global_speaker)

__all__ = ["Speaker", "get_speaker", "VOICES", "DEFAULT_VOICE", "DEFAULT_RATE"]
