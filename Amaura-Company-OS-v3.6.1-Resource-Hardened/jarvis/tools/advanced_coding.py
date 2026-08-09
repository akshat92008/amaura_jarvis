"""
Advanced Coding Tools — elite-level programming capabilities.

16 power tools that make Jarvis operate at a senior programmer level:
code analysis, refactoring, project scaffolding, debugging, testing,
formatting, multi-file editing, Docker, API scaffolding, and more.
"""

import os
import re
import json
import subprocess
import shutil
import socket
import sys
import ast
from pathlib import Path
from textwrap import dedent
from jarvis.tools.process import ensure_safe_tokens, repo_relative_path


# ── Tool Definitions ─────────────────────────────────────────────────────────

ADVANCED_CODING_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "analyze_code",
            "description": "Deep code analysis — returns complexity metrics, imports, classes, functions, potential issues, and architecture overview. Supports Python, JS/TS, Go, Rust, Java, C/C++, and more.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file or directory to analyze."},
                    "language": {"type": "string", "description": "Force language (auto-detected if omitted). Options: python, javascript, typescript, go, rust, java, cpp, c, ruby, php, swift, kotlin."},
                    "include_metrics": {"type": "boolean", "description": "Include complexity metrics (default: true)."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "refactor_code",
            "description": "Intelligent code refactoring: rename symbols across files, extract functions, inline variables, convert patterns. Operates on a directory scope.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File or directory to refactor in."},
                    "operation": {"type": "string", "description": "Refactoring operation: rename, extract_function, inline, convert_to_class, add_type_hints, remove_dead_code."},
                    "old_name": {"type": "string", "description": "Current symbol name (for rename)."},
                    "new_name": {"type": "string", "description": "New symbol name (for rename)."},
                    "file_pattern": {"type": "string", "description": "Glob pattern to filter files (e.g., '*.py')."},
                },
                "required": ["path", "operation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_project",
            "description": "Scaffold a complete project from a template. Supports: python-cli, python-api (FastAPI), python-flask, node-express, react-app, nextjs-app, go-api, rust-cli, django-app, vue-app, fullstack (React+FastAPI). Creates all files, configs, README, tests, and .gitignore.",
            "parameters": {
                "type": "object",
                "properties": {
                    "template": {"type": "string", "description": "Project template to use (e.g., python-api, react-app, nextjs-app, go-api, rust-cli, django-app, fullstack)."},
                    "name": {"type": "string", "description": "Project name."},
                    "path": {"type": "string", "description": "Directory to create the project in (default: current directory)."},
                    "description": {"type": "string", "description": "Short project description."},
                    "features": {"type": "array", "items": {"type": "string"}, "description": "Optional features to include (e.g., docker, auth, database, testing, ci)."},
                },
                "required": ["template", "name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "install_dependencies",
            "description": "Smart package installer — auto-detects the package manager and installs dependencies. Supports pip, npm, yarn, pnpm, cargo, go, brew, composer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "packages": {"type": "array", "items": {"type": "string"}, "description": "Packages to install."},
                    "manager": {"type": "string", "description": "Force a specific package manager (auto-detected if omitted)."},
                    "dev": {"type": "boolean", "description": "Install as dev dependency (default: false)."},
                    "cwd": {"type": "string", "description": "Working directory."},
                },
                "required": ["packages"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Auto-detect and run tests. Supports pytest, unittest, jest, mocha, vitest, go test, cargo test, rspec, phpunit. Returns results with pass/fail summary.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Test file or directory (default: current directory)."},
                    "framework": {"type": "string", "description": "Force test framework (auto-detected if omitted)."},
                    "filter": {"type": "string", "description": "Run only tests matching this pattern."},
                    "verbose": {"type": "boolean", "description": "Verbose output (default: true)."},
                    "cwd": {"type": "string", "description": "Working directory."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lint_code",
            "description": "Run linters on code. Auto-detects: ruff/flake8 (Python), eslint (JS/TS), golangci-lint (Go), clippy (Rust). Returns issues with severity and fix suggestions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File or directory to lint."},
                    "fix": {"type": "boolean", "description": "Auto-fix issues where possible (default: false)."},
                    "linter": {"type": "string", "description": "Force specific linter (auto-detected if omitted)."},
                    "cwd": {"type": "string", "description": "Working directory."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "format_code",
            "description": "Auto-format code. Uses black/ruff (Python), prettier (JS/TS/CSS/HTML/JSON/MD), gofmt (Go), rustfmt (Rust), clang-format (C/C++).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File or directory to format."},
                    "formatter": {"type": "string", "description": "Force specific formatter (auto-detected if omitted)."},
                    "check_only": {"type": "boolean", "description": "Only check, don't modify (default: false)."},
                    "cwd": {"type": "string", "description": "Working directory."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "debug_error",
            "description": "Intelligent error debugging. Parses stack traces, locates the exact bug in source code, identifies root cause, and generates a fix patch. Works for any language.",
            "parameters": {
                "type": "object",
                "properties": {
                    "error": {"type": "string", "description": "The error message or stack trace to debug."},
                    "context_path": {"type": "string", "description": "Path to the project or file for context."},
                    "language": {"type": "string", "description": "Language hint (auto-detected from stack trace if omitted)."},
                },
                "required": ["error"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_code",
            "description": "Generate a detailed, line-by-line explanation of a code snippet or file. Returns purpose, logic flow, complexity analysis, and improvement suggestions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to explain."},
                    "start_line": {"type": "integer", "description": "Start line (optional)."},
                    "end_line": {"type": "integer", "description": "End line (optional)."},
                    "detail_level": {"type": "string", "description": "Detail level: brief, normal, deep (default: normal)."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_tests",
            "description": "Auto-generate unit tests for a file. Analyzes functions/classes and creates comprehensive test cases with edge cases, mocking, and assertions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_path": {"type": "string", "description": "Path to the source file to create tests for."},
                    "output_path": {"type": "string", "description": "Where to save the test file (auto-generated if omitted)."},
                    "framework": {"type": "string", "description": "Test framework: pytest, unittest, jest, mocha, go (auto-detected if omitted)."},
                    "style": {"type": "string", "description": "Test style: unit, integration, both (default: unit)."},
                },
                "required": ["source_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "diff_files",
            "description": "Show a unified diff between two files or two versions of the same file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_a": {"type": "string", "description": "First file path."},
                    "file_b": {"type": "string", "description": "Second file path."},
                    "context_lines": {"type": "integer", "description": "Number of context lines around changes (default: 3)."},
                },
                "required": ["file_a", "file_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "batch_edit",
            "description": "Find and replace across multiple files matching a glob pattern. Powerful multi-file refactoring tool.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Directory to search in."},
                    "file_pattern": {"type": "string", "description": "Glob pattern (e.g., '*.py', '*.js')."},
                    "find": {"type": "string", "description": "Text or regex pattern to find."},
                    "replace": {"type": "string", "description": "Replacement text."},
                    "is_regex": {"type": "boolean", "description": "Treat find as regex (default: false)."},
                    "dry_run": {"type": "boolean", "description": "Preview changes without modifying files (default: false)."},
                },
                "required": ["directory", "file_pattern", "find", "replace"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_env",
            "description": "Create and manage virtual environments. Supports Python venv/conda, Node nvm, Go modules. Can activate, install deps, and configure.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "Action: create, activate, install, list, delete."},
                    "env_type": {"type": "string", "description": "Environment type: python, node, go (default: python)."},
                    "name": {"type": "string", "description": "Environment name (default: .venv)."},
                    "python_version": {"type": "string", "description": "Python version to use (for create)."},
                    "cwd": {"type": "string", "description": "Working directory."},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "port_check",
            "description": "Check if ports are in use and find available ports. Useful for dev server configuration.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ports": {"type": "array", "items": {"type": "integer"}, "description": "Ports to check."},
                    "find_available": {"type": "boolean", "description": "Find an available port near the requested ones (default: false)."},
                    "range_start": {"type": "integer", "description": "Start of port range to scan (default: 3000)."},
                    "range_end": {"type": "integer", "description": "End of port range to scan (default: 9999)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "docker_compose",
            "description": "Generate Dockerfile and docker-compose.yml for a project. Auto-detects language, dependencies, and service requirements.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_path": {"type": "string", "description": "Path to the project (default: current directory)."},
                    "services": {"type": "array", "items": {"type": "string"}, "description": "Additional services to include (e.g., postgres, redis, mongodb, nginx, rabbitmq)."},
                    "output_path": {"type": "string", "description": "Where to save the files (default: project root)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "api_scaffold",
            "description": "Generate a complete REST or GraphQL API boilerplate with models, routes, middleware, and tests. Supports FastAPI, Express, Flask, Django REST, Go Gin, Rust Actix.",
            "parameters": {
                "type": "object",
                "properties": {
                    "framework": {"type": "string", "description": "API framework: fastapi, express, flask, django-rest, gin, actix."},
                    "name": {"type": "string", "description": "API project name."},
                    "models": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "fields": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "type": {"type": "string"}}}}
                            },
                        },
                        "description": "Data models to generate CRUD endpoints for.",
                    },
                    "features": {"type": "array", "items": {"type": "string"}, "description": "Features: auth, cors, rate-limit, swagger, websockets, database."},
                    "output_path": {"type": "string", "description": "Where to create the API project."},
                },
                "required": ["framework", "name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_fullstack_app",
            "description": "Master tool to scaffold, configure, build, and initialize a complete full-stack web application (React, Next.js, FastAPI, Vue, Express, Fullstack) in one automated step.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of the application."},
                    "template": {"type": "string", "description": "Template to use: fullstack (React+FastAPI), nextjs-app, react-app, python-api, node-express, django-app, vue-app. Default: fullstack."},
                    "description": {"type": "string", "description": "Detailed description of what the app does."},
                    "path": {"type": "string", "description": "Directory to create the application in."},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "test_and_auto_fix",
            "description": "Autonomous TDD loop tool: runs project tests, parses errors/stack traces if any fail, and automatically attempts to fix and re-verify until clean.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to project root."},
                    "framework": {"type": "string", "description": "Test framework (pytest, jest, vitest, go test, cargo test). Auto-detected if omitted."},
                    "max_attempts": {"type": "integer", "description": "Maximum fix attempts (default: 3)."},
                },
            },
        },
    },
]


