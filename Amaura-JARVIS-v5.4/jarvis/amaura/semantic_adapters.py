"""Compatibility adapters behind the Phase 9 SemanticRequestGraph.

These patches do not classify top-level intent. They only prevent legacy
capability adapters from re-vetoing an action that the semantic graph already
classified and authorized.
"""
from __future__ import annotations

from typing import Any

_INSTALLED = False


def install_semantic_adapters() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from jarvis.amaura import direct_action as da

    # Repository execution is invoked only after SemanticRequestGraph has
    # classified the request as REPOSITORY. The legacy adapter must therefore
    # not demand the literal words repo/project/codebase a second time.
    original_repo_try = da.DirectActionRouter._try_repository_inspection.__func__

    def graph_authorized_repo_try(cls: Any, text: str, workspace: str = "") -> Any:
        original_check = cls._is_repository_inspection_request
        cls._is_repository_inspection_request = classmethod(lambda _cls, _text: True)
        try:
            return original_repo_try(cls, text, workspace=workspace)
        finally:
            cls._is_repository_inspection_request = original_check

    da.DirectActionRouter._try_repository_inspection = classmethod(graph_authorized_repo_try)
    _INSTALLED = True
