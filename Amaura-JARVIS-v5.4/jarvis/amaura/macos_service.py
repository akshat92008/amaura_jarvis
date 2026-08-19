"""Compatibility shim for historical Amaura macOS service callers.

ARCH is now the only supported persistent macOS runtime. Older imports of
``jarvis.amaura.macos_service`` are deliberately routed to the canonical ARCH
LaunchAgent contract so they cannot recreate a split company-daemon service.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jarvis import arch_macos_service as _arch_macos_service

DEFAULT_LABEL = _arch_macos_service.DEFAULT_LABEL
LEGACY_LABELS = _arch_macos_service.LEGACY_LABELS


def launch_agent_payload(
    repository_root: str | Path,
    *,
    label: str = DEFAULT_LABEL,
    poll_seconds: float | None = None,
) -> dict[str, Any]:
    """Return the canonical ARCH payload; ``poll_seconds`` is legacy-only."""
    _ = poll_seconds
    return _arch_macos_service.launch_agent_payload(repository_root, label=label)


def write_launch_agent(
    repository_root: str | Path,
    *,
    destination: str | Path | None = None,
    label: str = DEFAULT_LABEL,
    poll_seconds: float | None = None,
) -> Path:
    """Write the canonical ARCH LaunchAgent through the historical API."""
    _ = poll_seconds
    return _arch_macos_service.write_launch_agent(
        repository_root,
        destination=destination,
        label=label,
    )


__all__ = ["DEFAULT_LABEL", "LEGACY_LABELS", "launch_agent_payload", "write_launch_agent"]
