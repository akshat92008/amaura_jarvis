"""
Research Tools — deep web research, page summarization, and study aids.
Gives Jarvis the ability to research topics autonomously.
"""

import html
import os
import re
from datetime import datetime
from pathlib import Path

from jarvis.amaura.models import GovernanceError
from jarvis.amaura.network import fetch_public_text

# ── Tool Definitions ─────────────────────────────────────────────────────────

RESEARCH_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "deep_research",
            "description": "Perform deep web research on a topic. Searches multiple queries, fetches top results, and compiles a structured research report.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "The topic to research."},
                    "num_queries": {
                        "type": "integer",
                        "description": "Number of search queries to generate (default: 3).",
                    },
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_url",
            "description": "Fetch a web page and extract the key information in a concise summary.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch and summarize."},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_pdf",
            "description": "Extract text content from a PDF file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the PDF file."},
                    "max_pages": {"type": "integer", "description": "Maximum number of pages to read (default: all)."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_research",
            "description": "Save research notes or findings to a markdown file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Title of the research document."},
                    "content": {"type": "string", "description": "Research content in markdown format."},
                    "output_path": {
                        "type": "string",
                        "description": "Where to save the file (default: ~/Desktop/research/).",
                    },
                },
                "required": ["title", "content"],
            },
        },
    },
]


# ── Tool Implementations ─────────────────────────────────────────────────────


def _fetch_url_text(url: str, max_length: int = 8000) -> str:
    """Fetch a public URL through the governed, redirect-free network layer."""
    try:
        raw = fetch_public_text(url, max_length=max(1, min(int(max_length) * 3, 100_000)))
        text = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_length] + ("..." if len(text) > max_length else "")
    except (GovernanceError, ValueError) as exc:
        return f"(failed to fetch: {exc})"


def tool_deep_research(topic: str, num_queries: int = 3) -> str:
    """Perform deep web research by running multiple searches and compiling results."""
    try:
        from ddgs import DDGS
    except ImportError:
        return "❌ ddgs not installed. Run: pip install ddgs"

    # Generate search variations
    queries = [topic]
    if num_queries >= 2:
        queries.append(f"{topic} explained")
    if num_queries >= 3:
        queries.append(f"{topic} latest developments 2025 2026")

    all_results = []
    seen_urls = set()

    for query in queries:
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=5))
            for r in results:
                url = r.get("href", "")
                if url not in seen_urls:
                    seen_urls.add(url)
                    all_results.append(
                        {
                            "title": r.get("title", ""),
                            "url": url,
                            "snippet": r.get("body", ""),
                            "query": query,
                        }
                    )
        except Exception:
            continue

    if not all_results:
        return f"❌ No results found for: {topic}"

    # Fetch content from top results (limit to 5 to avoid timeout)
    detailed = []
    for r in all_results[:5]:
        url = r["url"]
        content = _fetch_url_text(url, max_length=3000)
        detailed.append(
            {
                **r,
                "content": content,
            }
        )

    # Compile research report
    report_lines = [
        f"# Research Report: {topic}",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Sources examined:** {len(detailed)}",
        f"**Search queries used:** {', '.join(queries)}",
        "",
        "---",
        "",
    ]

    for i, item in enumerate(detailed, 1):
        report_lines.append(f"## Source {i}: {item['title']}")
        report_lines.append(f"**URL:** {item['url']}")
        report_lines.append(f"**Snippet:** {item['snippet']}")
        report_lines.append("")
        report_lines.append("### Extracted Content")
        report_lines.append(item["content"][:2000])
        report_lines.append("")
        report_lines.append("---")
        report_lines.append("")

    return "\n".join(report_lines)


def tool_summarize_url(url: str) -> str:
    """Fetch and return the main content of a URL."""
    text = _fetch_url_text(url, max_length=10000)
    if text.startswith("(failed"):
        return f"❌ {text}"
    return f"Content from {url}:\n\n{text}"