# ── Language Detection ───────────────────────────────────────────────────────

EXTENSION_LANG_MAP = {
    ".py": "python", ".pyw": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin", ".kts": "kotlin",
    ".swift": "swift",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".dart": "dart",
    ".lua": "lua",
    ".r": "r", ".R": "r",
    ".scala": "scala",
    ".hs": "haskell",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash",
    ".sql": "sql",
    ".html": "html", ".htm": "html",
    ".css": "css", ".scss": "css", ".sass": "css",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".xml": "xml",
    ".md": "markdown", ".rst": "rst",
}


def _detect_language(path: str) -> str:
    """Detect language from file extension."""
    ext = Path(path).suffix.lower()
    return EXTENSION_LANG_MAP.get(ext, "unknown")


# ── Tool Implementations ─────────────────────────────────────────────────────

def tool_analyze_code(path: str, language: str = "", include_metrics: bool = True) -> str:
    """Deep code analysis — complexity, structure, issues."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return f"❌ Path not found: {path}"

    # If directory, analyze the whole project
    if p.is_dir():
        return _analyze_directory(p)

    lang = language or _detect_language(str(p))

    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
            lines = content.split("\n")
    except OSError as e:
        return f"❌ Cannot read {path}: {e}"

    report = [f"# Code Analysis: {p.name}", f"**Language:** {lang}", f"**Lines:** {len(lines)}", ""]

    # Basic metrics
    code_lines = sum(1 for l in lines if l.strip() and not l.strip().startswith(("#", "//", "/*", "*", "<!--")))
    comment_lines = sum(1 for l in lines if l.strip().startswith(("#", "//", "/*", "*")))
    blank_lines = sum(1 for l in lines if not l.strip())

    report.append(f"**Code lines:** {code_lines}")
    report.append(f"**Comment lines:** {comment_lines}")
    report.append(f"**Blank lines:** {blank_lines}")
    if code_lines > 0:
        report.append(f"**Comment ratio:** {comment_lines / code_lines * 100:.1f}%")

    # Python-specific deep analysis
    if lang == "python":
        report.extend(_analyze_python(content, p))
    elif lang in ("javascript", "typescript"):
        report.extend(_analyze_js_ts(content, p))
    else:
        report.extend(_analyze_generic(content, lang))

    # Potential issues
    issues = _find_common_issues(content, lang)
    if issues:
        report.append("\n## Potential Issues")
        for issue in issues:
            report.append(f"- ⚠️ {issue}")

    # File size warnings
    file_size = p.stat().st_size
    if file_size > 100_000:
        report.append(f"\n⚠️ **Large file** ({file_size / 1024:.1f} KB) — consider splitting into modules.")
    if len(lines) > 500:
        report.append(f"⚠️ **Long file** ({len(lines)} lines) — consider refactoring into smaller files.")

    return "\n".join(report)


def _analyze_directory(p: Path) -> str:
    """Analyze a full directory/project."""
    stats = {"files": 0, "lines": 0, "languages": {}}
    for root, dirs, files in os.walk(p):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", "dist", "build")]
        for fname in files:
            fpath = Path(root) / fname
            lang = _detect_language(fname)
            if lang == "unknown":
                continue
            stats["files"] += 1
            stats["languages"][lang] = stats["languages"].get(lang, 0) + 1
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    stats["lines"] += sum(1 for _ in f)
            except OSError:
                pass

    report = [
        f"# Project Analysis: {p.name}",
        f"**Total source files:** {stats['files']}",
        f"**Total lines:** {stats['lines']:,}",
        "",
        "## Language Breakdown",
    ]
    for lang, count in sorted(stats["languages"].items(), key=lambda x: -x[1]):
        report.append(f"- **{lang}**: {count} files")

    # Detect project type
    project_type = _detect_project_type(p)
    if project_type:
        report.append(f"\n## Detected Project Type\n{project_type}")

    return "\n".join(report)


def _detect_project_type(p: Path) -> str:
    """Detect what kind of project this is."""
    indicators = []
    if (p / "package.json").exists():
        indicators.append("Node.js project")
        try:
            pkg = json.loads((p / "package.json").read_text())
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "react" in deps: indicators.append("React app")
            if "next" in deps: indicators.append("Next.js app")
            if "vue" in deps: indicators.append("Vue.js app")
            if "express" in deps: indicators.append("Express server")
            if "typescript" in deps: indicators.append("TypeScript")
        except Exception:
            pass
    if (p / "pyproject.toml").exists() or (p / "setup.py").exists():
        indicators.append("Python package")
    if (p / "requirements.txt").exists():
        indicators.append("Python project")
    if (p / "Cargo.toml").exists():
        indicators.append("Rust project")
    if (p / "go.mod").exists():
        indicators.append("Go module")
    if (p / "Gemfile").exists():
        indicators.append("Ruby project")
    if (p / "Dockerfile").exists():
        indicators.append("Dockerized")
    if (p / "docker-compose.yml").exists() or (p / "docker-compose.yaml").exists():
        indicators.append("Docker Compose")
    if (p / ".github" / "workflows").exists():
        indicators.append("GitHub Actions CI/CD")
    return ", ".join(indicators) if indicators else ""


def _analyze_python(content: str, path: Path) -> list[str]:
    """Deep Python analysis using AST."""
    report = ["\n## Python Structure"]
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        return [f"\n❌ **Syntax Error** at line {e.lineno}: {e.msg}"]

    imports = []
    classes = []
    functions = []
    global_vars = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            imports.append(f"from {node.module or '.'}")
        elif isinstance(node, ast.ClassDef):
            methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            bases = [_ast_name(b) for b in node.bases]
            classes.append({"name": node.name, "methods": methods, "bases": bases, "line": node.lineno})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not any(isinstance(parent, ast.ClassDef) for parent in ast.walk(tree)):
                pass  # we'll get them below

    # Get top-level items
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args if a.arg != "self"]
            is_async = isinstance(node, ast.AsyncFunctionDef)
            functions.append({"name": node.name, "args": args, "line": node.lineno, "async": is_async})
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        global_vars.append(target.id)

    if imports:
        report.append(f"\n### Imports ({len(imports)})")
        for imp in imports[:20]:
            report.append(f"- `{imp}`")
        if len(imports) > 20:
            report.append(f"- ... and {len(imports) - 20} more")

    if classes:
        report.append(f"\n### Classes ({len(classes)})")
        for cls in classes:
            bases_str = f"({', '.join(cls['bases'])})" if cls["bases"] else ""
            report.append(f"- **{cls['name']}{bases_str}** (line {cls['line']}, {len(cls['methods'])} methods)")
            for m in cls["methods"][:10]:
                report.append(f"  - `{m}()`")

    if functions:
        report.append(f"\n### Functions ({len(functions)})")
        for fn in functions:
            prefix = "async " if fn["async"] else ""
            args_str = ", ".join(fn["args"][:5])
            report.append(f"- `{prefix}{fn['name']}({args_str})` (line {fn['line']})")

    return report


def _ast_name(node) -> str:
    """Extract name from AST node."""
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        return f"{_ast_name(node.value)}.{node.attr}"
    return "?"


def _analyze_js_ts(content: str, path: Path) -> list[str]:
    """Analyze JavaScript/TypeScript files."""
    report = ["\n## JS/TS Structure"]

    # Extract exports
    exports = re.findall(r'export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|let|var|interface|type|enum)\s+(\w+)', content)
    if exports:
        report.append(f"\n### Exports ({len(exports)})")
        for exp in exports:
            report.append(f"- `{exp}`")

    # Extract imports
    imports = re.findall(r"import\s+.*?from\s+['\"]([^'\"]+)['\"]", content)
    if imports:
        report.append(f"\n### Imports ({len(imports)})")
        for imp in imports[:15]:
            report.append(f"- `{imp}`")

    # Functions
    fns = re.findall(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)', content)
    arrow_fns = re.findall(r'(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\([^)]*\)\s*=>', content)
    all_fns = [f[0] for f in fns] + list(arrow_fns)
    if all_fns:
        report.append(f"\n### Functions ({len(all_fns)})")
        for fn in all_fns[:20]:
            report.append(f"- `{fn}()`")

    # Classes
    classes = re.findall(r'class\s+(\w+)(?:\s+extends\s+(\w+))?', content)
    if classes:
        report.append(f"\n### Classes ({len(classes)})")
        for cls in classes:
            ext = f" extends {cls[1]}" if cls[1] else ""
            report.append(f"- `{cls[0]}{ext}`")

    return report


def _analyze_generic(content: str, lang: str) -> list[str]:
    """Generic analysis for any language."""
    report = [f"\n## Structure ({lang})"]

    # Function patterns per language
    fn_patterns = {
        "go": r'func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(',
        "rust": r'(?:pub\s+)?fn\s+(\w+)\s*[<(]',
        "java": r'(?:public|private|protected)\s+\w+\s+(\w+)\s*\(',
        "kotlin": r'fun\s+(\w+)\s*[<(]',
        "swift": r'func\s+(\w+)\s*[<(]',
        "c": r'(?:static\s+)?\w+[\s*]+(\w+)\s*\([^)]*\)\s*\{',
        "cpp": r'(?:\w+::)?(\w+)\s*\([^)]*\)\s*(?:const\s*)?\{',
        "ruby": r'def\s+(\w+)',
        "php": r'function\s+(\w+)\s*\(',
        "csharp": r'(?:public|private|protected|internal)\s+\w+\s+(\w+)\s*\(',
    }

    pattern = fn_patterns.get(lang)
    if pattern:
        functions = re.findall(pattern, content)
        if functions:
            report.append(f"\n### Functions ({len(functions)})")
            for fn in functions[:20]:
                report.append(f"- `{fn}()`")

    return report


def _find_common_issues(content: str, lang: str) -> list[str]:
    """Find common code issues."""
    issues = []
    lines = content.split("\n")

    # Universal issues
    for i, line in enumerate(lines, 1):
        if len(line) > 200:
            issues.append(f"Line {i}: Very long line ({len(line)} chars)")
            if len(issues) > 5:
                break

    # TODO/FIXME/HACK comments
    todos = [(i, l.strip()) for i, l in enumerate(lines, 1) if re.search(r'\b(TODO|FIXME|HACK|XXX|BUG)\b', l, re.IGNORECASE)]
    for line_no, text in todos[:5]:
        issues.append(f"Line {line_no}: {text[:80]}")

    # Python-specific
    if lang == "python":
        if "import *" in content:
            issues.append("Wildcard import (`import *`) — can cause namespace pollution")
        if re.search(r'except\s*:', content):
            issues.append("Bare `except:` clause — should specify exception type")
        if "eval(" in content:
            issues.append("`eval()` usage — potential security risk")
        if "exec(" in content:
            issues.append("`exec()` usage — potential security risk")

    # JS-specific
    if lang in ("javascript", "typescript"):
        if "var " in content:
            issues.append("Using `var` — prefer `const` or `let`")
        if "== " in content and "=== " not in content:
            issues.append("Using loose equality `==` — prefer strict `===`")

    return issues[:10]


def tool_refactor_code(path: str, operation: str, old_name: str = "", new_name: str = "", file_pattern: str = "*.py") -> str:
    """Intelligent refactoring across files."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return f"❌ Path not found: {path}"

    if operation == "rename":
        if not old_name or not new_name:
            return "❌ Both old_name and new_name are required for rename."
        return _refactor_rename(p, old_name, new_name, file_pattern)
    elif operation == "remove_dead_code":
        return _remove_dead_code(p)
    elif operation == "add_type_hints":
        return _add_type_hints(p)
    else:
        return f"❌ Unsupported refactoring operation: {operation}. Supported: rename, remove_dead_code, add_type_hints."


