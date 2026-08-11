#!/usr/bin/env python3
"""Sign a private Amaura model-evaluation pack with HMAC-SHA256."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="JSON object with version and cases, or a raw case array")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    secret = os.environ.get("AMAURA_EVALUATION_PACK_HMAC_KEY", "").encode()
    if len(secret) < 32:
        raise SystemExit("AMAURA_EVALUATION_PACK_HMAC_KEY must contain at least 32 bytes")
    raw = json.loads(args.input.read_text(encoding="utf-8"))
    unsigned = {"version": 1, "cases": raw if isinstance(raw, list) else raw.get("cases", [])}
    if len(unsigned["cases"]) < 20:
        raise SystemExit("A production evaluation pack must contain at least 20 cases")
    payload = {**unsigned, "signature": hmac.new(secret, canonical(unsigned), hashlib.sha256).hexdigest()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"signed {len(unsigned['cases'])} cases -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
