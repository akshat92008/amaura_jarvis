"""Compatibility adapters behind the Phase 9 SemanticRequestGraph.

These patches do not classify top-level intent. They only prevent legacy
capability adapters from re-vetoing an action that the semantic graph already
classified and authorized, and normalize syntax-only command prefixes before
one central semantic parse.
"""
from __future__ import annotations

import re
from typing import Any

_INSTALLED = False


def install_semantic_adapters() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from jarvis.amaura import direct_action as da
    from jarvis.amaura import semantic_core as core

    # Syntax normalization only: keep Echo:/Repeat: from leaking ':' into the
    # exact literal payload while still using the same SemanticParser.
    original_parse = core.SemanticParser.parse.__func__

    def normalized_parse(cls: Any, text: str, known_extensions: tuple[str, ...]) -> Any:
        normalized = re.sub(r"^(\s*(?:echo|repeat))\s*:\s*", r"\1 ", text, flags=re.IGNORECASE)
        graph = original_parse(cls, normalized, known_extensions)
        graph.original_text = text
        return graph

    core.SemanticParser.parse = classmethod(normalized_parse)

    # Repository execution is invoked only after SemanticRequestGraph has
    # classified the request as REPOSITORY. The legacy adapter must therefore
    # not demand the literal words repo/project/codebase a second time.
    original_repo_try = da.DirectActionRouter._try_repository_inspection.__func__

    def graph_authorized_repo_try(cls: Any, text: str, workspace: str = "") -> Any:
        original_descriptor = cls.__dict__.get("_is_repository_inspection_request")
        cls._is_repository_inspection_request = classmethod(lambda _cls, _text: True)
        try:
            return original_repo_try(cls, text, workspace=workspace)
        finally:
            if original_descriptor is not None:
                cls._is_repository_inspection_request = original_descriptor

    da.DirectActionRouter._try_repository_inspection = classmethod(graph_authorized_repo_try)
    _INSTALLED = True
