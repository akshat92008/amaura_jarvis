"""
Surgical AST Indexer Module.
Uses Python's ast module to build a fast, token-efficient symbol graph of codebases,
extracting function signatures, class definitions, docstrings, and imports
without bloating context windows.
"""

import ast
import os
from pathlib import Path


class ASTIndexer:
    def __init__(self, workspace_dir=None):
        self.workspace_dir = Path(workspace_dir or os.getcwd()).resolve()

    def parse_file(self, relative_path):
        full_path = self.workspace_dir / relative_path
        if not full_path.exists() or not relative_path.endswith(".py"):
            return None

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                code = f.read()
            tree = ast.parse(code)
        except Exception as e:
            return {"error": f"Failed to parse AST: {e}"}

        symbols = {"classes": [], "functions": [], "imports": []}

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                methods = [m.name for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
                symbols["classes"].append({
                    "name": node.name,
                    "methods": methods,
                    "line": node.lineno
                })
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = [a.arg for a in node.args.args]
                symbols["functions"].append({
                    "name": node.name,
                    "args": args,
                    "line": node.lineno
                })
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    symbols["imports"].append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    symbols["imports"].append(f"{module}.{alias.name}")

        return symbols

    def build_symbol_graph(self):
        graph = {}
        for root, _, files in os.walk(self.workspace_dir):
            for file in files:
                if file.endswith(".py") and "__pycache__" not in root:
                    rel_path = os.path.relpath(os.path.join(root, file), self.workspace_dir)
                    symbols = self.parse_file(rel_path)
                    if symbols and "error" not in symbols:
                        graph[rel_path] = symbols
        return graph
