"""Governed worker execution: JARVIS dispatches, employees execute, reviewers verify."""

from __future__ import annotations

import json
import os
import re
import shlex
import time
from pathlib import Path
from typing import Any, ClassVar

from jarvis.amaura.completion_contract import (
    CompletionContractError,
    build_completion_packet,
    completion_system_prompt,
    extract_completion_contract,
    validate_completion_contract,
)
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.evidence import (
    create_review_attestation,
    deterministic_evidence_review,
    validate_criterion_review,
)
from jarvis.amaura.gitops import (
    finalize_task_commit,
    is_git_repository,
    is_software_task,
    prepare_task_worktree,
)
from jarvis.amaura.models import GovernanceError, TaskState
from jarvis.amaura.network import fetch_public_text
from jarvis.amaura.policy import PATH_ARGUMENTS
from jarvis.amaura.registry import get_agent
from jarvis.amaura.sandbox import StatefulDockerSandbox, run_governed_command
from jarvis.amaura.security import redact_sensitive_text
from jarvis.amaura.tool_authorization import authorization_denial_result
from jarvis.models import resolve_model
from jarvis.tools.result import parse_tool_result
from jarvis.tools.security import tool_workspace


class _LocalOllamaClient:
    """Device-only OpenAI-compatible client with no cloud fallback."""

    def __init__(self):
        from openai import OpenAI

        base_url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
        self._client = OpenAI(base_url=f"{base_url}/v1", api_key="ollama", timeout=120.0)
        self.last_execution_metadata: dict[str, Any] = {}

    def chat_sync(self, *, model_id: str, messages: list[dict], tools: list[dict] | None = None):
        kwargs: dict[str, Any] = {"model": model_id, "messages": messages, "temperature": 0.2}
        if tools:
            kwargs["tools"] = tools
        try:
            response = self._client.chat.completions.create(**kwargs)
            self.last_execution_metadata = {
                "requested_provider": "local",
                "actual_provider": "ollama",
                "requested_model": model_id,
                "actual_model": str(getattr(response, "model", "") or model_id),
                "fallback_reason": "",
                "credential_id": "local",
            }
            return response
        except Exception as exc:
            raise GovernanceError(
                "Device-only inference failed; no cloud fallback was attempted. Start Ollama and configure AMAURA_LOCAL_MODEL."
            ) from exc


class _OmniRouteClient:
    """OpenAI-compatible governed worker client routed through local OmniRoute."""

    def __init__(self):
        from openai import OpenAI

        raw_base = (
            os.environ.get("AMAURA_OMNIROUTE_BASE_URL", "").strip() or os.environ.get("OMNIROUTE_BASE_URL", "").strip()
        ).rstrip("/")
        api_key = (
            os.environ.get("AMAURA_OMNIROUTE_API_KEY", "").strip() or os.environ.get("OMNIROUTE_API_KEY", "").strip()
        )
        if not raw_base or not api_key:
            raise GovernanceError("OmniRoute worker execution requires its base URL and API key")
        if not raw_base.startswith(("http://", "https://")):
            raise GovernanceError("OmniRoute base URL must start with http:// or https://")
        if raw_base.endswith("/chat/completions"):
            raw_base = raw_base[: -len("/chat/completions")]
        if not raw_base.endswith("/v1"):
            raw_base += "/v1"
        timeout = max(5.0, min(float(os.environ.get("AMAURA_OMNIROUTE_WORKER_TIMEOUT_SECONDS", "180")), 600.0))
        self._client = OpenAI(base_url=raw_base, api_key=api_key, timeout=timeout)
        self.last_execution_metadata: dict[str, Any] = {}

    def chat_sync(self, *, model_id: str, messages: list[dict], tools: list[dict] | None = None):
        fallback_model = os.environ.get("AMAURA_OMNIROUTE_FALLBACK_MODEL", "").strip()
        models = [model_id]
        if fallback_model and fallback_model != model_id:
            models.append(fallback_model)
        last_error: Exception | None = None
        for index, model in enumerate(models):
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": 0.2,
            }
            if tools:
                kwargs["tools"] = tools
            try:
                response = self._client.chat.completions.create(**kwargs)
                if not getattr(response, "choices", None):
                    raise GovernanceError("OmniRoute returned no completion choices")
                message = response.choices[0].message
                if not str(getattr(message, "content", "") or "").strip() and not (
                    getattr(message, "tool_calls", None) or []
                ):
                    raise GovernanceError("OmniRoute returned an empty worker completion")
                actual_model = str(getattr(response, "model", "") or model)
                self.last_execution_metadata = {
                    "requested_provider": "omniroute",
                    "actual_provider": "omniroute",
                    "requested_model": model_id,
                    "actual_model": actual_model,
                    "fallback_reason": "primary_failed" if index else "",
                    "gateway": "omniroute",
                    "credential_id": "omniroute-local-gateway",
                }
                return response
            except Exception as exc:  # the configured fallback receives one bounded attempt
                last_error = exc
        detail = redact_sensitive_text(str(last_error or "unknown error"))[:1000]
        raise GovernanceError(f"OmniRoute worker execution failed: {detail}") from last_error


