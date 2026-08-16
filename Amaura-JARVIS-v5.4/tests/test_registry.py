import unittest

from jarvis.tools.registry import execute_tool, get_tool_count


class TestRegistry(unittest.TestCase):
    def test_registry_tool_counts(self):
        counts = get_tool_count()
        self.assertGreater(counts["total"], 60)
        self.assertIn("app_builder", counts)
        self.assertIn("ast_indexer", counts)
        self.assertIn("vision", counts)
        self.assertIn("vector_memory", counts)

    def test_execute_tool(self):
        res = execute_tool("generate_morning_briefing", {})
        self.assertIn("Good morning, sir", res)


if __name__ == "__main__":
    unittest.main()