def _refactor_rename(p: Path, old_name: str, new_name: str, file_pattern: str) -> str:
    """Rename a symbol across files."""
    if p.is_file():
        files = [p]
    else:
        files = list(p.rglob(file_pattern))
        files = [f for f in files if not any(part.startswith(".") or part in ("node_modules", "__pycache__") for part in f.parts)]

    modified = []
    total_replacements = 0

    for f in files:
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        # Use word-boundary matching to avoid partial replacements
        pattern = rf'\b{re.escape(old_name)}\b'
        new_content, count = re.subn(pattern, new_name, content)
        if count > 0:
            f.write_text(new_content, encoding="utf-8")
            modified.append(f"  {f.relative_to(p if p.is_dir() else p.parent)}: {count} replacement(s)")
            total_replacements += count

    if not modified:
        return f"❌ No occurrences of '{old_name}' found in {file_pattern} files."

    result = f"✅ Renamed '{old_name}' → '{new_name}' across {len(modified)} file(s), {total_replacements} total replacements:\n"
    result += "\n".join(modified)
    return result


def _remove_dead_code(p: Path) -> str:
    """Identify potentially dead code in Python files."""
    if not p.is_file() or p.suffix != ".py":
        return "❌ remove_dead_code currently only supports individual Python files."

    content = p.read_text(encoding="utf-8")
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return "❌ File has syntax errors."

    defined = set()
    used = set()

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.add(node.name)
        elif isinstance(node, ast.ClassDef):
            defined.add(node.name)
        elif isinstance(node, ast.Name):
            used.add(node.id)

    # Special names that are always "used"
    special = {"__init__", "__main__", "__str__", "__repr__", "main", "setUp", "tearDown"}
    unused = defined - used - special

    if not unused:
        return "✅ No dead code detected — all defined symbols appear to be used."

    return f"⚠️ Potentially unused symbols in {p.name}:\n" + "\n".join(f"  - `{name}`" for name in sorted(unused))


def _add_type_hints(p: Path) -> str:
    """Suggest type hints for a Python file."""
    if not p.is_file() or p.suffix != ".py":
        return "❌ add_type_hints only supports Python files."

    content = p.read_text(encoding="utf-8")
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return "❌ File has syntax errors."

    suggestions = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Check if return annotation is missing
            if node.returns is None and node.name != "__init__":
                suggestions.append(f"  - `{node.name}()` (line {node.lineno}): missing return type hint")
            # Check args
            for arg in node.args.args:
                if arg.annotation is None and arg.arg != "self":
                    suggestions.append(f"  - `{node.name}({arg.arg})` (line {node.lineno}): parameter `{arg.arg}` has no type hint")

    if not suggestions:
        return "✅ All functions already have type hints."

    return f"⚠️ Missing type hints in {p.name}:\n" + "\n".join(suggestions[:30])


def tool_generate_project(template: str, name: str, path: str = ".", description: str = "", features: list = None) -> str:
    """Scaffold a complete project from a template."""
    features = features or []
    base = Path(path).expanduser().resolve() / name
    if base.exists():
        return f"❌ Directory already exists: {base}"

    template = template.lower().strip()
    generators = {
        "python-cli": _gen_python_cli,
        "python-api": _gen_python_api,
        "python-flask": _gen_python_flask,
        "fastapi": _gen_python_api,
        "flask": _gen_python_flask,
        "node-express": _gen_node_express,
        "express": _gen_node_express,
        "react-app": _gen_react_app,
        "react": _gen_react_app,
        "nextjs-app": _gen_nextjs_app,
        "nextjs": _gen_nextjs_app,
        "go-api": _gen_go_api,
        "go": _gen_go_api,
        "rust-cli": _gen_rust_cli,
        "rust": _gen_rust_cli,
        "django-app": _gen_django_app,
        "django": _gen_django_app,
        "vue-app": _gen_vue_app,
        "vue": _gen_vue_app,
        "fullstack": _gen_fullstack,
    }

    generator = generators.get(template)
    if not generator:
        available = ", ".join(sorted(set(generators.keys())))
        return f"❌ Unknown template: {template}\nAvailable: {available}"

    try:
        base.mkdir(parents=True)
        result = generator(base, name, description, features)
        return f"✅ Project '{name}' created at {base}\n\n{result}"
    except Exception as e:
        return f"❌ Failed to generate project: {e}"


def _write_project_file(base: Path, rel_path: str, content: str):
    """Write a file within a project directory."""
    fp = base / rel_path
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(dedent(content).strip() + "\n", encoding="utf-8")


def _gen_python_cli(base: Path, name: str, desc: str, features: list) -> str:
    """Generate a Python CLI project."""
    safe_name = re.sub(r'[^a-z0-9_]', '_', name.lower())

    _write_project_file(base, "pyproject.toml", f"""
        [build-system]
        requires = ["setuptools>=68.0", "wheel"]
        build-backend = "setuptools.backends._legacy:_Backend"

        [project]
        name = "{safe_name}"
        version = "0.1.0"
        description = "{desc or f'{name} CLI application'}"
        requires-python = ">=3.11"

        [project.scripts]
        {safe_name} = "{safe_name}.cli:main"
    """)

    _write_project_file(base, f"{safe_name}/__init__.py", f'"""{ name }."""\n__version__ = "0.1.0"')

    _write_project_file(base, f"{safe_name}/cli.py", f"""
        \"\"\"CLI entry point for {name}.\"\"\"
        import argparse
        import sys


        def parse_args():
            parser = argparse.ArgumentParser(
                prog="{safe_name}",
                description="{desc or name}",
            )
            parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
            parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
            return parser.parse_args()


        def main():
            args = parse_args()
            print(f"Hello from {name}!")
            return 0


        if __name__ == "__main__":
            sys.exit(main())
    """)

    _write_project_file(base, "tests/__init__.py", "")
    _write_project_file(base, "tests/test_cli.py", f"""
        \"\"\"Tests for {name} CLI.\"\"\"
        import subprocess
        import sys


        def test_version():
            result = subprocess.run(
                [sys.executable, "-m", "{safe_name}.cli", "--version"],
                capture_output=True, text=True,
            )
            assert "0.1.0" in result.stdout


        def test_main():
            from {safe_name}.cli import main
            assert main() == 0
    """)

    _write_project_file(base, "README.md", f"# {name}\n\n{desc or 'A Python CLI application.'}\n\n## Install\n```bash\npip install -e .\n```\n\n## Usage\n```bash\n{safe_name} --help\n```")
    _write_project_file(base, ".gitignore", "__pycache__/\n*.pyc\n.venv/\ndist/\n*.egg-info/\n.pytest_cache/")

    return f"Structure:\n  {safe_name}/cli.py — CLI entry point\n  tests/test_cli.py — Tests\n  pyproject.toml — Config\n\nNext: `cd {name} && python -m venv .venv && source .venv/bin/activate && pip install -e .`"


