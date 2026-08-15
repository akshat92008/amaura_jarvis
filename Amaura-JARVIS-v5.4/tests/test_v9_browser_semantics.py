"""V9 browser composition regressions."""
from jarvis.amaura.browser_semantic_patch import normalize_selector_list


def test_css_selector_list_is_expanded_for_legacy_parser() -> None:
    text = 'Report these CSS selectors: ".save-a", ".memory-b", ".open-c", ".screen-d".'
    normalized = normalize_selector_list(text)
    assert 'selector ".save-a"' in normalized
    assert 'selector ".memory-b"' in normalized
    assert 'selector ".open-c"' in normalized
    assert 'selector ".screen-d"' in normalized


def test_non_selector_quotes_are_not_rewritten() -> None:
    text = 'Open https://example.com and report title "Hello".'
    assert normalize_selector_list(text) == text
