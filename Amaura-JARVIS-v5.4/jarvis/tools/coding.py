"""
Coding Tools — the agent's hands. 20 tools for file I/O, shell, git, web.
Ported from Nexus tools.py for Jarvis.
"""

import fnmatch
import os
import re
import subprocess
from pathlib import Path

from jarvis.amaura.models import GovernanceError
from jarvis.amaura.network import fetch_public_text
from jarvis.history import get_history
from jarvis.tools.process import parse_command_argv, repo_relative_path, validate_git_revision

# ── Tool Definitions (OpenAI function-calling format) ────────────────────────

CODING_TOOL_DEFINITIONS = [
    # ─── FILE TOOLS ──────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file at the given path. Returns the file text with line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or relative file path to read."},
                    "start_line": {"type": "integer", "description": "Optional 1-based start line (inclusive)."},
                    "end_line": {"type": "integer", "description": "Optional 1-based end line (inclusive)."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file with the given content. Parent directories are created automatically.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write to."},
                    "content": {"type": "string", "description": "Full file content to write."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace a specific string in a file with new content. old_text must match exactly and be unique.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to edit."},
                    "old_text": {
                        "type": "string",
                        "description": "The exact text to find and replace (must be unique).",
                    },
                    "new_text": {"type": "string", "description": "The replacement text."},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List the contents of a directory with file types and sizes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path to list (default: current directory)."},
                    "recursive": {"type": "boolean", "description": "If true, list recursively."},
                    "max_depth": {"type": "integer", "description": "Max recursion depth (default: 3)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search for a regex pattern across files in a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to search for."},
                    "directory": {"type": "string", "description": "Directory to search in (default: current)."},
                    "file_pattern": {"type": "string", "description": "Glob pattern to filter files (e.g., '*.py')."},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_files",
            "description": "Find files matching a glob pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern (e.g., '*.py', '*test*')."},
                    "directory": {"type": "string", "description": "Directory to search (default: current)."},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_project_structure",
            "description": "Get a tree view of the project directory structure.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Root path (default: current directory)."},
                    "max_depth": {"type": "integer", "description": "Max depth to show (default: 3)."},
                },
            },
        },
    },
    # ─── SHELL TOOLS ─────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a shell command and return stdout/stderr. Use for builds, tests, installs, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to execute."},
                    "cwd": {"type": "string", "description": "Working directory (default: current)."},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default: 120)."},
                },
                "required": ["command"],
            },
        },
    },
    # ─── GIT TOOLS ───────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Get the full git repository status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cwd": {"type": "string", "description": "Repository directory."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "View git diffs (working changes, staged, or between commits).",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Diff target (e.g., 'HEAD~1', branch name)."},
                    "staged": {"type": "boolean", "description": "Show staged changes."},
                    "file_path": {"type": "string", "description": "Limit diff to a specific file."},
                    "cwd": {"type": "string", "description": "Repository directory."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": "Stage and commit changes with a message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Commit message."},
                    "files": {"type": "array", "items": {"type": "string"}, "description": "Specific files to stage."},
                    "all": {"type": "boolean", "description": "Stage all changes (git add -A)."},
                    "cwd": {"type": "string", "description": "Repository directory."},
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_log",
            "description": "View commit history.",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "Number of commits to show (default: 10)."},
                    "oneline": {"type": "boolean", "description": "One-line format."},
                    "cwd": {"type": "string", "description": "Repository directory."},
                },
            },
        },
    },
    # ─── WEB TOOLS ───────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch and read a web page, converting HTML to readable text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch."},
                    "max_length": {"type": "integer", "description": "Max characters to return (default: 10000)."},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web using DuckDuckGo and return top results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "max_results": {"type": "integer", "description": "Max results to return (default: 5)."},
                },
                "required": ["query"],
            },
        },
    },
]


# ── Tool Implementations ─────────────────────────────────────────────────────


