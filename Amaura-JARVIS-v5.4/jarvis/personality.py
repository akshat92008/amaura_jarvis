from __future__ import annotations

import json
import logging
import random
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from jarvis.paths import get_data_dir

log = logging.getLogger(__name__)

STATE_FILE = get_data_dir() / "personality_state.json"


class PersonalityMode(StrEnum):
    LAB = "LAB"
    COMBAT = "COMBAT"
    MORNING = "MORNING"
    CARE = "CARE"
    STEALTH = "STEALTH"


PERSONALITY_SIGNATURES: dict[str, list[str]] = {
    "general": [
        "Right away, sir.",
        "Already done, sir.",
        "As always, sir, a great pleasure watching you work.",
    ],
    "completion": [
        "Will there be anything else, sir?",
        "Task complete. Shall I run diagnostics?",
    ],
    "error": [
        "We appear to have a situation, sir.",
        "I've identified the issue, sir.",
    ],
    "greeting": [
        "At your service, sir.",
        "Systems online and ready, sir.",
    ],
    "pushback": [
        "I'd advise against that, sir.",
        "If I may suggest an alternative, sir.",
    ],
    "farewell": [
        "Rest well, sir.",
        "I'll keep watch, sir.",
    ],
}


class FrustrationDetector:
    """Lightweight regex-based frustration detector."""

    PROFANITY_PATTERN = re.compile(r'\b(fuck|shit|damn|crap|hell|ass|bullshit)\b', re.IGNORECASE)
    FRUSTRATION_PHRASES = [
        r"this doesn'?t work",
        r"still broken",
        r"why won'?t",
        r"\bugh\b",
        r"come on",
        r"not again",
        r"this is ridiculous",
    ]
    FRUSTRATION_PATTERN = re.compile("|".join(FRUSTRATION_PHRASES), re.IGNORECASE)

    def detect(self, message: str, session_context: dict[str, Any] | None = None) -> float:
        """Calculate a frustration score from 0.0 to 1.0 based on message content."""
        score = 0.0
        
        # Check profanity (moderate bump)
        if self.PROFANITY_PATTERN.search(message):
            score += 0.3
            
        # Check frustration phrases (larger bump)
        if self.FRUSTRATION_PATTERN.search(message):
            score += 0.4
            
        # Check ALL CAPS (excluding short words or pure acronyms, simple heuristic: >50% uppercase letters)
        letters = [c for c in message if c.isalpha()]
        if len(letters) > 10:
            upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
            if upper_ratio > 0.6:
                score += 0.3
                
        # Additional bump if repeated similar queries could be tracked in session_context, 
        # but kept simple here.
        if session_context and session_context.get("repeated_errors", False):
            score += 0.2

        return min(1.0, score)


@dataclass
class PersonalityState:
    mode: PersonalityMode = PersonalityMode.LAB
    session_start: str | None = None
    interactions_today: int = 0
    last_frustration_score: float = 0.0
    last_interaction_date: str | None = None


