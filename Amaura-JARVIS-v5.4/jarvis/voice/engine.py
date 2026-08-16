"""
Voice Engine — orchestrates the listen → think → speak cycle.
"""

from jarvis.voice.listener import is_available as stt_available
from jarvis.voice.listener import listen
from jarvis.voice.speaker import get_speaker


class VoiceEngine:
    """Manages the full voice interaction loop."""

    def __init__(self, voice: str = "Daniel", rate: int = 180):
        self.speaker = get_speaker()
        self.speaker.set_voice(voice)
        self.speaker.set_rate(rate)
        self.enabled = False
        self._stt_available = stt_available()

    @property
    def available(self) -> bool:
        """Check if voice engine is available."""
        return self._stt_available

    def enable(self):
        """Enable voice mode."""
        self.enabled = True

    def disable(self):
        """Disable voice mode."""
        self.enabled = False
        self.speaker.stop()

    def toggle(self) -> bool:
        """Toggle voice mode. Returns new state."""
        if self.enabled:
            self.disable()
        else:
            self.enable()
        return self.enabled

    def listen_once(self, timeout: int = 10) -> str | None:
        """Listen for a single voice command."""
        if not self._stt_available:
            return None
        return listen(timeout=timeout)

    def speak(self, text: str, blocking: bool = False):
        """Speak the response."""
        if self.enabled:
            self.speaker.speak_async(text)

    def stop_speaking(self):
        """Interrupt current speech."""
        self.speaker.stop()

    def greet(self):
        """Speak the startup greeting."""
        self.speaker.speak_async("Interface online. Governed operations remain readiness gated.")
