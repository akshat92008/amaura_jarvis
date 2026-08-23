#!/usr/bin/env python3
"""Run the complete fail-closed local JARVIS daily-use certification."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from jarvis.amaura.local_certification import certify_local_runtime  # noqa: E402


def main() -> int:
    report = certify_local_runtime(REPOSITORY_ROOT)
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0 if report.get("ready") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
