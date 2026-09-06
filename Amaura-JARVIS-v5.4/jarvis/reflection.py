"""
Post-Mission Reflection & Self-Learning system for JARVIS.
Stores lessons learned from tasks to improve future performance.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime

from jarvis.paths import get_data_dir

DB_PATH = get_data_dir() / "lessons_learned.db"

@dataclass
class Lesson:
    """A single lesson learned from a task."""
    id: str
    timestamp: str
    task_summary: str
    outcome: str
    tools_used: list[str]
    errors_encountered: list[str]
    user_corrections: list[str]
    lesson_learned: str
    category: str
    relevance_keywords: list[str]
    times_recalled: int = 0


@dataclass
class TaskLog:
    """A log of a completed task to be analyzed."""
    task_id: str
    user_prompt: str
    messages: list[dict]
    tools_called: list[dict]
    duration_seconds: float
    final_outcome: str
    user_corrections: list[str] = field(default_factory=list)


class PostMissionReflector:
    """Analyzes task logs and extracts lessons learned for future use."""

    def __init__(self):
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        """Initialize the SQLite database for lessons learned."""
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS lessons (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    task_summary TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    tools_used TEXT,
                    errors TEXT,
                    user_corrections TEXT,
                    lesson_learned TEXT NOT NULL,
                    category TEXT,
                    relevance_keywords TEXT,
                    times_recalled INTEGER DEFAULT 0
                )
                """
            )

    def reflect(self, task_log: TaskLog) -> Lesson:
        """Analyze a task log and extract a lesson learned."""
        # Heuristic analysis to determine errors, tools, and categories
        errors = []
        tools_used = []
        for tool in task_log.tools_called:
            tool_name = tool.get("name", "unknown")
            if tool_name not in tools_used:
                tools_used.append(tool_name)
            
            result = tool.get("result_summary", "").lower()
            if "error" in result or "exception" in result or "fail" in result:
                errors.append(f"{tool_name} failed: {result[:100]}")

        # Determine category
        category = "system"
        prompt_lower = task_log.user_prompt.lower()
        if any(word in prompt_lower for word in ["code", "python", "bug", "fix", "script"]):
            category = "coding"
        elif any(word in prompt_lower for word in ["debug", "error", "stacktrace"]):
            category = "debugging"
        elif any(word in prompt_lower for word in ["research", "search", "find", "look up"]):
            category = "research"
        elif "explain" in prompt_lower or "summary" in prompt_lower:
            category = "communication"

        # Generate lesson_learned string based on heuristics
        lesson_learned = ""
        if errors and task_log.final_outcome != "success":
            lesson_learned = f"Avoid patterns leading to errors: {'; '.join(errors[:2])}."
        elif task_log.user_corrections:
            lesson_learned = f"User prefers: {'; '.join(task_log.user_corrections)}."
        elif task_log.final_outcome == "success":
            lesson_learned = f"Successfully used {', '.join(tools_used[:3])} to accomplish: {task_log.user_prompt[:50]}."
        else:
            lesson_learned = f"Task resulted in {task_log.final_outcome}. Tools used: {', '.join(tools_used[:3])}."

        # Extract keywords
        relevance_keywords = list(set([word for word in task_log.user_prompt.lower().split() if len(word) > 4][:10]))

        lesson = Lesson(
            id=str(uuid.uuid4()),
            timestamp=datetime.now().isoformat(),
            task_summary=task_log.user_prompt[:200],
            outcome=task_log.final_outcome,
            tools_used=tools_used,
            errors_encountered=errors,
            user_corrections=task_log.user_corrections,
            lesson_learned=lesson_learned,
            category=category,
            relevance_keywords=relevance_keywords
        )

        with self._lock, sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO lessons (
                    id, timestamp, task_summary, outcome, tools_used,
                    errors, user_corrections, lesson_learned, category, relevance_keywords
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lesson.id,
                    lesson.timestamp,
                    lesson.task_summary,
                    lesson.outcome,
                    json.dumps(lesson.tools_used),
                    json.dumps(lesson.errors_encountered),
                    json.dumps(lesson.user_corrections),
                    lesson.lesson_learned,
                    lesson.category,
                    json.dumps(lesson.relevance_keywords)
                )
            )
        
        return lesson

    def _row_to_lesson(self, row: tuple) -> Lesson:
        return Lesson(
            id=row[0],
            timestamp=row[1],
            task_summary=row[2],
            outcome=row[3],
            tools_used=json.loads(row[4] or "[]"),
            errors_encountered=json.loads(row[5] or "[]"),
            user_corrections=json.loads(row[6] or "[]"),
            lesson_learned=row[7],
            category=row[8],
            relevance_keywords=json.loads(row[9] or "[]"),
            times_recalled=row[10]
        )

    def pre_flight_check(self, task_description: str, limit: int = 3) -> list[Lesson]:
        """Query lessons DB for past experiences relevant to the new task."""
        keywords = [word for word in task_description.lower().split() if len(word) > 3]
        
        with self._lock, sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute("SELECT * FROM lessons")
            rows = cursor.fetchall()
            
        scored_lessons = []
        for row in rows:
            lesson = self._row_to_lesson(row)
            score = 0
            
            # Simple keyword matching
            for kw in keywords:
                if kw in lesson.task_summary.lower():
                    score += 2
                if any(kw in rkw.lower() for rkw in lesson.relevance_keywords):
                    score += 1
            
            if score > 0:
                scored_lessons.append((score, lesson))
                
        scored_lessons.sort(key=lambda x: x[0], reverse=True)
        top_lessons = [l for _, l in scored_lessons[:limit]]
        
        if top_lessons:
            # Update times_recalled
            with self._lock, sqlite3.connect(DB_PATH) as conn:
                for lesson in top_lessons:
                    conn.execute("UPDATE lessons SET times_recalled = times_recalled + 1 WHERE id = ?", (lesson.id,))
                    lesson.times_recalled += 1
                    
        return top_lessons

    def get_pre_flight_prompt(self, task_description: str) -> str | None:
        """Format relevant lessons as a system prompt section."""
        lessons = self.pre_flight_check(task_description)
        if not lessons:
            return None
            
        lines = ["[LESSONS FROM PAST EXPERIENCE]"]
        for lesson in lessons:
            date_str = lesson.timestamp[:10]
            if lesson.user_corrections:
                lines.append(f"• {lesson.lesson_learned} (corrected on {date_str})")
            elif lesson.outcome != "success":
                lines.append(f"• {lesson.lesson_learned} (learned from failure on {date_str})")
            else:
                lines.append(f"• {lesson.lesson_learned} (learned from success on {date_str})")
                
        return "\n".join(lines)

    def get_stats(self) -> dict:
        """Return statistics about lessons learned."""
        with self._lock, sqlite3.connect(DB_PATH) as conn:
            total = conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
            successes = conn.execute("SELECT COUNT(*) FROM lessons WHERE outcome = 'success'").fetchone()[0]
            failures = conn.execute("SELECT COUNT(*) FROM lessons WHERE outcome = 'failure'").fetchone()[0]
            partials = conn.execute("SELECT COUNT(*) FROM lessons WHERE outcome = 'partial'").fetchone()[0]
            
            categories_rows = conn.execute("SELECT category, COUNT(*) as c FROM lessons GROUP BY category ORDER BY c DESC LIMIT 5").fetchall()
            top_categories = [{"category": row[0], "count": row[1]} for row in categories_rows]
            
            # Simple most common errors extraction
            errors_rows = conn.execute("SELECT errors FROM lessons WHERE errors != '[]'").fetchall()
            error_counts = {}
            for row in errors_rows:
                err_list = json.loads(row[0] or "[]")
                for err in err_list:
                    # Simplify error string to group them
                    simplified = err.split(":")[0] if ":" in err else err
                    error_counts[simplified] = error_counts.get(simplified, 0) + 1
                    
            most_common_errors = [{"error": k, "count": v} for k, v in sorted(error_counts.items(), key=lambda item: item[1], reverse=True)[:5]]
            
        return {
            "total_lessons": total,
            "successes": successes,
            "failures": failures,
            "partials": partials,
            "most_common_errors": most_common_errors,
            "top_categories": top_categories
        }

    def search_lessons(self, query: str, limit: int = 5) -> list[Lesson]:
        """Full-text search across lessons."""
        query_lower = query.lower()
        with self._lock, sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute("SELECT * FROM lessons")
            rows = cursor.fetchall()
            
        results = []
        for row in rows:
            lesson = self._row_to_lesson(row)
            if (query_lower in lesson.task_summary.lower() or 
                query_lower in lesson.lesson_learned.lower() or 
                any(query_lower in kw for kw in lesson.relevance_keywords)):
                results.append(lesson)
                
        return results[:limit]


# Thread-safe singleton
_instance = None
_instance_lock = threading.Lock()

def get_reflector() -> PostMissionReflector:
    """Get or create the singleton PostMissionReflector instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = PostMissionReflector()
    return _instance


REFLECTION_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_lessons",
            "description": "Search past lessons learned by JARVIS.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to find relevant past lessons."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return.",
                        "default": 5
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_learning_stats",
            "description": "Get statistics about what JARVIS has learned from past missions.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]


def tool_search_lessons(query: str, limit: int = 5) -> str:
    """Execute search_lessons tool."""
    reflector = get_reflector()
    results = reflector.search_lessons(query=query, limit=limit)
    return json.dumps([asdict(r) for r in results], indent=2)


def tool_get_learning_stats() -> str:
    """Execute get_learning_stats tool."""
    reflector = get_reflector()
    return json.dumps(reflector.get_stats(), indent=2)


REFLECTION_DISPATCH = {
    "search_lessons": tool_search_lessons,
    "get_learning_stats": tool_get_learning_stats,
}