def tool_read_file(path: str, start_line: int | None = None, end_line: int | None = None) -> str:
    """Read a file and return its contents with line numbers."""
    from jarvis.tools.security import resolve_workspace_path

    try:
        p = resolve_workspace_path(path, must_exist=False)
    except PermissionError as exc:
        return f"❌ {exc}"
    if not p.exists():
        return f"❌ File not found: {path}"
    if not p.is_file():
        return f"❌ Not a file: {path}"
    if p.stat().st_size > 5_000_000:
        return f"❌ File too large ({p.stat().st_size:,} bytes). Use start_line/end_line."

    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError as err:
        return f"❌ Cannot read {path}: {err}"

    total = len(lines)
    s = max(1, start_line or 1)
    end_idx = min(total, end_line or total)

    if s > total:
        return f"❌ start_line ({s}) exceeds file length ({total} lines)."

    selected = lines[s - 1 : end_idx]
    numbered = [f"{i}: {line.rstrip()}" for i, line in enumerate(selected, s)]

    header = f"File: {p} ({total} lines)\nShowing lines {s}-{end_idx}:\n"
    return header + "\n".join(numbered)


def tool_write_file(path: str, content: str) -> str:
    """Write content to a file (create or overwrite)."""
    p = Path(path).expanduser().resolve()

    history = get_history()
    snapshot = history.snapshot_before_write(str(p))

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        history.record_change(str(p), "write_file", snapshot)
        lines = content.count("\n") + 1
        return f"✅ Wrote {lines} lines to {p}"
    except OSError as e:
        return f"❌ Cannot write to {path}: {e}"


def tool_edit_file(path: str, old_text: str, new_text: str) -> str:
    """Find and replace text in a file."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return f"❌ File not found: {path}"

    try:
        with open(p, encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        return f"❌ Cannot read {path}: {e}"

    count = content.count(old_text)
    if count == 0:
        return f"❌ Text not found in {p.name}. Make sure old_text matches exactly."
    if count > 1:
        return f"❌ Found {count} occurrences of old_text. Provide more context to make it unique."

    history = get_history()
    snapshot = history.snapshot_before_write(str(p))

    new_content = content.replace(old_text, new_text, 1)
    with open(p, "w", encoding="utf-8") as f:
        f.write(new_content)
    history.record_change(str(p), "edit_file", snapshot)
    return f"✅ Edited {p.name}"


def tool_list_directory(path: str = ".", recursive: bool = False, max_depth: int = 3) -> str:
    """List directory contents."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return f"❌ Directory not found: {path}"
    if not p.is_dir():
        return f"❌ Not a directory: {path}"

    entries = []
    try:
        items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        for item in items:
            if item.name.startswith(".") and item.name not in (".env", ".gitignore"):
                continue
            if item.is_dir():
                child_count = sum(1 for _ in item.iterdir()) if item.exists() else 0
                entries.append(f"📁 {item.name}/ ({child_count} items)")
            else:
                size = item.stat().st_size
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.1f} KB"
                else:
                    size_str = f"{size / (1024 * 1024):.1f} MB"
                entries.append(f"📄 {item.name} ({size_str})")
    except PermissionError:
        return f"❌ Permission denied: {path}"

    if not entries:
        return f"(empty directory: {p})"
    return f"Directory: {p}\n" + "\n".join(entries)


def tool_search_code(pattern: str, directory: str = ".", file_pattern: str = "") -> str:
    """Search for a pattern in files using regex."""
    p = Path(directory).expanduser().resolve()
    if not p.exists():
        return f"❌ Directory not found: {directory}"

    results = []
    max_results = 50
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"❌ Invalid regex pattern: {e}"

    for root, dirs, files in os.walk(p):
        # Skip hidden and common non-source dirs
        dirs[:] = [
            d
            for d in dirs
            if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".git", "venv", ".venv")
        ]

        for fname in files:
            if file_pattern and not fnmatch.fnmatch(fname, file_pattern):
                continue
            fpath = Path(root) / fname
            try:
                if fpath.stat().st_size > 1_000_000:
                    continue
                with open(fpath, encoding="utf-8", errors="replace") as f:
                    for lineno, line in enumerate(f, 1):
                        if regex.search(line):
                            rel = fpath.relative_to(p)
                            results.append(f"{rel}:{lineno}: {line.rstrip()[:120]}")
                            if len(results) >= max_results:
                                break
            except (OSError, UnicodeDecodeError):
                continue
            if len(results) >= max_results:
                break
        if len(results) >= max_results:
            break

    if not results:
        return f"No matches for pattern '{pattern}'"
    header = f"Found {len(results)} match(es) for '{pattern}':\n"
    return header + "\n".join(results)


