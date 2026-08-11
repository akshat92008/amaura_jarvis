"""
AST Codebase Symbol Indexer Module for JARVIS.
Parses ASTs across project files to extract type signatures, function contracts, imports, and class structures.
"""

import os
import ast
import re
from typing import Dict, Any, List

AST_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "index_codebase_ast",
            "description": "Parse ASTs of Python/JS/TS files in a directory to extract classes, functions, docstrings, and signature contracts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root_dir": {
                        "type": "string",
                        "description": "Directory path to parse and index (defaults to workspace root).",
                        "default": "."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_symbol",
            "description": "Search indexed codebase symbols for class or function definitions matching a keyword.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Symbol name or keyword to search for (e.g. 'execute_tool')."
                    },
                    "root_dir": {
                        "type": "string",
                        "description": "Directory path containing indexed symbols.",
                        "default": "."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_ast_dependencies",
            "description": "Analyze cross-file imports and module dependencies using AST parsing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root_dir": {
                        "type": "string",
                        "description": "Directory path to analyze.",
                        "default": "."
                    }
                }
            }
        }
    }
]


class ASTSymbolIndexer:
    def __init__(self, root_dir: str = "."):
        self.root_dir = os.path.abspath(root_dir)
        self.symbols: List[Dict[str, Any]] = []
        self.imports: List[Dict[str, Any]] = []

    def build_index(self) -> List[Dict[str, Any]]:
        self.symbols = []
        self.imports = []
        for dirpath, _, filenames in os.walk(self.root_dir):
            if any(part.startswith('.') or part in ('__pycache__', 'node_modules', 'venv', '.venv') for part in dirpath.split(os.sep)):
                continue

            for file in filenames:
                file_path = os.path.join(dirpath, file)
                rel_path = os.path.relpath(file_path, self.root_dir)

                if file.endswith('.py'):
                    self._parse_python_file(file_path, rel_path)
                elif file.endswith(('.js', '.ts', '.jsx', '.tsx')):
                    self._parse_js_file(file_path, rel_path)

        return self.symbols

    def _parse_python_file(self, file_path: str, rel_path: str):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            tree = ast.parse(content, filename=rel_path)

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    self.symbols.append({
                        "name": node.name,
                        "type": "class",
                        "file": rel_path,
                        "line": node.lineno,
                        "docstring": ast.get_docstring(node) or "",
                        "methods": [n.name for n in node.body if isinstance(n, ast.FunctionDef)]
                    })
                elif isinstance(node, ast.FunctionDef) and not getattr(node, '_is_method', False):
                    args = [arg.arg for arg in node.args.args]
                    self.symbols.append({
                        "name": node.name,
                        "type": "function",
                        "file": rel_path,
                        "line": node.lineno,
                        "args": args,
                        "docstring": ast.get_docstring(node) or ""
                    })
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        self.imports.append({"file": rel_path, "module": alias.name})
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        self.imports.append({"file": rel_path, "module": node.module})
        except Exception:
            pass

    def _parse_js_file(self, file_path: str, rel_path: str):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            for idx, line in enumerate(lines, 1):
                class_match = re.search(r'class\s+([A-Za-z0-9_]+)', line)
                func_match = re.search(r'function\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)', line) or re.search(r'(?:const|let|var)\s+([A-Za-z0-9_]+)\s*=\s*(?:\([^)]*\)|[A-Za-z0-9_]+)\s*=>', line)
                import_match = re.search(r'import\s+.*from\s+[\'"]([^\'"]+)[\'"]', line) or re.search(r'require\([\'"]([^\'"]+)[\'"]\)', line)

                if class_match:
                    self.symbols.append({
                        "name": class_match.group(1),
                        "type": "class",
                        "file": rel_path,
                        "line": idx,
                        "docstring": "",
                        "methods": []
                    })
                elif func_match:
                    self.symbols.append({
                        "name": func_match.group(1),
                        "type": "function",
                        "file": rel_path,
                        "line": idx,
                        "args": [],
                        "docstring": ""
                    })
                if import_match:
                    self.imports.append({"file": rel_path, "module": import_match.group(1)})
        except Exception:
            pass


def index_codebase_ast(root_dir: str = ".") -> str:
    """Index AST symbols across Python and JS/TS files in root_dir."""
    indexer = ASTSymbolIndexer(root_dir)
    symbols = indexer.build_index()
    
    class_count = sum(1 for s in symbols if s['type'] == 'class')
    func_count = sum(1 for s in symbols if s['type'] == 'function')

    summary = f"🔍 **AST Codebase Index Complete**\n\n- **Total Symbols:** {len(symbols)}\n- **Classes:** {class_count}\n- **Functions:** {func_count}\n\n"
    preview = []
    for s in symbols[:15]:
        if s['type'] == 'class':
            preview.append(f"• `class {s['name']}` ({s['file']}:{s['line']}) — Methods: {', '.join(s.get('methods', [])[:5])}")
        else:
            args_str = ", ".join(s.get('args', []))
            preview.append(f"• `def {s['name']}({args_str})` ({s['file']}:{s['line']})")

    return summary + "### Symbol Sample:\n" + "\n".join(preview)


def search_symbol(query: str, root_dir: str = ".") -> str:
    """Search indexed AST symbols matching a query string."""
    indexer = ASTSymbolIndexer(root_dir)
    symbols = indexer.build_index()
    
    matches = [s for s in symbols if query.lower() in s['name'].lower()]

    if not matches:
        return f"🔍 No symbol definition found matching '{query}'."

    results = [f"Found **{len(matches)}** matching symbol(s) for '{query}':\n"]
    for s in matches:
        if s['type'] == 'class':
            methods = ", ".join(s.get('methods', []))
            results.append(f"📦 **class `{s['name']}`** in `{s['file']}:{s['line']}`\n  Methods: {methods}\n  Docstring: {s['docstring'][:100]}")
        else:
            args = ", ".join(s.get('args', []))
            results.append(f"⚡ **def `{s['name']}({args})`** in `{s['file']}:{s['line']}`\n  Docstring: {s['docstring'][:100]}")

    return "\n\n".join(results)


def analyze_ast_dependencies(root_dir: str = ".") -> str:
    """Analyze cross-file imports and module dependencies using AST parsing."""
    indexer = ASTSymbolIndexer(root_dir)
    indexer.build_index()
    
    if not indexer.imports:
        return f"🔗 No external/internal imports indexed in `{root_dir}`."

    file_map: Dict[str, List[str]] = {}
    for imp in indexer.imports:
        file_map.setdefault(imp['file'], []).append(imp['module'])

    output = [f"🔗 **AST Dependency Map ({len(file_map)} files indexed):**\n"]
    for f_path, mods in list(file_map.items())[:15]:
        output.append(f"• `{f_path}` imports: {', '.join(list(dict.fromkeys(mods))[:6])}")

    return "\n".join(output)


AST_DISPATCH = {
    "index_codebase_ast": index_codebase_ast,
    "search_symbol": search_symbol,
    "analyze_ast_dependencies": analyze_ast_dependencies
}

