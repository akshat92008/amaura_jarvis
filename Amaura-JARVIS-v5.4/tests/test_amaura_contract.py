"""Release contracts that prevent workforce/tool and CI drift."""

from __future__ import annotations

import unittest
from pathlib import Path

from jarvis.amaura.capabilities import EXECUTABLE_EMPLOYEE_TOOLS
from jarvis.amaura.registry import ALL_AGENTS
from jarvis.tools.registry import ALL_DISPATCH, ALL_TOOL_DEFINITIONS


class TestAmauraReleaseContract(unittest.TestCase):
    def test_every_employee_tool_is_executable_and_declared(self):
        employee_tools = {tool for agent in ALL_AGENTS for tool in agent.tools}
        definition_names = {definition["function"]["name"] for definition in ALL_TOOL_DEFINITIONS}
        self.assertEqual(len(ALL_AGENTS), 57)
        self.assertEqual(employee_tools, EXECUTABLE_EMPLOYEE_TOOLS)
        self.assertTrue(employee_tools.issubset(definition_names))
        self.assertTrue(employee_tools.issubset(ALL_DISPATCH))

    def test_release_automation_covers_python_311_and_312(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn('"3.11"', workflow)
        self.assertIn('"3.12"', workflow)
        self.assertIn("scripts/release_gate.py --static-only", workflow)
        self.assertIn("scripts/stress_amaura.py", workflow)


if __name__ == "__main__":
    unittest.main()
