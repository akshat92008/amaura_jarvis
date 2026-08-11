"""Backward-compatible shim for the pre-Noryx Nexus integration.

New autonomous engineering MUST use :class:`NoryxDeliveryAdapter`, whose v2
result contract requires independently verifiable Git/test evidence.  This
module preserves the old Nexus receipt/invocation surface for historical v3.x
integrations and migrations only; the Amaura executor never selects it as a
coding backend.
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from jarvis.amaura.models import GovernanceError
from jarvis.amaura.noryx_bridge import NoryxDeliveryAdapter, NoryxRunResult, _receipt


class NexusDeliveryAdapter(NoryxDeliveryAdapter):
    """Deprecated v3.x compatibility adapter.

    Its weaker historical result format is retained only so existing connector
    callers do not break during migration.  It is intentionally not used by
    ``GovernedTaskRunner`` and therefore cannot satisfy v4.1 autonomous coding
    evidence requirements.
    """

    RECEIPT_PROVIDER = "nexus"
    RECEIPT_OPERATION = "run_nexus_delivery"

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
            raise GovernanceError("Legacy Nexus CLI command is not configured")
        repository = Path(repository_path).expanduser().resolve()
        if not repository.is_dir() or not (repository / ".git").exists():
            raise GovernanceError("Legacy Nexus delivery requires a repository/worktree marker")
        if not objective.strip():
            raise GovernanceError("Legacy Nexus delivery objective is required")
        timeout = max(60, min(int(timeout_seconds), 7200))
        request_payload = {
            "schema": "amaura.noryx-task.v1",
            "objective": objective.strip(),
            "acceptance_criteria": [
                str(value).strip() for value in (acceptance_criteria or []) if str(value).strip()
            ],
            "repository_path": str(repository),
            "idempotency_key": idempotency_key,
            "requirements": {"fail_closed": True, "do_not_deploy": True, "result_schema": "amaura.noryx-result.v2"},
        }
        with tempfile.TemporaryDirectory(prefix="amaura-nexus-legacy-") as temp_dir:
            request_file = Path(temp_dir) / "request.json"
            result_file = Path(temp_dir) / "result.json"
            request_file.write_text(json.dumps(request_payload, indent=2, sort_keys=True), encoding="utf-8")
            parts = shlex.split(self.command)
            extra = os.environ.get(
                "AMAURA_NEXUS_ARGUMENTS",
                "run --request-file {request} --result-file {result}",
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
                raise GovernanceError("Legacy Nexus delivery exceeded its approved timeout") from exc
            stdout = completed.stdout[-100_000:]
            stderr = completed.stderr[-100_000:]
            if completed.returncode != 0:
                raise GovernanceError(
                    f"Legacy Nexus delivery failed with exit code {completed.returncode}: {stderr[-1600:]}"
                )
            if not result_file.is_file():
                raise GovernanceError("Legacy Nexus exited successfully but returned no structured result")
            try:
                parsed = json.loads(result_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise GovernanceError("Legacy Nexus returned an unreadable result file") from exc
            if not isinstance(parsed, dict) or not parsed or parsed.get("success") is False:
                raise GovernanceError("Legacy Nexus returned an invalid/failing structured result")
            output = {"returncode": completed.returncode, "stdout": stdout, "stderr": stderr, "result": parsed}
            output_hash = hashlib.sha256(json.dumps(output, sort_keys=True, default=str).encode()).hexdigest()
            external_id = str(parsed.get("run_id", "")).strip() or "nexus-" + output_hash[:20]
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
                verification={
                    "legacy_compatibility": True,
                    "autonomous_engineering_qualified": False,
                    "note": "Use NoryxDeliveryAdapter for evidence-qualified autonomous repository engineering.",
                },
            )


__all__ = ["NexusDeliveryAdapter", "NoryxDeliveryAdapter", "NoryxRunResult"]
