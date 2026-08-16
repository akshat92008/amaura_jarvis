"""
Long-Term Vector Memory & Knowledge Graph Module ("JARVIS Brain").
Combines dense vector embeddings, cosine similarity, and BM25 hybrid search for lifetime memory
with auto-summarization, compression, importance scoring, and pruning.
"""

import hashlib
import re
import sqlite3
import time

import numpy as np

from jarvis.paths import get_data_dir

VECTOR_MEMORY_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "remember_fact",
            "description": "Store a long-term fact, project detail, preference, architecture note, or past bug resolution into JARVIS Memory Brain with optional importance and tags.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fact": {
                        "type": "string",
                        "description": "Fact or knowledge string to store (e.g. 'GCP VM uses n1-standard-4 with NVIDIA T4 GPU').",
                    },
                    "category": {
                        "type": "string",
                        "description": "Category tag ('architecture', 'preference', 'config', 'bugfix', 'project', 'conversation').",
                        "default": "general",
                    },
                    "importance": {
                        "type": "number",
                        "description": "Importance score from 1.0 (normal) to 10.0 (critical).",
                        "default": 1.0,
                    },
                    "source": {
                        "type": "string",
                        "description": "Source of memory ('user', 'conversation', 'project', 'system').",
                        "default": "user",
                    },
                    "tags": {
                        "type": "string",
                        "description": "Comma-separated tags for memory indexing.",
                        "default": "",
                    },
                },
                "required": ["fact"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_memory",
            "description": "Recall long-term memories or facts matching a query from JARVIS Memory Brain using hybrid dense vector cosine similarity + BM25 search.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query or concept to recall."},
                    "category": {"type": "string", "description": "Optional category filter."},
                    "limit": {"type": "integer", "description": "Maximum number of memories to return.", "default": 10},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_memories",
            "description": "Summarize stored memories by category or project focus into consolidated knowledge insights.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Category to summarize (or omit for all categories)."}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compress_memories",
            "description": "Cluster highly similar memories and compress them into unified knowledge facts to save memory space.",
            "parameters": {
                "type": "object",
                "properties": {
                    "similarity_threshold": {
                        "type": "number",
                        "description": "Cosine similarity threshold for merging (default: 0.85).",
                        "default": 0.85,
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prune_memories",
            "description": "Clean up duplicate, low-importance, or obsolete memory entries from JARVIS Brain.",
            "parameters": {
                "type": "object",
                "properties": {
                    "min_importance": {
                        "type": "number",
                        "description": "Minimum importance threshold to keep.",
                        "default": 0.0,
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_project_memory",
            "description": "Search project-specific decisions, architecture choices, bugs, fixes, and preferences.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Project question or query."}},
                "required": ["query"],
            },
        },
    },
]


class VectorEmbeddingEngine:
    """
    Generates real 256-dimensional dense float vectors using n-gram feature hashing
    and L2 normalization for fast, deterministic semantic vector embedding.
    """

    DIMENSION = 256

    @classmethod
    def embed(cls, text: str) -> np.ndarray:
        """Create a deterministic local embedding without importing ML runtimes.

        Token and token-bigram features are mapped with BLAKE2b rather than
        Python's randomized ``hash()``. This keeps embeddings reproducible and
        avoids late BLAS/thread-pool initialization in long-running workers.
        """
        if not text or not text.strip():
            return np.zeros(cls.DIMENSION, dtype=np.float32)

        tokens = re.findall(r"[a-z0-9]+", text.lower())
        if not tokens:
            return np.zeros(cls.DIMENSION, dtype=np.float32)

        features = [f"u:{token}" for token in tokens]
        features.extend(f"b:{left}_{right}" for left, right in zip(tokens, tokens[1:], strict=False))
        vec = np.zeros(cls.DIMENSION, dtype=np.float32)
        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest, "big") % cls.DIMENSION
            vec[index] += 1.0

        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return vec

    @classmethod
    def serialize_vector(cls, vec: np.ndarray) -> bytes:
        return vec.tobytes()

    @classmethod
    def deserialize_vector(cls, data: bytes | None) -> np.ndarray:
        if not data:
            return np.zeros(cls.DIMENSION, dtype=np.float32)
        try:
            return np.frombuffer(data, dtype=np.float32)
        except Exception:
            return np.zeros(cls.DIMENSION, dtype=np.float32)

    @classmethod
    def cosine_similarity(cls, vec1: np.ndarray, vec2: np.ndarray) -> float:
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(vec1, vec2) / (norm1 * norm2))