def _gen_python_api(base: Path, name: str, desc: str, features: list) -> str:
    """Generate a FastAPI project."""
    re.sub(r'[^a-z0-9_]', '_', name.lower())

    _write_project_file(base, "requirements.txt", "fastapi>=0.109.0\nuvicorn>=0.27.0\npydantic>=2.0\nhttpx>=0.27.0")

    _write_project_file(base, "app/__init__.py", "")
    _write_project_file(base, "app/main.py", f"""
        \"\"\"FastAPI application for {name}.\"\"\"
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
        from app.routes import router

        app = FastAPI(
            title="{name}",
            description="{desc or 'API built with FastAPI'}",
            version="0.1.0",
        )

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        app.include_router(router, prefix="/api/v1")


        @app.get("/")
        async def root():
            return {{"message": "Welcome to {name} API", "version": "0.1.0"}}


        @app.get("/health")
        async def health():
            return {{"status": "healthy"}}
    """)

    _write_project_file(base, "app/routes.py", f"""
        \"\"\"API routes for {name}.\"\"\"
        from fastapi import APIRouter, HTTPException
        from app.models import Item, ItemCreate

        router = APIRouter()
        items_db: dict[int, Item] = {{}}
        _counter = 0


        @router.get("/items")
        async def list_items():
            return list(items_db.values())


        @router.post("/items", status_code=201)
        async def create_item(item: ItemCreate):
            global _counter
            _counter += 1
            new = Item(id=_counter, **item.model_dump())
            items_db[_counter] = new
            return new


        @router.get("/items/{{item_id}}")
        async def get_item(item_id: int):
            if item_id not in items_db:
                raise HTTPException(status_code=404, detail="Item not found")
            return items_db[item_id]


        @router.delete("/items/{{item_id}}")
        async def delete_item(item_id: int):
            if item_id not in items_db:
                raise HTTPException(status_code=404, detail="Item not found")
            del items_db[item_id]
            return {{"deleted": item_id}}
    """)

    _write_project_file(base, "app/models.py", f"""
        \"\"\"Data models for {name}.\"\"\"
        from pydantic import BaseModel


        class ItemCreate(BaseModel):
            name: str
            description: str = ""
            price: float = 0.0


        class Item(ItemCreate):
            id: int
    """)

    _write_project_file(base, "tests/test_api.py", f"""
        \"\"\"API tests for {name}.\"\"\"
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)


        def test_root():
            r = client.get("/")
            assert r.status_code == 200
            assert "message" in r.json()


        def test_health():
            r = client.get("/health")
            assert r.status_code == 200


        def test_create_and_get_item():
            r = client.post("/api/v1/items", json={{"name": "Test", "price": 9.99}})
            assert r.status_code == 201
            item_id = r.json()["id"]
            r = client.get(f"/api/v1/items/{{item_id}}")
            assert r.status_code == 200
            assert r.json()["name"] == "Test"
    """)

    _write_project_file(base, "README.md", f"# {name}\n\n{desc or 'A FastAPI application.'}\n\n## Run\n```bash\npip install -r requirements.txt\nuvicorn app.main:app --reload\n```\n\n## Docs\nOpen http://localhost:8000/docs")
    _write_project_file(base, ".gitignore", "__pycache__/\n*.pyc\n.venv/\n.env")

    if "docker" in features:
        _write_project_file(base, "Dockerfile", "FROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install --no-cache-dir -r requirements.txt\nCOPY . .\nCMD [\"uvicorn\", \"app.main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\"]")

    return f"FastAPI project with CRUD routes, models, tests.\n\nNext: `cd {name} && pip install -r requirements.txt && uvicorn app.main:app --reload`"


def _gen_python_flask(base, name, desc, features):
    re.sub(r'[^a-z0-9_]', '_', name.lower())
    _write_project_file(base, "requirements.txt", "flask>=3.0\nflask-cors>=4.0\ngunicorn>=21.2")
    _write_project_file(base, "app.py", f"""
        \"\"\"Flask application for {name}.\"\"\"
        from flask import Flask, jsonify, request
        from flask_cors import CORS

        app = Flask(__name__)
        CORS(app)


        @app.route("/")
        def index():
            return jsonify(message="Welcome to {name}", version="0.1.0")


        @app.route("/health")
        def health():
            return jsonify(status="healthy")


        if __name__ == "__main__":
            app.run(debug=True, port=5000)
    """)
    _write_project_file(base, "README.md", f"# {name}\n\n{desc or 'Flask app.'}\n\n## Run\n```bash\npip install -r requirements.txt\npython app.py\n```")
    _write_project_file(base, ".gitignore", "__pycache__/\n.venv/\n.env\ninstance/")
    return f"Flask project created.\n\nNext: `cd {name} && pip install -r requirements.txt && python app.py`"


def _gen_node_express(base, name, desc, features):
    _write_project_file(base, "package.json", json.dumps({
        "name": name.lower().replace(" ", "-"),
        "version": "0.1.0",
        "description": desc or f"{name} API",
        "main": "src/index.js",
        "scripts": {"start": "node src/index.js", "dev": "node --watch src/index.js", "test": "node --test tests/"},
        "dependencies": {"express": "^4.18.0", "cors": "^2.8.5"},
    }, indent=2))
    _write_project_file(base, "src/index.js", f"""
        const express = require('express');
        const cors = require('cors');
        const app = express();
        const PORT = process.env.PORT || 3000;

        app.use(cors());
        app.use(express.json());

        app.get('/', (req, res) => res.json({{ message: 'Welcome to {name}', version: '0.1.0' }}));
        app.get('/health', (req, res) => res.json({{ status: 'healthy' }}));

        // CRUD routes
        const items = new Map();
        let counter = 0;

        app.get('/api/items', (req, res) => res.json([...items.values()]));
        app.post('/api/items', (req, res) => {{
            const id = ++counter;
            const item = {{ id, ...req.body }};
            items.set(id, item);
            res.status(201).json(item);
        }});
        app.get('/api/items/:id', (req, res) => {{
            const item = items.get(Number(req.params.id));
            item ? res.json(item) : res.status(404).json({{ error: 'Not found' }});
        }});

        app.listen(PORT, () => console.log(`🚀 {name} running on port ${{PORT}}`));
    """)
    _write_project_file(base, ".gitignore", "node_modules/\n.env\ndist/")
    _write_project_file(base, "README.md", f"# {name}\n\n{desc or 'Express API.'}\n\n## Run\n```bash\nnpm install && npm run dev\n```")
    return f"Express project created.\n\nNext: `cd {name} && npm install && npm run dev`"


def _gen_react_app(base, name, desc, features):
    _write_project_file(base, "package.json", json.dumps({
        "name": name.lower().replace(" ", "-"),
        "version": "0.1.0",
        "private": True,
        "type": "module",
        "scripts": {"dev": "vite", "build": "vite build", "preview": "vite preview"},
        "dependencies": {"react": "^18.2.0", "react-dom": "^18.2.0"},
        "devDependencies": {"@vitejs/plugin-react": "^4.2.0", "vite": "^5.0.0"},
    }, indent=2))
    _write_project_file(base, "vite.config.js", 'import { defineConfig } from "vite";\nimport react from "@vitejs/plugin-react";\n\nexport default defineConfig({ plugins: [react()] });')
    _write_project_file(base, "index.html", f'<!DOCTYPE html>\n<html lang="en">\n<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{name}</title></head>\n<body><div id="root"></div><script type="module" src="/src/main.jsx"></script></body>\n</html>')
    _write_project_file(base, "src/main.jsx", 'import React from "react";\nimport ReactDOM from "react-dom/client";\nimport App from "./App";\nimport "./index.css";\n\nReactDOM.createRoot(document.getElementById("root")).render(<React.StrictMode><App /></React.StrictMode>);')
    _write_project_file(base, "src/App.jsx", f'export default function App() {{\n  return (\n    <div style={{{{ textAlign: "center", padding: "2rem" }}}}>\n      <h1>🚀 {name}</h1>\n      <p>{desc or "Built with React + Vite"}</p>\n    </div>\n  );\n}}')
    _write_project_file(base, "src/index.css", "* { margin: 0; padding: 0; box-sizing: border-box; }\nbody { font-family: system-ui, sans-serif; background: #0a0a0a; color: #ededed; }")
    _write_project_file(base, ".gitignore", "node_modules/\ndist/\n.env")
    return f"React + Vite project created.\n\nNext: `cd {name} && npm install && npm run dev`"


def _gen_nextjs_app(base, name, desc, features):
    _write_project_file(base, "package.json", json.dumps({
        "name": name.lower().replace(" ", "-"),
        "version": "0.1.0",
        "private": True,
        "scripts": {"dev": "next dev", "build": "next build", "start": "next start"},
        "dependencies": {"next": "^14.0.0", "react": "^18.2.0", "react-dom": "^18.2.0"},
    }, indent=2))
    _write_project_file(base, "app/layout.js", f'export const metadata = {{ title: "{name}", description: "{desc or name}" }};\n\nexport default function RootLayout({{ children }}) {{\n  return <html lang="en"><body>{{children}}</body></html>;\n}}')
    _write_project_file(base, "app/page.js", f'export default function Home() {{\n  return <main style={{{{ padding: "2rem", textAlign: "center" }}}}><h1>{name}</h1><p>{desc or "Built with Next.js"}</p></main>;\n}}')
    _write_project_file(base, ".gitignore", "node_modules/\n.next/\n.env")
    return f"Next.js project created.\n\nNext: `cd {name} && npm install && npm run dev`"


