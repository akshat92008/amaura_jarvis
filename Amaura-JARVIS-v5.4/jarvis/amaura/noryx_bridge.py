"""Strongly-typed governed bridge to a locally installed Noryx engineering CLI.

A process exit code is not proof of engineering success.  Noryx must return a
v2 result contract and Amaura independently verifies that contract against the
Git worktree before the task can enter review.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from jarvis.amaura.models import GovernanceError
from jarvis.amaura.verification import SecureVerifierRunner


def _receipt(**kwargs: Any):
    from jarvis.amaura.integrations import ProviderReceipt

    return ProviderReceipt.issue(**kwargs)


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise GovernanceError(f"Git verification failed: {completed.stderr[-1600:]}")
    return completed.stdout.strip()


def _normalise_relpath(value: str) -> str:
    raw = str(value).strip().replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe changed-file path: {value}")
    return str(path)


class NoryxTestEvidence(BaseModel):
    model_config = ConfigDict(extra="allow")

    command: str = Field(min_length=1, max_length=4000)
    exit_code: int
    passed: bool = True
    summary: str = Field(default="", max_length=8000)

    @model_validator(mode="after")
    def _must_pass(self) -> NoryxTestEvidence:
        if self.exit_code != 0 or not self.passed:
            raise ValueError("successful Noryx result cannot contain a failing test command")
        return self


class NoryxEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str = Field(min_length=1, max_length=120)
    reference: str = Field(min_length=1, max_length=20_000)
    sha256: str = Field(default="", max_length=128)
    summary: str = Field(default="", max_length=8000)


class NoryxResultContract(BaseModel):
    """Minimum acceptable proof for an autonomous repository write."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    schema_version: Literal["amaura.noryx-result.v2"] = Field(
        default="amaura.noryx-result.v2", alias="schema", serialization_alias="schema"
    )
    success: Literal[True]
    summary: str = Field(min_length=3, max_length=20_000)
    changed_files: list[str] = Field(min_length=1, max_length=1000)
    tests: list[NoryxTestEvidence] = Field(min_length=1, max_length=200)
    evidence: list[NoryxEvidenceItem] = Field(min_length=1, max_length=500)
    run_id: str = Field(default="", max_length=300)
    base_commit: str = Field(default="", max_length=100)
    head_commit: str = Field(default="", max_length=100)
    diff_hash: str = Field(default="", max_length=128)
    remaining_failures: list[str] = Field(default_factory=list, max_length=100)
    executor_models: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("changed_files", mode="before")
    @classmethod
    def _changed_files(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("changed_files must be a list")
        clean: list[str] = []
        for item in value:
            path = _normalise_relpath(str(item))
            if path not in clean:
                clean.append(path)
        return clean

    @field_validator("tests", mode="before")
    @classmethod
    def _normalise_tests(cls, value: Any) -> list[Any]:
        # Accept one structured test object or an explicit list; reject vague
        # booleans/strings that cannot be independently interpreted.
        if isinstance(value, dict) and "command" in value:
            return [value]
        if not isinstance(value, list):
            raise ValueError("tests must contain structured command/exit-code evidence")
        return value

    @model_validator(mode="after")
    def _no_known_failures(self) -> NoryxResultContract:
        if self.remaining_failures:
            raise ValueError("success=true cannot include remaining_failures")
        return self


@dataclass(frozen=True, slots=True)
class NoryxRunResult:
    receipt: Any
    returncode: int
    stdout: str
    stderr: str
    result: dict[str, Any]
    request: dict[str, Any]
    verification: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt": self.receipt.to_dict() if hasattr(self.receipt, "to_dict") else self.receipt,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "result": self.result,
            "request": self.request,
            "verification": self.verification,
        }


