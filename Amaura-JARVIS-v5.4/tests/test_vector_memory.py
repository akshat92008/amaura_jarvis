import unittest
import tempfile
import os
import numpy as np
from jarvis.tools.vector_memory import JarvisVectorBrain, VectorEmbeddingEngine

class TestVectorMemory(unittest.TestCase):
    def setUp(self):
        self.db_file = tempfile.mktemp(suffix=".db")
        self.brain = JarvisVectorBrain(db_path=self.db_file)

    def tearDown(self):
        if os.path.exists(self.db_file):
            os.remove(self.db_file)

    def test_embeddings_and_cosine(self):
        vec1 = VectorEmbeddingEngine.embed("GCP VM uses n1-standard-4 with NVIDIA T4 GPU")
        vec2 = VectorEmbeddingEngine.embed("NVIDIA GPU on Google Cloud Platform")
        vec3 = VectorEmbeddingEngine.embed("Baking chocolate chip cookies in oven")
        
        self.assertEqual(len(vec1), 256)
        self.assertIsInstance(vec1, np.ndarray)
        
        sim_1_2 = VectorEmbeddingEngine.cosine_similarity(vec1, vec2)
        sim_1_3 = VectorEmbeddingEngine.cosine_similarity(vec1, vec3)
        self.assertGreater(sim_1_2, sim_1_3)

    def test_remember_and_recall(self):
        self.brain.remember("GCP VM uses n1-standard-4 with NVIDIA T4 GPU", "config", importance=8.0)
        recalled = self.brain.recall("GCP VM GPU")
        self.assertIn("NVIDIA T4 GPU", recalled)
        self.assertIn("Imp: 8.0", recalled)

    def test_importance_and_hybrid_scoring(self):
        self.brain.remember("Low priority note about logging", category="general", importance=1.0)
        self.brain.remember("CRITICAL: Always use n1-standard-4 with T4 GPU for model training", category="architecture", importance=9.5)
        
        recalled = self.brain.recall("training GPU")
        self.assertIn("CRITICAL", recalled)

    def test_summarization_and_compression(self):
        self.brain.remember("Use PostgreSQL for main relational database", category="architecture", importance=8.0)
        self.brain.remember("Use PostgreSQL for production database cluster", category="architecture", importance=7.5)
        self.brain.remember("PostgreSQL handles structured data tables", category="architecture", importance=6.0)
        
        summary = self.brain.summarize(category="architecture")
        self.assertIn("ARCHITECTURE", summary)
        self.assertIn("PostgreSQL", summary)
        
        compress_res = self.brain.compress(similarity_threshold=0.60)
        self.assertIn("Compressed", compress_res)

    def test_prune_memories(self):
        self.brain.remember("Duplicate note A", category="test", importance=1.0)
        self.brain.remember("Duplicate note A", category="test", importance=1.0)
        self.brain.remember("Low priority garbage", category="test", importance=0.5)
        
        prune_res = self.brain.prune(min_importance=0.8)
        self.assertIn("Cleaned", prune_res)

    def test_search_project_memory(self):
        self.brain.remember("Architecture decision: Use FastAPI and Playwright V2", category="architecture", importance=9.0)
        proj_mem = self.brain.search_project_memory("Playwright")
        self.assertIn("Playwright V2", proj_mem)

if __name__ == "__main__":
    unittest.main()
