"""Normalize path extraction for the Phase 9 semantic request graph.

The legacy filename regex can rediscover an absolute path without its leading
slash. For example, one explicit ``/tmp/work/input.txt`` may otherwise produce
both::

    /tmp/work/input.txt
    tmp/work/input.txt

That corrupts semantic path cardinality and can make a two-path workflow appear
to contain four paths. This normalizer removes only proven shadow occurrences:
the relative-looking candidate must be a suffix of an extracted absolute path,
and every occurrence of it in the original sentence must be immediately
preceded by ``/``. A genuinely independently written relative path is retained.
"""

from __future__ import annotations

_INSTALLED = False


def install_semantic_path_normalization() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from jarvis.amaura import semantic_core as core

    current_extract = core.extract_paths

    def normalized_extract_paths(text: str, known_extensions: tuple[str, ...]) -> list[str]:
        paths = current_extract(text, known_extensions)
        absolute_paths = [path for path in paths if path.startswith("/")]
        if not absolute_paths:
            return paths

        result: list[str] = []
        for candidate in paths:
            if candidate.startswith("/"):
                if candidate not in result:
                    result.append(candidate)
                continue

            shadow_of_absolute = any(absolute.endswith("/" + candidate) for absolute in absolute_paths)
            if not shadow_of_absolute:
                if candidate not in result:
                    result.append(candidate)
                continue

            starts: list[int] = []
            start = 0
            while True:
                index = text.find(candidate, start)
                if index < 0:
                    break
                starts.append(index)
                start = index + 1

            # Drop only when every textual occurrence belongs to the already
            # extracted absolute path. If the user also wrote the relative path
            # independently, it remains a distinct semantic entity.
            solely_absolute_shadow = bool(starts) and all(index > 0 and text[index - 1] == "/" for index in starts)
            if not solely_absolute_shadow and candidate not in result:
                result.append(candidate)

        return result

    core.extract_paths = normalized_extract_paths
    _INSTALLED = True
