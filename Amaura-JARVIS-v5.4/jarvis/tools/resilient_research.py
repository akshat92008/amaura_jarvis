"""Bounded public research handlers for the central tool registry.

The legacy DuckDuckGo client can occasionally block below Python's normal
exception boundary. These handlers isolate each search in a short-lived child
process with a parent-enforced timeout, so a stalled provider becomes failed
tool evidence instead of freezing the governed worker loop.
"""

from __future__ import annotations

import html
import json
import re
import subprocess
import sys
from datetime import datetime
from typing import Any

_SEARCH_TIMEOUT_SECONDS = 12
_SEARCH_CLIENT_TIMEOUT_SECONDS = 8
_MAX_RESULTS = 10
_MAX_QUERY_CHARS = 500

_SEARCH_CHILD = r"""
import json
import sys
import warnings

warnings.filterwarnings("ignore", category=RuntimeWarning)
from duckduckgo_search import DDGS

query = sys.argv[1]
max_results = int(sys.argv[2])
timeout = int(sys.argv[3])
with DDGS(timeout=timeout) as ddgs:
    results = list(ddgs.text(query, max_results=max_results))
print(json.dumps(results, ensure_ascii=False))
"""


def _bounded_ddg_results(query: str, max_results: int = 5) -> tuple[list[dict[str, Any]], str | None]:
    """Return DuckDuckGo results under a hard wall-clock timeout."""
    clean_query = str(query).strip()
    if not clean_query:
        return [], "Search query must not be empty"
    if len(clean_query) > _MAX_QUERY_CHARS:
        clean_query = clean_query[:_MAX_QUERY_CHARS]
    try:
        bounded_results = max(1, min(int(max_results), _MAX_RESULTS))
    except (TypeError, ValueError):
        return [], "max_results must be an integer"

    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                _SEARCH_CHILD,
                clean_query,
                str(bounded_results),
                str(_SEARCH_CLIENT_TIMEOUT_SECONDS),
            ],
            shell=False,
            capture_output=True,
            text=True,
            timeout=_SEARCH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return [], f"Search timed out after {_SEARCH_TIMEOUT_SECONDS}s"
    except OSError as exc:
        return [], f"Search process could not start: {exc}"

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "search backend failed").strip()
        detail = detail[-800:]
        return [], f"Search backend failed: {detail}"

    try:
        decoded = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError:
        return [], "Search backend returned malformed JSON"
    if not isinstance(decoded, list):
        return [], "Search backend returned an invalid result set"

    normalized: list[dict[str, Any]] = []
    for item in decoded[:bounded_results]:
        if isinstance(item, dict):
            normalized.append(item)
    return normalized, None


def tool_web_search(query: str, max_results: int = 5) -> str:
    """Search the public web without allowing a provider hang to block JARVIS."""
    results, error = _bounded_ddg_results(query, max_results)
    if error:
        return f"❌ {error}"
    if not results:
        return f"No results found for: {query}"

    lines = [f"Search results for: {query}\n"]
    for index, result in enumerate(results, 1):
        lines.append(f"{index}. {result.get('title', 'No title')}")
        lines.append(f"   {result.get('href', '')}")
        lines.append(f"   {str(result.get('body', ''))[:200]}")
        lines.append("")
    return "\n".join(lines)


def _fetch_url_text(url: str, max_length: int = 8_000) -> str:
    """Fetch one already-discovered public URL through Amaura's SSRF-safe layer.

    The import is intentionally lazy. ``resilient_research`` is imported while
    the central tool registry is bootstrapping, and importing ``jarvis.amaura``
    at module import time would recursively reinstall the semantic frontend and
    re-import the registry.
    """
    try:
        from jarvis.amaura.network import fetch_public_text

        raw = fetch_public_text(url, max_length=max(1, min(int(max_length) * 3, 100_000)))
    except Exception as exc:
        # Page retrieval is best-effort research evidence. Network governance,
        # DNS, response-size, and transport failures become recoverable source
        # failures rather than aborting the larger research operation.
        return f"(failed to fetch: {exc})"
    text = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_length] + ("..." if len(text) > max_length else "")


def tool_deep_research(topic: str, num_queries: int = 3) -> str:
    """Run bounded multi-query research and preserve partial-source recovery."""
    clean_topic = str(topic).strip()
    if not clean_topic:
        return "❌ Research topic must not be empty"
    try:
        query_count = max(1, min(int(num_queries), 3))
    except (TypeError, ValueError):
        return "❌ num_queries must be an integer"

    queries = [clean_topic]
    if query_count >= 2:
        queries.append(f"{clean_topic} explained")
    if query_count >= 3:
        queries.append(f"{clean_topic} latest developments 2025 2026")

    all_results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    search_failures: list[str] = []
    for query in queries:
        results, error = _bounded_ddg_results(query, 5)
        if error:
            search_failures.append(f"{query}: {error}")
            continue
        for result in results:
            url = str(result.get("href") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            all_results.append(
                {
                    "title": str(result.get("title") or ""),
                    "url": url,
                    "snippet": str(result.get("body") or ""),
                    "query": query,
                }
            )

    if not all_results:
        suffix = f" ({'; '.join(search_failures)})" if search_failures else ""
        return f"❌ No results found for: {clean_topic}{suffix}"

    detailed: list[dict[str, Any]] = []
    for result in all_results[:5]:
        detailed.append({**result, "content": _fetch_url_text(result["url"], max_length=3_000)})

    report_lines = [
        f"# Research Report: {clean_topic}",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Sources examined:** {len(detailed)}",
        f"**Search queries used:** {', '.join(queries)}",
    ]
    if search_failures:
        report_lines.append(f"**Recovered search failures:** {len(search_failures)}")
    report_lines.extend(["", "---", ""])

    for index, item in enumerate(detailed, 1):
        report_lines.extend(
            [
                f"## Source {index}: {item['title']}",
                f"**URL:** {item['url']}",
                f"**Snippet:** {item['snippet']}",
                "",
                "### Extracted Content",
                str(item["content"])[:2_000],
                "",
                "---",
                "",
            ]
        )
    return "\n".join(report_lines)


RESILIENT_RESEARCH_DISPATCH = {
    "web_search": tool_web_search,
    "deep_research": tool_deep_research,
}


__all__ = [
    "RESILIENT_RESEARCH_DISPATCH",
    "tool_deep_research",
    "tool_web_search",
]
