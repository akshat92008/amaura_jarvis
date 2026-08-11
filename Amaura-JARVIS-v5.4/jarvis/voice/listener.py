"""
Voice Listener — Speech-to-Text using SpeechRecognition library.
Captures audio from the microphone and transcribes it.
"""



def is_available() -> bool:
    """Check if voice input dependencies are available."""
    try:
        import speech_recognition
        import pyaudio
        return True
    except (ImportError, AttributeError, OSError):
        return False


def listen(timeout: int = 10, phrase_time_limit: int = 30) -> str | None:
    """
    Listen for speech and return transcribed text.
    Returns None if nothing was heard or an error occurred.
    """
    try:
        import speech_recognition as sr
    except ImportError:
        return None

    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 300
    recognizer.dynamic_energy_threshold = True

    try:
        with sr.Microphone() as source:
            # Brief calibration
            recognizer.adjust_for_ambient_noise(source, duration=0.5)

            # Listen
            audio = recognizer.listen(
                source,
                timeout=timeout,
                phrase_time_limit=phrase_time_limit,
            )

        # Transcribe using Google's free STT
        text = recognizer.recognize_google(audio)
        return text.strip()

    except Exception:
        # Silently fail — could be timeout, no speech, API error
        return None


def listen_continuous(callback, stop_event=None):
    """
    Continuously listen and call callback(text) for each utterance.
    Runs until stop_event is set.
    """
    try:
        import speech_recognition as sr
    except ImportError:
        return

    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 300
    recognizer.dynamic_energy_threshold = True

    with sr.Microphone() as source:
        recognizer.adjust_for_ambient_noise(source, duration=1)

        while True:
            if stop_event and stop_event.is_set():
                break

            try:
                audio = recognizer.listen(source, timeout=5, phrase_time_limit=30)
                text = recognizer.recognize_google(audio)
                if text.strip():
                    callback(text.strip())
            except Exception:
                continue
