"""
User Memory — persistent personal knowledge that persists across sessions.
Stores personal facts, preferences, and routines in ~/.jarvis/personal.json.
Extended from Nexus with personal assistant capabilities.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from jarvis.paths import get_data_dir


PREFS_FILE = get_data_dir() / "personal.json"


@dataclass
class PersonalMemory:
    """Persistent personal knowledge about the user."""
    # Identity
    name: str = ""
    nickname: str = ""

    # Preferences
    preferred_model: str = ""
    preferred_language: str = ""
    theme: str = "dark"
    verbose: bool = True
    voice_enabled: bool = False
    voice_name: str = "Daniel"  # macOS voice

    # Personal facts the user has shared
    facts: list[str] = field(default_factory=list)

    # Work preferences
    work_conventions: list[str] = field(default_factory=list)
    coding_style: dict[str, str] = field(default_factory=dict)

    # Things Jarvis has learned NOT to do
    corrections: list[dict] = field(default_factory=list)
    disliked_patterns: list[str] = field(default_factory=list)

    # Routines
    morning_routine: list[str] = field(default_factory=list)
    evening_routine: list[str] = field(default_factory=list)

    # Frequently used paths
    favorite_directories: list[str] = field(default_factory=list)

    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_prompt_addon(self) -> str:
        """Generate a system prompt addon from personal knowledge."""
        parts = []

        if self.name:
            parts.append("[PERSONAL KNOWLEDGE — About the User]")
            parts.append(f"  Name: {self.name}")
            if self.nickname:
                parts.append(f"  Preferred name: {self.nickname}")

        if self.facts:
            if not parts:
                parts.append("[PERSONAL KNOWLEDGE — About the User]")
            parts.append("  Known facts:")
            for fact in self.facts[-20:]:
                parts.append(f"    • {fact}")

        if self.work_conventions:
            parts.append("  Work conventions:")
            for conv in self.work_conventions:
                parts.append(f"    • {conv}")

        if self.coding_style:
            parts.append("  Coding style:")
            for key, value in self.coding_style.items():
                parts.append(f"    {key}: {value}")

        if self.corrections:
            recent = self.corrections[-5:]
            parts.append("  Learned corrections (apply these going forward):")
            for corr in recent:
                parts.append(f"    • {corr.get('lesson', '')}")

        if self.disliked_patterns:
            parts.append("  Avoid these patterns:")
            for pattern in self.disliked_patterns:
                parts.append(f"    ✗ {pattern}")

        if parts:
            parts.append("[END PERSONAL KNOWLEDGE]")
            return "\n".join(parts)
        return ""


class UserMemory:
    """Manages persistent personal knowledge across sessions."""

    def __init__(self):
        self._prefs: PersonalMemory | None = None

    def load(self) -> PersonalMemory:
        """Load personal memory from disk."""
        if self._prefs is not None:
            return self._prefs

        PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)

        if PREFS_FILE.exists():
            try:
                with open(PREFS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._prefs = PersonalMemory(**{
                    k: v for k, v in data.items()
                    if k in PersonalMemory.__dataclass_fields__
                })
            except (json.JSONDecodeError, OSError, TypeError):
                self._prefs = PersonalMemory()
        else:
            self._prefs = PersonalMemory()

        return self._prefs

    def save(self):
        """Save personal memory to disk."""
        prefs = self.load()
        prefs.updated_at = datetime.now().isoformat()
        PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PREFS_FILE, "w", encoding="utf-8") as f:
            json.dump(asdict(prefs), f, indent=2)

    def set_name(self, name: str):
        """Set the user's name."""
        prefs = self.load()
        prefs.name = name
        self.save()

    def add_fact(self, fact: str):
        """Remember a personal fact about the user."""
        prefs = self.load()
        if fact not in prefs.facts:
            prefs.facts.append(fact)
            if len(prefs.facts) > 200:
                prefs.facts = prefs.facts[-200:]
            self.save()
            try:
                from jarvis.tools.vector_memory import remember_fact
                remember_fact(fact, category="preference", importance=8.0, source="personal_memory")
            except Exception:
                pass

    def add_convention(self, convention: str):
        """Add a work convention."""
        prefs = self.load()
        if convention not in prefs.work_conventions:
            prefs.work_conventions.append(convention)
            if len(prefs.work_conventions) > 50:
                prefs.work_conventions = prefs.work_conventions[-50:]
            self.save()
            try:
                from jarvis.tools.vector_memory import remember_fact
                remember_fact(convention, category="convention", importance=8.5, source="personal_memory")
            except Exception:
                pass

    def record_correction(self, lesson: str, context: str = ""):
        """Record something the user corrected."""
        prefs = self.load()
        prefs.corrections.append({
            "lesson": lesson,
            "context": context,
            "timestamp": datetime.now().isoformat(),
        })
        if len(prefs.corrections) > 100:
            prefs.corrections = prefs.corrections[-100:]
        self.save()
        try:
            from jarvis.tools.vector_memory import remember_fact
            corr_text = f"Correction: {lesson}. Context: {context}" if context else f"Correction: {lesson}"
            remember_fact(corr_text, category="correction", importance=9.0, source="personal_memory")
        except Exception:
            pass

    def set_preference(self, key: str, value) -> bool:
        """Set a preference."""
        prefs = self.load()
        if hasattr(prefs, key):
            setattr(prefs, key, value)
            self.save()
            return True
        return False

    def get_prompt_addon(self) -> str:
        """Get the system prompt addon."""
        prefs = self.load()
        return prefs.to_prompt_addon()

    def get_summary(self) -> str:
        """Human-readable summary of personal memory."""
        prefs = self.load()
        lines = ["👤 Personal Memory"]
        if prefs.name:
            lines.append(f"  Name: {prefs.name}")
        lines.append(f"  Known facts: {len(prefs.facts)}")
        lines.append(f"  Conventions: {len(prefs.work_conventions)}")
        lines.append(f"  Corrections: {len(prefs.corrections)}")
        lines.append(f"  Voice: {'enabled' if prefs.voice_enabled else 'disabled'}")
        lines.append(f"  Updated: {prefs.updated_at[:19]}")
        return "\n".join(lines)

    def reset(self):
        """Reset all personal memory."""
        self._prefs = PersonalMemory()
        self.save()
