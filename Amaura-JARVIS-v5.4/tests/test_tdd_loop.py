import unittest
from jarvis.tools.tdd_loop import test_and_auto_fix

class TestTDDLoop(unittest.TestCase):
    def test_tdd_loop_passing(self):
        result = test_and_auto_fix(runner="echo 'OK'", target=".")
        self.assertIn("Test Suite Passed Cleanly", result)

if __name__ == "__main__":
    unittest.main()
