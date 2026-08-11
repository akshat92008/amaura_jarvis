#!/usr/bin/env python3
"""Run a private JARVIS cognition/Noryx benchmark pack and emit JSON evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from jarvis.amaura.intelligence_benchmark import run_benchmark


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pack", help="Private benchmark pack JSON")
    parser.add_argument("--noryx-command", default=None)
    parser.add_argument("--engineering", action="store_true", help="Also run real Noryx repository scenarios")
    parser.add_argument("--output", default="JARVIS_INTELLIGENCE_BENCHMARK.json")
    args = parser.parse_args()
    result = run_benchmark(pack_path=args.pack, noryx_command=args.noryx_command, run_engineering=args.engineering)
    target = Path(args.output).expanduser().resolve()
    target.write_text(json.dumps(result.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0 if result.failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
