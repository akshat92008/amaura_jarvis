"""
Voice Speaker — Streaming Text-to-Speech using macOS `say` command.
British voice (Daniel) for the authentic Jarvis experience.
Supports sentence-level streaming TTS and instant barge-in interruption.
"""

import atexit
import re
import queue
import subprocess
import threading
from typing import Optional, List

# Available macOS voices that sound good for Jarvis
VOICES = {
    "daniel": "Daniel",        # British English (default Jarvis voice)
    "alex": "Alex",            # American English
    "samantha": "Samantha",    # American English (female)
    "karen": "Karen",          # Australian English
    "moira": "Moira",          # Irish English
    "rishi": "Rishi",          # Indian English
    "tessa": "Tessa",          # South African English
}

DEFAULT_VOICE = "Daniel"
DEFAULT_RATE = 180  # Words per minute


class Speaker:
    """Text-to-Speech engine using macOS say command with streaming & interruption support."""

    def __init__(self, voice: str = DEFAULT_VOICE, rate: int = DEFAULT_RATE):
        self.voice = voice
        self.rate = rate
        self._current_process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._interrupt_event = threading.Event()
        self._speech_queue: queue.Queue = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._threads: set[threading.Thread] = set()
        self._threads_lock = threading.Lock()

    def speak(self, text: str, blocking: bool = True):
        """Speak the given text."""
        if not text or not text.strip():
            return

        clean = self._clean_for_speech(text)
        if not clean:
            return

        self.stop()
        self._interrupt_event.clear()

        cmd = ["say", "-v", self.voice, "-r", str(self.rate), clean]

        with self._lock:
            if blocking:
                try:
                    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    self._current_process = p
                    while p.poll() is None:
                        if self._interrupt_event.is_set():
                            p.terminate()
                            break
                        p.wait(timeout=0.1)
                except (subprocess.TimeoutExpired, Exception):
                    pass
            else:
                try:
                    self._current_process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
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

    def speak_stream(self, text_generator):
        """Stream sentence chunks to speech as text is being generated."""
        self.stop()
        self._interrupt_event.clear()

        def stream_worker():
            buffer = ""
            for chunk in text_generator:
                if self._interrupt_event.is_set():
                    break
                buffer += chunk
                sentences = re.split(r'([.!?\n]+)', buffer)
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
        text = re.sub(r'```[\s\S]*?```', 'code block omitted', text)
        text = re.sub(r'`[^`]+`', '', text)
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
        text = re.sub(r'\*([^*]+)\*', r'\1', text)
        text = re.sub(r'#+\s*', '', text)
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        text = re.sub(r'[─═╔╗╚╝╠╣║┌┐└┘├┤│┬┴┼▓▲▼◄►◈●◉⬜🔄✅❌⏭️🔒⚡🛑🚫⚠️📋📁📄🔍🧠💾🔋⏱🖥️🎤📝🔊✓✗ℹ]', '', text)
        text = re.sub(r'/[\w/.-]+', '', text)
        text = re.sub(r'https?://\S+', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        if len(text) > 1000:
            text = text[:1000] + ". I'll stop here. Check the output for full response."
        return text

    @staticmethod
    def list_voices() -> List[str]:
        try:
            result = subprocess.run(
                ["say", "-v", "?"],
                capture_output=True, text=True, timeout=10,
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


_speaker: Optional[Speaker] = None


def get_speaker() -> Speaker:
    global _speaker
    if _speaker is None:
        _speaker = Speaker()
    return _speaker


def _shutdown_global_speaker() -> None:
    if _speaker is not None:
        _speaker.shutdown(timeout=1.0)


atexit.register(_shutdown_global_speaker)
