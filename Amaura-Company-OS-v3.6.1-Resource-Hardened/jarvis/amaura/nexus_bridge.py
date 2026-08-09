"""Approval-gated bridge to a locally installed Nexus execution engine."""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from jarvis.amaura.models import GovernanceError


def _receipt(**kwargs: Any):
    from jarvis.amaura.integrations import ProviderReceipt
    return ProviderReceipt.issue(**kwargs)


class NexusDeliveryAdapter:
    def __init__(self, *, command: str | None = None, receipt_key: str | None = None) -> None:
        self.command = (command if command is not None else os.environ.get("AMAURA_NEXUS_COMMAND", "nexus")).strip()
        self.receipt_key = receipt_key

    @property
    def configured(self) -> bool:
        try:
            parts = shlex.split(self.command)
        except ValueError:
            return False
        return bool(parts and (Path(parts[0]).is_file() or shutil.which(parts[0])))

    def run(self, *, repository_path: str, objective: str, idempotency_key: str,
            acceptance_criteria: list[str] | None = None, timeout_seconds: int = 1800) -> Any:
        if not self.configured:
            raise GovernanceError("Nexus CLI is not installed or AMAURA_NEXUS_COMMAND is invalid")
        repository = Path(repository_path).expanduser().resolve()
        if not repository.is_dir() or not (repository / ".git").exists():
            raise GovernanceError("Nexus delivery requires an existing Git repository")
        if not objective.strip():
            raise GovernanceError("Nexus delivery objective is required")
        timeout = max(60, min(int(timeout_seconds), 7200))
        request_payload = {"schema": "amaura.nexus-task.v1", "objective": objective.strip(),
                           "acceptance_criteria": [str(v).strip() for v in (acceptance_criteria or []) if str(v).strip()],
                           "repository_path": str(repository), "idempotency_key": idempotency_key}
        with tempfile.TemporaryDirectory(prefix="amaura-nexus-") as temp_dir:
            request_file = Path(temp_dir) / "request.json"
            result_file = Path(temp_dir) / "result.json"
            request_file.write_text(json.dumps(request_payload, indent=2, sort_keys=True), encoding="utf-8")
            parts = shlex.split(self.command)
            extra = os.environ.get("AMAURA_NEXUS_ARGUMENTS", "run --request-file {request} --result-file {result}")
            arguments = [value.format(request=str(request_file), result=str(result_file), repository=str(repository)) for value in shlex.split(extra)]
            env = {key: value for key, value in os.environ.items() if key not in {"PYTHONINSPECT", "PYTHONSTARTUP"}}
            env["AMAURA_NEXUS_TASK_ID"] = idempotency_key
            try:
                completed = subprocess.run(parts + arguments, cwd=repository, env=env, stdin=subprocess.DEVNULL,
                                           capture_output=True, text=True, timeout=timeout, check=False)
            except subprocess.TimeoutExpired as exc:
                raise GovernanceError("Nexus delivery exceeded its approved timeout") from exc
            output = {"returncode": completed.returncode, "stdout": completed.stdout[-100_000:], "stderr": completed.stderr[-100_000:]}
            if result_file.is_file():
                try:
                    parsed = json.loads(result_file.read_text(encoding="utf-8"))
                    if isinstance(parsed, dict):
                        output["result"] = parsed
                except (OSError, json.JSONDecodeError):
                    output["result_parse_error"] = True
            if completed.returncode != 0:
                raise GovernanceError(f"Nexus delivery failed with exit code {completed.returncode}: {completed.stderr[-1000:]}")
            output_hash = hashlib.sha256(json.dumps(output, sort_keys=True).encode()).hexdigest()
            external_id = str((output.get("result") or {}).get("run_id", "")).strip() if isinstance(output.get("result"), dict) else ""
            external_id = external_id or "nexus-" + output_hash[:20]
            return _receipt(provider="nexus", operation="run_nexus_delivery", external_id=external_id,
                            idempotency_key=idempotency_key, payload=request_payload,
                            thread_id=str(repository), status="completed", key=self.receipt_key)

__all__ = ["NexusDeliveryAdapter"]
