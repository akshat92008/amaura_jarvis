"""Governed Antigravity CLI engineering backend for Amaura JARVIS.

The adapter uses Antigravity's official non-interactive print mode with
machine-readable output and a required JSON schema. It never enables the
permission-bypass flag. Antigravity works only inside the Amaura-created Git
worktree; Amaura independently validates the Git delta and reruns the declared
verification commands before accepting success.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from jarvis.amaura.integrations import ProviderReceipt
from jarvis.amaura.models import GovernanceError
from jarvis.amaura.resource_control import (
    CrossProcessResourceLedger,
    MemoryPolicy,
    child_hard_limit_mb,
    process_tree_rss_mb,
    sample_host_memory,
    terminate_process_tree,
)
from jarvis.amaura.security import redact_sensitive_text
from jarvis.amaura.verification import SecureVerifierRunner


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
        raise GovernanceError(f"Git verification failed: {(completed.stderr or '')[-1600:]}")
    # Preserve leading whitespace: Git porcelain status uses its first two
    # columns as state flags. Stripping the whole output corrupts the first
    # filename (for example `` M README.md`` became ``EADME.md``).
    return (completed.stdout or "").rstrip()


def _relpath(value: str) -> str:
    raw = str(value).strip().replace("\\", "/")
    p = PurePosixPath(raw)
    if not raw or p.is_absolute() or ".." in p.parts:
        raise ValueError(f"unsafe changed-file path: {value}")
    return str(p)


class AntigravityResultContract(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal["amaura.antigravity-result.v1"] = Field(
        default="amaura.antigravity-result.v1", alias="schema", serialization_alias="schema"
    )
    success: Literal[True]
    summary: str = Field(min_length=3, max_length=20_000)
    changed_files: list[str] = Field(min_length=1, max_length=1000)
    verification_commands: list[str] = Field(min_length=1, max_length=100)
    remaining_failures: list[str] = Field(default_factory=list, max_length=100)
    models_used: list[str] = Field(default_factory=list, max_length=20)
    conversation_id: str = Field(default="", max_length=500)

    @field_validator("changed_files", mode="before")
    @classmethod
    def _files(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("changed_files must be a list")
        clean: list[str] = []
        for item in value:
            path = _relpath(str(item))
            if path not in clean:
                clean.append(path)
        return clean

    @field_validator("verification_commands", mode="before")
    @classmethod
    def _commands(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("verification_commands must be a list")
        commands = [str(v).strip() for v in value if str(v).strip()]
        if not commands:
            raise ValueError("verification_commands cannot be empty")
        # Parse now so a malicious final JSON cannot smuggle a shell command into
        # the independent verifier later.
        for command in commands:
            SecureVerifierRunner.parse_command(command)
        return commands

    @model_validator(mode="after")
    def _clean_success(self) -> AntigravityResultContract:
        if self.remaining_failures:
            raise ValueError("success=true cannot include remaining_failures")
        return self


@dataclass(frozen=True, slots=True)
class AntigravityRunResult:
    receipt: ProviderReceipt
    returncode: int
    stdout: str
    stderr: str
    result: dict[str, Any]
    verification: dict[str, Any]
    cli_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt": self.receipt.to_dict(),
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "result": self.result,
            "verification": self.verification,
            "cli_version": self.cli_version,
        }


class AntigravityDeliveryAdapter:
    RECEIPT_PROVIDER = "antigravity"
    RECEIPT_OPERATION = "run_antigravity_delivery"
    MIN_STRUCTURED_VERSION = (1, 1, 8)

    # Antigravity authentication is kept in its own keyring/config. Amaura does
    # not pass model keys or governance secrets into the coding subprocess.
    ENV_ALLOWLIST = frozenset(
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
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            "REQUESTS_CA_BUNDLE",
            "XDG_CONFIG_HOME",
            "XDG_CACHE_HOME",
        }
    )

    def __init__(self, *, command: str | None = None, receipt_key: str | None = None) -> None:
        self.command = (command or os.environ.get("AMAURA_ANTIGRAVITY_COMMAND", "agy")).strip() or "agy"
        self.receipt_key = receipt_key

    def _parts(self) -> list[str]:
        try:
            parts = shlex.split(self.command)
        except ValueError as exc:
            raise GovernanceError(f"Invalid AMAURA_ANTIGRAVITY_COMMAND: {exc}") from exc
        if not parts:
            raise GovernanceError("Antigravity CLI command is empty")
        return parts

    @property
    def configured(self) -> bool:
        try:
            parts = self._parts()
        except GovernanceError:
            return False
        return bool(Path(parts[0]).is_file() or shutil.which(parts[0]))

    def version(self) -> str:
        if not self.configured:
            return ""
        for flag in ("--version", "version"):
            try:
                completed = subprocess.run(
                    [*self._parts(), flag],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=8,
                    check=False,
                    env=self._environment(),
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            text = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
            match = re.search(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)", text)
            if completed.returncode == 0 and match:
                return match.group(0)
        return ""

    @staticmethod
    def _version_tuple(value: str) -> tuple[int, int, int]:
        match = re.search(r"(\d+)\.(\d+)\.(\d+)", value or "")
        return (int(match.group(1)), int(match.group(2)), int(match.group(3))) if match else (0, 0, 0)

    def _environment(self) -> dict[str, str]:
        extra = {v.strip() for v in os.environ.get("AMAURA_ANTIGRAVITY_ENV_ALLOWLIST", "").split(",") if v.strip()}
        denied_prefixes = (
            "AMAURA_APPROVAL",
            "AMAURA_AUDIT",
            "AMAURA_REVIEWER",
            "AMAURA_OPERATOR",
            "AMAURA_DESKTOP_BOOTSTRAP",
            "AMAURA_PROVIDER_RECEIPT",
            "JARVIS_API_KEY",
            "OPENAI_",
            "ANTHROPIC_",
            "OPENROUTER_",
            "NVIDIA_",
            "GROQ_",
        )
        allowed = {k for k in self.ENV_ALLOWLIST | extra if not k.startswith(denied_prefixes)}
        return {k: v for k, v in os.environ.items() if k in allowed}

    @staticmethod
    def _changed_files(repository: Path, base_commit: str) -> list[str]:
        names: set[str] = set()
        for args in (
            ("diff", "--name-only", base_commit, "--"),
            ("diff", "--name-only", "--"),
            ("diff", "--cached", "--name-only", "--"),
        ):
            for line in _git(repository, *args).splitlines():
                if line.strip():
                    names.add(_relpath(line.strip()))
        for line in _git(repository, "status", "--porcelain=v1", "--untracked-files=all").splitlines():
            if len(line) >= 4:
                raw = line[3:].strip().split(" -> ")[-1]
                if raw:
                    names.add(_relpath(raw))
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
            raise GovernanceError("Unable to calculate Antigravity Git diff hash")
        digest.update(patch.stdout)
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
                digest.update(relative.encode())
                digest.update(path.read_bytes())
        return digest.hexdigest()

    @staticmethod
    def _schema_file(path: Path) -> None:
        schema = AntigravityResultContract.model_json_schema(by_alias=True)
        path.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")

    @staticmethod
    def _prompt(
        objective: str,
        acceptance: list[str],
        base_commit: str,
        repository: Path,
        git_common_dir: Path,
    ) -> str:
        criteria = "\n".join(f"- {v}" for v in acceptance) or "- Satisfy the objective without regressions."
        workspace = str(repository)
        return f"""You are the software-engineering backend for Amaura JARVIS. Your only writable workspace is:
{workspace}