def tool_find_files(pattern: str, directory: str = ".") -> str:
    """Find files matching a glob pattern."""
    p = Path(directory).expanduser().resolve()
    if not p.exists():
        return f"❌ Directory not found: {directory}"

    matches = []
    for match in p.rglob(pattern):
        if any(part.startswith(".") for part in match.parts):
            continue
        if "node_modules" in match.parts or "__pycache__" in match.parts:
            continue
        matches.append(str(match.relative_to(p)))
        if len(matches) >= 100:
            break

    if not matches:
        return f"No files matching '{pattern}'"
    return f"Found {len(matches)} file(s):\n" + "\n".join(matches)


def tool_get_project_structure(path: str = ".", max_depth: int = 3) -> str:
    """Get a tree view of the project."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return f"❌ Path not found: {path}"

    lines = [str(p)]
    _build_tree(p, lines, "", max_depth, 0)
    return "\n".join(lines)


def _build_tree(directory: Path, lines: list, prefix: str, max_depth: int, depth: int):
    """Recursively build a tree structure."""
    if depth >= max_depth:
        return

    try:
        items = sorted(directory.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    except PermissionError:
        return

    # Filter
    items = [i for i in items if not i.name.startswith(".") or i.name in (".env", ".gitignore")]
    items = [i for i in items if i.name not in ("node_modules", "__pycache__", ".git", "venv", ".venv")]

    for idx, item in enumerate(items):
        is_last = idx == len(items) - 1
        connector = "└── " if is_last else "├── "
        lines.append(f"{prefix}{connector}{item.name}{'/' if item.is_dir() else ''}")

        if item.is_dir():
            extension = "    " if is_last else "│   "
            _build_tree(item, lines, prefix + extension, max_depth, depth + 1)


def tool_run_command(command: str, cwd: str | None = None, timeout: int = 120) -> str:
    """Execute one shell-free command in the approved workspace."""
    work_dir = cwd or os.getcwd()
    try:
        argv = parse_command_argv(command)
        result = subprocess.run(
            argv,
            shell=False,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=max(1, min(int(timeout), 300)),
            env={**os.environ, "PAGER": "cat", "GIT_PAGER": "cat"},
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            if output:
                output += "\n"
            output += result.stderr
        if not output.strip():
            output = "(no output)"
        if result.returncode != 0:
            return f"❌ Command failed (exit code {result.returncode}):\n{output}"
        return output.strip()
    except subprocess.TimeoutExpired:
        return f"❌ Command timed out after {timeout}s"
    except (OSError, ValueError) as exc:
        return f"❌ Cannot execute command: {exc}"


def tool_git_status(cwd: str | None = None) -> str:
    """Get git repository status without invoking a shell."""
    work_dir = cwd or os.getcwd()
    try:
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            shell=False,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        status = subprocess.run(
            ["git", "status", "--short"],
            shell=False,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if branch.returncode != 0:
            return "Not a git repository."
        result = f"Branch: {branch.stdout.strip()}\n"
        result += f"\n{status.stdout.strip()}" if status.stdout.strip() else "Working tree clean."
        return result
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"❌ Git error: {exc}"


def tool_git_diff(target: str = "", staged: bool = False, file_path: str = "", cwd: str | None = None) -> str:
    """View git diffs using an argument vector and a validated revision."""
    work_dir = cwd or os.getcwd()
    try:
        revision = validate_git_revision(target)
        argv = ["git", "diff"]
        if staged:
            argv.append("--staged")
        if revision:
            argv.extend(["--end-of-options", revision])
        if file_path:
            argv.extend(["--", repo_relative_path(file_path, work_dir)])
        result = subprocess.run(
            argv,
            shell=False,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "GIT_PAGER": "cat"},
        )
        if result.returncode != 0:
            return f"❌ Git diff failed: {result.stderr.strip()}"
        return result.stdout.strip() or "(no differences)"
    except (OSError, ValueError, PermissionError, subprocess.TimeoutExpired) as exc:
        return f"❌ Git diff error: {exc}"


def tool_git_commit(message: str, files: list | None = None, all: bool = False, cwd: str | None = None) -> str:
    """Stage and commit changes without shell interpolation."""
    work_dir = cwd or os.getcwd()
    if not isinstance(message, str) or not message.strip() or "\x00" in message or "\n" in message or "\r" in message:
        return "❌ Commit message must be a non-empty single line."
    try:
        if all:
            staged = subprocess.run(
                ["git", "add", "-A"], shell=False, cwd=work_dir, capture_output=True, text=True, timeout=10
            )
            if staged.returncode != 0:
                return f"❌ Stage failed: {staged.stderr.strip()}"
        elif files:
            relative_files = [repo_relative_path(item, work_dir) for item in files]
            staged = subprocess.run(
                ["git", "add", "--", *relative_files],
                shell=False,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if staged.returncode != 0:
                return f"❌ Stage failed: {staged.stderr.strip()}"
        result = subprocess.run(
            ["git", "commit", "-m", message],
            shell=False,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return f"❌ Commit failed: {result.stderr.strip()}"
        return f"✅ {result.stdout.strip()}"
    except (OSError, PermissionError, subprocess.TimeoutExpired) as exc:
        return f"❌ Git commit error: {exc}"


def tool_git_log(count: int = 10, oneline: bool = True, cwd: str | None = None) -> str:
    """View commit history without shell interpolation."""
    work_dir = cwd or os.getcwd()
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 1000:
        raise ValueError("git log count must be an integer from 1 to 1000")
    argv = ["git", "log", "-n", str(count)]
    if oneline:
        argv.append("--oneline")
    try:
        result = subprocess.run(
            argv,
            shell=False,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "GIT_PAGER": "cat"},
        )
        if result.returncode != 0:
            return f"❌ Git log failed: {result.stderr.strip()}"
        return result.stdout.strip() or "No commits yet."
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"❌ Git log error: {exc}"


def tool_web_fetch(url: str, max_length: int = 10000) -> str:
    """Fetch public HTTP(S) content through the governed SSRF-safe transport."""
    try:
        return fetch_public_text(url, max_length=max(1, min(int(max_length), 100_000)))
    except (GovernanceError, ValueError) as exc:
        return f"❌ {exc}"


def tool_web_search(query: str, max_results: int = 5) -> str:
    """Search the web using DuckDuckGo."""
    try:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return f"No results found for: {query}"
        lines = [f"Search results for: {query}\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.get('title', 'No title')}")
            lines.append(f"   {r.get('href', '')}")
            lines.append(f"   {r.get('body', '')[:200]}")
            lines.append("")
        return "\n".join(lines)
    except ImportError:
        return "❌ duckduckgo_search not installed. Run: pip install duckduckgo_search"
    except Exception as e:
        return f"❌ Search error: {e}"


# ── Dispatch ─────────────────────────────────────────────────────────────────

CODING_DISPATCH = {
    "read_file": lambda **kw: tool_read_file(kw.get("path", ""), kw.get("start_line"), kw.get("end_line")),
    "write_file": lambda **kw: tool_write_file(kw.get("path", ""), kw.get("content", "")),
    "edit_file": lambda **kw: tool_edit_file(kw.get("path", ""), kw.get("old_text", ""), kw.get("new_text", "")),
    "list_directory": lambda **kw: tool_list_directory(
        kw.get("path", "."), kw.get("recursive", False), kw.get("max_depth", 3)
    ),
    "search_code": lambda **kw: tool_search_code(
        kw.get("pattern", ""), kw.get("directory", "."), kw.get("file_pattern", "")
    ),
    "find_files": lambda **kw: tool_find_files(kw.get("pattern", ""), kw.get("directory", ".")),
    "get_project_structure": lambda **kw: tool_get_project_structure(kw.get("path", "."), kw.get("max_depth", 3)),
    "run_command": lambda **kw: tool_run_command(kw.get("command", ""), kw.get("cwd"), kw.get("timeout", 120)),
    "git_status": lambda **kw: tool_git_status(kw.get("cwd")),
    "git_diff": lambda **kw: tool_git_diff(
        kw.get("target", ""), kw.get("staged", False), kw.get("file_path", ""), kw.get("cwd")
    ),
    "git_commit": lambda **kw: tool_git_commit(
        kw.get("message", ""), kw.get("files"), kw.get("all", False), kw.get("cwd")
    ),
    "git_log": lambda **kw: tool_git_log(kw.get("count", 10), kw.get("oneline", True), kw.get("cwd")),
    "web_fetch": lambda **kw: tool_web_fetch(kw.get("url", ""), kw.get("max_length", 10000)),
    "web_search": lambda **kw: tool_web_search(kw.get("query", ""), kw.get("max_results", 5)),
}
