#!/usr/bin/env python3
"""Deterministic JARVIS cognition smoke benchmark.

This is intentionally separate from the reliability test suite. It exercises
founder-language intent routing and dynamic-plan invariants. For serious model
qualification, pass a private JSONL scenario pack with --cases; the file is not
bundled into release artifacts, reducing benchmark overfitting.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path

from jarvis.amaura.brain import GoalCompiler, GoalRequest
from jarvis.amaura.cognition import IntentEngine


@dataclass(frozen=True)
class IntentCase:
    text: str
    expected: str


BUILTIN_INTENTS = [
    IntentCase("What is Noryx doing?", "conversation"),
    IntentCase("Why did the release fail?", "conversation"),
    IntentCase("How should we structure the API?", "conversation"),
    IntentCase("Can you explain the approval model?", "conversation"),
    IntentCase("Should I deploy this today?", "conversation"),
    IntentCase("Build the client portal", "mission"),
    IntentCase("Fix the failing authentication tests", "mission"),
    IntentCase("Research the current onboarding problem", "mission"),
    IntentCase("Prepare a launch report", "mission"),
    IntentCase("Audit the repository and repair critical issues", "mission"),
    IntentCase("Continue the Noryx release work", "mission"),
    IntentCase("Run the company operating review", "mission"),
    IntentCase("Create a tested API endpoint", "mission"),
    IntentCase("Investigate the build failure", "mission"),
    IntentCase("Refactor the billing module", "mission"),
    IntentCase("Remember that production deployment always needs my approval", "memory_write"),
    IntentCase("Please remember: Noryx owns repository engineering", "memory_write"),
    IntentCase("Forget the old staging URL", "memory_forget"),
    IntentCase("Please forget about the retired CRM", "memory_forget"),
    IntentCase("status", "status"),
    IntentCase("company status", "status"),
    IntentCase("what's happening", "status"),
    IntentCase("where are we with the release", "status"),
    IntentCase("status of the client portal", "status"),
]


def load_cases(path: Path | None) -> list[IntentCase]:
    if path is None:
        return BUILTIN_INTENTS
    cases: list[IntentCase] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or not row.get("text") or not row.get("expected"):
            raise ValueError(f"Invalid case on line {index}")
        cases.append(IntentCase(str(row["text"]), str(row["expected"])))
    return cases


def planning_checks() -> list[dict]:
    compiler = GoalCompiler()
    objectives = [
        "Build a tested dashboard feature",
        "Research a release checklist",
        "Analyze company operating risks",
        "Prepare a content launch brief",
        "Investigate client acquisition bottlenecks",
        "Review internal operations and recommend improvements",
    ]
    output = []
    for objective in objectives:
        request = GoalRequest(objective=objective, autonomy="plan_only", max_steps=8)
        plan = compiler.compile(request)
        keys = [task.key for task in plan.tasks]
        key_set = set(keys)
        dependencies_valid = all(set(task.depends_on) <= key_set for task in plan.tasks)
        reviewers_separated = all(task.owner_id != task.reviewer_id for task in plan.tasks)
        output.append(
            {
                "objective": objective,
                "domain": plan.domain,
                "task_count": len(plan.tasks),
                "unique_keys": len(keys) == len(key_set),
                "dependencies_valid": dependencies_valid,
                "reviewers_separated": reviewers_separated,
                "passed": bool(plan.tasks and len(keys) == len(key_set) and dependencies_valid and reviewers_separated),
            }
        )
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=None, help="Private JSONL intent scenario pack")
    parser.add_argument("--allow-llm", action="store_true", help="Allow configured intent/planner models")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if not args.allow_llm:
        os.environ["AMAURA_JARVIS_INTENT_MODEL"] = "0"
        os.environ["AMAURA_JARVIS_LLM_PLANNER"] = "0"
    engine = IntentEngine()
    intent_rows = []
    for case in load_cases(args.cases):
        actual = engine.classify(case.text)
        intent_rows.append(
            {"text": case.text, "expected": case.expected, "actual": actual, "passed": actual == case.expected}
        )
    plans = planning_checks()
    result = {
        "intent": {
            "total": len(intent_rows),
            "passed": sum(1 for row in intent_rows if row["passed"]),
            "cases": intent_rows,
        },
        "planning": {
            "total": len(plans),
            "passed": sum(1 for row in plans if row["passed"]),
            "cases": plans,
        },
    }
    result["passed"] = (
        result["intent"]["passed"] == result["intent"]["total"]
        and result["planning"]["passed"] == result["planning"]["total"]
    )
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