def _find_candidate_pdfs(requested_path: str) -> list[tuple[Path, float]]:
    """Find candidate PDF files matching the requested path query."""
    clean_name = Path(requested_path).stem.lower()
    keywords = [w for w in re.findall(r"\w+", clean_name) if w not in ("the", "a", "an", "pdf")]
    if not keywords:
        keywords = [clean_name]

    search_dirs = [
        Path.home() / "Desktop",
        Path.home() / "Downloads",
        Path.home() / "Documents",
        Path.cwd(),
    ]

    candidates = []
    seen = set()

    for sdir in search_dirs:
        if not sdir.exists():
            continue
        try:
            for root, dirs, files in os.walk(sdir):
                rel_depth = len(Path(root).relative_to(sdir).parts)
                if rel_depth > 2:
                    dirs.clear()
                    continue
                for f in files:
                    if f.lower().endswith(".pdf"):
                        full_p = Path(root) / f
                        if full_p in seen:
                            continue
                        seen.add(full_p)
                        fname_lower = f.lower()
                        fname_words = set(re.findall(r"\w+", fname_lower))

                        matches = sum(1 for kw in keywords if kw in fname_lower or kw in fname_words)
                        if matches > 0:
                            score = matches / len(keywords)
                            candidates.append((full_p, score))
        except Exception:
            pass

    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates


def tool_read_pdf(path: str, max_pages: int | None = None) -> str:
    """Extract text from a PDF file with automatic fuzzy path resolution and multi-engine extraction."""
    p = Path(path).expanduser().resolve()
    resolved_note = ""

    if not p.exists():
        candidates = _find_candidate_pdfs(path)
        if candidates and candidates[0][1] >= 0.3:
            top_match = candidates[0][0]
            resolved_note = f"ℹ️ Auto-resolved path to: {top_match}\n\n"
            p = top_match
        else:
            cand_list = "\n".join([f"  • {c[0]}" for c in candidates[:5]])
            if cand_list:
                return f"❌ PDF not found at exact path: '{path}'\nDid you mean one of these PDFs on your system?\n{cand_list}"
            return f"❌ PDF not found: {path}"

    text = ""

    # Engine 1: pdftotext (poppler)
    try:
        import subprocess

        cmd = ["pdftotext", str(p), "-"]
        if max_pages:
            cmd = ["pdftotext", "-l", str(max_pages), str(p), "-"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            text = result.stdout.strip()
    except Exception:
        pass

    # Engine 2: pypdf
    if not text:
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(p))
            target_page_count = max_pages if max_pages else len(reader.pages)
            extracted = []
            for page in reader.pages:
                t = page.extract_text()
                if t and t.strip():
                    extracted.append(t.strip())
                    if len(extracted) >= target_page_count:
                        break
            if extracted:
                text = "\n\n".join(extracted)
        except Exception:
            pass

    # Engine 3: fitz (PyMuPDF)
    if not text:
        try:
            import fitz

            doc = fitz.open(str(p))
            target_page_count = max_pages if max_pages else len(doc)
            extracted = []
            for page in doc:
                t = page.get_text()
                if t and t.strip():
                    extracted.append(t.strip())
                    if len(extracted) >= target_page_count:
                        break
            if extracted:
                text = "\n\n".join(extracted)
        except Exception:
            pass

    # Engine 4: pdfminer
    if not text:
        try:
            from pdfminer.high_level import extract_text as pdfminer_extract

            text = pdfminer_extract(str(p), maxpages=max_pages or 0)
        except Exception:
            pass

    if not text or not text.strip():
        return f"❌ PDF found at '{p}' but text extraction yielded empty content."

    text = text.strip()
    if len(text) > 30000:
        text = text[:30000] + "\n\n... (truncated for length)"

    return f"{resolved_note}PDF Content ({p.name}):\n\n{text}"


def tool_save_research(title: str, content: str, output_path: str = "") -> str:
    """Save research to a markdown file."""
    if not output_path:
        research_dir = Path.home() / "Desktop" / "research"
        safe_title = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")[:50]
        output_path = str(research_dir / f"{safe_title}_{datetime.now().strftime('%Y%m%d')}.md")

    p = Path(output_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)

    with open(p, "w", encoding="utf-8") as f:
        f.write(content)

    return f"✅ Research saved to {p}"


# ── Dispatch ─────────────────────────────────────────────────────────────────

RESEARCH_DISPATCH = {
    "deep_research": lambda **kw: tool_deep_research(kw.get("topic", ""), kw.get("num_queries", 3)),
    "summarize_url": lambda **kw: tool_summarize_url(kw.get("url", "")),
    "read_pdf": lambda **kw: tool_read_pdf(kw.get("path", ""), kw.get("max_pages")),
    "save_research": lambda **kw: tool_save_research(
        kw.get("title", ""), kw.get("content", ""), kw.get("output_path", "")
    ),
}
