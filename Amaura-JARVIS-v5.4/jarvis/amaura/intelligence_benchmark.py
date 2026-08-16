"""Private-pack benchmark harness for JARVIS cognition and Noryx engineering.

This module intentionally separates *framework tests* from *capability proof*.
Built-in unit tests verify contracts.  A launch qualification can point this
harness at a private scenario pack and, optionally, real Git fixture repositories
so the shipped source does not contain the answers to its own benchmark.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jarvis.amaura.cognition import ExecutiveKernel, ExecutiveRequest
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.models import GovernanceError
from jarvis.amaura.noryx_bridge import NoryxDeliveryAdapter


class CognitiveScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=2, max_length=160)
    prompt: str = Field(min_length=2, max_length=30_000)
    expected_intent: Literal["conversation", "mission", "status", "memory_write", "memory_forget", "mission_control"]
    required_step_keys: list[str] = Field(default_factory=list, max_length=30)
    forbidden_action_types: list[str] = Field(default_factory=list, max_length=30)
    max_tasks: int = Field(default=12, ge=1, le=30)
    workspace: str = ""


class EngineeringScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=2, max_length=160)
    repository: str = Field(min_length=1)
    objective: str = Field(min_length=2, max_length=30_000)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=50)
    verifier_argv: list[list[str]] = Field(min_length=1, max_length=30)
    expected_changed_files: list[str] = Field(default_factory=list, max_length=1000)
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)

    @model_validator(mode="after")
    def _safe_verifiers(self) -> EngineeringScenario:
        for argv in self.verifier_argv:
            if not argv or not all(isinstance(part, str) and part for part in argv):
                raise ValueError("verifier_argv must contain non-empty argument vectors")
        return self


class BenchmarkPack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    cognitive: list[CognitiveScenario] = Field(default_factory=list, max_length=1000)
    engineering: list[EngineeringScenario] = Field(default_factory=list, max_length=500)


@dataclass(slots=True)
class CaseResult:
    id: str
    category: str
    passed: bool
    duration_seconds: float
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BenchmarkResult:
    source_sha256: str
    attempted: int
    passed: int
    failed: int
    cases: list[CaseResult]

    @property
    def pass_rate(self) -> float:
        return self.passed / self.attempted if self.attempted else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_sha256": self.source_sha256,
            "attempted": self.attempted,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": self.pass_rate,
            "cases": [asdict(case) for case in self.cases],
        }


def load_pack(path: str | Path) -> tuple[BenchmarkPack, str]:
    target = Path(path).expanduser().resolve()
    try:
        raw = target.read_bytes()
        parsed = json.loads(raw)
        pack = BenchmarkPack.model_validate(parsed)
    except Exception as exc:
        raise GovernanceError(f"Invalid JARVIS benchmark pack: {exc}") from exc
    if not pack.cognitive and not pack.engineering:
        raise GovernanceError("Benchmark pack contains no cases")
    return pack, hashlib.sha256(raw).hexdigest()


def _run_verifier(repository: Path, argv: list[str], timeout: int) -> dict[str, Any]:
    completed = subprocess.run(
        argv,
        cwd=repository,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=min(timeout, 1800),
        check=False,
    )
    return {
        "argv": argv,
        "exit_code": completed.returncode,
        "stdout_tail": completed.stdout[-5000:],
        "stderr_tail": completed.stderr[-5000:],
        "passed": completed.returncode == 0,
    }


def run_benchmark(
    *,
    pack_path: str | Path,
    noryx_command: str | None = None,
    run_engineering: bool = False,
) -> BenchmarkResult:
    pack, source_hash = load_pack(pack_path)
    results: list[CaseResult] = []

    for case in pack.cognitive:
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="amaura-bench-") as temp_dir:
            control = AmauraControlPlane(Path(temp_dir) / "amaura.db")
            try:
                kernel = ExecutiveKernel(control, conversation_handler=lambda text, context: "benchmark conversation")
                response = kernel.handle(
                    ExecutiveRequest(
                        text=case.prompt,
                        workspace=case.workspace,
                        autonomy="plan_only",
                        coding_backend="auto",
                    ),
                    allow_missions=True,
                )
                details: dict[str, Any] = {"intent": response.intent}
                passed = response.intent == case.expected_intent
                if response.intent == "mission" and response.goal_id:
                    status = kernel.brain.status(response.goal_id)
                    active = status.get("active_tasks") or []
                    step_keys = {str((task.get("metadata") or {}).get("step_key") or "") for task in active}
                    action_types = {str(task.get("action_type") or "") for task in active}
                    details.update(
                        {
                            "step_keys": sorted(step_keys),
                            "action_types": sorted(action_types),
                            "task_count": len(active),
                        }
                    )
                    passed = passed and set(case.required_step_keys).issubset(step_keys)
                    passed = passed and not (set(case.forbidden_action_types) & action_types)
                    passed = passed and len(active) <= case.max_tasks
                results.append(CaseResult(case.id, "cognitive", passed, time.perf_counter() - started, details))
            finally:
                control.close()

    if run_engineering:
        adapter = NoryxDeliveryAdapter(command=noryx_command)
        if not adapter.configured:
            raise GovernanceError("Engineering benchmark requested but Noryx is not configured")
        for case in pack.engineering:
            started = time.perf_counter()
            source_repo = Path(case.repository).expanduser().resolve()
            if not (source_repo / ".git").exists():
                raise GovernanceError(f"Engineering fixture is not a Git repository: {source_repo}")
            with tempfile.TemporaryDirectory(prefix="amaura-noryx-bench-") as temp_dir:
                worktree = Path(temp_dir) / "repo"
                subprocess.run(
                    ["git", "clone", "--quiet", str(source_repo), str(worktree)],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=True,
                )
                run = adapter.run_with_result(
                    repository_path=str(worktree),
                    objective=case.objective,
                    idempotency_key=f"benchmark:{case.id}",
                    acceptance_criteria=case.acceptance_criteria,
                    timeout_seconds=case.timeout_seconds,
                )
                verifier_results = [_run_verifier(worktree, argv, case.timeout_seconds) for argv in case.verifier_argv]
                changed = set(run.verification.get("changed_files") or [])
                passed = all(item["passed"] for item in verifier_results)
                if case.expected_changed_files:
                    passed = passed and set(case.expected_changed_files).issubset(changed)
                results.append(
                    CaseResult(
                        case.id,
                        "engineering",
                        passed,
                        time.perf_counter() - started,
                        {
                            "changed_files": sorted(changed),
                            "diff_hash": run.verification.get("diff_hash"),
                            "verifiers": verifier_results,
                        },
                    )
                )

    passed = sum(1 for case in results if case.passed)
    return BenchmarkResult(source_hash, len(results), passed, len(results) - passed, results)


__all__ = [
    "BenchmarkPack",
    "BenchmarkResult",
    "CaseResult",
    "CognitiveScenario",
    "EngineeringScenario",
    "load_pack",
    "run_benchmark",
]
