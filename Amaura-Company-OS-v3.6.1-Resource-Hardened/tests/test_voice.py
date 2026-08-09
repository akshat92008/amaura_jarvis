import unittest
from jarvis.voice.speaker import get_speaker
from jarvis.voice.duplex_voice import (
    DuplexVoiceEngine,
    VoiceState,
    trigger_barge_in,
    push_to_talk_command,
    get_voice_session_status
)

class TestStreamingVoice(unittest.TestCase):
    def test_speaker_clean_and_stream(self):
        speaker = get_speaker()
        clean = speaker._clean_for_speech("Hello **world**! `code snippet` [link](http://test.com)")
        self.assertEqual(clean, "Hello world! link")

    def test_wake_word_detection(self):
        engine = DuplexVoiceEngine(wake_word="Hey JARVIS")
        self.assertTrue(engine.detect_wake_word("hey jarvis what is the weather"))
        self.assertTrue(engine.detect_wake_word("Jarvis open browser"))
        self.assertFalse(engine.detect_wake_word("random text query"))

    def test_voice_session_state_machine(self):
        engine = DuplexVoiceEngine()
        self.assertEqual(engine.state, VoiceState.IDLE)

        start_res = engine.start_session("Hey JARVIS")
        self.assertEqual(engine.state, VoiceState.WAKE_WORD_WAIT)
        self.assertIn("Duplex Live Voice Session Active", start_res)

        ptt_res = engine.push_to_talk("Run tests")
        self.assertIn("Push-to-Talk Processed", ptt_res)

        barge_res = engine.handle_barge_in()
        self.assertIn("Barge-In", barge_res)

        stop_res = engine.stop_session()
        self.assertEqual(engine.state, VoiceState.IDLE)
        self.assertIn("Terminated", stop_res)

    def test_tool_dispatches(self):
        status = get_voice_session_status()
        self.assertIn("Duplex Voice Session Status", status)

        ptt = push_to_talk_command("Hello Jarvis")
        self.assertIn("Push-to-Talk Processed", ptt)

        barge = trigger_barge_in()
        self.assertIn("Barge-In", barge)

if __name__ == "__main__":
    unittest.main()
