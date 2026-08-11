import unittest
from jarvis.models import SmartHybridModelRouter, resolve_model

class TestRouter(unittest.TestCase):
    def test_routing(self):
        m1 = SmartHybridModelRouter.route_query("Please analyze the screenshot of my UI layout")
        self.assertEqual(m1, "llama-vision")

        m2 = SmartHybridModelRouter.route_query("Write a python function to compute fibonacci")
        self.assertEqual(m2, "fable-5-reasoning")

        m3 = SmartHybridModelRouter.route_query("Review complex system architecture design")
        self.assertEqual(m3, "fable-5-reasoning")

    def test_resolve_model(self):
        m = resolve_model("llama")
        self.assertIsNotNone(m)
        self.assertEqual(m["id"], "meta/llama-3.1-70b-instruct")

if __name__ == "__main__":
    unittest.main()
