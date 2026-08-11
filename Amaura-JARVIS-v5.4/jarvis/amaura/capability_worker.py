"""Isolated worker for memory-heavy Amaura OSS capabilities.

The parent process gives this worker two workspace-local JSON paths.  The worker
instantiates exactly one registered adapter, runs one operation, writes a
structured result, and exits so model/browser/OCR memory is returned to macOS.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from jarvis.amaura.capability_runtime import (
    ADAPTER_TYPES,
    CapabilityUnavailable,
)
from jarvis.amaura.models import GovernanceError
from jarvis.tools.security import resolve_workspace_path


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--response", required=True)
    args = parser.parse_args()

    request = resolve_workspace_path(args.request, must_exist=True)
    response = resolve_workspace_path(args.response, must_exist=True)
    try:
        payload = json.loads(request.read_text(encoding="utf-8"))
        key = str(payload.get("capability", "")).strip()
        operation = str(payload.get("operation", "")).strip()
        params = payload.get("params") or {}
        if not isinstance(params, dict):
            raise GovernanceError("Capability params must be an object")
        adapter_type = next((item for item in ADAPTER_TYPES if item.descriptor.key == key), None)
        if adapter_type is None:
            raise GovernanceError(f"Unknown capability: {key}")
        result = adapter_type().execute(operation, params).to_dict()
        _write(response, {"ok": True, "result": result})
        return 0
    except BaseException as exc:
        if isinstance(exc, CapabilityUnavailable):
            error_type = "CapabilityUnavailable"
        elif isinstance(exc, GovernanceError):
            error_type = "GovernanceError"
        elif isinstance(exc, PermissionError):
            error_type = "PermissionError"
        elif isinstance(exc, FileNotFoundError):
            error_type = "FileNotFoundError"
        else:
            error_type = type(exc).__name__
        _write(response, {"ok": False, "error_type": error_type, "error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
