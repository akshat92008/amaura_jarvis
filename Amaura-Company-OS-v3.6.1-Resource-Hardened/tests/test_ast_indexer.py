import unittest
import os
import tempfile
import shutil
from jarvis.tools.ast_indexer import index_codebase_ast, search_symbol

class TestASTIndexer(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        sample_file = os.path.join(self.test_dir, "sample.py")
        with open(sample_file, "w") as f:
            f.write("class Calculator:\n    def add(self, a, b):\n        return a + b\n")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_index_and_search(self):
        idx_res = index_codebase_ast(self.test_dir)
        self.assertIn("AST Codebase Index Complete", idx_res)
        
        search_res = search_symbol("Calculator", self.test_dir)
        self.assertIn("class `Calculator`", search_res)

if __name__ == "__main__":
    unittest.main()
