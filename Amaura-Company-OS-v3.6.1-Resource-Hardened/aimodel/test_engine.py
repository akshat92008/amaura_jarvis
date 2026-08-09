"""
Integration Test Suite for Project Nexus-Coder / Fable-5 Engine.
Verifies config loading, router provider detection, AST indexing, file execution,
and self-healing debugger routines.
"""

import unittest
import os
import shutil
from pathlib import Path

from config import load_config, save_config
from router import MultiProviderRouter
from executor import WorkspaceExecutor
from ast_indexer import ASTIndexer
from debugger import SelfHealingDebugger


class TestNexusCoderEngine(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path("./test_sandbox").resolve()
        self.test_dir.mkdir(exist_ok=True)
        self.executor = WorkspaceExecutor(workspace_dir=self.test_dir)

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_01_config_loading(self):
        config = load_config()
        self.assertIn("ollama_url", config)
        self.assertIn("default_provider", config)

    def test_02_router_provider_discovery(self):
        router = MultiProviderRouter()
        providers = router.get_available_providers()
        self.assertIn("ollama_local", providers)
        self.assertIn("mlx_local", providers)

    def test_03_workspace_executor_file_operations(self):
        rel_path = "sample_module.py"
        code = "def hello():\n    return 'world'\n"
        written = self.executor.write_file(rel_path, code)
        self.assertTrue(Path(written).exists())
        
        read_code = self.executor.read_file(rel_path)
        self.assertEqual(read_code, code)

        cmd_res = self.executor.run_command("python3 sample_module.py")
        self.assertTrue(cmd_res["success"])

    def test_04_ast_indexer(self):
        indexer = ASTIndexer(workspace_dir=self.test_dir)
        code = "class Calculator:\n    def add(self, a, b):\n        return a + b\n"
        self.executor.write_file("calc.py", code)
        symbols = indexer.build_symbol_graph()
        self.assertIn("calc.py", symbols)

    def test_05_self_healing_execution(self):
        debugger = SelfHealingDebugger(workspace_dir=self.test_dir, max_attempts=2)
        # Write a passing test file
        self.executor.write_file("test_pass.py", "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n")
        res = debugger.run_and_repair("python3 -m unittest test_pass.py")
        self.assertTrue(res["success"])


if __name__ == "__main__":
    unittest.main()
