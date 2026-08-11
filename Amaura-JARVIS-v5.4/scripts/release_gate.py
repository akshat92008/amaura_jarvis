#!/usr/bin/env python3
"""Compatibility wrapper for Amaura's installable release-certification gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from jarvis.amaura.doctor import certify_release  # noqa: E402


def _run(static_only: bool):
    return certify_release(repository_root=REPOSITORY_ROOT, static_only=static_only)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--static-only",
        action="store_true",
        help="Validate source contracts without requiring local infrastructure.",
    )
    args = parser.parse_args()
    try:
        report = _run(args.static_only)
    except Exception as exc:  # gate must always emit structured JSON
        report = {
            "ready": False,
            "source_certified": False,
            "production_ready": False,
            "mode": "static" if args.static_only else "production",
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    key = "source_certified" if args.static_only else "production_ready"
    return 0 if report.get(key) else 1


if __name__ == "__main__":
    raise SystemExit(main())