class GovernedTaskRunner:
    """Runs one company employee strictly inside a JARVIS-issued task packet."""

    _WORKSPACE_DEFAULT_ARGUMENTS: ClassVar[dict[str, str]] = {
        "search_code": "directory",
        "find_files": "directory",
        "get_project_structure": "path",
        "run_command": "cwd",
        "run_tests": "cwd",
        "lint_code": "cwd",
        "analyze_code": "path",
        "git_status": "cwd",
        "git_diff": "cwd",
        "git_log": "cwd",
        "index_codebase_ast": "root_dir",
        "search_symbol": "root_dir",
    }

    def __init__(self, control_plane: AmauraControlPlane, client_factory=None):
        self.control = control_plane
        self.client_factory = client_factory

    def _client(self, route: dict[str, Any], employee):
        if self.client_factory is not None:
            return self.client_factory(route, employee)
        if route["provider"] == "local":
            return _LocalOllamaClient()
        if route["provider"] == "omniroute":
            return _OmniRouteClient()
        if os.environ.get("AMAURA_DISABLE_CLOUD") == "1":
            raise GovernanceError("Cloud model access is disabled for this execution")
        from jarvis.api import NvidiaClient

        agent_key = os.getenv(f"NVIDIA_API_KEY_{employee.agent_id.upper()}")
        allow_fallbacks = os.environ.get("AMAURA_MODEL_MODE", "local").strip().lower() == "balanced"
        return NvidiaClient(api_key=agent_key, allow_fallbacks=allow_fallbacks)

    @classmethod
    def _scope_tool_args(cls, tool_name: str, args: dict[str, Any], workspace: str) -> dict[str, Any]:
        """Make policy validation and actual tool execution resolve the same paths."""
        scoped = dict(args)
        default_argument = cls._WORKSPACE_DEFAULT_ARGUMENTS.get(tool_name)
        if default_argument and not scoped.get(default_argument):
            scoped[default_argument] = workspace
        root = Path(workspace).expanduser().resolve()
        for key, raw_value in list(scoped.items()):
            if key not in PATH_ARGUMENTS or not isinstance(raw_value, str) or not raw_value:
                continue
            candidate = Path(raw_value).expanduser()
            if not candidate.is_absolute():
                candidate = root / candidate
            scoped[key] = str(candidate.resolve())
        return scoped

    def _execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        execute_tool,
        sandbox: StatefulDockerSandbox | None = None,
        workspace: str | None = None,
    ) -> str:
        if tool_name == "web_fetch":
            result = fetch_public_text(
                str(args["url"]),
                max_length=int(args.get("max_length", 10_000)),
            )
            if result.startswith("❌"):
                return json.dumps({"ok": False, "data": {}, "error": result, "external_id": "", "retryable": False})
            return json.dumps(
                {"ok": True, "data": {"output": result}, "error": None, "external_id": "", "retryable": False}
            )
        if tool_name not in {"run_command", "run_tests", "lint_code"}:
            with tool_workspace(workspace or Path.cwd()):
                return execute_tool(tool_name, args)
        if tool_name == "run_tests":
            framework = str(args.get("framework", "") or "pytest")
            path = str(args.get("path", "."))
            test_filter = str(args.get("filter", ""))
            verbose = bool(args.get("verbose", True))
            commands: dict[str, list[str]] = {
                "pytest": ["python", "-m", "pytest", path],
                "unittest": ["python", "-m", "unittest", "discover", path],
                "jest": ["npx", "jest", path],
                "vitest": ["npx", "vitest", "run", path],
                "mocha": ["npx", "mocha", path],
                "go": ["go", "test", "./..." if path == "." else path],
                "cargo": ["cargo", "test"],
                "rspec": ["bundle", "exec", "rspec", path],
                "phpunit": ["./vendor/bin/phpunit", path],
            }
            tokens = commands[framework]
            if verbose and framework in {"pytest", "unittest", "jest", "go"}:
                tokens.append("-v" if framework != "jest" else "--verbose")
            if test_filter:
                if framework == "pytest":
                    tokens.extend(("-k", test_filter))
                elif framework == "go":
                    tokens.extend(("-run", test_filter))
                elif framework == "cargo":
                    tokens.append(test_filter)
            command = shlex.join(tokens)
        elif tool_name == "lint_code":
            linter = str(args.get("linter", "") or "ruff")
            path = str(args.get("path", "."))
            fix = bool(args.get("fix", False))
            commands = {
                "ruff": ["python", "-m", "ruff", "check", path],
                "flake8": ["python", "-m", "flake8", path],
                "eslint": ["npx", "eslint", path],
                "golangci-lint": ["golangci-lint", "run", path],
                "clippy": ["cargo", "clippy"],
            }
            tokens = commands[linter]
            if fix and linter in {"ruff", "eslint"}:
                tokens.append("--fix")
            command = shlex.join(tokens)
        else:
            command = str(args["command"])
        timeout = max(1, min(int(args.get("timeout", 120)), 300))
        try:
            if sandbox:
                completed = sandbox.run(command, timeout=timeout)
            else:
                completed = run_governed_command(
                    command,
                    workspace=str(args["cwd"]),
                    timeout=timeout,
                )
        except GovernanceError as exc:
            return json.dumps(
                {
                    "ok": False,
                    "data": {},
                    "error": f"Cannot execute command: {exc}",
                    "external_id": "",
                    "retryable": False,
                }
            )
        output = completed.stdout
        if completed.stderr:
            output += ("\n" if output else "") + completed.stderr
        output = output.strip() or "(no output)"
        if completed.returncode != 0:
            return json.dumps(
                {
                    "ok": False,
                    "data": {},
                    "error": f"Command failed (exit code {completed.returncode}):\n{output}",
                    "external_id": "",
                    "retryable": False,
                }
            )
        return json.dumps(
            {"ok": True, "data": {"output": output}, "error": None, "external_id": "", "retryable": False}
        )

    def _ensure_task_active(self, task_id: str) -> dict[str, Any]:
        current = self.control.store.get_work_item(task_id)
        if current.get("state") == TaskState.CANCELLED.value:
            raise GovernanceError(
                "Mission/task was cancelled while execution was in progress; late worker output is discarded"
            )
        metadata = dict(current.get("metadata") or {})
        if metadata.get("mission_pause_requested"):
            raise GovernanceError("Mission was paused while execution was in progress; late worker output is discarded")
        if metadata.get("dynamic_goal"):
            programme_id = str(metadata.get("programme_id") or "")
            if not programme_id:
                raise GovernanceError("Dynamic mission task has no programme authority reference")
            programme = self.control.store.get_work_item(programme_id)
            pmeta = dict(programme.get("metadata") or {})
            if (
                pmeta.get("mission_runnable") is not True
                or pmeta.get("mission_paused") is True
                or pmeta.get("cancel_requested") is True
                or programme.get("state")
                in {TaskState.DRAFT.value, TaskState.CANCELLED.value, TaskState.COMPLETED.value}
            ):
                raise GovernanceError(
                    "Mission authority changed while execution was in progress; stale worker output is discarded"
                )
            if int(metadata.get("mission_generation", 1) or 1) != int(pmeta.get("mission_generation", 1) or 1):
                raise GovernanceError(
                    "Mission generation changed while execution was in progress; stale worker output is discarded"
                )
        return current

    def _run_antigravity_delivery(
        self, task_id: str, task: dict[str, Any], packet_dict: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute repository engineering through the official Antigravity CLI."""
        from jarvis.amaura.antigravity_bridge import AntigravityDeliveryAdapter
        from jarvis.amaura.gitops import WorktreeRecord

        workspace = str(packet_dict.get("_workspace") or "")
        adapter = AntigravityDeliveryAdapter()
        if not adapter.configured:
            raise GovernanceError(
                "coding_backend=antigravity was requested but the Antigravity CLI (`agy`) is not configured"
            )

        def should_cancel() -> bool:
            try:
                self._ensure_task_active(task_id)
                return False
            except GovernanceError:
                return True

        def phase_callback(phase: str, payload: dict[str, Any]) -> None:
            current = self.control.store.get_work_item(task_id)
            metadata = dict(current.get("metadata") or {})
            metadata.update(
                {
                    "engineering_phase": phase,
                    "engineering_phase_at": time.time(),
                    "engineering_executor": "antigravity",
                    "engineering_idempotency_key": f"amaura:{task_id}",
                }
            )
            if payload.get("pid"):
                metadata["antigravity_pid"] = int(payload["pid"])
            if payload.get("base_commit"):
                metadata["antigravity_base_commit"] = str(payload["base_commit"])
            if "returncode" in payload:
                metadata["antigravity_returncode"] = int(payload["returncode"])
            self.control.store.update_work_item(task_id, metadata=metadata)

        # If the previous process died after Antigravity started but before a
        # durable finished receipt was recorded, do not blindly invoke the same
        # engineering mission again. Reconciliation is safer than duplicate
        # repository work. Operators may explicitly clear/retry after inspection.
        current_meta = dict(self.control.store.get_work_item(task_id).get("metadata") or {})
        if current_meta.get("engineering_phase") == "executor_started" and current_meta.get("antigravity_pid"):
            raise GovernanceError(
                "Antigravity execution has an unreconciled prior start record. Inspect/reconcile the worktree before retrying."
            )
        last_progress_write = [0.0]

        def progress_callback(event: dict[str, Any]) -> None:
            # Stream useful Antigravity state into durable task metadata without
            # turning every CLI token/event into a database write. The desktop
            # can poll this field and show what the coding worker is doing.
            now = time.monotonic()
            if now - last_progress_write[0] < 0.75:
                return
            last_progress_write[0] = now
            try:
                from jarvis.security import redact_sensitive_text

                raw = json.dumps(event, ensure_ascii=False, sort_keys=True, default=str)
                summary = redact_sensitive_text(raw)[:1800]
                current = self.control.store.get_work_item(task_id)
                metadata = dict(current.get("metadata") or {})
                metadata.update(
                    {
                        "antigravity_progress": summary,
                        "antigravity_progress_at": time.time(),
                    }
                )
                self.control.store.update_work_item(task_id, metadata=metadata)
            except Exception:
                # Progress telemetry must never be able to break execution.
                return

        result = adapter.run_with_result(
            repository_path=workspace,
            objective=str(packet_dict.get("objective") or task.get("description") or ""),
            acceptance_criteria=list(task.get("acceptance_criteria") or []),
            idempotency_key=f"amaura:{task_id}",
            timeout_seconds=int((task.get("metadata") or {}).get("antigravity_timeout_seconds", 3600)),
            should_cancel=should_cancel,
            progress_callback=progress_callback,
            phase_callback=phase_callback,
        )
        self._ensure_task_active(task_id)
        evidence: list[dict[str, Any]] = []
        execution_record = self.control.evidence.put_json(
            result.to_dict(), source=f"task:{task_id}:antigravity_execution"
        )
        evidence.append(
            {
                "type": "antigravity_execution",
                "reference": execution_record.reference,
                "sha256": execution_record.sha256,
                "byte_length": execution_record.byte_length,
                "success": True,
                "excerpt": str(result.result.get("summary") or "Antigravity completed the engineering task")[:500],
            }
        )
        verify_record = self.control.evidence.put_json(
            result.verification, source=f"task:{task_id}:antigravity_verification"
        )
        evidence.append(
            {
                "type": "antigravity_verification",
                "reference": verify_record.reference,
                "sha256": verify_record.sha256,
                "byte_length": verify_record.byte_length,
                "success": True,
                "excerpt": f"diff={str(result.verification.get('diff_hash') or '')[:12]} files={len(result.verification.get('changed_files') or [])} independent_tests={len(result.verification.get('independent_tests') or [])}",
            }
        )
        for index, test_result in enumerate(result.verification.get("independent_tests") or []):
            record = self.control.evidence.put_json(
                test_result, source=f"task:{task_id}:amaura_antigravity_test:{index}"
            )
            evidence.append(
                {
                    "type": "independent_test",
                    "reference": record.reference,
                    "sha256": record.sha256,
                    "byte_length": record.byte_length,
                    "success": bool(test_result.get("passed")),
                    "excerpt": f"Amaura verifier exit={test_result.get('exit_code')} command={str(test_result.get('command') or '')[:320]}",
                }
            )
        executor_receipt = {
            "backend": "antigravity",
            "external_id": result.receipt.external_id,
            "models_used": list(result.verification.get("executor_models") or []),
            "actual_model": str((result.verification.get("executor_models") or [""])[0]),
            "provider": "antigravity",
            "cli_version": result.cli_version,
            "diff_hash": str(result.verification.get("diff_hash") or ""),
        }
        ext_record = self.control.evidence.put_json(
            executor_receipt, source=f"task:{task_id}:external_executor_receipt"
        )
        evidence.append(
            {
                "type": "external_executor_receipt",
                "reference": ext_record.reference,
                "sha256": ext_record.sha256,
                "byte_length": ext_record.byte_length,
                "success": True,
                "excerpt": f"backend=antigravity cli={result.cli_version} models={','.join(executor_receipt['models_used'][:5]) or 'not-declared'}",
            }
        )
        metadata = dict(task.get("metadata") or {})
        metadata.update(
            {
                "coding_backend_used": "antigravity",
                "antigravity_external_id": result.receipt.external_id,
                "antigravity_cli_version": result.cli_version,
                "antigravity_diff_hash": result.verification.get("diff_hash"),
                "antigravity_changed_files": list(result.verification.get("changed_files") or []),
                "antigravity_independent_tests": list(result.verification.get("independent_tests") or []),
                "antigravity_executor_models": list(result.verification.get("executor_models") or []),
                "engineering_phase": "verified",
                "engineering_phase_at": time.time(),
            }
        )
        if metadata.get("git_worktree_path"):
            self._ensure_task_active(task_id)
            worktree = WorktreeRecord(
                repository_root=str(metadata.get("git_repository_root", "")),
                worktree_path=str(metadata.get("git_worktree_path", "")),
                branch=str(metadata.get("git_branch", "")),
                base_branch=str(metadata.get("git_base_branch", "")),
                base_commit=str(metadata.get("git_base_commit", "")),
                isolation_mode=str(metadata.get("git_isolation_mode", "linked_worktree")),
            )
            commit = finalize_task_commit(
                worktree, task_id=task_id, title=str(task.get("title", "Antigravity engineering update"))
            )
            observed, committed = set(result.verification.get("changed_files") or []), set(commit.changed_files)
            if observed != committed:
                raise GovernanceError(
                    f"Antigravity verification delta does not match finalized commit: verified={sorted(observed)!r} committed={sorted(committed)!r}"
                )
            verification_commands = list(result.verification.get("verification_commands") or [])
            metadata.update(
                {
                    "git_commit": commit.commit,
                    "git_changed_files": list(commit.changed_files),
                    "verification_commands": verification_commands,
                }
            )
            if verification_commands and not metadata.get("post_merge_validation"):
                metadata["post_merge_validation"] = str(verification_commands[0])
            metadata.update({"engineering_phase": "commit_created", "engineering_phase_at": time.time()})
            self.control.store.update_work_item(task_id, metadata=metadata)
            commit_record = self.control.evidence.put_json(commit.to_dict(), source=f"task:{task_id}:git_commit")
            evidence.append(
                {
                    "type": "git_commit",
                    "reference": commit_record.reference,
                    "sha256": commit_record.sha256,
                    "byte_length": commit_record.byte_length,
                    "success": True,
                    "excerpt": f"commit={commit.commit[:12]} files={len(commit.changed_files)} backend=antigravity",
                }
            )
        self._ensure_task_active(task_id)
        summary = str(result.result["summary"]).strip()
        submitted = self.control.submit_task(task_id, task["owner_id"], summary, evidence)
        final_meta = dict(self.control.store.get_work_item(task_id).get("metadata") or {})
        final_meta.update({"engineering_phase": "submitted_for_review", "engineering_phase_at": time.time()})
        self.control.store.update_work_item(task_id, metadata=final_meta)
        return {
            "status": submitted["state"],
            "task_id": task_id,
            "employee": get_agent(task["owner_id"]).name,
            "iterations": 1,
            "summary": summary,
            "evidence": evidence,
            "coding_backend": "antigravity",
            "reviewer": submitted["reviewer_id"],
        }

    def _run_noryx_delivery(self, task_id: str, task: dict[str, Any], packet_dict: dict[str, Any]) -> dict[str, Any]:
        """Execute a repository-write task through Noryx inside Amaura's isolated worktree."""
        from jarvis.amaura.gitops import WorktreeRecord
        from jarvis.amaura.noryx_bridge import NoryxDeliveryAdapter

        workspace = str(packet_dict.get("_workspace") or "")
        adapter = NoryxDeliveryAdapter()
        if not adapter.configured:
            raise GovernanceError("coding_backend=noryx was requested but Noryx is not configured")
        result = adapter.run_with_result(
            repository_path=workspace,
            objective=str(packet_dict.get("objective") or task.get("description") or ""),
            acceptance_criteria=list(task.get("acceptance_criteria") or []),
            idempotency_key=f"amaura:{task_id}",
            timeout_seconds=int((task.get("metadata") or {}).get("noryx_timeout_seconds", 1800)),
        )
        self._ensure_task_active(task_id)
        evidence: list[dict[str, Any]] = []
        execution_record = self.control.evidence.put_json(
            result.to_dict(),
            source=f"task:{task_id}:noryx_execution",
        )
        evidence.append(
            {
                "type": "noryx_execution",
                "reference": execution_record.reference,
                "sha256": execution_record.sha256,
                "byte_length": execution_record.byte_length,
                "success": True,
                "excerpt": str(result.result.get("summary") or "Noryx completed the engineering task")[:500],
            }
        )
        verification_record = self.control.evidence.put_json(
            result.verification,
            source=f"task:{task_id}:noryx_verification",
        )
        evidence.append(
            {
                "type": "noryx_verification",
                "reference": verification_record.reference,
                "sha256": verification_record.sha256,
                "byte_length": verification_record.byte_length,
                "success": True,
                "excerpt": (
                    f"diff={str(result.verification.get('diff_hash') or '')[:12]} "
                    f"files={len(result.verification.get('changed_files') or [])} "
                    f"tests={len(result.verification.get('tests') or [])}"
                ),
            }
        )
        for index, test_result in enumerate(result.verification.get("tests") or []):
            test_record = self.control.evidence.put_json(
                test_result,
                source=f"task:{task_id}:noryx_test:{index}",
            )
            evidence.append(
                {
                    "type": "noryx_test",
                    "reference": test_record.reference,
                    "sha256": test_record.sha256,
                    "byte_length": test_record.byte_length,
                    "success": bool(test_result.get("passed")) and int(test_result.get("exit_code", 1)) == 0,
                    "excerpt": (
                        f"exit={test_result.get('exit_code')} command={str(test_result.get('command') or '')[:320]}"
                    ),
                }
            )

        for index, test_result in enumerate(result.verification.get("independent_tests") or []):
            test_record = self.control.evidence.put_json(
                test_result,
                source=f"task:{task_id}:amaura_independent_test:{index}",
            )
            evidence.append(
                {
                    "type": "independent_test",
                    "reference": test_record.reference,
                    "sha256": test_record.sha256,
                    "byte_length": test_record.byte_length,
                    "success": bool(test_result.get("passed")) and int(test_result.get("exit_code", 1)) == 0,
                    "excerpt": (
                        f"Amaura verifier exit={test_result.get('exit_code')} command={str(test_result.get('command') or '')[:320]}"
                    ),
                }
            )

        executor_receipt = {
            "backend": "noryx",
            "external_id": getattr(result.receipt, "external_id", ""),
            "models_used": list(result.verification.get("executor_models") or []),
            "actual_model": str((result.verification.get("executor_models") or [""])[0]),
            "provider": "noryx",
            "diff_hash": str(result.verification.get("diff_hash") or ""),
        }
        external_record = self.control.evidence.put_json(
            executor_receipt,
            source=f"task:{task_id}:external_executor_receipt",
        )
        evidence.append(
            {
                "type": "external_executor_receipt",
                "reference": external_record.reference,
                "sha256": external_record.sha256,
                "byte_length": external_record.byte_length,
                "success": True,
                "excerpt": (
                    "backend=noryx models=" + ",".join(executor_receipt["models_used"][:5])
                    if executor_receipt["models_used"]
                    else "backend=noryx model-provenance=not-declared"
                ),
            }
        )

        metadata = dict(task.get("metadata") or {})
        metadata.update(
            {
                "coding_backend_used": "noryx",
                "noryx_external_id": getattr(result.receipt, "external_id", ""),
                "noryx_diff_hash": str(result.verification.get("diff_hash") or ""),
                "noryx_changed_files": list(result.verification.get("changed_files") or []),
                "noryx_tests": list(result.verification.get("tests") or []),
                "noryx_independent_tests": list(result.verification.get("independent_tests") or []),
                "noryx_executor_models": list(result.verification.get("executor_models") or []),
            }
        )
        if metadata.get("git_worktree_path"):
            self._ensure_task_active(task_id)
            worktree = WorktreeRecord(
                repository_root=str(metadata.get("git_repository_root", "")),
                worktree_path=str(metadata.get("git_worktree_path", "")),
                branch=str(metadata.get("git_branch", "")),
                base_branch=str(metadata.get("git_base_branch", "")),
                base_commit=str(metadata.get("git_base_commit", "")),
                isolation_mode=str(metadata.get("git_isolation_mode", "linked_worktree")),
            )
            commit = finalize_task_commit(
                worktree,
                task_id=task_id,
                title=str(task.get("title", "Noryx engineering update")),
            )
            observed_files = set(result.verification.get("changed_files") or [])
            committed_files = set(commit.changed_files)
            if observed_files != committed_files:
                raise GovernanceError(
                    "Noryx verification delta does not match Amaura's finalized task commit: "
                    f"verified={sorted(observed_files)!r} committed={sorted(committed_files)!r}"
                )
            metadata.update(
                {
                    "git_commit": commit.commit,
                    "git_changed_files": list(commit.changed_files),
                }
            )
            self.control.store.update_work_item(task_id, metadata=metadata)
            commit_record = self.control.evidence.put_json(
                commit.to_dict(),
                source=f"task:{task_id}:git_commit",
            )
            evidence.append(
                {
                    "type": "git_commit",
                    "reference": commit_record.reference,
                    "sha256": commit_record.sha256,
                    "byte_length": commit_record.byte_length,
                    "success": True,
                    "excerpt": f"commit={commit.commit[:12]} files={len(commit.changed_files)} backend=noryx",
                }
            )

        self._ensure_task_active(task_id)
        summary = str(result.result["summary"]).strip()
        submitted = self.control.submit_task(task_id, task["owner_id"], summary, evidence)
        return {
            "status": submitted["state"],
            "task_id": task_id,
            "employee": get_agent(task["owner_id"]).name,
            "iterations": 1,
            "summary": summary,
            "evidence": evidence,
            "coding_backend": "noryx",
            "reviewer": submitted["reviewer_id"],
        }

    def run(self, task_id: str, max_iterations: int = 12) -> dict[str, Any]:
        # repository_write tasks use the same isolated Git path as engineering delivery.
        max_iterations = max(1, min(max_iterations, 30))
        task = self.control.store.get_work_item(task_id)
        if task["state"] in {TaskState.ASSIGNED.value, TaskState.BLOCKED.value}:
            task = self.control.start_task(task_id, actor="jarvis")
        if task["state"] == TaskState.BLOCKED.value:
            return {"status": "blocked", "task": task, "reason": "Dependencies are incomplete"}
        if task["state"] != TaskState.IN_PROGRESS.value:
            raise GovernanceError(f"Task runner cannot execute state '{task['state']}'")

        packet_dict = self.control.task_packet(task_id, actor="jarvis")
        if is_software_task(task) and packet_dict.get("_workspace") and is_git_repository(packet_dict["_workspace"]):
            worktree = prepare_task_worktree(packet_dict["_workspace"], task_id)
            metadata = {
                **dict(task.get("metadata") or {}),
                "git_repository_root": worktree.repository_root,
                "git_worktree_path": worktree.worktree_path,
                "git_branch": worktree.branch,
                "git_base_branch": worktree.base_branch,
                "git_base_commit": worktree.base_commit,
                "git_isolation_mode": worktree.isolation_mode,
            }
            task = self.control.store.update_work_item(task_id, metadata=metadata)
            packet_dict["_workspace"] = worktree.worktree_path
            packet_dict["repository_context"]["workspace_dir"] = worktree.worktree_path
        elif is_software_task(task) and os.environ.get("AMAURA_STRICT_GIT", "0") == "1":
            raise GovernanceError("Repository-writing tasks require a clean Git repository in strict launch mode")

        coding_backend = str((task.get("metadata") or {}).get("coding_backend") or "antigravity").strip().lower()
        if task.get("action_type") == "repository_write" and coding_backend not in {
            "internal",
            "noryx",
            "antigravity",
            "auto",
        }:
            raise GovernanceError(f"Unknown repository coding backend: {coding_backend}")
        if task.get("action_type") == "repository_write":
            # Antigravity is the primary production coding worker while Noryx
            # remains an explicit experimental backend. Founder-facing software
            # missions are expected to arrive as `antigravity`; `auto` remains
            # only for legacy/internal compatibility.
            if coding_backend in {"antigravity", "auto"}:
                from jarvis.amaura.antigravity_bridge import AntigravityDeliveryAdapter

                antigravity = AntigravityDeliveryAdapter()
                if antigravity.configured:
                    return self._run_antigravity_delivery(task_id, task, packet_dict)
                if coding_backend == "antigravity":
                    raise GovernanceError("Antigravity CLI (`agy`) is required for coding_backend=antigravity")
            if coding_backend == "noryx":
                if os.environ.get("AMAURA_ENABLE_EXPERIMENTAL_NORYX", "0").strip().lower() not in {
                    "1",
                    "true",
                    "yes",
                    "on",
                }:
                    raise GovernanceError(
                        "Noryx is experimental and disabled by default. Set "
                        "AMAURA_ENABLE_EXPERIMENTAL_NORYX=1 only when you intentionally qualify it."
                    )
                from jarvis.amaura.noryx_bridge import NoryxDeliveryAdapter

                noryx = NoryxDeliveryAdapter()
                if not noryx.configured:
                    raise GovernanceError("Noryx was explicitly requested but is not configured")
                return self._run_noryx_delivery(task_id, task, packet_dict)

        if task.get("action_type") == "direct_action":
            from jarvis.amaura.direct_action import DirectActionRouter

            desc = task.get("description", "")
            workspace = packet_dict.pop("_workspace", "")
            approved_names = set(packet_dict.pop("_approved_tools", []))
            direct_evidence: list[dict[str, Any]] = []

            direct_result = DirectActionRouter.execute(desc, context="", control=self.control, workspace=workspace)

            if direct_result:
                record = self.control.evidence.put_json(
                    {
                        "success": direct_result.success,
                        "output": direct_result.output,
                        "execution_type": direct_result.execution_type,
                        "tool_name": direct_result.tool_name,
                        "provider": direct_result.provider,
                        "policy_decision": direct_result.policy_decision,
                        "telemetry": direct_result.telemetry,
                        **direct_result.telemetry,
                    },
                    source=f"task:{task_id}:direct_action",
                )
                direct_evidence.append(
                    {
                        "type": "direct_action",
                        "reference": record.reference,
                        "sha256": record.sha256,
                        "byte_length": record.byte_length,
                        "success": direct_result.success,
                        "excerpt": direct_result.output[:500],
                    }
                )
                metadata = dict(task.get("metadata") or {})
                self.control.store.update_work_item(task_id, metadata=metadata)
                submitted = self.control.submit_task(task_id, "builder", direct_result.output, direct_evidence)
                return {
                    "status": submitted["state"],
                    "task_id": task_id,
                    "employee": "builder",
                    "iterations": 1,
                    "summary": direct_result.output,
                    "evidence": direct_evidence,
                    "model_execution_receipt": {
                        "requested_route": "deterministic-direct-action",
                        "actual_model": direct_result.model or direct_result.tool_name,
                        "provider": direct_result.provider,
                    },
                    "reviewer": submitted["reviewer_id"],
                }

        route = packet_dict.pop("_model_route")
        workspace = packet_dict.pop("_workspace")
        approved_names = set(packet_dict.pop("_approved_tools"))

        from jarvis.amaura.models import CanonicalTaskPacket

        packet_model = CanonicalTaskPacket.model_validate(packet_dict)
        clean_packet = packet_model.model_dump(mode="json")

        from jarvis.tools.registry import ALL_TOOL_DEFINITIONS, execute_tool

        employee = get_agent(task["owner_id"])
        local_only = route["provider"] == "local"
        if local_only:
            model_cfg = {"id": route["model_key"], "supports_tools": True}
        else:
            resolved_model = resolve_model(route["model_key"])
            model_cfg = {
                "id": (resolved_model or {}).get("id", route["model_key"]),
                "supports_tools": (resolved_model or {}).get("supports_tools", True),
            }
        tools = [definition for definition in ALL_TOOL_DEFINITIONS if definition["function"]["name"] in approved_names]
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": employee.system_prompt
                + (
                    "\n\nUse authorised tools until evidence is sufficient for every acceptance criterion. "
                    "When you stop calling tools, return a concise draft summary. JARVIS will run a separate "
                    "evidence-to-deliverable completion gate before independent review. Do not claim success "
                    "unless tool results support it."
                ),
            },
            {"role": "user", "content": "JARVIS TASK PACKET:\n" + json.dumps(clean_packet, indent=2)},
        ]
        client = self._client(route, employee)
        evidence: list[dict[str, Any]] = []
        final_response = ""
        iterations = 0
        response = None  # holds the latest response for the final execution receipt
        total_input_tokens = 0
        total_output_tokens = 0
        actual_models: list[str] = []
        provider_executions: list[dict[str, Any]] = []
        completion_gate_attempts = 0

        sandbox = None
        sandbox_mode = os.environ.get("AMAURA_SANDBOX_MODE", "docker").strip().lower()
        if sandbox_mode == "docker":
            try:
                sandbox = StatefulDockerSandbox(workspace=workspace)
            except GovernanceError as exc:
                sandbox_error = str(exc)
                record = self.control.evidence.put_text(sandbox_error, source=f"task:{task_id}:sandbox_init_failure")
                evidence.append(
                    {
                        "type": "sandbox_init_failure",
                        "reference": record.reference,
                        "sha256": record.sha256,
                        "byte_length": record.byte_length,
                        "success": False,
                        "excerpt": sandbox_error[:500],
                    }
                )

        try:
            for iteration in range(1, max_iterations + 1):
                iterations = iteration
                self._ensure_task_active(task_id)
                response = client.chat_sync(
                    model_id=model_cfg["id"],
                    messages=messages,
                    tools=tools if model_cfg.get("supports_tools") and tools else None,
                )
                usage = getattr(response, "usage", None)
                total_input_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
                total_output_tokens += int(getattr(usage, "completion_tokens", 0) or 0)
                metadata = dict(getattr(client, "last_execution_metadata", {}) or {})
                actual_model = str(
                    metadata.get("actual_model") or getattr(response, "model", route["model_key"]) or route["model_key"]
                )
                if actual_model not in actual_models:
                    actual_models.append(actual_model)
                if metadata and metadata not in provider_executions:
                    provider_executions.append(metadata)
                if (
                    os.environ.get("AMAURA_MODEL_MODE", "local").strip().lower() == "cloud"
                    and route["provider"] == "nvidia"
                    and str(metadata.get("actual_provider") or "nvidia") != "nvidia"
                ):
                    raise GovernanceError("Cloud-only worker execution may not fall back to another provider")
                choice = response.choices[0]
                content = choice.message.content or ""
                tool_calls = choice.message.tool_calls or []
                if not tool_calls:
                    draft_summary = content.strip()
                    if not task.get("acceptance_criteria"):
                        final_response = draft_summary
                        break

                    # Tool success is evidence collection, not semantic completion. A
                    # dedicated no-tools synthesis pass must convert immutable evidence
                    # into a criterion-specific deliverable before independent review.
                    if not any(item.get("success") is True for item in evidence):
                        messages.append({"role": "assistant", "content": draft_summary})
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "JARVIS COMPLETION GATE REJECTED: no successful evidence exists for the "
                                    "acceptance criteria. Continue working with authorised tools; do not submit yet."
                                ),
                            }
                        )
                        continue

                    completion_gate_attempts += 1
                    synthesis_packet = build_completion_packet(
                        task_packet=clean_packet,
                        draft_summary=draft_summary,
                        evidence=evidence,
                        evidence_reader=self.control.evidence,
                    )
                    synthesis_response = client.chat_sync(
                        model_id=model_cfg["id"],
                        messages=[
                            {"role": "system", "content": completion_system_prompt()},
                            {
                                "role": "user",
                                "content": "JARVIS COMPLETION SYNTHESIS PACKET:\n"
                                + json.dumps(synthesis_packet, indent=2, ensure_ascii=False),
                            },
                        ],
                        tools=None,
                    )
                    synthesis_usage = getattr(synthesis_response, "usage", None)
                    total_input_tokens += int(getattr(synthesis_usage, "prompt_tokens", 0) or 0)
                    total_output_tokens += int(getattr(synthesis_usage, "completion_tokens", 0) or 0)
                    synthesis_metadata = dict(getattr(client, "last_execution_metadata", {}) or {})
                    synthesis_model = str(
                        synthesis_metadata.get("actual_model")
                        or getattr(synthesis_response, "model", route["model_key"])
                        or route["model_key"]
                    )
                    if synthesis_model not in actual_models:
                        actual_models.append(synthesis_model)
                    if synthesis_metadata and synthesis_metadata not in provider_executions:
                        provider_executions.append(synthesis_metadata)
                    if (
                        os.environ.get("AMAURA_MODEL_MODE", "local").strip().lower() == "cloud"
                        and route["provider"] == "nvidia"
                        and str(synthesis_metadata.get("actual_provider") or "nvidia") != "nvidia"
                    ):
                        raise GovernanceError("Cloud-only completion synthesis may not fall back to another provider")

                    synthesis_text = synthesis_response.choices[0].message.content or ""
                    try:
                        contract = extract_completion_contract(synthesis_text)
                        contract = validate_completion_contract(
                            contract,
                            acceptance_criteria=list(task.get("acceptance_criteria") or []),
                            evidence=evidence,
                        )
                    except CompletionContractError as exc:
                        gate_meta = dict(self.control.store.get_work_item(task_id).get("metadata") or {})
                        gate_meta.update(
                            {
                                "completion_gate_status": "rejected",
                                "completion_gate_attempts": completion_gate_attempts,
                                "completion_gate_last_error": str(exc)[:1200],
                            }
                        )
                        self.control.store.update_work_item(task_id, metadata=gate_meta)
                        messages.append({"role": "assistant", "content": draft_summary})
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "JARVIS COMPLETION GATE REJECTED: "
                                    + str(exc)
                                    + ". Re-check every acceptance criterion. If evidence is insufficient, gather "
                                    "more evidence with authorised tools; otherwise correct the deliverable and stop "
                                    "tool use again for another synthesis pass."
                                ),
                            }
                        )
                        continue

                    contract_record = self.control.evidence.put_json(
                        contract,
                        source=f"task:{task_id}:completion_contract",
                    )
                    evidence.append(
                        {
                            "type": "completion_contract",
                            "reference": contract_record.reference,
                            "sha256": contract_record.sha256,
                            "byte_length": contract_record.byte_length,
                            "success": True,
                            "excerpt": str(contract.get("summary") or "")[:500],
                        }
                    )
                    gate_meta = dict(self.control.store.get_work_item(task_id).get("metadata") or {})
                    gate_meta.update(
                        {
                            "completion_gate_status": "passed",
                            "completion_gate_attempts": completion_gate_attempts,
                            "completion_gate_contract_ref": contract_record.reference,
                        }
                    )
                    gate_meta.pop("completion_gate_last_error", None)
                    self.control.store.update_work_item(task_id, metadata=gate_meta)
                    final_response = json.dumps(contract, indent=2, ensure_ascii=False)
                    break

                messages.append(
                    {
                        "role": "assistant",
                        "content": content or None,
                        "tool_calls": [
                            {
                                "id": call.id,
                                "type": "function",
                                "function": {"name": call.function.name, "arguments": call.function.arguments},
                            }
                            for call in tool_calls
                        ],
                    }
                )
                for call in tool_calls:
                    try:
                        args = json.loads(call.function.arguments)
                    except json.JSONDecodeError as exc:
                        raise GovernanceError(f"Employee produced invalid arguments for {call.function.name}") from exc
                    if call.function.name == "run_command" and not args.get("cwd"):
                        args["cwd"] = workspace
                    self._ensure_task_active(task_id)
                    scoped_args = self._scope_tool_args(call.function.name, args, workspace)
                    denied_result = authorization_denial_result(
                        self.control,
                        task_id=task_id,
                        agent_id=employee.agent_id,
                        tool_name=call.function.name,
                        args=scoped_args,
                    )
                    if denied_result is not None:
                        result = denied_result
                    else:
                        result = self._execute_tool(
                            call.function.name,
                            scoped_args,
                            execute_tool,
                            sandbox=sandbox,
                            workspace=workspace,
                        )
                    result = redact_sensitive_text(result)
                    record = self.control.evidence.put_text(
                        result,
                        source=f"task:{task_id}:tool:{call.function.name}",
                    )
                    parsed_result = parse_tool_result(result)
                    success = parsed_result.ok
                    excerpt_str = str(parsed_result.data.get("output", result))
                    if parsed_result.error:
                        excerpt_str += "\nError: " + parsed_result.error

                    evidence.append(
                        {
                            "type": "tool_result",
                            "reference": record.reference,
                            "sha256": record.sha256,
                            "byte_length": record.byte_length,
                            "tool": call.function.name,
                            "success": success,
                            "excerpt": excerpt_str[:500],
                        }
                    )
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
            else:
                raise GovernanceError(f"Employee exceeded the {max_iterations}-iteration execution limit")
        finally:
            if sandbox:
                sandbox.close()

        if not final_response.strip():
            raise GovernanceError("Employee returned no completion summary")

        self._ensure_task_active(task_id)
        if is_software_task(task) and task.get("metadata", {}).get("git_worktree_path"):
            metadata = dict(task.get("metadata") or {})
            from jarvis.amaura.gitops import WorktreeRecord

            worktree = WorktreeRecord(
                repository_root=str(metadata.get("git_repository_root", "")),
                worktree_path=str(metadata.get("git_worktree_path", "")),
                branch=str(metadata.get("git_branch", "")),
                base_branch=str(metadata.get("git_base_branch", "")),
                base_commit=str(metadata.get("git_base_commit", "")),
                isolation_mode=str(metadata.get("git_isolation_mode", "linked_worktree")),
            )
            commit = finalize_task_commit(
                worktree,
                task_id=task_id,
                title=str(task.get("title", "software update")),
            )
            metadata.update(
                {
                    "git_commit": commit.commit,
                    "git_changed_files": list(commit.changed_files),
                }
            )
            task = self.control.store.update_work_item(task_id, metadata=metadata)
            commit_record = self.control.evidence.put_json(
                commit.to_dict(),
                source=f"task:{task_id}:git_commit",
            )
            evidence.append(
                {
                    "type": "git_commit",
                    "reference": commit_record.reference,
                    "sha256": commit_record.sha256,
                    "byte_length": commit_record.byte_length,
                    "success": True,
                    "excerpt": (
                        f"commit={commit.commit[:12]} files={len(commit.changed_files)} "
                        f"diff_bytes={len(commit.diff.encode('utf-8', errors='replace'))}"
                    ),
                }
            )

        if not evidence:
            if task.get("acceptance_criteria"):
                raise GovernanceError(
                    "Employee submitted no verifiable evidence to satisfy acceptance criteria. Agent prose is insufficient."
                )
            record = self.control.evidence.put_text(
                final_response,
                source=f"task:{task_id}:agent_output",
            )
            evidence.append(
                {
                    "type": "agent_output",
                    "reference": record.reference,
                    "sha256": record.sha256,
                    "byte_length": record.byte_length,
                    "success": True,
                    "excerpt": final_response[:500],
                }
            )

        estimated_cost = route["estimated_cost_cents"]
        # P0-8: record the actual model and provider for every inference, not just the route name.
        # The provider may have remapped the requested model to a fallback.
        final_provider = (
            str(provider_executions[-1].get("actual_provider")) if provider_executions else route["provider"]
        )
        model_execution_receipt = {
            "requested_route": route["model_key"],
            "requested_provider": route["provider"],
            "actual_model": actual_models[-1] if actual_models else route["model_key"],
            "models_used": actual_models,
            "provider": final_provider,
            "providers_used": [
                item.get("actual_provider") for item in provider_executions if item.get("actual_provider")
            ]
            or [route["provider"]],
            "provider_executions": provider_executions,
            "fallback_model_key": route.get("fallback_model_key"),
            "sandbox_mode": sandbox_mode,
            "container_id": getattr(sandbox, "container_id", None) if sandbox else None,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "estimated_cost_cents": estimated_cost,
            "iterations": iterations,
            "completion_gate_attempts": completion_gate_attempts,
        }
        receipt_record = self.control.evidence.put_json(
            model_execution_receipt,
            source=f"task:{task_id}:model_execution_receipt",
        )
        evidence.append(
            {
                "type": "model_execution_receipt",
                "reference": receipt_record.reference,
                "sha256": receipt_record.sha256,
                "byte_length": receipt_record.byte_length,
                "success": True,
                "excerpt": f"model={model_execution_receipt['actual_model']} provider={model_execution_receipt['provider']} tokens={model_execution_receipt['input_tokens']}+{model_execution_receipt['output_tokens']}",
            }
        )
        if estimated_cost:
            self.control.record_cost(
                task_id, employee.agent_id, estimated_cost, "model_inference", metadata=model_execution_receipt
            )
        submitted = self.control.submit_task(task_id, employee.agent_id, final_response, evidence)
        return {
            "status": submitted["state"],
            "task_id": task_id,
            "employee": employee.name,
            "iterations": iterations,
            "summary": final_response,
            "evidence": evidence,
            "model_execution_receipt": model_execution_receipt,
            "reviewer": submitted["reviewer_id"],
        }


