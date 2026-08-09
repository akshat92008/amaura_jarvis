"""
Unit & Integration Tests for Project Fable-5 Engine Integration in JARVIS.
"""

import os
import shutil
import tempfile
import unittest

from jarvis.agent import JarvisAgent
from jarvis.fable_engine import (
    ASTIndexer,
    FablePlanner,
    MultiProviderRouter,
    SelfHealingDebugger,
    WorkspaceExecutor,
    load_config,
)
from jarvis.models import resolve_model


class TestFableEngineIntegration(unittest.TestCase):
    def setUp(self):
        self.orig_cwd = os.getcwd()
        self.test_dir = tempfile.mkdtemp()
        self.sample_py = os.path.join(self.test_dir, "sample.py")
        with open(self.sample_py, "w", encoding="utf-8") as f:
            f.write(
                "import os\n\n"
                "class CyberEngine:\n"
                "    def run(self, mode: str):\n"
                "        return mode.upper()\n\n"
                "def helper_func(a, b):\n"
                "    return a + b\n"
            )

    def tearDown(self):
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_config_loader(self):
        conf = load_config()
        self.assertIn("max_heal_attempts", conf)
        self.assertIn("ollama_url", conf)

    def test_router_providers(self):
        router = MultiProviderRouter()
        providers = router.get_available_providers()
        self.assertIn("ollama_local", providers)
        self.assertIn("mlx_local", providers)

    def test_router_generate_fallback(self):
        router = MultiProviderRouter()
        res = router.generate("Test prompt for autonomous fallback")
        self.assertIn("content", res)
        self.assertIn("provider", res)

    def test_ast_indexer(self):
        indexer = ASTIndexer(self.test_dir)
        symbols = indexer.parse_file("sample.py")
        self.assertIsNotNone(symbols)
        self.assertEqual(len(symbols["classes"]), 1)
        self.assertEqual(symbols["classes"][0]["name"], "CyberEngine")
        self.assertEqual(symbols["classes"][0]["methods"], ["run"])
        self.assertEqual(len(symbols["functions"]), 1)
        self.assertEqual(symbols["functions"][0]["name"], "helper_func")

        graph = indexer.build_symbol_graph()
        self.assertIn("sample.py", graph)

    def test_workspace_executor(self):
        executor = WorkspaceExecutor(self.test_dir)
        written = executor.write_file("sub/test.txt", "Hello Fable 5")
        self.assertTrue(os.path.exists(written))

        read_back = executor.read_file("sub/test.txt")
        self.assertEqual(read_back, "Hello Fable 5")

        cmd_res = executor.run_command("python3 sample.py")
        self.assertTrue(cmd_res["success"])

    def test_fable_planner(self):
        planner = FablePlanner()
        plan = planner.generate_plan_and_code("Create a game in python")
        self.assertIn("thinking", plan)
        self.assertIn("files", plan)
        self.assertTrue(len(plan["files"]) > 0)
        self.assertIn("test_command", plan)

    def test_self_healing_debugger(self):
        debugger = SelfHealingDebugger(self.test_dir, max_attempts=1)
        res = debugger.run_and_repair("python3 sample.py")
        self.assertTrue(res["success"])

    def test_model_resolver_aliases(self):
        cfg_fable = resolve_model("fable-5-reasoning")
        self.assertIsNotNone(cfg_fable)

        cfg_alias = resolve_model("fable-5-engine")
        self.assertIsNotNone(cfg_alias)
        self.assertEqual(cfg_fable["id"], cfg_alias["id"])

        cfg_mythos = resolve_model("mythos")
        self.assertIsNotNone(cfg_mythos)
        self.assertEqual(cfg_fable["id"], cfg_mythos["id"])

    def test_agent_run_fable_reasoning(self):
        agent = JarvisAgent(working_dir=self.test_dir)
        res = agent.run_fable_reasoning("build a python adventure game")
        self.assertIn("thinking", res)
        self.assertIn("files", res)
        self.assertIn("verification", res)


if __name__ == "__main__":
    unittest.main()
