#!/usr/bin/env python3
"""Run the held-out Amaura worker and reviewer model gate."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from jarvis.amaura.evaluation import evaluate_model  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ollama-url",
        default=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"),
    )
    parser.add_argument(
        "--worker-model",
        default=os.environ.get("AMAURA_LOCAL_MODEL", ""),
    )
    parser.add_argument(
        "--reviewer-model",
        default=os.environ.get("AMAURA_LOCAL_REVIEW_MODEL", ""),
    )
    args = parser.parse_args()
    if not args.worker_model or not args.reviewer_model:
        report = {
            "ready": False,
            "error": "worker_and_reviewer_models_are_required",
            "evaluations": [],
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    if args.worker_model == args.reviewer_model:
        report = {
            "ready": False,
            "error": "worker_and_reviewer_models_must_be_distinct",
            "evaluations": [],
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    evaluations = [
        evaluate_model(args.worker_model, base_url=args.ollama_url).to_dict(),
        evaluate_model(args.reviewer_model, base_url=args.ollama_url).to_dict(),
    ]
    report = {
        "ready": all(item["ready"] for item in evaluations),
        "error": "",
        "evaluations": evaluations,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
