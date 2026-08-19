"""Narrow mission-routing repairs discovered during v7 target-Mac qualification.

The repair keeps repository engineering work on the governed software-delivery
path. A deterministic repository-inspection capability may still handle genuine
read-only inspection, but it must never absorb a founder request that also asks
to repair/patch code through an engineering backend such as Antigravity.
"""

from __future__ import annotations

import re
from typing import Any

_INSTALLED = False

_REPOSITORY_CONTEXT_TOKENS = {
    "repo",
    "repository",
    "codebase",
}
_ENGINEERING_MUTATION_TOKENS = {
    "fix",
    "repair",
    "patch",
    "debug",
    "implement",
    "refactor",
    "modify",
    "change",
    "correct",
}
_ENGINEERING_SIGNAL_TOKENS = {
    "antigravity",
    "noryx",
    "coding",
    "bug",
    "test",
    "tests",
    "failing",
    "failure",
    "regression",
}
_ENGINEERING_MUTATION_PHRASES = (
    "smallest safe repair",
    "make the repair",
    "make a repair",
    "apply the fix",
    "apply a patch",
    "source modification",
    "source change",
)
_ENGINEERING_SIGNAL_PHRASES = (
    "root cause",
    "failing test",
    "tests are failing",
    "coding path",
    "coding backend",
    "engineering backend",
    "independently verify",
)


def _install_attr(obj: object, name: str, value: object) -> None:
    setattr(obj, name, value)


def _repository_engineering_request(request: Any) -> bool:
    """Return True only for repository work that asks for an engineering mutation."""
    text = str(getattr(request, "objective", "") or "").strip().lower()
    if not text:
        return False
    tokens = set(re.findall(r"[a-z0-9_+-]+", text))
    workspace = str(getattr(request, "workspace", "") or "").strip()

    repository_context = bool(workspace) or bool(tokens & _REPOSITORY_CONTEXT_TOKENS) or "current workspace" in text
    mutation_requested = bool(tokens & _ENGINEERING_MUTATION_TOKENS) or any(
        phrase in text for phrase in _ENGINEERING_MUTATION_PHRASES
    )
    engineering_signal = bool(tokens & _ENGINEERING_SIGNAL_TOKENS) or any(
        phrase in text for phrase in _ENGINEERING_SIGNAL_PHRASES
    )
    return repository_context and mutation_requested and engineering_signal


def install_v7_mission_repairs() -> None:
    """Prevent repository repair missions from collapsing into direct inspection."""
    global _INSTALLED
    if _INSTALLED:
        return

    from jarvis.amaura.brain import GoalCompiler
    from jarvis.amaura.models import GovernanceError

    current_classify = GoalCompiler.classify
    current_direct_plan = GoalCompiler._direct_action_plan
    if getattr(current_classify, "_amaura_v7_repository_engineering_guard", False):
        _INSTALLED = True
        return

    def classify_with_repository_engineering_precedence(self: Any, request: Any) -> Any:
        if _repository_engineering_request(request):
            return "software"
        return current_classify(self, request)

    def guarded_direct_action_plan(self: Any, request: Any, workspace: str) -> Any:
        if _repository_engineering_request(request):
            raise GovernanceError(
                "Repository engineering request cannot use direct_action; "
                "route it through the governed software delivery path"
            )
        return current_direct_plan(self, request, workspace)

    _install_attr(
        classify_with_repository_engineering_precedence,
        "_amaura_v7_repository_engineering_guard",
        True,
    )
    _install_attr(GoalCompiler, "classify", classify_with_repository_engineering_precedence)
    _install_attr(GoalCompiler, "_direct_action_plan", guarded_direct_action_plan)
    _INSTALLED = True


__all__ = ["install_v7_mission_repairs"]
