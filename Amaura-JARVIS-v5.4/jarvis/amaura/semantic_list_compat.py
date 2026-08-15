"""Narrow directory-list grammar compatibility for the semantic graph.

Directory-bearing phrases such as ``Show the contents of '/workspace/logs'``
must not be stolen by generic show/display read grammar.  This adapter only
retypes a request as DIRECTORY_LIST when directory/list language is explicit and
a syntactically valid target path is present.  It authorizes no side effects.
"""
from __future__ import annotations

import re
from typing import Any

_INSTALLED = False


def install_semantic_list_compat() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from jarvis.amaura import direct_action as da
    from jarvis.amaura import semantic_core as core

    current_parse = core.SemanticParser.parse.__func__

    def parse_with_directory_precedence(
        cls: Any,
        text: str,
        known_extensions: tuple[str, ...],
    ) -> Any:
        graph = current_parse(cls, text, known_extensions)
        lower = text.lower()
        explicit_list = bool(re.search(
            r"\b(?:"
            r"show\s+(?:me\s+)?(?:the\s+)?contents\s+of|"
            r"display\s+(?:the\s+)?entries\s+inside|"
            r"what\s+is\s+inside\s+(?:the\s+)?(?:directory|folder)|"
            r"what\s+(?:files|entries)\s+are\s+in|"
            r"list\s+(?:all\s+)?(?:files|entries|items)|"
            r"directory\s+contents|folder\s+contents"
            r")\b",
            lower,
        ))
        if not explicit_list:
            return graph

        paths = core.extract_paths(text, known_extensions)
        quoted = re.search(r"['\"`]([^'\"`\n]+)['\"`]", text)
        target = paths[0] if paths else (quoted.group(1) if quoted else "")
        if not target:
            return graph

        # If the target is explicitly called a directory/folder, or it does not
        # carry a known file extension, directory semantics win over show/read.
        named_directory = bool(re.search(r"\b(?:directory|folder)\b", lower))
        looks_file = any(target.lower().endswith(ext) for ext in known_extensions)
        if named_directory or not looks_file:
            return core.SemanticRequestGraph(
                original_text=text,
                action=core.SemanticAction.DIRECTORY_LIST,
                response_mode=core._response_mode(text),
                paths=[core.PathBinding(target, core.SemanticPathRole.TARGET, "explicit_directory_list_clause")],
                evidence=["directory_list_clause_precedence"],
            )
        return graph

    core.SemanticParser.parse = classmethod(parse_with_directory_precedence)
    _INSTALLED = True
