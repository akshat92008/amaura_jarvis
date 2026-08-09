"""
Workspace Executor & Tool Operations Engine.

Legacy Fable execution is intentionally constrained to a declared workspace and
a small command allowlist. It is not a substitute for the Amaura governed
sandbox.
"""

import os
import shlex
import subprocess
from pathlib import Path


_ALLOWED_EXECUTABLES = {
    "python", "python3", "pytest", "ruff", "mypy", "npm", "npx", "node",
    "pnpm", "yarn", "git",
}
_SHELL_META = {";", "&&", "||", "|", ">", "<", "`", "$(", "${"}


class WorkspaceExecutor:
    def __init__(self, workspace_dir=None):
        self.workspace_dir = Path(workspace_dir or os.getcwd()).resolve()

    def _resolve(self, relative_path):
        candidate = Path(relative_path)
        if candidate.is_absolute():
            raise ValueError("Absolute paths are not allowed")
        target = (self.workspace_dir / candidate).resolve(strict=False)
        try:
            target.relative_to(self.workspace_dir)
        except ValueError as exc:
            raise ValueError("Path escapes the configured workspace") from exc
        return target

    def write_file(self, relative_path, content):
        target_path = self._resolve(relative_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        # Re-resolve after directory creation to detect symlink-based escapes.
        target_path = self._resolve(relative_path)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)
        return str(target_path)

    def read_file(self, relative_path):
        target_path = self._resolve(relative_path)
        if not target_path.exists() or not target_path.is_file():
            return None
        with open(target_path, "r", encoding="utf-8") as f:
            return f.read()

    def list_workspace(self):
        items = []
        for root, dirs, files in os.walk(self.workspace_dir, followlinks=False):
            dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "venv", ".venv"}]
            for file in files:
                full = Path(root) / file
                try:
                    resolved = full.resolve(strict=False)
                    resolved.relative_to(self.workspace_dir)
                except (OSError, ValueError):
                    continue
                rel = os.path.relpath(full, self.workspace_dir)
                if not rel.startswith(".") and "__pycache__" not in rel:
                    items.append(rel)
        return sorted(items)

    def _parse_command(self, command_str):
        if not isinstance(command_str, str) or not command_str.strip():
            raise ValueError("Command must be a non-empty string")
        if any(token in command_str for token in _SHELL_META):
            raise ValueError("Shell operators and interpolation are not allowed")
        args = shlex.split(command_str, posix=True)
        if not args:
            raise ValueError("Command must not be empty")
        executable = Path(args[0]).name
        if executable not in _ALLOWED_EXECUTABLES:
            raise ValueError(f"Executable '{executable}' is not allowlisted")
        return args

    def run_command(self, command_str, timeout=30):
        try:
            args = self._parse_command(command_str)
            res = subprocess.run(
                args,
                shell=False,
                cwd=self.workspace_dir,
                capture_output=True,
                text=True,
                timeout=min(max(int(timeout), 1), 300),
            )
            return {
                "exit_code": res.returncode,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "success": res.returncode == 0,
            }
        except subprocess.TimeoutExpired:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command timed out after {timeout}s",
                "success": False,
            }
        except Exception as exc:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": str(exc),
                "success": False,
            }
