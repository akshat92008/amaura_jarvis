"""Authoritative Session Mission Context for Amaura JARVIS.

Guarantees durable, session-anchored reference continuity across multi-turn
founder conversations, preventing pronoun references from leaking into global
historical tasks or spawning ungrounded duplicate goals in CompanyStore.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any

from jarvis.amaura.store import utc_now


@dataclass(slots=True)
class SessionAnchor:
    session_id: str
    goal_id: str
    updated_at: str
    reason: str


class SessionMissionContext:
    """Authoritative session-anchored mission context backed by CompanyStore."""

    NAMESPACE = "jarvis.session_context"

    DEICTIC_PRONOUNS = frozenset(
        {
            "it",
            "that",
            "this",
            "the task",
            "that task",
            "this task",
            "the mission",
            "that mission",
            "this mission",
            "the project",
            "that project",
            "this project",
            "the one",
            "that one",
            "this one",
            "that thing",
            "the thing",
            "the task i gave you",
            "task i gave you",
            "what i asked earlier",
            "what i asked you to build",
            "the same one",
            "same one",
            "its",
            "it's",
        }
    )

    CONTROL_VERBS = frozenset(
        {
            "continue",
            "resume",
            "execute",
            "run",
            "finish",
            "focus",
            "pause",
            "cancel",
            "approve",
            "proceed",
            "start",
            "work on",
        }
    )

    BARE_CONFIRMATIONS = frozenset(
        {
            "yes",
            "yep",
            "yeah",
            "okay",
            "ok",
            "sure",
            "proceed",
            "go ahead",
            "do it",
            "yes do it",
            "yes please",
            "go ahead with it",
        }
    )

    def __init__(self, control: Any) -> None:
        if hasattr(control, "store"):
            self.control = control
            self.store = control.store
        else:
            self.control = None
            self.store = control
        self._cache: dict[str, SessionAnchor] = {}
        self._lock = threading.Lock()

    def get_active_goal(self, session_id: str) -> str | None:
        """Get the authoritative active goal ID for this session."""
        if not session_id:
            return None
        with self._lock:
            cached = self._cache.get(session_id)
            if cached is not None:
                try:
                    item = self.store.get_work_item(cached.goal_id)
                    if item:
                        return cached.goal_id
                except Exception:
                    pass
                del self._cache[session_id]

        try:
            record = self.store.get_knowledge(self.NAMESPACE, session_id)
            val = record.get("value") or {}
            if isinstance(val, dict):
                goal_id = str(val.get("current_goal_id") or "")
                if goal_id:
                    try:
                        item = self.store.get_work_item(goal_id)
                        if item:
                            anchor = SessionAnchor(
                                session_id=session_id,
                                goal_id=goal_id,
                                updated_at=str(val.get("updated_at") or utc_now()),
                                reason=str(val.get("reason") or "persisted"),
                            )
                            with self._lock:
                                self._cache[session_id] = anchor
                            return goal_id
                    except Exception:
                        pass
        except Exception:
            pass
        return None

    def set_active_goal(self, session_id: str, goal_id: str, *, reason: str = "created") -> bool:
        """Set the authoritative active goal for a session after verifying it exists in CompanyStore."""
        if not session_id or not goal_id:
            return False
        try:
            item = self.store.get_work_item(goal_id)
            if not item:
                return False
        except Exception:
            return False

        now = utc_now()
        payload = {
            "current_goal_id": goal_id,
            "updated_at": now,
            "reason": reason,
        }
        try:
            self.store.upsert_knowledge(
                self.NAMESPACE,
                session_id,
                payload,
                [goal_id],
                "internal",
                "jarvis",
            )
        except Exception:
            pass

        with self._lock:
            self._cache[session_id] = SessionAnchor(
                session_id=session_id,
                goal_id=goal_id,
                updated_at=now,
                reason=reason,
            )
        return True

    def clear_active_goal(self, session_id: str) -> None:
        """Clear active goal binding for a session."""
        if not session_id:
            return
        with self._lock:
            self._cache.pop(session_id, None)
        try:
            self.store.delete_knowledge(self.NAMESPACE, session_id)
        except Exception:
            pass

    def list_session_goals(self, session_id: str) -> list[str]:
        """List all goal IDs associated with this session."""
        if not session_id:
            return []
        goals: list[str] = []
        active = self.get_active_goal(session_id)
        if active:
            goals.append(active)
        try:
            items = self.store.list_work_items(limit=200)
            for it in items:
                if it.get("item_type") == "programme":
                    meta = it.get("metadata") or {}
                    sess = meta.get("executive_session_id") or (meta.get("goal_request") or {}).get(
                        "metadata", {}
                    ).get("executive_session_id")
                    if sess == session_id:
                        gid = str(it.get("id") or "")
                        if gid and gid not in goals:
                            goals.append(gid)
        except Exception:
            pass
        return goals

    CONTROL_RE = re.compile(
        r"^(?:(?:bro|nah|please|hey|just|okay|ok|so|now|and|well|actually)\s+)?"
        r"(?:continue|resume|execute|run|finish|focus(?:\s+on)?|pause|cancel|approve|proceed(?:\s+with)?|start|work\s+on)"
        r"\s+(?:it|that|this|the\s+task|that\s+task|this\s+task|the\s+mission|that\s+mission|this\s+mission|the\s+project|that\s+project|this\s+project|the\s+game|that\s+game|this\s+game|the\s+one|that\s+one|this\s+one|the\s+thing|that\s+thing|this\s+thing|the\s+same(?:\s+one)?|my\s+current\s+project|current\s+project|active\s+task)"
        r"(?:\s+(?:first|now|please|immediately|already))?$",
        re.IGNORECASE,
    )

    @classmethod
    def is_referential_control_language(cls, text: str) -> bool:
        """Check if text is deictic/referential control or confirmation language."""
        clean = " ".join(str(text).strip().lower().split())
        clean_no_punct = re.sub(r"[?!.,;:]", "", clean).strip()
        if clean_no_punct in cls.BARE_CONFIRMATIONS:
            return True
        if len(clean.split()) > 10:
            return False
        return bool(cls.CONTROL_RE.match(clean_no_punct))

    @classmethod
    def is_pure_deictic_reference(cls, text: str) -> bool:
        """Check if query is purely referential/deictic without explicit named project content."""
        clean = " ".join(str(text).strip().lower().split())
        clean_no_punct = re.sub(r"[?!.,;:]", "", clean).strip()
        if clean_no_punct in cls.BARE_CONFIRMATIONS:
            return True
        if len(clean.split()) > 15:
            return False
        vague_phrases = (
            "what are the results of the task i gave you",
            "what are the results of the task",
            "what were the results of the task",
            "what is the result of the task",
            "what's its status",
            "whats its status",
            "what is its status",
            "status of that",
            "continue it",
            "continue that",
            "focus on that",
            "focus on that first",
            "execute it",
            "execute that",
            "execute the same one",
            "run it",
            "finish that",
            "did it finish",
            "what happened with that thing i asked",
            "what happened with that thing i asked you to build",
            "what happened with the thing i asked you to build",
            "what happened with that thing",
            "what happened with the thing",
            "go ahead with it",
        )
        if any(clean_no_punct.startswith(vp) or clean_no_punct == vp for vp in vague_phrases):
            return True
        return False