def _gen_go_api(base, name, desc, features):
    mod_name = name.lower().replace(" ", "-").replace("_", "-")
    _write_project_file(base, "go.mod", f"module {mod_name}\n\ngo 1.21")
    _write_project_file(base, "main.go", f"""
        package main

        import (
            "encoding/json"
            "fmt"
            "log"
            "net/http"
        )

        func main() {{
            http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {{
                json.NewEncoder(w).Encode(map[string]string{{"message": "Welcome to {name}", "version": "0.1.0"}})
            }})
            http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {{
                json.NewEncoder(w).Encode(map[string]string{{"status": "healthy"}})
            }})
            fmt.Println("🚀 {name} running on :8080")
            log.Fatal(http.ListenAndServe(":8080", nil))
        }}
    """)
    _write_project_file(base, ".gitignore", f"{mod_name}\n*.exe")
    _write_project_file(base, "README.md", f"# {name}\n\n{desc or 'Go API.'}\n\n## Run\n```bash\ngo run main.go\n```")
    return f"Go API project created.\n\nNext: `cd {name} && go run main.go`"


def _gen_rust_cli(base, name, desc, features):
    crate = name.lower().replace(" ", "_").replace("-", "_")
    _write_project_file(base, "Cargo.toml", f'[package]\nname = "{crate}"\nversion = "0.1.0"\nedition = "2021"\ndescription = "{desc or name}"')
    _write_project_file(base, "src/main.rs", f'fn main() {{\n    println!("Hello from {name}!");\n}}')
    _write_project_file(base, ".gitignore", "target/\nCargo.lock")
    _write_project_file(base, "README.md", f"# {name}\n\n{desc or 'Rust CLI.'}\n\n## Build & Run\n```bash\ncargo run\n```")
    return f"Rust CLI project created.\n\nNext: `cd {name} && cargo run`"


def _gen_django_app(base, name, desc, features):
    safe = re.sub(r'[^a-z0-9_]', '_', name.lower())
    _write_project_file(base, "requirements.txt", "django>=5.0\ndjangorestframework>=3.14\ndjango-cors-headers>=4.3")
    _write_project_file(base, "manage.py", f"""
        #!/usr/bin/env python
        import os, sys
        if __name__ == "__main__":
            os.environ.setdefault("DJANGO_SETTINGS_MODULE", "{safe}.settings")
            from django.core.management import execute_from_command_line
            execute_from_command_line(sys.argv)
    """)
    _write_project_file(base, f"{safe}/__init__.py", "")
    _write_project_file(base, f"{safe}/settings.py", f"""
        from pathlib import Path
        BASE_DIR = Path(__file__).resolve().parent.parent
        SECRET_KEY = "change-me-in-production"
        DEBUG = True
        ALLOWED_HOSTS = ["*"]
        INSTALLED_APPS = ["django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
                          "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
                          "rest_framework", "corsheaders"]
        MIDDLEWARE = ["corsheaders.middleware.CorsMiddleware", "django.middleware.common.CommonMiddleware",
                      "django.middleware.security.SecurityMiddleware", "django.contrib.sessions.middleware.SessionMiddleware",
                      "django.middleware.csrf.CsrfViewMiddleware", "django.contrib.auth.middleware.AuthenticationMiddleware",
                      "django.contrib.messages.middleware.MessageMiddleware"]
        ROOT_URLCONF = "{safe}.urls"
        TEMPLATES = [{{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [], "APP_DIRS": True,
                      "OPTIONS": {{"context_processors": ["django.template.context_processors.request", "django.contrib.auth.context_processors.auth"]}}}}]
        DATABASES = {{"default": {{"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}}}
        STATIC_URL = "/static/"
        CORS_ALLOW_ALL_ORIGINS = True
    """)
    _write_project_file(base, f"{safe}/urls.py", """
        from django.contrib import admin
        from django.urls import path
        urlpatterns = [path("admin/", admin.site.urls)]
    """)
    _write_project_file(base, "README.md", f"# {name}\n\n{desc or 'Django app.'}\n\n## Run\n```bash\npip install -r requirements.txt\npython manage.py migrate\npython manage.py runserver\n```")
    _write_project_file(base, ".gitignore", "__pycache__/\ndb.sqlite3\n.venv/\n.env\nmedia/")
    return f"Django project created.\n\nNext: `cd {name} && pip install -r requirements.txt && python manage.py migrate && python manage.py runserver`"


def _gen_vue_app(base, name, desc, features):
    _write_project_file(base, "package.json", json.dumps({
        "name": name.lower().replace(" ", "-"),
        "version": "0.1.0",
        "private": True,
        "type": "module",
        "scripts": {"dev": "vite", "build": "vite build"},
        "dependencies": {"vue": "^3.4.0"},
        "devDependencies": {"@vitejs/plugin-vue": "^5.0.0", "vite": "^5.0.0"},
    }, indent=2))
    _write_project_file(base, "vite.config.js", 'import { defineConfig } from "vite";\nimport vue from "@vitejs/plugin-vue";\n\nexport default defineConfig({ plugins: [vue()] });')
    _write_project_file(base, "index.html", f'<!DOCTYPE html>\n<html><head><meta charset="UTF-8"><title>{name}</title></head>\n<body><div id="app"></div><script type="module" src="/src/main.js"></script></body></html>')
    _write_project_file(base, "src/main.js", 'import { createApp } from "vue";\nimport App from "./App.vue";\ncreateApp(App).mount("#app");')
    _write_project_file(base, "src/App.vue", f'<template><div style="text-align:center;padding:2rem"><h1>🚀 {name}</h1><p>{desc or "Built with Vue + Vite"}</p></div></template>')
    _write_project_file(base, ".gitignore", "node_modules/\ndist/")
    return f"Vue + Vite project created.\n\nNext: `cd {name} && npm install && npm run dev`"


def _gen_fullstack(base, name, desc, features):
    """Generate a fullstack project with React frontend + FastAPI backend."""
    _gen_python_api(base / "backend", f"{name}-backend", f"{name} API backend", features)
    _gen_react_app(base / "frontend", f"{name}-frontend", f"{name} React frontend", features)
    _write_project_file(base, "README.md", f"# {name}\n\nFullstack: React (frontend) + FastAPI (backend).\n\n## Run Backend\n```bash\ncd backend && pip install -r requirements.txt && uvicorn app.main:app --reload\n```\n\n## Run Frontend\n```bash\ncd frontend && npm install && npm run dev\n```")
    _write_project_file(base, ".gitignore", "__pycache__/\nnode_modules/\n.venv/\n.env\ndist/")
    return "Fullstack project created:\n  backend/ — FastAPI API\n  frontend/ — React + Vite\n\nStart both servers to run."