def _extract_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, count=1, flags=re.IGNORECASE)
        candidate = re.sub(r"\s*```$", "", candidate, count=1)
    start, end = candidate.find("{"), candidate.rfind("}")
    if start < 0 or end <= start:
        raise GovernanceError("Reviewer returned no JSON decision")
    try:
        value = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError as exc:
        raise GovernanceError("Reviewer returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise GovernanceError("Reviewer decision must be a JSON object")
    return value


class GovernedReviewRunner:
    """Run the registered independent reviewer without granting founder authority."""

    def __init__(self, control_plane: AmauraControlPlane, client_factory=None):
        self.control = control_plane
        self.client_factory = client_factory

    def _client(self, reviewer, *, provider: str, model_key: str):
        route = {"provider": provider, "model_key": model_key}
        if self.client_factory is not None:
            return self.client_factory(route, reviewer)
        if provider == "omniroute":
            return _OmniRouteClient()
        if provider == "nvidia":
            if os.environ.get("AMAURA_DISABLE_CLOUD") == "1":
                raise GovernanceError("Cloud review is disabled for this execution")
            from jarvis.api import NvidiaClient

            reviewer_key = os.environ.get("NVIDIA_REVIEW_API_KEY", "").strip()
            return NvidiaClient(api_key=reviewer_key or None, allow_fallbacks=False)
        return _LocalOllamaClient()

    def _worker_models_from_evidence(self, task: dict[str, Any]) -> set[str]:
        models: set[str] = set()
        for item in task.get("evidence") or []:
            if item.get("type") not in {"model_execution_receipt", "external_executor_receipt"}:
                continue
            reference = str(item.get("reference") or "")
            if not reference:
                continue
            try:
                receipt = json.loads(self.control.evidence.get_text(reference))
            except (GovernanceError, json.JSONDecodeError):
                continue
            actual = str(receipt.get("actual_model") or "").strip()
            if actual:
                models.add(actual)
            for model in receipt.get("models_used") or []:
                value = str(model).strip()
                if value:
                    models.add(value)
        return models

    def run(self, task_id: str) -> dict[str, Any]:
        task = self.control.store.get_work_item(task_id)
        if task["state"] != TaskState.AWAITING_REVIEW.value:
            raise GovernanceError("Task is not awaiting independent review")
        reviewer_id = task["reviewer_id"]
        if not reviewer_id or reviewer_id == "founder":
            raise GovernanceError("Founder approval cannot be automated")
        if reviewer_id == task["owner_id"]:
            raise GovernanceError("No agent may certify its own work")
        self.control._ensure_agent_enabled(reviewer_id)
        reviewer = get_agent(reviewer_id)

        review_mode_raw = os.environ.get("AMAURA_REVIEW_MODE", "").strip().lower()
        if (
            task.get("action_type") == "direct_action"
            or (task.get("metadata") or {}).get("goal_plan", {}).get("domain") == "direct_action"
            or (
                task.get("action_type") == "repository_write"
                and (task.get("metadata") or {}).get("coding_backend_used") == "antigravity"
                and review_mode_raw in {"", "auto", "deterministic"}
            )
        ):
            deterministic = deterministic_evidence_review(task, self.control.evidence)
            approve = bool(deterministic.get("approve"))
            findings = (
                "Verified via independent tests and deterministic evidence."
                if approve
                else (
                    "Verification failed: "
                    + "; ".join(deterministic.get("findings") or ["evidence check failed"])
                )
            )
            evidence_refs = [ref["reference"] for ref in (task.get("evidence") or []) if ref.get("reference")]
            criteria = task.get("acceptance_criteria") or ["Action completed successfully"]
            decision = {
                "approve": approve,
                "findings": findings,
                "criteria": [
                    {
                        "criterion_index": idx + 1,
                        "criterion": c,
                        "passed": approve,
                        "evidence_refs": evidence_refs if approve else [],
                        "notes": "Verified via independent evidence" if approve else "Verification failed",
                    }
                    for idx, c in enumerate(criteria)
                ],
            }
            attestation = create_review_attestation(
                task_id=task_id,
                reviewer_id=reviewer_id,
                reviewer_model="deterministic-fast-path",
                reviewer_provider="internal",
                requested_reviewer_model="deterministic-fast-path",
                decision=decision,
                deterministic_review=deterministic,
            )
            updated = self.control.review_task(
                task_id, actor=reviewer_id, approve=approve, findings=findings, attestation=attestation
            )
            self.control.store.record_review_attestation(attestation)
            return updated

        review_mode = os.environ.get("AMAURA_REVIEW_MODE", "auto").strip().lower()
        if review_mode == "auto":
            review_mode = (
                "omniroute" if os.environ.get("AMAURA_MODEL_PROVIDER", "").strip().lower() == "omniroute" else "local"
            )
        if review_mode not in {"local", "cloud", "omniroute"}:
            raise GovernanceError("AMAURA_REVIEW_MODE must be auto, local, cloud, or omniroute")
        worker_model = os.environ.get("AMAURA_LOCAL_MODEL", "nova:3b").strip()
        if review_mode == "omniroute":
            model_id = os.environ.get("AMAURA_OMNIROUTE_REVIEW_MODEL", "").strip() or "auto/best-reasoning"
            if not (
                os.environ.get("AMAURA_OMNIROUTE_BASE_URL", "").strip()
                or os.environ.get("OMNIROUTE_BASE_URL", "").strip()
            ) or not (
                os.environ.get("AMAURA_OMNIROUTE_API_KEY", "").strip()
                or os.environ.get("OMNIROUTE_API_KEY", "").strip()
            ):
                raise GovernanceError("OmniRoute review requires its base URL and API key")
            worker_models = self._worker_models_from_evidence(task)
            if model_id in worker_models:
                raise GovernanceError(
                    "Independent reviewer model must differ from every worker model used for the task"
                )
            review_provider = "omniroute"
        elif review_mode == "cloud":
            model_id = os.environ.get("AMAURA_CLOUD_REVIEW_MODEL", "").strip()
            if not model_id:
                raise GovernanceError("AMAURA_CLOUD_REVIEW_MODEL is required when AMAURA_REVIEW_MODE=cloud")
            if not (
                os.environ.get("NVIDIA_REVIEW_API_KEY", "").strip() or os.environ.get("NVIDIA_API_KEY", "").strip()
            ):
                raise GovernanceError("Cloud review requires NVIDIA_REVIEW_API_KEY or NVIDIA_API_KEY")
            worker_models = self._worker_models_from_evidence(task)
            if model_id in worker_models:
                raise GovernanceError(
                    "Independent reviewer model must differ from every worker model used for the task"
                )
            if not worker_models and os.environ.get("AMAURA_STRICT_REVIEW", "0") == "1":
                raise GovernanceError("Strict cloud review requires worker/external-executor model provenance")
            review_provider = "nvidia"
        else:
            model_id = os.environ.get("AMAURA_LOCAL_REVIEW_MODEL", "").strip() or worker_model
            if model_id == worker_model:
                raise GovernanceError("Independent automated review requires a model distinct from AMAURA_LOCAL_MODEL")
            review_provider = "local"
        deterministic = deterministic_evidence_review(task, self.control.evidence)
        failed_evidence = [item for item in task["evidence"] if item.get("success") is False]
        review_packet = {
            "task_id": task["id"],
            "title": task["title"],
            "objective": task["description"],
            "acceptance_criteria": task["acceptance_criteria"],
            "submission_summary": task["summary"],
            "evidence": task["evidence"],
            "risk": task["risk"],
            "action_type": task["action_type"],
            "rules": [
                "Reject unsupported completion claims.",
                "Reject when any acceptance criterion lacks evidence.",
                "Never infer that a tool or test succeeded.",
                "Return JSON only.",
            ],
        }
        messages = [
            {
                "role": "system",
                "content": (
                    reviewer.system_prompt + "\n\nAct as an independent verifier. Return exactly one JSON object with "
                    '"approve" (boolean), "findings" (non-empty string), and '
                    '"criteria" (one object per acceptance criterion). Each criterion object must contain '
                    '"criterion_index" (1-based integer), "criterion" (exact text), "passed" (boolean), '
                    '"evidence_refs" (array containing only submitted evidence:// references), and "notes".'
                ),
            },
            {"role": "user", "content": "INDEPENDENT REVIEW PACKET:\n" + json.dumps(review_packet, indent=2)},
        ]
        review_client = self._client(reviewer, provider=review_provider, model_key=model_id)
        response = review_client.chat_sync(model_id=model_id, messages=messages, tools=None)
        route_metadata = dict(getattr(review_client, "last_execution_metadata", {}) or {})
        actual_provider = str(route_metadata.get("actual_provider") or review_provider).strip()
        actual_model = str(route_metadata.get("actual_model") or model_id).strip()
        if review_mode in {"cloud", "omniroute"}:
            expected_provider = "nvidia" if review_mode == "cloud" else "omniroute"
            if actual_provider != expected_provider:
                raise GovernanceError(f"{expected_provider} independent review may not fall back to another provider")
            worker_models = self._worker_models_from_evidence(task)
            if actual_model in worker_models:
                raise GovernanceError("Actual reviewer model must differ from every worker model used for the task")
        content = response.choices[0].message.content or ""
        decision = _extract_json_object(content)
        approve_value = decision.get("approve")
        findings_value = decision.get("findings")
        if not isinstance(approve_value, bool) or not isinstance(findings_value, str) or not findings_value.strip():
            raise GovernanceError("Reviewer decision is missing approve/findings")
        review_approve = approve_value
        review_findings = findings_value
        criterion_review = validate_criterion_review(task, decision, self.control.evidence)
        if not deterministic["approve"]:
            review_approve = False
            deterministic_findings = "; ".join(deterministic["findings"])
            review_findings = (
                f"Rejected by deterministic evidence verification: {deterministic_findings}. {review_findings.strip()}"
            )
        if not criterion_review["ok"]:
            review_approve = False
            review_findings = (
                "Rejected by criterion coverage verification: "
                + "; ".join(criterion_review["findings"])
                + ". "
                + review_findings.strip()
            )
        decision = {
            "approve": review_approve,
            "findings": review_findings.strip(),
            "criteria": criterion_review["criteria"],
        }
        attestation = create_review_attestation(
            task_id=task_id,
            reviewer_id=reviewer_id,
            reviewer_model=actual_model,
            reviewer_provider=actual_provider,
            requested_reviewer_model=model_id,
            decision=decision,
            deterministic_review=deterministic,
        )
        updated = self.control.review_task(
            task_id,
            actor=reviewer_id,
            approve=review_approve,
            findings=review_findings.strip(),
            attestation=attestation,
        )
        self.control.store.record_review_attestation(attestation)
        self.control.store.audit(
            reviewer_id,
            "automated_independent_review",
            "task",
            task_id,
            "approved" if review_approve else "rejected",
            {
                "requested_model": model_id,
                "actual_model": actual_model,
                "actual_provider": actual_provider,
                "criteria": decision.get("criteria", []),
                "criterion_review": criterion_review,
                "failed_evidence": len(failed_evidence),
                "submission_sha256": deterministic["submission_sha256"],
                "attestation_signature": attestation["signature"],
            },
        )
        return {
            "task_id": task_id,
            "reviewer_id": reviewer_id,
            "reviewer_model": actual_model,
            "requested_reviewer_model": model_id,
            "reviewer_provider": actual_provider,
            "approve": review_approve,
            "findings": review_findings.strip(),
            "state": updated["state"],
            "criteria": decision.get("criteria", []),
            "criterion_review": criterion_review,
            "deterministic_review": deterministic,
            "attestation": attestation,
        }