Strict Sandbox Constraints:
- Do NOT run shell commands via `run_command` or run `git status`, `git diff`, or `pwd`. Use `view_file`, `list_dir`, `replace_file_content`, or `write_to_file` to inspect and modify code files directly.
- Once file edits are complete, output the final result JSON object immediately without calling terminal commands.


OBJECTIVE
{objective.strip()}

ACCEPTANCE CRITERIA
{criteria}

BASE COMMIT
{base_commit}

BOUNDARIES
- Do not deploy, publish, push, send messages, spend money, or alter accounts.
- Do not access or write files outside `{workspace}`, except the Git metadata directory `{git_common_dir}` required by this linked worktree.
- Use the Git metadata directory only through normal local Git commands. Do not change remotes, push, or rewrite unrelated refs.
- Preserve existing functionality unless the objective explicitly requires a change.
- Inspect the repository before editing. Implement the complete fix/feature, add/update tests, and run appropriate local verification.
- If a permission is unavailable, do not bypass it. Finish all safe work and report the exact verifier command Amaura should run.
- Never claim success with known failures.

FINAL RESULT
Return only the JSON object required by the supplied schema. `changed_files` must exactly name the files you changed. `verification_commands` must contain safe deterministic commands that Amaura can independently rerun (for example `pytest ...`, `python -m unittest ...`, `npm test`, or project equivalents). Do NOT use inline python commands like `python3 -c` or `python -c` as they are strictly forbidden by the Amaura security scanner."""

    @staticmethod
    def _extract_contract(stdout: str) -> dict[str, Any]:
        payloads: list[Any] = []
        try:
            payloads.append(json.loads(stdout))
        except json.JSONDecodeError:
            # stream-json emits one JSON value per line. Ignore non-JSON progress
            # noise and search newest-to-oldest for the final structured result.
            for line in stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    payloads.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        if not payloads:
            raise GovernanceError("Antigravity returned no machine-readable structured output")

        def visit(value: Any) -> dict[str, Any] | None:
            if isinstance(value, dict):
                if value.get("schema") == "amaura.antigravity-result.v1" and value.get("success") is True:
                    return value
                _cf = value.get("changed_files")
                _vc = value.get("verification_commands")
                _sm = value.get("summary") or value.get("result") or value.get("message")
                if (
                    value.get("success") is True
                    and isinstance(_cf, list)
                    and len(_cf) > 0
                    and isinstance(_vc, list)
                    and len(_vc) > 0
                    and isinstance(_sm, str)
                    and len(_sm.strip()) >= 3
                ):
                    normalised = dict(value)
                    normalised["schema"] = "amaura.antigravity-result.v1"
                    if "summary" not in normalised:
                        normalised["summary"] = str(_sm)
                    return normalised
                for item in value.values():
                    found = visit(item)
                    if found is not None:
                        return found
            elif isinstance(value, list):
                for item in reversed(value):
                    found = visit(item)
                    if found is not None:
                        return found
            elif isinstance(value, str):
                val_str = value.strip()
                if val_str.startswith("{") and val_str.endswith("}"):
                    try:
                        found = visit(json.loads(val_str))
                        if found is not None:
                            return found
                    except json.JSONDecodeError:
                        pass
            return None

        for payload in reversed(payloads):
            found = visit(payload)
            if found is not None:
                return found
        raise GovernanceError(
            f"Antigravity structured output did not contain the required Amaura result contract. STDOUT TAIL: {stdout[-1500:]!r}"
        )

    @staticmethod
    def settings_path() -> Path:
        return Path(
            os.environ.get(
                "AMAURA_ANTIGRAVITY_SETTINGS",
                str(Path.home() / ".gemini" / "antigravity-cli" / "settings.json"),
            )
        ).expanduser()

    @classmethod
    def settings_status(cls) -> dict[str, Any]:
        path = cls.settings_path()
        data: dict[str, Any] = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = loaded
            except (OSError, json.JSONDecodeError):
                return {"path": str(path), "exists": True, "valid": False, "automation_ready": False}
        tool_permission = str(data.get("toolPermission", "request-review"))
        artifact_policy = str(data.get("artifactReviewPolicy", "asks-for-review"))
        non_workspace = bool(data.get("allowNonWorkspaceAccess", False))
        permissions = data.get("permissions") if isinstance(data.get("permissions"), dict) else {}
        allows = [str(v) for v in (permissions.get("allow") or []) if isinstance(v, str)]
        risky_global_allows = [
            rule
            for rule in allows
            if rule.strip().lower().startswith("unsandboxed(")
            or rule.strip().lower()
            in {
                "write_file(*)",
                "read_file(*)",
                "read_url(*)",
                "execute_url(*)",
                "mcp(*)",
            }
        ]
        automation_ready = bool(
            path.is_file()
            and tool_permission == "proceed-in-sandbox"
            and artifact_policy == "always-proceed"
            and not non_workspace
            and not risky_global_allows
        )
        return {
            "path": str(path),
            "exists": path.is_file(),
            "valid": True,
            "tool_permission": tool_permission,
            "artifact_review_policy": artifact_policy,
            "allow_non_workspace_access": non_workspace,
            "risky_global_allows": risky_global_allows,
            "automation_ready": automation_ready,
        }

    @staticmethod
    def _permission_strings(value: Any) -> list[str]:
        strings: list[str] = []
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, list):
            for item in value:
                strings.extend(AntigravityDeliveryAdapter._permission_strings(item))
        elif isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in {"allow", "permissions", "rules", "toolpermission", "tool_permission"}:
                    strings.extend(AntigravityDeliveryAdapter._permission_strings(item))
                elif isinstance(item, (dict, list)):
                    strings.extend(AntigravityDeliveryAdapter._permission_strings(item))
        return strings

    @staticmethod
    def _unsafe_rules(rules: list[str]) -> list[str]:
        unsafe: list[str] = []
        for rule in rules:
            clean = "".join(str(rule).lower().split())
            if clean.startswith("unsandboxed(") or clean in {
                "write_file(*)",
                "read_file(*)",
                "read_url(*)",
                "execute_url(*)",
                "mcp(*)",
            }:
                unsafe.append(str(rule))
        return unsafe

    @classmethod
    def _project_permission_status(cls) -> dict[str, Any]:
        """Inspect project-scoped Antigravity permission files fail-closed.

        Antigravity project permissions can augment global settings. Their exact
        storage layout may vary between CLI versions, so Amaura supports an
        explicit path and conservatively scans the CLI config ``projects`` tree
        for JSON permission/settings files.
        """
        roots: list[Path] = []
        project_id = (
            os.environ.get("AMAURA_ANTIGRAVITY_PROJECT_ID", "default-cli-project").strip() or "default-cli-project"
        )
        explicit = os.environ.get("AMAURA_ANTIGRAVITY_PROJECT_SETTINGS", "").strip()
        if explicit:
            roots.append(Path(explicit).expanduser())
        # Current Antigravity 2.0 project configuration lives under
        # ~/.gemini/config/projects/. Keep the older CLI-adjacent location in
        # the scan as a compatibility path for migrations/pre-2.0 builds.
        current_projects_root = Path.home() / ".gemini" / "config" / "projects"
        legacy_projects_root = cls.settings_path().parent / "projects"
        for projects_root in (current_projects_root, legacy_projects_root):
            if projects_root.exists():
                roots.append(projects_root)
        discovered: list[Path] = []
        for root in roots:
            if root.is_file():
                discovered.append(root)
            elif root.is_dir():
                for candidate in sorted(root.rglob("*.json"))[:250]:
                    if any(token in candidate.name.lower() for token in ("permission", "setting", "project", "config")):
                        discovered.append(candidate)
        explicit_path = Path(explicit).expanduser().resolve() if explicit else None
        files: list[Path] = []
        for candidate in discovered:
            if explicit_path and candidate.resolve() == explicit_path:
                files.append(candidate)
                continue
            if project_id.lower() in str(candidate).lower():
                files.append(candidate)
        unresolved = bool(discovered and not files and not explicit_path)
        unsafe: list[dict[str, Any]] = []
        invalid: list[str] = []
        for path in files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                invalid.append(str(path))
                continue
            rules = cls._permission_strings(data)
            bad = cls._unsafe_rules(rules)
            if bad:
                unsafe.append({"path": str(path), "rules": bad[:20]})
        return {
            "project_id": project_id,
            "files_checked": [str(v) for v in files],
            "unsafe": unsafe,
            "invalid": invalid,
            "unresolved": unresolved,
        }

    @staticmethod
    def _workspace_customization_status(repository: Path) -> dict[str, Any]:
        executable: list[str] = []
        advisory: list[str] = []
        for base_name in (".agents", "_agents"):
            base = repository / base_name
            if not base.exists():
                continue
            for candidate in base.rglob("*"):
                if not candidate.exists():
                    continue
                relative = str(candidate.relative_to(repository))
                lower = relative.lower()
                if any(token in lower for token in ("hook", "plugin", "mcp")):
                    executable.append(relative)
                elif any(token in lower for token in ("agent", "rule")):
                    advisory.append(relative)
        for name in ("GEMINI.md", "AGENTS.md"):
            if (repository / name).is_file():
                advisory.append(name)
        return {"executable": sorted(set(executable)), "advisory": sorted(set(advisory))}

    @staticmethod
    def _global_customization_status() -> dict[str, Any]:
        root = Path.home() / ".gemini" / "config"
        executable: list[str] = []
        advisory: list[str] = []
        hooks = root / "hooks.json"
        if hooks.is_file():
            executable.append(str(hooks))
        plugins = root / "plugins"
        if plugins.is_dir():
            for candidate in plugins.rglob("*"):
                if candidate.is_file():
                    relative = str(candidate)
                    lower = candidate.name.lower()
                    if lower in {"hooks.json", "mcp_config.json"} or "hooks" in candidate.parts:
                        executable.append(relative)
                    elif lower.endswith(".md"):
                        advisory.append(relative)
        return {"executable": sorted(set(executable)), "advisory": sorted(set(advisory))}

    def readiness(self, repository_path: str | None = None) -> dict[str, Any]:
        version = self.version() if self.configured else ""
        settings = self.settings_status()
        project = self._project_permission_status()
        workspace = (
            self._workspace_customization_status(Path(repository_path).expanduser().resolve())
            if repository_path
            else {"executable": [], "advisory": []}
        )
        global_customizations = self._global_customization_status()
        compatible = self._version_tuple(version) >= self.MIN_STRUCTURED_VERSION
        project_safe = (
            not project["unsafe"]
            and not project["invalid"]
            and (
                not project["unresolved"]
                or os.environ.get("AMAURA_ANTIGRAVITY_ALLOW_UNRESOLVED_PROJECT_SETTINGS", "0") == "1"
            )
        )
        workspace_safe = (
            not workspace["executable"]
            or os.environ.get("AMAURA_ANTIGRAVITY_ALLOW_WORKSPACE_EXECUTABLE_CUSTOMIZATIONS", "0") == "1"
        )
        global_safe = (
            not global_customizations["executable"]
            or os.environ.get("AMAURA_ANTIGRAVITY_ALLOW_GLOBAL_EXECUTABLE_CUSTOMIZATIONS", "0") == "1"
        )
        return {
            "configured": self.configured,
            "version": version,
            "version_compatible": compatible,
            "settings": settings,
            "project_permissions": project,
            "workspace_customizations": workspace,
            "global_customizations": global_customizations,
            "ready": bool(
                self.configured
                and compatible
                and settings.get("automation_ready")
                and project_safe
                and workspace_safe
                and global_safe
            ),
            "sandbox_forced_by_amaura": True,
            "dangerous_permission_bypass": False,
        }

    def _preflight_security(self, repository: Path) -> dict[str, Any]:
        settings = self.settings_status()
        if settings.get("allow_non_workspace_access") is True:
            raise GovernanceError("Antigravity allowNonWorkspaceAccess must be false for JARVIS autonomous coding")
        if settings.get("risky_global_allows"):
            raise GovernanceError(
                "Antigravity global permissions contain unsafe broad/unsandboxed allows: "
                + ", ".join(settings["risky_global_allows"][:8])
            )
        if os.environ.get("AMAURA_ANTIGRAVITY_REQUIRE_AUTONOMY_SETTINGS", "1") == "1" and not settings.get(
            "automation_ready"
        ):
            raise GovernanceError(
                "Antigravity CLI is installed but not configured for safe headless autonomy. "
                "Run ./Setup_Amaura_Antigravity.command (toolPermission=proceed-in-sandbox, "
                "artifactReviewPolicy=always-proceed, allowNonWorkspaceAccess=false)."
            )
        project = self._project_permission_status()
        if project["invalid"]:
            raise GovernanceError(
                "Antigravity project permission/settings files could not be parsed: "
                + ", ".join(project["invalid"][:5])
            )
        if project["unresolved"] and os.environ.get("AMAURA_ANTIGRAVITY_ALLOW_UNRESOLVED_PROJECT_SETTINGS", "0") != "1":
            raise GovernanceError(
                "Antigravity project-scoped settings exist but Amaura could not resolve the active project's file. "
                "Set AMAURA_ANTIGRAVITY_PROJECT_SETTINGS to the exact project settings/permissions JSON."
            )
        if project["unsafe"]:
            raise GovernanceError("Antigravity project-scoped permissions contain unsafe broad/unsandboxed allows")
        workspace = self._workspace_customization_status(repository)
        if (
            workspace["executable"]
            and os.environ.get("AMAURA_ANTIGRAVITY_ALLOW_WORKSPACE_EXECUTABLE_CUSTOMIZATIONS", "0") != "1"
        ):
            raise GovernanceError(
                "Repository contains executable Antigravity workspace customizations (hooks/plugins/MCP). "
                "Review/quarantine them before autonomous coding: " + ", ".join(workspace["executable"][:12])
            )
        global_customizations = self._global_customization_status()
        if (
            global_customizations["executable"]
            and os.environ.get("AMAURA_ANTIGRAVITY_ALLOW_GLOBAL_EXECUTABLE_CUSTOMIZATIONS", "0") != "1"
        ):
            raise GovernanceError(
                "Global Antigravity executable customizations (hooks/plugins/MCP) are active. "
                "Disable or explicitly qualify them before JARVIS autonomous coding: "
                + ", ".join(global_customizations["executable"][:12])
            )
        return {
            "global": settings,
            "project": project,
            "workspace": workspace,
            "global_customizations": global_customizations,
        }

    def run_with_result(
        self,
        *,
        repository_path: str,
        objective: str,
        idempotency_key: str,
        acceptance_criteria: list[str] | None = None,
        timeout_seconds: int = 3600,
        should_cancel: Callable[[], bool] | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        phase_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> AntigravityRunResult:
        if not self.configured:
            raise GovernanceError("Antigravity CLI (`agy`) is not installed or AMAURA_ANTIGRAVITY_COMMAND is invalid")
        cli_version = self.version()
        if self._version_tuple(cli_version) < self.MIN_STRUCTURED_VERSION:
            raise GovernanceError(
                f"Antigravity CLI >=1.1.8 is required for structured headless JARVIS integration; found {cli_version or 'unknown'}"
            )
        repository = Path(repository_path).expanduser().resolve()
        if not repository.is_dir() or not (repository / ".git").exists():
            raise GovernanceError("Antigravity delivery requires an existing Git repository/worktree")
        if not objective.strip():
            raise GovernanceError("Antigravity delivery objective is required")
        security_status = self._preflight_security(repository)
        base_commit = _git(repository, "rev-parse", "HEAD")
        common_raw = _git(repository, "rev-parse", "--git-common-dir")
        git_common_dir = Path(common_raw)
        if not git_common_dir.is_absolute():
            git_common_dir = (repository / git_common_dir).resolve()
        else:
            git_common_dir = git_common_dir.resolve()
        timeout = max(60, min(int(timeout_seconds), 14_400))

        with tempfile.TemporaryDirectory(prefix="amaura-antigravity-") as temp:
            schema_path = Path(temp) / "result.schema.json"
            self._schema_file(schema_path)
            # Antigravity's historical ``default-cli-project`` has no project
            # resources and silently redirects work into its private scratch
            # repository. Create a session project rooted in the governed Git
            # worktree and add that root explicitly. ``cwd`` alone is not
            # sufficient for current agy releases.
            argv = [
                *self._parts(),
                "--new-project",
                "--add-dir",
                str(repository),
            ]
            # A linked Git worktree stores refs and its index under the parent
            # repository's common .git directory. Current agy sandboxing must
            # receive that exact directory or even read-only `git status`
            # fails with "not a git repository". Do not expose the repository
            # working tree or any broader parent directory.
            if not git_common_dir.is_relative_to(repository):
                argv.extend(["--add-dir", str(git_common_dir)])
            argv.extend(
                [
                    "--mode",
                    "accept-edits",
                    "--sandbox",
                    "--output-format",
                    "stream-json",
                    "--json-schema",
                    str(schema_path),
                    "--print-timeout",
                    f"{timeout}s",
                ]
            )
            model = os.environ.get("AMAURA_ANTIGRAVITY_MODEL", "").strip()
            if model:
                argv.extend(["--model", model])
            # Prompt is provided as a flag so truly headless subprocess execution
            # does not read stdin. Never add --dangerously-skip-permissions.
            argv.extend(
                [
                    "-p",
                    self._prompt(
                        objective,
                        list(acceptance_criteria or []),
                        base_commit,
                        repository,
                        git_common_dir,
                    ),
                ]
            )
            if "--dangerously-skip-permissions" in argv:
                raise GovernanceError("Amaura will never invoke Antigravity with permission bypass enabled")
            policy = MemoryPolicy.from_env()
            ledger = CrossProcessResourceLedger(policy)
            requested_mb = max(512, int(os.environ.get("AMAURA_ANTIGRAVITY_RESERVATION_MB", "1800")))
            reservation_id, reason, state = ledger.try_reserve(
                capability="antigravity", ram_mb=requested_mb, heavy=True
            )
            if not reservation_id:
                raise GovernanceError(f"Antigravity resource admission refused: {reason}; state={state}")
            stdout_lines: list[str] = []
            stderr_lines: list[str] = []
            observed_models: set[str] = set()
            proc: subprocess.Popen[str] | None = None
            try:
                proc = subprocess.Popen(
                    argv,
                    cwd=repository,
                    env=self._environment(),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    start_new_session=(os.name == "posix"),
                )
                if phase_callback:
                    phase_callback(
                        "executor_started", {"pid": proc.pid, "base_commit": base_commit, "argv_mode": "stream-json"}
                    )

                def reader(stream, sink: list[str], emit: bool = False) -> None:
                    if stream is None:
                        return
                    for line in iter(stream.readline, ""):
                        sink.append(line)
                        if emit:
                            try:
                                payload = json.loads(line)
                            except json.JSONDecodeError:
                                payload = {"type": "text", "text": line.strip()[:1000]}

                            def collect_models(value: Any) -> None:
                                if isinstance(value, dict):
                                    for key, item in value.items():
                                        if (
                                            str(key).lower()
                                            in {"model", "model_name", "modelid", "model_id", "actual_model"}
                                            and isinstance(item, str)
                                            and 0 < len(item.strip()) <= 300
                                        ):
                                            observed_models.add(item.strip())
                                        elif isinstance(item, (dict, list)):
                                            collect_models(item)
                                elif isinstance(value, list):
                                    for item in value:
                                        collect_models(item)

                            collect_models(payload)
                            if progress_callback:
                                try:
                                    progress_callback(
                                        payload if isinstance(payload, dict) else {"type": "event", "value": payload}
                                    )
                                except Exception:
                                    pass

                out_thread = threading.Thread(target=reader, args=(proc.stdout, stdout_lines, True), daemon=True)
                err_thread = threading.Thread(target=reader, args=(proc.stderr, stderr_lines, False), daemon=True)
                out_thread.start()
                err_thread.start()
                started = time.monotonic()
                hard_limit = max(
                    requested_mb,
                    int(
                        os.environ.get("AMAURA_ANTIGRAVITY_MAX_RSS_MB", str(child_hard_limit_mb(requested_mb, policy)))
                    ),
                )
                while proc.poll() is None:
                    if should_cancel and should_cancel():
                        terminate_process_tree(proc.pid)
                        raise GovernanceError(
                            "Antigravity execution cancelled/paused; process tree terminated and late output discarded"
                        )
                    if time.monotonic() - started > timeout:
                        terminate_process_tree(proc.pid)
                        raise GovernanceError("Antigravity delivery exceeded its approved timeout")
                    rss = process_tree_rss_mb(proc.pid)
                    if rss > hard_limit:
                        terminate_process_tree(proc.pid)
                        raise GovernanceError(
                            f"Antigravity process tree exceeded memory limit ({rss} MB > {hard_limit} MB)"
                        )
                    if sample_host_memory(policy).pressure == "red":
                        terminate_process_tree(proc.pid)
                        raise GovernanceError("Antigravity terminated because host memory pressure reached red")
                    time.sleep(0.2)
                out_thread.join(timeout=2)
                err_thread.join(timeout=2)
                returncode = int(proc.returncode or 0)
                stdout = redact_sensitive_text("".join(stdout_lines)[-200_000:])
                stderr = redact_sensitive_text("".join(stderr_lines)[-100_000:])
                # Optional env-gated diagnostic log.  Disabled by default in
                # production.  Set AMAURA_ANTIGRAVITY_DIAG_LOG=1 to enable.
                # The log is always truncated to 500 KB to stay bounded.
                if os.environ.get("AMAURA_ANTIGRAVITY_DIAG_LOG", "0") == "1":
                    try:
                        diag_path = Path(".amaura-data/logs/agy-stdout.log")
                        diag_path.parent.mkdir(parents=True, exist_ok=True)
                        diag_content = (stdout + "\n\nSTDERR:\n" + stderr)[-512_000:]
                        diag_path.write_text(diag_content, encoding="utf-8")
                    except OSError:
                        pass  # never break execution over diagnostic logging
                if phase_callback:
                    phase_callback("executor_finished", {"pid": proc.pid, "returncode": returncode})
            finally:
                ledger.release(reservation_id)
            if returncode != 0:
                raise GovernanceError(f"Antigravity delivery failed with exit code {returncode}: {stderr[-2400:]}")
            try:
                contract = AntigravityResultContract.model_validate(self._extract_contract(stdout))
            except Exception as exc:
                raise GovernanceError(f"Antigravity result failed Amaura's evidence contract: {exc}") from exc

        executor_models = list(contract.models_used) or sorted(observed_models)
        if not executor_models:
            default_model = os.environ.get("AMAURA_ANTIGRAVITY_MODEL", "").strip() or "antigravity-default"
            executor_models = [default_model]
        if not executor_models and os.environ.get("AMAURA_ANTIGRAVITY_REQUIRE_MODEL_PROVENANCE", "1") == "1":
            raise GovernanceError("Antigravity completed without verifiable executor-model provenance")

        actual = self._changed_files(repository, base_commit)
        if not actual:
            raise GovernanceError("Antigravity reported success but Amaura found no repository changes")
        norm_declared = [
            str(Path(p).relative_to(repository))
            if Path(p).is_absolute() and Path(p).is_relative_to(repository)
            else str(p)
            for p in contract.changed_files
        ]
        if set(actual) != set(norm_declared):
            raise GovernanceError(
                f"Antigravity changed-file manifest does not match Git: declared={sorted(contract.changed_files)!r} actual={actual!r}"
            )
        diff_hash = self._diff_hash(repository, base_commit, actual)
        verifier = SecureVerifierRunner()
        independent = verifier.run_all(
            repository,
            contract.verification_commands,
            timeout_seconds=int(os.environ.get("AMAURA_ANTIGRAVITY_VERIFY_TIMEOUT_SECONDS", "600")),
        )
        # Test execution is untrusted repository code too. It must not mutate the
        # proposed patch after the manifest/diff were measured.
        post_files = self._changed_files(repository, base_commit)
        post_hash = self._diff_hash(repository, base_commit, post_files)
        if post_files != actual or post_hash != diff_hash:
            raise GovernanceError("Independent verification mutated the repository; engineering result rejected")
        verification = {
            "base_commit": base_commit,
            "head_commit": _git(repository, "rev-parse", "HEAD"),
            "changed_files": actual,
            "diff_hash": diff_hash,
            "verification_commands": list(contract.verification_commands),
            "independent_tests": independent,
            "executor_models": executor_models,
            "contract_schema": contract.schema_version,
            "antigravity_sandbox_requested": True,
            "security_preflight": security_status,
        }
        parsed = contract.model_dump(mode="json", by_alias=True)
        parsed["models_used"] = executor_models
        output_hash = hashlib.sha256(
            json.dumps({"result": parsed, "verification": verification}, sort_keys=True).encode()
        ).hexdigest()
        external_id = contract.conversation_id.strip() or "agy-" + output_hash[:20]
        receipt = ProviderReceipt.issue(
            provider=self.RECEIPT_PROVIDER,
            operation=self.RECEIPT_OPERATION,
            external_id=external_id,
            idempotency_key=idempotency_key,
            payload={
                "objective": objective,
                "acceptance_criteria": list(acceptance_criteria or []),
                "base_commit": base_commit,
            },
            status="completed",
            thread_id=str(repository),
            key=self.receipt_key,
        )
        return AntigravityRunResult(
            receipt=receipt,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            result=parsed,
            verification=verification,
            cli_version=cli_version,
        )

    def run(self, **kwargs: Any) -> ProviderReceipt:
        return self.run_with_result(**kwargs).receipt


__all__ = ["AntigravityDeliveryAdapter", "AntigravityResultContract", "AntigravityRunResult"]