class NoryxDeliveryAdapter:
    RECEIPT_PROVIDER = "noryx"
    RECEIPT_OPERATION = "run_noryx_delivery"

    DEFAULT_ENV_ALLOWLIST = frozenset(
        {
            "PATH",
            "HOME",
            "USER",
            "LOGNAME",
            "SHELL",
            "TMPDIR",
            "TEMP",
            "TMP",
            "LANG",
            "LC_ALL",
            "TERM",
            "COLORTERM",
            "PYTHONPATH",
            "VIRTUAL_ENV",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            "REQUESTS_CA_BUNDLE",
            # Explicit coding-model credentials only. Governance, approval,
            # audit, provider-signing and desktop bootstrap secrets are excluded.
            "NVIDIA_API_KEY",
            "GROQ_API_KEY",
            "OPENROUTER_API_KEY",
            "OLLAMA_URL",
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "GOOGLE_API_KEY",
        }
    )

    def __init__(self, *, command: str | None = None, receipt_key: str | None = None) -> None:
        configured = command if command is not None else os.environ.get("AMAURA_NORYX_COMMAND", "").strip()
        if not configured:
            configured = os.environ.get("AMAURA_NEXUS_COMMAND", "noryx").strip() or "noryx"
        self.command = configured
        self.receipt_key = receipt_key

    @property
    def configured(self) -> bool:
        try:
            parts = shlex.split(self.command)
        except ValueError:
            return False
        return bool(parts and (Path(parts[0]).is_file() or shutil.which(parts[0])))

    def _environment(self, idempotency_key: str) -> dict[str, str]:
        extra = {item.strip() for item in os.environ.get("AMAURA_NORYX_ENV_ALLOWLIST", "").split(",") if item.strip()}
        # Explicit operator additions are supported, but dangerous Amaura keys
        # remain denied even if accidentally named in the allowlist.
        denied_prefixes = (
            "AMAURA_APPROVAL",
            "AMAURA_AUDIT",
            "AMAURA_REVIEWER",
            "AMAURA_OPERATOR",
            "AMAURA_DESKTOP_BOOTSTRAP",
            "AMAURA_PROVIDER_RECEIPT",
            "JARVIS_API_KEY",
        )
        allowed = {key for key in (self.DEFAULT_ENV_ALLOWLIST | extra) if not key.startswith(denied_prefixes)}
        env = {key: value for key, value in os.environ.items() if key in allowed}
        env["AMAURA_NORYX_TASK_ID"] = idempotency_key
        env["AMAURA_NEXUS_TASK_ID"] = idempotency_key  # legacy Noryx/Nexus builds
        return env

    @staticmethod
    def _changed_files(repository: Path, base_commit: str) -> list[str]:
        names: set[str] = set()
        try:
            for line in _git(repository, "diff", "--name-only", base_commit, "--").splitlines():
                if line.strip():
                    names.add(_normalise_relpath(line.strip()))
        except GovernanceError:
            # If the base commit disappeared, fail later on commit verification.
            raise
        for args in (("diff", "--name-only", "--"), ("diff", "--cached", "--name-only", "--")):
            for line in _git(repository, *args).splitlines():
                if line.strip():
                    names.add(_normalise_relpath(line.strip()))
        status = _git(repository, "status", "--porcelain=v1", "--untracked-files=all")
        for line in status.splitlines():
            if len(line) < 4:
                continue
            raw = line[3:].strip()
            if " -> " in raw:
                raw = raw.split(" -> ", 1)[1]
            if raw:
                names.add(_normalise_relpath(raw))
        return sorted(names)

    @staticmethod
    def _diff_hash(repository: Path, base_commit: str, changed_files: list[str]) -> str:
        digest = hashlib.sha256()
        patch = subprocess.run(
            ["git", "diff", "--binary", base_commit, "--"],
            cwd=repository,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if patch.returncode != 0:
            raise GovernanceError("Unable to calculate Noryx Git diff hash")
        digest.update(patch.stdout)
        # Include untracked files that are not represented in git diff.
        for relative in changed_files:
            path = repository / relative
            tracked = (
                subprocess.run(
                    ["git", "ls-files", "--error-unmatch", relative],
                    cwd=repository,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    check=False,
                ).returncode
                == 0
            )
            if path.is_file() and not tracked:
                digest.update(relative.encode("utf-8"))
                digest.update(path.read_bytes())
        return digest.hexdigest()

    @staticmethod
    def _test_argv(command: str) -> list[str]:
        """Compatibility shim around the shared fail-closed verifier parser."""
        return SecureVerifierRunner.parse_command(command)

    @classmethod
    def _run_independent_tests(
        cls,
        repository: Path,
        tests: list[NoryxTestEvidence],
    ) -> list[dict[str, Any]]:
        if os.environ.get("AMAURA_NORYX_INDEPENDENT_VERIFY", "1") != "1":
            raise GovernanceError("Independent Noryx verification may not be disabled")
        timeout = max(5, min(int(os.environ.get("AMAURA_NORYX_VERIFY_TIMEOUT_SECONDS", "300")), 1800))
        return SecureVerifierRunner().run_all(repository, [test.command for test in tests], timeout_seconds=timeout)

    @staticmethod
    def _verify_contract(
        repository: Path,
        *,
        contract: NoryxResultContract,
        base_commit: str,
    ) -> dict[str, Any]:
        head_commit = _git(repository, "rev-parse", "HEAD")
        if contract.base_commit and contract.base_commit != base_commit:
            raise GovernanceError("Noryx result base_commit does not match the worktree Amaura assigned")
        if contract.head_commit and contract.head_commit != head_commit:
            raise GovernanceError("Noryx result head_commit does not match the current worktree HEAD")
        actual_changed = NoryxDeliveryAdapter._changed_files(repository, base_commit)
        declared = sorted(contract.changed_files)
        if not actual_changed:
            raise GovernanceError("Noryx reported success but Amaura found no repository changes")
        if set(declared) != set(actual_changed):
            raise GovernanceError(
                "Noryx changed-file manifest does not match the independently observed Git delta: "
                f"declared={declared} actual={actual_changed}"
            )
        diff_hash = NoryxDeliveryAdapter._diff_hash(repository, base_commit, actual_changed)
        if contract.diff_hash and contract.diff_hash.lower() != diff_hash.lower():
            raise GovernanceError("Noryx diff_hash does not match Amaura's independently calculated diff hash")
        independent_tests = NoryxDeliveryAdapter._run_independent_tests(repository, contract.tests)
        post_files = NoryxDeliveryAdapter._changed_files(repository, base_commit)
        post_hash = NoryxDeliveryAdapter._diff_hash(repository, base_commit, post_files)
        if post_files != actual_changed or post_hash != diff_hash:
            raise GovernanceError("Independent Noryx verification mutated the repository; result rejected")
        return {
            "base_commit": base_commit,
            "head_commit": head_commit,
            "changed_files": actual_changed,
            "diff_hash": diff_hash,
            "tests": [test.model_dump(mode="json") for test in contract.tests],
            "independent_tests": independent_tests,
            "executor_models": list(contract.executor_models),
            "contract_schema": contract.schema_version,
        }

    def run_with_result(
        self,
        *,
        repository_path: str,
        objective: str,
        idempotency_key: str,
        acceptance_criteria: list[str] | None = None,
        timeout_seconds: int = 1800,
    ) -> NoryxRunResult:
        if not self.configured:
            raise GovernanceError("Noryx CLI is not installed or AMAURA_NORYX_COMMAND is invalid")
        repository = Path(repository_path).expanduser().resolve()
        if not repository.is_dir():
            raise GovernanceError("Noryx delivery requires an existing repository directory")
        if not (repository / ".git").exists():
            raise GovernanceError("Noryx delivery requires an existing Git repository/worktree")
        if not objective.strip():
            raise GovernanceError("Noryx delivery objective is required")
        timeout = max(60, min(int(timeout_seconds), 7200))
        base_commit = _git(repository, "rev-parse", "HEAD")
        request_payload = {
            "schema": "amaura.noryx-task.v1",
            "objective": objective.strip(),
            "acceptance_criteria": [str(value).strip() for value in (acceptance_criteria or []) if str(value).strip()],
            "repository_path": str(repository),
            "base_commit": base_commit,
            "idempotency_key": idempotency_key,
            "requirements": {
                "fail_closed": True,
                "result_schema": "amaura.noryx-result.v2",
                "return_changed_files": True,
                "return_test_evidence": True,
                "return_evidence": True,
                "return_git_commits": True,
                "return_executor_models": True,
                "do_not_deploy": True,
            },
        }
        with tempfile.TemporaryDirectory(prefix="amaura-noryx-") as temp_dir:
            request_file = Path(temp_dir) / "request.json"
            result_file = Path(temp_dir) / "result.json"
            request_file.write_text(json.dumps(request_payload, indent=2, sort_keys=True), encoding="utf-8")
            parts = shlex.split(self.command)
            extra = os.environ.get(
                "AMAURA_NORYX_ARGUMENTS",
                os.environ.get("AMAURA_NEXUS_ARGUMENTS", "run --request-file {request} --result-file {result}"),
            )
            arguments = [
                value.format(request=str(request_file), result=str(result_file), repository=str(repository))
                for value in shlex.split(extra)
            ]
            try:
                completed = subprocess.run(
                    parts + arguments,
                    cwd=repository,
                    env=self._environment(idempotency_key),
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise GovernanceError("Noryx delivery exceeded its approved timeout") from exc

            stdout = completed.stdout[-100_000:]
            stderr = completed.stderr[-100_000:]
            if completed.returncode != 0:
                raise GovernanceError(f"Noryx delivery failed with exit code {completed.returncode}: {stderr[-1600:]}")
            if not result_file.is_file():
                raise GovernanceError("Noryx exited successfully but returned no structured result")
            try:
                raw = json.loads(result_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise GovernanceError("Noryx returned an unreadable result file") from exc
            if not isinstance(raw, dict):
                raise GovernanceError("Noryx result must be a JSON object")
            try:
                contract = NoryxResultContract.model_validate(raw)
            except Exception as exc:
                raise GovernanceError(f"Noryx result failed the required v2 evidence contract: {exc}") from exc
            verification = self._verify_contract(repository, contract=contract, base_commit=base_commit)
            parsed = contract.model_dump(mode="json", by_alias=True)
            # Always expose Amaura's independently verified values, not merely the
            # values declared by Noryx.
            parsed["base_commit"] = verification["base_commit"]
            parsed["head_commit"] = verification["head_commit"]
            parsed["diff_hash"] = verification["diff_hash"]

            output = {
                "returncode": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "result": parsed,
                "verification": verification,
            }
            output_hash = hashlib.sha256(json.dumps(output, sort_keys=True, default=str).encode()).hexdigest()
            external_id = contract.run_id.strip() or "noryx-" + output_hash[:20]
            receipt = _receipt(
                provider=self.RECEIPT_PROVIDER,
                operation=self.RECEIPT_OPERATION,
                external_id=external_id,
                idempotency_key=idempotency_key,
                payload=request_payload,
                thread_id=str(repository),
                status="completed",
                key=self.receipt_key,
            )
            return NoryxRunResult(
                receipt=receipt,
                returncode=completed.returncode,
                stdout=stdout,
                stderr=stderr,
                result=parsed,
                request=request_payload,
                verification=verification,
            )

    def run(self, **kwargs: Any) -> Any:
        return self.run_with_result(**kwargs).receipt


__all__ = [
    "NoryxDeliveryAdapter",
    "NoryxEvidenceItem",
    "NoryxResultContract",
    "NoryxRunResult",
    "NoryxTestEvidence",
]
