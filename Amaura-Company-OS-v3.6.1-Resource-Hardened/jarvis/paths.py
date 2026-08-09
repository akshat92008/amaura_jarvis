"""Portable, explicitly configurable JARVIS data locations."""

from __future__ import annotations

import os
import uuid
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def get_data_dir() -> Path:
    """Return a writable data root, preferring JARVIS_DATA_DIR then the user profile."""
    configured = os.environ.get("JARVIS_DATA_DIR", "").strip()
    candidates = [Path(configured).expanduser()] if configured else [Path.home() / ".jarvis", Path.cwd() / ".jarvis-data"]
    errors: list[str] = []
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / f".write-probe-{uuid.uuid4().hex}"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return candidate.resolve()
        except OSError as exc:
            errors.append(f"{candidate}: {exc}")
    raise RuntimeError("No writable JARVIS data directory. Set JARVIS_DATA_DIR. " + "; ".join(errors))


__all__ = ["get_data_dir"]
