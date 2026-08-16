"""Fail-closed execution isolation for untrusted employee commands."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from jarvis.amaura.models import GovernanceError


@dataclass(frozen=True, slots=True)
class SandboxResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    isolated: bool
    network_disabled: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class DockerSandbox:
    """Execute bounded commands in a no-network, least-privilege container. (Stateless)"""

    def __init__(
        self,
        *,
        docker_binary: str | None = None,
        image: str | None = None,
    ):
        self.docker_binary = docker_binary or shutil.which("docker")
        configured_digest = os.environ.get("AMAURA_SANDBOX_IMAGE_DIGEST", "").strip()
        if configured_digest and not (
            configured_digest.startswith("sha256:")
            and len(configured_digest) == 71
            and all(character in "0123456789abcdef" for character in configured_digest[7:].lower())
        ):
            raise GovernanceError("AMAURA_SANDBOX_IMAGE_DIGEST must be a sha256:<64 hex> image ID")
        self.image = (
            configured_digest
            or image
            or os.environ.get(
                "AMAURA_SANDBOX_IMAGE",
                "amaura-sandbox:3.6.0",
            )
        )

    @property
    def available(self) -> bool:
        return bool(self.docker_binary)

    def run(
        self,
        command: str | Sequence[str],
        *,
        workspace: str | Path,
        timeout: int = 120,
        environment: Mapping[str, str] | None = None,
    ) -> SandboxResult:
        if not self.docker_binary:
            raise GovernanceError("Docker isolation is required for employee commands but Docker is unavailable")
        root = Path(workspace).expanduser().resolve()
        if not root.is_dir():
            raise GovernanceError("Sandbox workspace does not exist")
        tokens = tuple(shlex.split(command)) if isinstance(command, str) else tuple(str(item) for item in command)
        if not tokens:
            raise GovernanceError("Sandbox command is empty")
        safe_environment = {
            key: value for key, value in (environment or {}).items() if key in {"CI", "LANG", "LC_ALL", "PYTHONPATH"}
        }
        arguments = [
            self.docker_binary,
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "256",
            "--memory",
            os.environ.get("AMAURA_SANDBOX_MEMORY", "1g"),
            "--cpus",
            os.environ.get("AMAURA_SANDBOX_CPUS", "1.5"),
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=128m",
            "--mount",
            f"type=bind,src={root},dst=/workspace,rw",
            "--workdir",
            "/workspace",
        ]
        for key, value in sorted(safe_environment.items()):
            arguments.extend(("--env", f"{key}={value}"))
        arguments.extend((self.image, *tokens))
        try:
            completed = subprocess.run(
                arguments,
                capture_output=True,
                text=True,
                timeout=max(1, min(int(timeout), 300)),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise GovernanceError(f"Sandboxed command timed out after {timeout} seconds") from exc
        except OSError as exc:
            raise GovernanceError("Docker sandbox could not be started") from exc
        return SandboxResult(
            command=tokens,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            isolated=True,
            network_disabled=True,
        )


class StatefulDockerSandbox:
    """Stateful OpenHands-style execution environment.
    Runs a persistent container and executes commands inside it via docker exec.
    """

    def __init__(
        self,
        workspace: str | Path,
        *,
        docker_binary: str | None = None,
        image: str | None = None,
        environment: Mapping[str, str] | None = None,
    ):
        self.docker_binary = docker_binary or shutil.which("docker")
        configured_digest = os.environ.get("AMAURA_SANDBOX_IMAGE_DIGEST", "").strip()
        if configured_digest and not (
            configured_digest.startswith("sha256:")
            and len(configured_digest) == 71
            and all(character in "0123456789abcdef" for character in configured_digest[7:].lower())
        ):
            raise GovernanceError("AMAURA_SANDBOX_IMAGE_DIGEST must be a sha256:<64 hex> image ID")
        self.image = (
            configured_digest
            or image
            or os.environ.get(
                "AMAURA_SANDBOX_IMAGE",
                "amaura-sandbox:3.6.0",
            )
        )
        self.workspace = Path(workspace).expanduser().resolve()
        if not self.workspace.is_dir():
            raise GovernanceError("Sandbox workspace does not exist")

        self.container_name = f"amaura-sandbox-{uuid.uuid4().hex[:8]}"
        self.environment = environment or {}
        self._running = False
        self._start_container()

    def _start_container(self) -> None:
        if not self.docker_binary:
            raise GovernanceError("Docker isolation is required but unavailable")

        safe_environment = {
            key: value for key, value in self.environment.items() if key in {"CI", "LANG", "LC_ALL", "PYTHONPATH"}
        }

        arguments = [
            self.docker_binary,
            "run",
            "-d",
            "--rm",
            "--name",
            self.container_name,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "256",
            "--memory",
            os.environ.get("AMAURA_SANDBOX_MEMORY", "1g"),
            "--cpus",
            os.environ.get("AMAURA_SANDBOX_CPUS", "1.5"),
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=128m",
            "--mount",
            f"type=bind,src={self.workspace},dst=/workspace,rw",
            "--workdir",
            "/workspace",
        ]
        for key, value in sorted(safe_environment.items()):
            arguments.extend(("--env", f"{key}={value}"))

        # Keep container alive
        arguments.extend((self.image, "tail", "-f", "/dev/null"))

        try:
            subprocess.run(
                arguments,
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            self._running = True
        except subprocess.TimeoutExpired as exc:
            raise GovernanceError("Stateful sandbox startup timed out") from exc
        except subprocess.CalledProcessError as exc:
            raise GovernanceError(f"Failed to start stateful sandbox: {exc.stderr}") from exc
        except OSError as exc:
            raise GovernanceError("Docker sandbox could not be started") from exc

    def close(self) -> None:
        """Stop the persistent container."""
        if self._running and self.docker_binary:
            subprocess.run(
                [self.docker_binary, "stop", "-t", "1", self.container_name],
                capture_output=True,
                check=False,
                timeout=10,
            )
            self._running = False

    def __del__(self) -> None:
        self.close()

    def run(
        self,
        command: str | Sequence[str],
        *,
        timeout: int = 120,
    ) -> SandboxResult:
        if not self._running or not self.docker_binary:
            raise GovernanceError("Sandbox is not running")

        tokens = tuple(shlex.split(command)) if isinstance(command, str) else tuple(str(item) for item in command)
        if not tokens:
            raise GovernanceError("Sandbox command is empty")

        arguments = [
            self.docker_binary,
            "exec",
            "-w",
            "/workspace",
            self.container_name,
        ]
        arguments.extend(tokens)

        try:
            completed = subprocess.run(
                arguments,
                capture_output=True,
                text=True,
                timeout=max(1, min(int(timeout), 300)),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise GovernanceError(f"Sandboxed command timed out after {timeout} seconds") from exc
        except OSError as exc:
            raise GovernanceError("Sandboxed command could not execute") from exc

        return SandboxResult(
            command=tokens,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            isolated=True,
            network_disabled=True,
        )


def run_governed_command(
    command: str,
    *,
    workspace: str | Path,
    timeout: int = 120,
) -> SandboxResult:
    """Run in Docker by default; host mode requires an explicit break-glass flag."""

    mode = os.environ.get("AMAURA_SANDBOX_MODE", "docker").strip().lower()
    if mode == "docker":
        return DockerSandbox().run(
            command,
            workspace=workspace,
            timeout=timeout,
            environment={"CI": "1", "LANG": "C.UTF-8"},
        )
    if mode != "host" or os.environ.get("AMAURA_ALLOW_HOST_EXECUTION") != "1":
        raise GovernanceError("Host command execution is disabled; configure Docker isolation")
    tokens = tuple(shlex.split(command))
    allowed_environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT", "PYTHONPATH"}
    }
    allowed_environment.update({"PAGER": "cat", "GIT_PAGER": "cat", "CI": "1"})
    try:
        completed = subprocess.run(
            tokens,
            shell=False,
            cwd=Path(workspace).expanduser().resolve(),
            capture_output=True,
            text=True,
            timeout=max(1, min(int(timeout), 300)),
            env=allowed_environment,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GovernanceError(f"Break-glass host command timed out after {timeout} seconds") from exc
    except OSError as exc:
        raise GovernanceError("Break-glass host command could not execute") from exc
    return SandboxResult(
        command=tokens,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        isolated=False,
        network_disabled=False,
    )


__all__ = [
    "DockerSandbox",
    "StatefulDockerSandbox",
    "SandboxResult",
    "run_governed_command",
]
