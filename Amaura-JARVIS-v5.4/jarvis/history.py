"""
File Change History — tracks every file modification for undo/diff support.
Adapted from Nexus for Jarvis. Stored in ~/.jarvis/history/.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path
from jarvis.paths import get_data_dir


HISTORY_DIR = get_data_dir() / "history"


class FileHistory:
    """Tracks file changes per session for undo and diff operations."""

    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = HISTORY_DIR / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.changes: list[dict] = []
        self._load_changes()

    def _changes_file(self) -> Path:
        return self.session_dir / "changes.json"

    def _load_changes(self):
        cf = self._changes_file()
        if cf.exists():
            try:
                with open(cf, "r") as f:
                    self.changes = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.changes = []

    def _save_changes(self):
        with open(self._changes_file(), "w") as f:
            json.dump(self.changes, f, indent=2)

    def snapshot_before_write(self, filepath: str) -> str | None:
        """Capture file state before modification."""
        p = Path(filepath).expanduser().resolve()
        if not p.exists() or not p.is_file():
            return None
        snap_name = f"{len(self.changes):04d}_{p.name}"
        snap_path = self.session_dir / snap_name
        try:
            shutil.copy2(str(p), str(snap_path))
            return str(snap_path)
        except (OSError, shutil.SameFileError):
            return None

    def record_change(self, filepath: str, tool_name: str, snapshot_path: str | None = None, description: str = ""):
        """Record a file change."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "filepath": str(Path(filepath).expanduser().resolve()),
            "tool": tool_name,
            "snapshot_path": snapshot_path,
            "description": description,
            "is_new_file": snapshot_path is None,
        }
        self.changes.append(entry)
        self._save_changes()

    def undo_last_change(self) -> tuple[bool, str]:
        """Undo the most recent file change."""
        if not self.changes:
            return False, "No changes to undo, sir."

        last = self.changes[-1]
        filepath = last["filepath"]
        snapshot = last.get("snapshot_path")

        if last["is_new_file"]:
            try:
                p = Path(filepath)
                if p.exists():
                    p.unlink()
                self.changes.pop()
                self._save_changes()
                return True, f"Deleted newly created file: {filepath}"
            except OSError as e:
                return False, f"Failed to delete {filepath}: {e}"
        elif snapshot and Path(snapshot).exists():
            try:
                shutil.copy2(snapshot, filepath)
                self.changes.pop()
                self._save_changes()
                return True, f"Restored {Path(filepath).name} to previous version"
            except OSError as e:
                return False, f"Failed to restore {filepath}: {e}"
        else:
            self.changes.pop()
            self._save_changes()
            return False, "Snapshot not available — change record removed but file not restored."

    def get_change_summary(self) -> str:
        """Summary of all changes in this session."""
        if not self.changes:
            return "No file changes in this session."
        lines = [f"📋 {len(self.changes)} file change(s) in this session:\n"]
        for i, change in enumerate(self.changes, 1):
            p = Path(change["filepath"])
            action = "created" if change["is_new_file"] else "modified"
            tool = change["tool"]
            ts = change["timestamp"].split("T")[1][:8]
            lines.append(f"  {i}. [{ts}] {action} {p.name} via {tool}")
        return "\n".join(lines)


# Global instance
_global_history: FileHistory | None = None


def get_history() -> FileHistory:
    """Get or create the global file history instance."""
    global _global_history
    if _global_history is None:
        _global_history = FileHistory()
    return _global_history


def init_history(session_id: str | None = None) -> FileHistory:
    """Initialize a new history session."""
    global _global_history
    _global_history = FileHistory(session_id)
    return _global_history