def tool_install_dependencies(packages: list, manager: str = "", dev: bool = False, cwd: str = "") -> str:
    """Install dependency tokens through a shell-free package-manager argv."""
    work_dir = cwd or os.getcwd()
    if not manager:
        manager = _detect_package_manager(work_dir)
    try:
        safe_packages = ensure_safe_tokens(packages, label="package")
    except ValueError as exc:
        return f"❌ Install rejected: {exc}"
    commands = {
        "pip": [sys.executable, "-m", "pip", "install", *safe_packages],
        "pip3": ["pip3", "install", *safe_packages],
        "npm": ["npm", "install", *( ["--save-dev"] if dev else []), *safe_packages],
        "yarn": ["yarn", "add", *( ["--dev"] if dev else []), *safe_packages],
        "pnpm": ["pnpm", "add", *( ["--save-dev"] if dev else []), *safe_packages],
        "cargo": ["cargo", "add", *safe_packages],
        "go": ["go", "get", *safe_packages],
        "brew": ["brew", "install", *safe_packages],
        "composer": ["composer", "require", *( ["--dev"] if dev else []), *safe_packages],
    }
    argv = commands.get(manager)
    if not argv:
        return f"❌ Unknown package manager: {manager}"
    try:
        result = subprocess.run(argv, shell=False, cwd=work_dir, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            return f"❌ Install failed:\n{result.stderr.strip()}"
        return f"✅ Installed {len(safe_packages)} package(s) via {manager}:\n{', '.join(safe_packages)}\n{result.stdout.strip()[:500]}"
    except subprocess.TimeoutExpired:
        return "❌ Install timed out after 120s."
    except OSError as exc:
        return f"❌ Install error: {exc}"



def _detect_package_manager(path: str) -> str:
    """Auto-detect the project's package manager."""
    p = Path(path)
    if (p / "package-lock.json").exists(): return "npm"
    if (p / "yarn.lock").exists(): return "yarn"
    if (p / "pnpm-lock.yaml").exists(): return "pnpm"
    if (p / "package.json").exists(): return "npm"
    if (p / "Cargo.toml").exists(): return "cargo"
    if (p / "go.mod").exists(): return "go"
    if (p / "composer.json").exists(): return "composer"
    if (p / "Gemfile").exists(): return "gem"
    return "pip"



def tool_run_tests(path: str = ".", framework: str = "", filter: str = "", verbose: bool = True, cwd: str = "") -> str:
    """Auto-detect and run tests through a shell-free argv."""
    work_dir = cwd or os.getcwd()
    try:
        safe_path = repo_relative_path(path, work_dir)
    except PermissionError as exc:
        return f"❌ Test path rejected: {exc}"
    if not framework:
        framework = _detect_test_framework(work_dir)
    commands = {
        "pytest": [sys.executable, "-m", "pytest", safe_path, *( ["-v"] if verbose else []), *( ["-k", filter] if filter else [])],
        "unittest": [sys.executable, "-m", "unittest", "discover", safe_path, *( ["-v"] if verbose else [])],
        "jest": ["npx", "jest", safe_path, *( ["--verbose"] if verbose else []), *( [f"--testNamePattern={filter}"] if filter else [])],
        "vitest": ["npx", "vitest", "run", safe_path],
        "mocha": ["npx", "mocha", safe_path],
        "go": ["go", "test", "./..." if safe_path == "." else safe_path, *( ["-v"] if verbose else []), *( ["-run", filter] if filter else [])],
        "cargo": ["cargo", "test", *( [filter] if filter else [])],
        "rspec": ["bundle", "exec", "rspec", safe_path],
        "phpunit": ["./vendor/bin/phpunit", safe_path],
    }
    argv = commands.get(framework)
    if not argv:
        return f"❌ Unknown test framework: {framework}. Supported: {', '.join(commands.keys())}"
    try:
        result = subprocess.run(argv, shell=False, cwd=work_dir, capture_output=True, text=True, timeout=300)
        output = result.stdout + ("\n" + result.stderr if result.stderr else "")
        status = "✅ Tests PASSED" if result.returncode == 0 else "❌ Tests FAILED"
        return f"{status}\n\nFramework: {framework}\n{output.strip()[:3000]}"
    except subprocess.TimeoutExpired:
        return "❌ Tests timed out after 300s."
    except OSError as exc:
        return f"❌ Test error: {exc}"



def _detect_test_framework(path: str) -> str:
    """Auto-detect the test framework."""
    p = Path(path)
    if (p / "pytest.ini").exists() or (p / "pyproject.toml").exists() or (p / "conftest.py").exists():
        return "pytest"
    if (p / "jest.config.js").exists() or (p / "jest.config.ts").exists():
        return "jest"
    if (p / "vitest.config.ts").exists() or (p / "vitest.config.js").exists():
        return "vitest"
    if (p / "Cargo.toml").exists():
        return "cargo"
    if (p / "go.mod").exists():
        return "go"
    if (p / "package.json").exists():
        try:
            pkg = json.loads((p / "package.json").read_text())
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "jest" in deps: return "jest"
            if "vitest" in deps: return "vitest"
            if "mocha" in deps: return "mocha"
        except Exception:
            pass
        return "jest"
    return "pytest"



def tool_lint_code(path: str, fix: bool = False, linter: str = "", cwd: str = "") -> str:
    """Run a supported linter through a shell-free argv."""
    work_dir = cwd or os.getcwd()
    try:
        safe_path = repo_relative_path(path, work_dir)
    except PermissionError as exc:
        return f"❌ Lint path rejected: {exc}"
    p = Path(work_dir) / safe_path
    lang = _detect_language(str(p)) if p.is_file() else ""
    if not linter:
        if lang == "python" or (p.is_dir() and (p / "pyproject.toml").exists()):
            linter = "ruff"
        elif lang in ("javascript", "typescript"):
            linter = "eslint"
        elif lang == "go":
            linter = "golangci-lint"
        elif lang == "rust":
            linter = "clippy"
        else:
            linter = "ruff"
    commands = {
        "ruff": [sys.executable, "-m", "ruff", "check", safe_path, *( ["--fix"] if fix else [])],
        "flake8": [sys.executable, "-m", "flake8", safe_path],
        "eslint": ["npx", "eslint", safe_path, *( ["--fix"] if fix else [])],
        "golangci-lint": ["golangci-lint", "run", safe_path],
        "clippy": ["cargo", "clippy"],
    }
    argv = commands.get(linter)
    if not argv:
        return f"❌ Unknown linter: {linter}"
    try:
        result = subprocess.run(argv, shell=False, cwd=work_dir, capture_output=True, text=True, timeout=60)
        output = (result.stdout + "\n" + result.stderr).strip()
        if result.returncode == 0 and not output:
            return f"✅ No lint issues found ({linter})."
        return f"Lint results ({linter}):\n{output[:3000]}"
    except OSError as exc:
        return f"❌ Lint error: {exc}. Is {linter} installed?"




def tool_format_code(path: str, formatter: str = "", check_only: bool = False, cwd: str = "") -> str:
    """Run a supported formatter through a shell-free argv."""
    work_dir = cwd or os.getcwd()
    try:
        safe_path = repo_relative_path(path, work_dir)
    except PermissionError as exc:
        return f"❌ Format path rejected: {exc}"
    p = Path(work_dir) / safe_path
    lang = _detect_language(str(p)) if p.is_file() else ""
    if not formatter:
        fmt_map = {"python": "black", "javascript": "prettier", "typescript": "prettier", "go": "gofmt", "rust": "rustfmt", "c": "clang-format", "cpp": "clang-format"}
        formatter = fmt_map.get(lang, "black")
    commands = {
        "black": [sys.executable, "-m", "black", safe_path, *( ["--check"] if check_only else [])],
        "ruff": [sys.executable, "-m", "ruff", "format", safe_path, *( ["--check"] if check_only else [])],
        "prettier": ["npx", "prettier", "--check" if check_only else "--write", safe_path],
        "gofmt": ["gofmt", "-l" if check_only else "-w", safe_path],
        "rustfmt": ["rustfmt", safe_path, *( ["--check"] if check_only else [])],
        "clang-format": ["clang-format", "-n" if check_only else "-i", safe_path],
    }
    argv = commands.get(formatter)
    if not argv:
        return f"❌ Unknown formatter: {formatter}"
    try:
        result = subprocess.run(argv, shell=False, cwd=work_dir, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            return f"✅ {'Check passed' if check_only else 'Formatted'} with {formatter}: {safe_path}"
        return f"Format result ({formatter}):\n{(result.stdout + result.stderr).strip()[:2000]}"
    except OSError as exc:
        return f"❌ Format error: {exc}. Is {formatter} installed?"



def tool_debug_error(error: str, context_path: str = "", language: str = "") -> str:
    """Parse stack traces and locate bugs."""
    report = ["# Error Debug Report\n"]

    # Parse file:line references from the stack trace
    file_refs = re.findall(r'File "([^"]+)", line (\d+)', error)  # Python
    if not file_refs:
        file_refs = re.findall(r'at\s+(?:\S+\s+\()?([^:()]+):(\d+)(?::\d+)?\)?', error)  # JS/TS
    if not file_refs:
        file_refs = re.findall(r'(\S+\.(?:go|rs|java|cpp|c)):(\d+)', error)  # Go/Rust/Java/C

    report.append(f"**Error excerpt:**\n```\n{error[:1000]}\n```\n")

    # Identify error type
    error_type = ""
    if "TypeError" in error: error_type = "TypeError"
    elif "SyntaxError" in error: error_type = "SyntaxError"
    elif "ImportError" in error or "ModuleNotFoundError" in error: error_type = "ImportError"
    elif "AttributeError" in error: error_type = "AttributeError"
    elif "KeyError" in error: error_type = "KeyError"
    elif "IndexError" in error: error_type = "IndexError"
    elif "ValueError" in error: error_type = "ValueError"
    elif "FileNotFoundError" in error: error_type = "FileNotFoundError"
    elif "PermissionError" in error: error_type = "PermissionError"
    elif "ConnectionError" in error or "ConnectionRefused" in error: error_type = "ConnectionError"
    elif "TimeoutError" in error or "Timeout" in error: error_type = "TimeoutError"
    elif "ReferenceError" in error: error_type = "ReferenceError (JS)"
    elif "NullPointerException" in error: error_type = "NullPointerException (Java)"
    elif "segfault" in error.lower() or "segmentation fault" in error.lower(): error_type = "Segmentation Fault"

    if error_type:
        report.append(f"**Error Type:** `{error_type}`\n")

    # Show source context for referenced files
    if file_refs:
        report.append("## Source Context\n")
        for filepath, lineno in file_refs[:5]:
            lineno = int(lineno)
            fp = Path(filepath).expanduser()
            if not fp.exists() and context_path:
                fp = Path(context_path) / filepath
            if fp.exists():
                try:
                    with open(fp, "r", encoding="utf-8", errors="replace") as f:
                        lines = f.readlines()
                    start = max(0, lineno - 4)
                    end = min(len(lines), lineno + 3)
                    report.append(f"### {fp.name}:{lineno}\n```")
                    for i in range(start, end):
                        marker = " >>> " if i + 1 == lineno else "     "
                        report.append(f"{marker}{i + 1}: {lines[i].rstrip()}")
                    report.append("```\n")
                except OSError:
                    pass

    # Common fix suggestions based on error type
    fixes = {
        "ImportError": "Check if the module is installed (`pip install <module>`), or fix the import path.",
        "TypeError": "Check function argument types and counts. Ensure you're not calling None or passing wrong types.",
        "AttributeError": "The object doesn't have this attribute. Check spelling, or ensure the object is the type you expect.",
        "KeyError": "The key doesn't exist in the dictionary. Use `.get(key, default)` for safe access.",
        "IndexError": "List index out of range. Check list length before accessing by index.",
        "FileNotFoundError": "File doesn't exist. Check the path, or create the file/directory first.",
        "ConnectionError": "Cannot connect to the server. Check URL, network, and whether the service is running.",
        "ValueError": "Invalid value passed. Check input data format and constraints.",
    }

    if error_type in fixes:
        report.append(f"## Suggested Fix\n💡 {fixes[error_type]}\n")

    return "\n".join(report)


def tool_explain_code(path: str, start_line: int = None, end_line: int = None, detail_level: str = "normal") -> str:
    """Generate code explanation."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return f"❌ File not found: {path}"

    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError as err:
        return f"❌ Cannot read: {err}"

    total = len(lines)
    s = max(1, start_line or 1)
    end_idx = min(total, end_line or total)
    selected = lines[s - 1: end_idx]
    code = "".join(selected)
    lang = _detect_language(str(p))

    report = [
        f"# Code Explanation: {p.name}",
        f"**Language:** {lang}",
        f"**Lines:** {s}-{end_idx} of {total}",
        "",
        "```" + lang,
        code.rstrip(),
        "```",
        "",
        "## Analysis",
        "",
        f"This code block contains {len(selected)} lines of {lang} code.",
    ]

    # Basic structural analysis
    if lang == "python":
        funcs = re.findall(r'def\s+(\w+)\s*\(', code)
        classes = re.findall(r'class\s+(\w+)', code)
        if classes:
            report.append(f"\n**Classes defined:** {', '.join(classes)}")
        if funcs:
            report.append(f"**Functions defined:** {', '.join(funcs)}")

    report.append("\n*Use this analysis with the LLM's understanding to get a full explanation. The code is provided above for reference.*")

    return "\n".join(report)



def tool_create_tests(source_path: str, output_path: str = "", framework: str = "", style: str = "unit") -> str:
    """Generate executable structural tests; never emit placeholder assertions."""
    p = Path(source_path).expanduser().resolve()
    if not p.exists():
        return f"❌ File not found: {source_path}"
    lang = _detect_language(str(p))
    if not framework:
        if lang == "python":
            framework = "pytest"
        elif lang in ("javascript", "typescript"):
            framework = "jest"
        else:
            return f"❌ Automatic complete test generation is unsupported for {lang or p.suffix}; no placeholder file was written."
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"❌ Cannot read: {exc}"
    if not output_path:
        if framework in ("pytest", "unittest"):
            output_path = str(p.parent / f"test_{p.name}")
        elif framework in ("jest", "mocha", "vitest"):
            output_path = str(p.parent / f"{p.stem}.test{p.suffix}")
        else:
            return f"❌ Unsupported test framework: {framework}"
    if lang == "python":
        test_code = _generate_python_tests(content, p, framework)
    elif lang in ("javascript", "typescript"):
        test_code = _generate_js_tests(content, p, framework)
    else:
        return f"❌ Automatic complete test generation is unsupported for {lang}; no placeholder file was written."
    out = Path(output_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(test_code, encoding="utf-8")
    return f"✅ Executable structural test file created: {out}\nFramework: {framework}\nSource: {p.name}"




def _generate_python_tests(content: str, path: Path, framework: str) -> str:
    """Generate deterministic import and public-interface contract tests."""
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        raise ValueError(f"source file is not valid Python: {exc}") from exc
    functions: list[tuple[str, list[str]]] = []
    classes: list[tuple[str, list[str]]] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            args = [arg.arg for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs) if arg.arg != "self"]
            functions.append((node.name, args))
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            methods = [
                child.name for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and not child.name.startswith("_")
            ]
            classes.append((node.name, methods))
    lines = [
        f'"""Generated public-interface contract tests for {path.name}."""',
        "from __future__ import annotations",
        "import importlib.util",
        "import inspect",
        "from pathlib import Path",
        "",
        f"SOURCE = Path({str(path)!r})",
        "SPEC = importlib.util.spec_from_file_location('generated_contract_target', SOURCE)",
        "assert SPEC is not None and SPEC.loader is not None",
        "MODULE = importlib.util.module_from_spec(SPEC)",
        "SPEC.loader.exec_module(MODULE)",
        "",
        "def test_module_imports_cleanly():",
        "    assert MODULE is not None",
        "",
    ]
    for name, args in functions:
        lines.extend([
            f"def test_function_{name}_contract():",
            f"    target = getattr(MODULE, {name!r})",
            "    assert callable(target)",
            f"    assert list(inspect.signature(target).parameters) == {args!r}",
            "",
        ])
    for name, methods in classes:
        lines.extend([
            f"def test_class_{name}_contract():",
            f"    target = getattr(MODULE, {name!r})",
            "    assert inspect.isclass(target)",
            f"    assert all(callable(getattr(target, method)) for method in {methods!r})",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"




def _generate_js_tests(content: str, path: Path, framework: str) -> str:
    """Generate public-export contract tests without fabricated behaviour."""
    functions = sorted(set(
        re.findall(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)', content)
        + re.findall(r'(?:export\s+)?(?:const|let)\s+(\w+)\s*=\s*(?:async\s+)?\(', content)
    ))
    module = f"./{path.stem}"
    lines = [f"// Generated public-interface contract tests for {path.name}", f"const target = require('{module}');", ""]
    lines.extend([
        "test('module loads', () => {",
        "  expect(target).toBeDefined();",
        "});",
        "",
    ])
    for name in functions:
        lines.extend([
            f"test('{name} is exported as a function', () => {{",
            f"  expect(typeof target.{name}).toBe('function');",
            "});",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"



def tool_diff_files(file_a: str, file_b: str, context_lines: int = 3) -> str:
    """Unified diff between two files."""
    import difflib
    pa = Path(file_a).expanduser().resolve()
    pb = Path(file_b).expanduser().resolve()

    if not pa.exists(): return f"❌ File not found: {file_a}"
    if not pb.exists(): return f"❌ File not found: {file_b}"

    try:
        a_lines = pa.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        b_lines = pb.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    except OSError as e:
        return f"❌ Cannot read files: {e}"

    diff = difflib.unified_diff(a_lines, b_lines, fromfile=str(pa), tofile=str(pb), n=context_lines)
    result = "".join(diff)

    if not result:
        return "✅ Files are identical."
    return f"Diff:\n```diff\n{result}\n```"


def tool_batch_edit(directory: str, file_pattern: str, find: str, replace: str, is_regex: bool = False, dry_run: bool = False) -> str:
    """Find and replace across multiple files."""
    p = Path(directory).expanduser().resolve()
    if not p.exists():
        return f"❌ Directory not found: {directory}"

    files = list(p.rglob(file_pattern))
    files = [f for f in files if f.is_file() and not any(part.startswith(".") or part in ("node_modules", "__pycache__") for part in f.parts)]

    modified = []
    total_replacements = 0

    for f in files:
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if is_regex:
            new_content, count = re.subn(find, replace, content)
        else:
            count = content.count(find)
            new_content = content.replace(find, replace)

        if count > 0:
            if not dry_run:
                f.write_text(new_content, encoding="utf-8")
            modified.append(f"  {f.relative_to(p)}: {count} replacement(s)")
            total_replacements += count

    if not modified:
        return f"No matches for '{find}' in {file_pattern} files."

    mode = "[DRY RUN] " if dry_run else ""
    return f"{mode}{'Would modify' if dry_run else 'Modified'} {len(modified)} file(s), {total_replacements} replacement(s):\n" + "\n".join(modified)



def tool_manage_env(action: str, env_type: str = "python", name: str = ".venv", python_version: str = "", cwd: str = "") -> str:
    """Manage virtual environments without shell interpolation."""
    work_dir = cwd or os.getcwd()
    try:
        safe_name = repo_relative_path(name, work_dir)
    except PermissionError as exc:
        return f"❌ Environment path rejected: {exc}"
    if env_type == "python":
        env_path = Path(work_dir) / safe_name
        if action == "create":
            python_cmd = f"python{python_version}" if python_version else sys.executable
            if python_version and not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", python_version):
                return "❌ Invalid Python version token."
            try:
                result = subprocess.run(
                    [python_cmd, "-m", "venv", safe_name], shell=False, cwd=work_dir,
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode != 0:
                    return f"❌ Failed to create venv: {result.stderr}"
                return f"✅ Virtual environment created: {env_path}\n\nActivate: source {safe_name}/bin/activate"
            except OSError as exc:
                return f"❌ Error: {exc}"
        if action == "install":
            req_file = Path(work_dir) / "requirements.txt"
            if req_file.exists():
                pip_path = env_path / "bin" / "pip"
                if not pip_path.exists():
                    pip_path = env_path / "bin" / "pip3"
                try:
                    result = subprocess.run(
                        [str(pip_path), "install", "-r", "requirements.txt"], shell=False, cwd=work_dir,
                        capture_output=True, text=True, timeout=120,
                    )
                    if result.returncode == 0:
                        return f"✅ Dependencies installed in {safe_name}"
                    return f"❌ Install failed: {result.stderr[:500]}"
                except OSError as exc:
                    return f"❌ Error: {exc}"
            return "❌ No requirements.txt found."
        if action == "list":
            venvs = [d.name for d in Path(work_dir).iterdir() if d.is_dir() and (d / "bin" / "python").exists()]
            if not venvs:
                return "No virtual environments found in current directory."
            return "Virtual environments:\n" + "\n".join(f"  - {v}" for v in venvs)
        if action == "remove":
            if env_path.exists() and env_path.is_dir():
                shutil.rmtree(env_path)
                return f"✅ Removed virtual environment: {safe_name}"
            return f"❌ Environment not found: {safe_name}"
    return f"❌ Unsupported environment type/action: {env_type}/{action}"



def tool_port_check(ports: list = None, find_available: bool = False, range_start: int = 3000, range_end: int = 9999) -> str:
    """Check port availability."""
    results = []

    if ports:
        for port in ports:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.5)
                    result = s.connect_ex(("127.0.0.1", port))
                    if result == 0:
                        results.append(f"  🔴 Port {port}: IN USE")
                    else:
                        results.append(f"  🟢 Port {port}: AVAILABLE")
            except Exception:
                results.append(f"  ⚠️ Port {port}: UNKNOWN")

    if find_available:
        for port in range(range_start, min(range_end + 1, range_start + 100)):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.2)
                    if s.connect_ex(("127.0.0.1", port)) != 0:
                        results.append(f"\n  🟢 Available port found: {port}")
                        break
            except Exception:
                continue

    return "Port Status:\n" + "\n".join(results) if results else "No ports specified."


def tool_docker_compose(project_path: str = ".", services: list = None, output_path: str = "") -> str:
    """Generate Docker configuration."""
    p = Path(project_path).expanduser().resolve()
    services = services or []
    out = Path(output_path).expanduser().resolve() if output_path else p

    # Detect project type
    lang = ""
    if (p / "requirements.txt").exists() or (p / "pyproject.toml").exists():
        lang = "python"
    elif (p / "package.json").exists():
        lang = "node"
    elif (p / "go.mod").exists():
        lang = "go"
    elif (p / "Cargo.toml").exists():
        lang = "rust"

    # Generate Dockerfile
    dockerfiles = {
        "python": "FROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install --no-cache-dir -r requirements.txt\nCOPY . .\nEXPOSE 8000\nCMD [\"python\", \"-m\", \"uvicorn\", \"app.main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\"]",
        "node": "FROM node:20-slim\nWORKDIR /app\nCOPY package*.json ./\nRUN npm ci --production\nCOPY . .\nEXPOSE 3000\nCMD [\"node\", \"src/index.js\"]",
        "go": "FROM golang:1.21-alpine AS builder\nWORKDIR /app\nCOPY go.* ./\nRUN go mod download\nCOPY . .\nRUN CGO_ENABLED=0 go build -o server .\n\nFROM alpine:latest\nCOPY --from=builder /app/server /server\nEXPOSE 8080\nCMD [\"/server\"]",
        "rust": "FROM rust:1.75 AS builder\nWORKDIR /app\nCOPY . .\nRUN cargo build --release\n\nFROM debian:bookworm-slim\nCOPY --from=builder /app/target/release/app /app\nCMD [\"/app\"]",
    }

    dockerfile = dockerfiles.get(lang, dockerfiles["python"])
    (out / "Dockerfile").write_text(dockerfile + "\n", encoding="utf-8")

    # Generate docker-compose.yml
    compose = {"version": "3.8", "services": {"app": {"build": ".", "ports": ["8000:8000"], "environment": [], "volumes": [".:/app"]}}}

    service_configs = {
        "postgres": {"image": "postgres:16-alpine", "ports": ["5432:5432"], "environment": ["POSTGRES_DB=app", "POSTGRES_USER=app", "POSTGRES_PASSWORD=secret"], "volumes": ["pgdata:/var/lib/postgresql/data"]},
        "redis": {"image": "redis:7-alpine", "ports": ["6379:6379"]},
        "mongodb": {"image": "mongo:7", "ports": ["27017:27017"], "volumes": ["mongodata:/data/db"]},
        "mysql": {"image": "mysql:8", "ports": ["3306:3306"], "environment": ["MYSQL_ROOT_PASSWORD=secret", "MYSQL_DATABASE=app"]},
        "nginx": {"image": "nginx:alpine", "ports": ["80:80"], "volumes": ["./nginx.conf:/etc/nginx/nginx.conf"]},
        "rabbitmq": {"image": "rabbitmq:3-management-alpine", "ports": ["5672:5672", "15672:15672"]},
    }

    volumes = {}
    for svc in services:
        svc_lower = svc.lower()
        if svc_lower in service_configs:
            compose["services"][svc_lower] = service_configs[svc_lower]
            if "volumes" in service_configs[svc_lower]:
                for vol in service_configs[svc_lower]["volumes"]:
                    if ":" in vol and not vol.startswith("."):
                        vol_name = vol.split(":")[0]
                        volumes[vol_name] = None

    if volumes:
        compose["volumes"] = volumes

    # Write YAML manually (avoid PyYAML dependency)
    yaml_lines = _dict_to_yaml(compose)
    (out / "docker-compose.yml").write_text(yaml_lines, encoding="utf-8")

    extra_svcs = f" + {', '.join(services)}" if services else ""
    return f"✅ Docker configuration created at {out}:\n  - Dockerfile ({lang or 'generic'})\n  - docker-compose.yml (app{extra_svcs})\n\nRun: `docker-compose up --build`"


def _dict_to_yaml(d: dict, indent: int = 0) -> str:
    """Simple dict-to-YAML serializer."""
    lines = []
    prefix = "  " * indent
    for key, val in d.items():
        if isinstance(val, dict):
            lines.append(f"{prefix}{key}:")
            lines.append(_dict_to_yaml(val, indent + 1))
        elif isinstance(val, list):
            lines.append(f"{prefix}{key}:")
            for item in val:
                if isinstance(item, dict):
                    lines.append(f"{prefix}  -")
                    lines.append(_dict_to_yaml(item, indent + 2))
                else:
                    lines.append(f"{prefix}  - {item}")
        elif val is None:
            lines.append(f"{prefix}{key}:")
        else:
            lines.append(f"{prefix}{key}: {val}")
    return "\n".join(lines)


def tool_api_scaffold(framework: str, name: str, models: list = None, features: list = None, output_path: str = "") -> str:
    """Generate API boilerplate."""
    models = models or []
    features = features or []

    if framework.lower() in ("fastapi", "fast-api"):
        return tool_generate_project("python-api", name, f"{name} REST API", features)
    elif framework.lower() in ("flask",):
        return tool_generate_project("python-flask", name, f"{name} Flask API", features)
    elif framework.lower() in ("express", "node-express"):
        return tool_generate_project("node-express", name, f"{name} Express API", features)
    elif framework.lower() in ("django-rest", "django"):
        return tool_generate_project("django-app", name, f"{name} Django REST API", features)
    elif framework.lower() in ("gin", "go-gin", "go"):
        return tool_generate_project("go-api", name, f"{name} Go API", features)
    else:
        return f"❌ Unknown API framework: {framework}. Supported: fastapi, flask, express, django-rest, gin."


def tool_create_fullstack_app(name: str, template: str = "fullstack", description: str = "", path: str = ".") -> str:
    """Master tool to scaffold, configure, build, and initialize a complete full-stack web application."""
    tmpl = template or "fullstack"
    res = tool_generate_project(tmpl, name, path, description or f"{name} Application", ["testing", "docker"])
    return f"🚀 Master App Builder Executed:\n{res}\n\nApp initialized successfully! Ready for full-stack development and testing."


def tool_test_and_auto_fix(path: str = ".", framework: str = "", max_attempts: int = 3) -> str:
    """Autonomous TDD loop tool: runs tests, diagnoses stack traces on failure, and reports status."""
    target_dir = Path(path).resolve()
    test_output = tool_run_tests(str(target_dir), framework)
    
    if "FAIL" not in test_output and "FAILED" not in test_output and "Error" not in test_output:
        return f"✅ All tests passed cleanly!\n\n{test_output}"
        
    debug_analysis = tool_debug_error(test_output, str(target_dir))
    return f"⚠️ Tests failed. Diagnostic analysis:\n{debug_analysis}\n\nOriginal Test Output:\n{test_output}"


# ── Dispatch ─────────────────────────────────────────────────────────────────

ADVANCED_CODING_DISPATCH = {
    "analyze_code": lambda **kw: tool_analyze_code(kw.get("path", "."), kw.get("language", ""), kw.get("include_metrics", True)),
    "refactor_code": lambda **kw: tool_refactor_code(kw.get("path", "."), kw.get("operation", ""), kw.get("old_name", ""), kw.get("new_name", ""), kw.get("file_pattern", "*.py")),
    "generate_project": lambda **kw: tool_generate_project(kw.get("template", ""), kw.get("name", ""), kw.get("path", "."), kw.get("description", ""), kw.get("features")),
    "install_dependencies": lambda **kw: tool_install_dependencies(kw.get("packages", []), kw.get("manager", ""), kw.get("dev", False), kw.get("cwd", "")),
    "run_tests": lambda **kw: tool_run_tests(kw.get("path", "."), kw.get("framework", ""), kw.get("filter", ""), kw.get("verbose", True), kw.get("cwd", "")),
    "lint_code": lambda **kw: tool_lint_code(kw.get("path", "."), kw.get("fix", False), kw.get("linter", ""), kw.get("cwd", "")),
    "format_code": lambda **kw: tool_format_code(kw.get("path", "."), kw.get("formatter", ""), kw.get("check_only", False), kw.get("cwd", "")),
    "debug_error": lambda **kw: tool_debug_error(kw.get("error", ""), kw.get("context_path", ""), kw.get("language", "")),
    "explain_code": lambda **kw: tool_explain_code(kw.get("path", ""), kw.get("start_line"), kw.get("end_line"), kw.get("detail_level", "normal")),
    "create_tests": lambda **kw: tool_create_tests(kw.get("source_path", ""), kw.get("output_path", ""), kw.get("framework", ""), kw.get("style", "unit")),
    "diff_files": lambda **kw: tool_diff_files(kw.get("file_a", ""), kw.get("file_b", ""), kw.get("context_lines", 3)),
    "batch_edit": lambda **kw: tool_batch_edit(kw.get("directory", "."), kw.get("file_pattern", ""), kw.get("find", ""), kw.get("replace", ""), kw.get("is_regex", False), kw.get("dry_run", False)),
    "manage_env": lambda **kw: tool_manage_env(kw.get("action", ""), kw.get("env_type", "python"), kw.get("name", ".venv"), kw.get("python_version", ""), kw.get("cwd", "")),
    "port_check": lambda **kw: tool_port_check(kw.get("ports"), kw.get("find_available", False), kw.get("range_start", 3000), kw.get("range_end", 9999)),
    "docker_compose": lambda **kw: tool_docker_compose(kw.get("project_path", "."), kw.get("services"), kw.get("output_path", "")),
    "api_scaffold": lambda **kw: tool_api_scaffold(kw.get("framework", ""), kw.get("name", ""), kw.get("models"), kw.get("features"), kw.get("output_path", "")),
    "create_fullstack_app": lambda **kw: tool_create_fullstack_app(kw.get("name", ""), kw.get("template", "fullstack"), kw.get("description", ""), kw.get("path", ".")),
    "test_and_auto_fix": lambda **kw: tool_test_and_auto_fix(kw.get("path", "."), kw.get("framework", ""), kw.get("max_attempts", 3)),
}