class PersonalityEngine:
    """Dynamic Personality Engine for JARVIS."""

    def __init__(self) -> None:
        self._state = PersonalityState()
        self._lock = threading.RLock()
        self._detector = FrustrationDetector()
        self.load_state()

    @property
    def mode(self) -> PersonalityMode:
        with self._lock:
            return self._state.mode

    @property
    def session_start(self) -> datetime | None:
        with self._lock:
            if self._state.session_start:
                try:
                    return datetime.fromisoformat(self._state.session_start)
                except ValueError:
                    pass
            return None

    @property
    def interactions_today(self) -> int:
        with self._lock:
            return self._state.interactions_today

    @property
    def last_frustration_score(self) -> float:
        with self._lock:
            return self._state.last_frustration_score

    def determine_mode(
        self,
        user_message: str,
        time_context: dict[str, Any] | None = None,
        session_context: dict[str, Any] | None = None,
    ) -> PersonalityMode:
        """Determine the appropriate personality mode based on context and input."""
        with self._lock:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            
            # Reset daily interactions if it's a new day
            if self._state.last_interaction_date != today_str:
                self._state.interactions_today = 0
                self._state.last_interaction_date = today_str

            # Morning check
            is_morning = 5 <= now.hour < 11
            if self._state.interactions_today == 0 and is_morning:
                self._state.mode = PersonalityMode.MORNING
                return self._state.mode

            # Frustration check
            frustration = self._detector.detect(user_message, session_context)
            if frustration > 0.6:
                self._state.mode = PersonalityMode.CARE
                return self._state.mode

            # Combat / Debugging check
            combat_keywords = r"(error|traceback|exception|debug|failed|stack trace)"
            if re.search(combat_keywords, user_message, re.IGNORECASE):
                self._state.mode = PersonalityMode.COMBAT
                return self._state.mode

            # Default
            self._state.mode = PersonalityMode.LAB
            return self._state.mode

    def get_personality_prompt(self) -> str:
        """Get the dynamic personality section for the system prompt based on the current mode."""
        with self._lock:
            mode = self._state.mode
            
        if mode == PersonalityMode.COMBAT:
            return (
                "Respond in combat mode: terse, action-first, single-clause answers. "
                "Skip pleasantries. Diagnose and fix."
            )
        elif mode == PersonalityMode.MORNING:
            return (
                "Begin with a warm time-appropriate greeting. Deliver any pending briefing. "
                "Be optimistic."
            )
        elif mode == PersonalityMode.CARE:
            return (
                "The user appears frustrated. Be patient, empathetic but not patronizing. "
                "Focus on solutions. Skip humor."
            )
        elif mode == PersonalityMode.STEALTH:
            return "Background task mode. Minimal output, just confirmations."
        else:
            return (
                "You speak with a refined British accent and dry wit. You are loyal, "
                "proactive, intelligent, and occasionally sarcastic. Address the user as 'sir' "
                "naturally. Keep responses concise and elegant."
            )

    def get_random_jarvis_phrase(self, context: str = 'general') -> str | None:
        """Returns a contextually appropriate JARVIS signature phrase with a 20% probability."""
        if random.random() > 0.2:
            return None
        phrases = PERSONALITY_SIGNATURES.get(context)
        if not phrases:
            return None
        return random.choice(phrases)

    def get_anti_sycophancy_check(self, user_message: str) -> str | None:
        """Return a pushback prompt injection if needed (simple heuristic)."""
        risky_keywords = r"(rm -rf|drop table|delete all|chmod 777|kill -9|force push|--force)"
        if re.search(risky_keywords, user_message, re.IGNORECASE):
            return (
                "If the user's approach has obvious flaws or is risky, respectfully push back "
                "with facts. Do not agree just to be agreeable. Use phrases like 'Sir, that "
                "approach may...' or 'If I may suggest an alternative...'"
            )
        return None

    def record_interaction(self, frustration_score: float) -> None:
        """Track interaction and update state."""
        with self._lock:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            
            if self._state.last_interaction_date != today_str:
                self._state.interactions_today = 0
                self._state.last_interaction_date = today_str
                
            if self._state.session_start is None:
                self._state.session_start = now.isoformat()
                
            self._state.interactions_today += 1
            self._state.last_frustration_score = frustration_score
            self.save_state()

    def load_state(self) -> None:
        """Load personality state from disk."""
        with self._lock:
            if STATE_FILE.exists():
                try:
                    with open(STATE_FILE, encoding="utf-8") as f:
                        data = json.load(f)
                    
                    # Ensure mode is casted properly if it matches the enum
                    if "mode" in data:
                        try:
                            data["mode"] = PersonalityMode(data["mode"])
                        except ValueError:
                            data["mode"] = PersonalityMode.LAB

                    # Update internal state with valid keys
                    valid_keys = {f.name for f in PersonalityState.__dataclass_fields__.values()}
                    filtered_data = {k: v for k, v in data.items() if k in valid_keys}
                    self._state = PersonalityState(**filtered_data)
                except (json.JSONDecodeError, OSError, TypeError) as e:
                    log.warning(f"Failed to load personality state, starting fresh. Error: {e}")
                    self._state = PersonalityState()
            else:
                self._state = PersonalityState()

    def save_state(self) -> None:
        """Save personality state to disk."""
        with self._lock:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            try:
                with open(STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump(asdict(self._state), f, indent=2)
            except OSError as e:
                log.error(f"Failed to save personality state: {e}")


_engine_instance: PersonalityEngine | None = None
_engine_lock = threading.Lock()

def get_personality() -> PersonalityEngine:
    """Get the thread-safe singleton instance of PersonalityEngine."""
    global _engine_instance
    with _engine_lock:
        if _engine_instance is None:
            _engine_instance = PersonalityEngine()
        return _engine_instance
