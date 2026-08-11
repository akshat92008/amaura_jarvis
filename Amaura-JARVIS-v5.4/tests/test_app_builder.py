import unittest
import os
import shutil
import tempfile
from jarvis.tools.app_builder import create_fullstack_app

class TestAppBuilder(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_create_fullstack_app(self):
        result = create_fullstack_app(
            project_name="demo_app",
            description="A test todo app",
            stack="vite-react-fastapi",
            target_dir=self.test_dir
        )
        self.assertIn("Fullstack Application 'demo_app' Successfully Created", result)
        app_path = os.path.join(self.test_dir, "demo_app")
        self.assertTrue(os.path.exists(os.path.join(app_path, "backend", "main.py")))
        self.assertTrue(os.path.exists(os.path.join(app_path, "frontend", "index.html")))
        self.assertTrue(os.path.exists(os.path.join(app_path, "README.md")))

if __name__ == "__main__":
    unittest.main()