class JarvisVectorBrain:
    def __init__(self, db_path: str | None = None):
        if not db_path:
            db_path = str(get_data_dir() / "vector_brain.db")
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fact TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                importance REAL DEFAULT 1.0,
                embedding BLOB,
                source TEXT DEFAULT 'user',
                tags TEXT DEFAULT '',
                access_count INTEGER DEFAULT 0,
                last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        # Check for missing columns in existing table (backward compatibility migration)
        cursor.execute("PRAGMA table_info(memories)")
        columns = [col[1] for col in cursor.fetchall()]
        migrations = [
            ("importance", "REAL DEFAULT 1.0"),
            ("embedding", "BLOB"),
            ("source", "TEXT DEFAULT 'user'"),
            ("tags", "TEXT DEFAULT ''"),
            ("access_count", "INTEGER DEFAULT 0"),
            ("last_accessed", "TEXT"),
        ]
        for col_name, col_def in migrations:
            if col_name not in columns:
                cursor.execute(f"ALTER TABLE memories ADD COLUMN {col_name} {col_def}")

        conn.commit()
        conn.close()

    def remember(
        self, fact: str, category: str = "general", importance: float = 1.0, source: str = "user", tags: str = ""
    ) -> str:
        if not fact or not fact.strip():
            return "❌ Memory fact cannot be empty."

        fact = fact.strip()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Check for exact duplicate
        cursor.execute("SELECT id, importance FROM memories WHERE fact = ?", (fact,))
        row = cursor.fetchone()
        if row:
            mem_id = row[0]
            # Update importance if higher
            if importance > (row[1] or 1.0):
                cursor.execute("UPDATE memories SET importance = ? WHERE id = ?", (importance, mem_id))
                conn.commit()
            conn.close()
            return f"🧠 **Fact already present in JARVIS Brain!** (ID: #{mem_id})"

        # Generate real dense vector embedding
        vec = VectorEmbeddingEngine.embed(fact)
        vec_bytes = VectorEmbeddingEngine.serialize_vector(vec)

        cursor.execute(
            """
            INSERT INTO memories (fact, category, importance, embedding, source, tags)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (fact, category, float(importance), vec_bytes, source, tags),
        )
        conn.commit()
        mem_id = cursor.lastrowid
        conn.close()

        return (
            f"🧠 **Memory Saved to Vector Brain!** (ID: #{mem_id})\n"
            f"- **Category:** `{category}`\n"
            f"- **Importance:** `{importance:.1f}/10.0`\n"
            f'- **Fact:** "{fact}"'
        )

    def recall(self, query: str, category: str | None = None, limit: int = 10) -> str:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if category:
            cursor.execute(
                "SELECT id, fact, category, importance, embedding, source, tags, access_count, created_at FROM memories WHERE category = ?",
                (category,),
            )
        else:
            cursor.execute(
                "SELECT id, fact, category, importance, embedding, source, tags, access_count, created_at FROM memories"
            )

        rows = cursor.fetchall()
        if not rows:
            conn.close()
            return "🧠 No matching memories found in JARVIS Brain."

        # Compute query dense embedding
        query_vec = VectorEmbeddingEngine.embed(query)
        query_words = set(query.lower().split())

        scored = []
        for r in rows:
            mem_id, fact, cat, importance, emb_bytes, src, tags, access_count, created_at = r
            importance = importance if importance is not None else 1.0

            # 1. Cosine similarity score
            mem_vec = VectorEmbeddingEngine.deserialize_vector(emb_bytes)
            cos_sim = VectorEmbeddingEngine.cosine_similarity(query_vec, mem_vec)

            # 2. BM25 / Keyword overlap score
            fact_words = set(fact.lower().split())
            keyword_score = sum(1.0 for w in query_words if w in fact_words) / max(1, len(query_words))

            # 3. Combined hybrid score (60% Dense Vector + 30% Keyword + 10% Importance)
            importance_weight = min(1.0, (importance / 10.0))
            hybrid_score = (0.6 * cos_sim) + (0.3 * keyword_score) + (0.1 * importance_weight)

            if hybrid_score > 0.05 or keyword_score > 0:
                scored.append((hybrid_score, r))

        scored.sort(key=lambda x: x[0], reverse=True)

        if not scored:
            scored = [(0.0, r) for r in rows[-limit:]]

        # Update access count & last_accessed timestamp for returned memories
        top_matches = scored[:limit]
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        for _, r in top_matches:
            mem_id = r[0]
            cursor.execute(
                "UPDATE memories SET access_count = access_count + 1, last_accessed = ? WHERE id = ?", (now_str, mem_id)
            )
        conn.commit()
        conn.close()

        results = [f"🧠 **JARVIS Brain Recalled ({len(top_matches)} semantic matches):**\n"]
        for score, r in top_matches:
            mem_id, fact, cat, imp, _, src, tags, _, _ = r
            imp_val = imp if imp is not None else 1.0
            results.append(f"• **[#{mem_id}] ({cat})** *(Score: {score:.2f}, Imp: {imp_val:.1f})*: {fact}")

        return "\n".join(results)

    def summarize(self, category: str | None = None) -> str:
        """Summarize stored memories by category or project focus."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        if category:
            cursor.execute(
                "SELECT fact, category, importance FROM memories WHERE category = ? ORDER BY importance DESC",
                (category,),
            )
        else:
            cursor.execute("SELECT fact, category, importance FROM memories ORDER BY category, importance DESC")
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return "🧠 No memories available to summarize."

        by_cat: dict[str, list[tuple[str, float]]] = {}
        for fact, cat, imp in rows:
            by_cat.setdefault(cat or "general", []).append((fact, imp or 1.0))

        summary_lines = ["📊 **JARVIS Memory Summary & Knowledge Map**\n"]
        for cat, facts in by_cat.items():
            summary_lines.append(f"### Category: `{cat.upper()}` ({len(facts)} entries)")
            for fact, imp in facts[:5]:
                summary_lines.append(f" - [Importance: {imp:.1f}] {fact}")
            if len(facts) > 5:
                summary_lines.append(f" - *...and {len(facts) - 5} more entries*")
            summary_lines.append("")

        return "\n".join(summary_lines)

    def compress(self, similarity_threshold: float = 0.85) -> str:
        """Cluster highly similar memories and merge them into consolidated entries."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, fact, category, importance, embedding FROM memories")
        rows = cursor.fetchall()
        if len(rows) < 2:
            conn.close()
            return "🧠 Insufficient memories to compress."

        merged_ids = set()
        merged_count = 0

        for i in range(len(rows)):
            id1, fact1, cat1, imp1, emb1 = rows[i]
            if id1 in merged_ids:
                continue

            vec1 = VectorEmbeddingEngine.deserialize_vector(emb1)
            cluster = [rows[i]]

            for j in range(i + 1, len(rows)):
                id2, fact2, cat2, imp2, emb2 = rows[j]
                if id2 in merged_ids or cat1 != cat2:
                    continue

                vec2 = VectorEmbeddingEngine.deserialize_vector(emb2)
                sim = VectorEmbeddingEngine.cosine_similarity(vec1, vec2)
                if sim >= similarity_threshold:
                    cluster.append(rows[j])

            if len(cluster) > 1:
                # Combine facts
                facts = [c[1] for c in cluster]
                max_imp = max((c[3] or 1.0) for c in cluster)
                combined_fact = " | ".join(dict.fromkeys(facts))  # preserve order & unique

                # Keep the first memory ID, update it, and delete the rest
                keep_id = cluster[0][0]
                new_vec = VectorEmbeddingEngine.embed(combined_fact)
                new_emb_bytes = VectorEmbeddingEngine.serialize_vector(new_vec)

                cursor.execute(
                    "UPDATE memories SET fact = ?, importance = ?, embedding = ? WHERE id = ?",
                    (combined_fact, max_imp, new_emb_bytes, keep_id),
                )

                for c in cluster[1:]:
                    merged_ids.add(c[0])
                    cursor.execute("DELETE FROM memories WHERE id = ?", (c[0],))
                merged_count += len(cluster) - 1

        conn.commit()
        conn.close()
        return f"🧠 **JARVIS Brain Compressed:** Merged {merged_count} highly similar memory entries."

    def prune(self, min_importance: float = 0.0) -> str:
        """Removes exact duplicates and low-importance records."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM memories WHERE rowid NOT IN (SELECT MIN(rowid) FROM memories GROUP BY fact)")
        dups_deleted = cursor.rowcount

        importance_deleted = 0
        if min_importance > 0.0:
            cursor.execute("DELETE FROM memories WHERE importance < ?", (min_importance,))
            importance_deleted = cursor.rowcount

        conn.commit()
        conn.close()
        return f"🧠 **JARVIS Brain Pruned:** Cleaned {dups_deleted} duplicate and {importance_deleted} low-importance memory records."

    def search_project_memory(self, query: str) -> str:
        """Specialized search across project decisions, architecture, bugs, and fixes."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, fact, category, importance, embedding, source, tags, access_count, created_at FROM memories WHERE category IN ('architecture', 'project', 'bugfix', 'config', 'preference')"
        )
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return self.recall(query)

        query_vec = VectorEmbeddingEngine.embed(query)
        scored = []
        for r in rows:
            mem_vec = VectorEmbeddingEngine.deserialize_vector(r[4])
            sim = VectorEmbeddingEngine.cosine_similarity(query_vec, mem_vec)
            scored.append((sim, r))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = ["📌 **JARVIS Project Memory Recalled:**\n"]
        for score, r in scored[:5]:
            results.append(f"• **[#{r[0]}] ({r[2]})** *(Relevance: {score:.2f})*: {r[1]}")
        return "\n".join(results)


_brain_instance = JarvisVectorBrain()


def remember_fact(
    fact: str, category: str = "general", importance: float = 1.0, source: str = "user", tags: str = ""
) -> str:
    return _brain_instance.remember(fact, category, importance, source, tags)


def recall_memory(query: str, category: str | None = None, limit: int = 10) -> str:
    return _brain_instance.recall(query, category, limit)


def summarize_memories(category: str | None = None) -> str:
    return _brain_instance.summarize(category)


def compress_memories(similarity_threshold: float = 0.85) -> str:
    return _brain_instance.compress(similarity_threshold)


def prune_memories(min_importance: float = 0.0) -> str:
    return _brain_instance.prune(min_importance)


def search_project_memory(query: str) -> str:
    return _brain_instance.search_project_memory(query)


VECTOR_MEMORY_DISPATCH = {
    "remember_fact": remember_fact,
    "recall_memory": recall_memory,
    "summarize_memories": summarize_memories,
    "compress_memories": compress_memories,
    "prune_memories": prune_memories,
    "search_project_memory": search_project_memory,
}
