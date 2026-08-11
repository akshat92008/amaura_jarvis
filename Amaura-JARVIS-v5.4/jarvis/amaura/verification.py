"""Independent, fail-closed command verification for autonomous engineering.

The verifier intentionally runs *after* a coding backend reports success.  The
backend's own test result is evidence, not truth.  On macOS the verifier uses
``sandbox-exec`` with network disabled and write access restricted to the
assigned worktree/temp directory.  On other platforms the default is Docker.
Host execution exists only as an explicit break-glass/testing mode.
"""
from __future__ import annotations

import os
import platform
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

from jarvis.amaura.models import GovernanceError
from jarvis.amaura.security import redact_sensitive_text


_DEFAULT_EXECUTABLES = frozenset({
    "python", "python3", "pytest", "uv", "npm", "pnpm", "yarn", "bun",
    "cargo", "go", "mvn", "mvnw", "gradle", "gradlew", "dotnet", "make",
    "cmake", "swift", "ruby", "bundle", "rspec", "tox",
    "ruff", "mypy",
})
_SHELL_OPERATORS = frozenset({"&&", "||", ";", "|", ">", ">>", "<", "2>", "2>>", "&"})


@dataclass(frozen=True, slots=True)
class VerificationResult:
    command: str
    argv: list[str]
    exit_code: int
    passed: bool
    stdout_tail: str
    stderr_tail: str
    isolation: str
    network_disabled: bool

    def to_dict(self) -> dict:
        return asdict(self)


class SecureVerifierRunner:
    """Run bounded verifier commands without trusting the coding agent.

    This is not a shell.  The first executable must exactly match an allowlist
    entry (absolute/path aliases are rejected), Python ``-c`` is forbidden, and
    production modes require an OS/container isolation boundary.
    """

    def __init__(self, *, mode: str | None = None) -> None:
        self.mode = (mode or os.environ.get("AMAURA_VERIFIER_MODE", "auto")).strip().lower()
        if self.mode not in {"auto", "native", "docker", "host"}:
            raise GovernanceError("AMAURA_VERIFIER_MODE must be auto, native, docker, or host")

    @staticmethod
    def parse_command(command: str, *, extra_allowlist: Iterable[str] = ()) -> list[str]:
        try:
            argv = shlex.split(str(command))
        except ValueError as exc:
            raise GovernanceError(f"Verifier command is malformed: {exc}") from exc
        if not argv:
            raise GovernanceError("Verifier command is empty")
        if any(part in _SHELL_OPERATORS for part in argv):
            raise GovernanceError("Verifier commands may not contain shell control operators")
        executable = argv[0]
        # Deliberately reject /tmp/python, ./pytest and similar path tricks.
        if Path(executable).name != executable:
            raise GovernanceError(f"Verifier executable must be an allowlisted command name, not a path: {executable}")
        configured = {
            item.strip() for item in os.environ.get("AMAURA_VERIFIER_ALLOWLIST", "").split(",") if item.strip()
        }
        allowed = _DEFAULT_EXECUTABLES | configured | {str(v).strip() for v in extra_allowlist if str(v).strip()}
        if executable not in allowed:
            raise GovernanceError(f"Verifier executable is outside the allowlist: {executable}")
        if executable in {"python", "python3"} and "-c" in argv[1:]:
            raise GovernanceError("Inline Python (-c) is forbidden in independent verification")
        return argv

    @staticmethod
    def _clean_environment(temp_home: str) -> dict[str, str]:
        allowed = {
            "PATH", "LANG", "LC_ALL", "TERM", "COLORTERM", "SSL_CERT_FILE", "SSL_CERT_DIR",
            "REQUESTS_CA_BUNDLE", "SYSTEMROOT", "WINDIR",
        }
        env = {k: v for k, v in os.environ.items() if k in allowed}
        env.update({"HOME": temp_home, "TMPDIR": temp_home, "TEMP": temp_home, "TMP": temp_home})
        # Prevent common language tooling from inheriting user-global config.
        env.update({
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPYCACHEPREFIX": str(Path(temp_home) / "pycache"),
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "npm_config_update_notifier": "false",
            "GIT_CONFIG_NOSYSTEM": "1",
        })
        return env

    def _resolve_mode(self) -> str:
        if self.mode != "auto":
            return self.mode
        if platform.system() == "Darwin" and shutil.which("sandbox-exec"):
            return "native"
        if shutil.which("docker"):
            return "docker"
        raise GovernanceError(
            "Independent verification has no isolation runtime. Install/enable Docker, or use macOS sandbox-exec. "
            "Host verification is break-glass only (AMAURA_VERIFIER_MODE=host + AMAURA_ALLOW_HOST_VERIFICATION=1)."
        )

    @staticmethod
    def _mac_profile(workspace: Path, temp_home: Path) -> str:
        # sandbox-exec profiles use literal paths; quote backslashes/quotes.
        def q(path: Path) -> str:
            return str(path).replace("\\", "\\\\").replace('"', '\\"')
        # Start from deny-by-default. The allowlist covers macOS runtime files,
        # common developer runtimes and the assigned worktree/temp home. This is
        # intentionally stricter than the v5.1 profile, which allowed arbitrary
        # host reads and only denied writes/network.
        read_roots = [
            workspace,
            temp_home,
            Path("/System"),
            Path("/usr"),
            Path("/bin"),
            Path("/sbin"),
            Path("/Library/Apple"),
            Path("/Library/Frameworks"),
            Path("/opt/homebrew"),
            Path("/private/var/db"),
            Path("/private/etc"),
            Path("/dev"),
        ]
        lines = [
            "(version 1)",
            "(deny default)",
            "(allow process*)",
            "(allow signal (target self))",
            "(allow sysctl-read)",
            "(allow mach-lookup)",
            "(allow ipc-posix-shm)",
            "(allow file-read-metadata)",
            "(deny network*)",
            f'(allow file-write* (subpath "{q(workspace)}"))',
            f'(allow file-write* (subpath "{q(temp_home)}"))',
            '(allow file-write* (subpath "/private/tmp"))',
            '(allow file-write* (subpath "/tmp"))',
        ]
        lines.extend(f'(allow file-read* (subpath "{q(path)}"))' for path in read_roots)
        return "\n".join(lines)

    def run(self, repository: str | Path, command: str, *, timeout_seconds: int = 300) -> VerificationResult:
        repo = Path(repository).expanduser().resolve()
        if not repo.is_dir():
            raise GovernanceError("Verifier repository does not exist")
        argv = self.parse_command(command)
        timeout = max(5, min(int(timeout_seconds), 1800))
        mode = self._resolve_mode()
        with tempfile.TemporaryDirectory(prefix="amaura-verify-") as temp:
            temp_home = Path(temp).resolve()
            env = self._clean_environment(str(temp_home))
            resolved_argv = list(argv)
            if resolved_argv and resolved_argv[0] == "python" and not shutil.which("python"):
                resolved_argv[0] = shutil.which("python3") or sys.executable
            if mode == "host":
                if os.environ.get("AMAURA_ALLOW_HOST_VERIFICATION", "0") != "1":
                    raise GovernanceError("Host verification requires AMAURA_ALLOW_HOST_VERIFICATION=1")
                launch = resolved_argv
                cwd = repo
                isolation = "host-breakglass"
                network_disabled = False
            elif mode == "native":
                if platform.system() != "Darwin" or not shutil.which("sandbox-exec"):
                    raise GovernanceError("Native verifier isolation currently requires macOS sandbox-exec")
                profile = self._mac_profile(repo, temp_home)
                launch = ["sandbox-exec", "-p", profile, *resolved_argv]
                cwd = repo
                isolation = "macos-sandbox-exec"
                network_disabled = True
            elif mode == "docker":
                if not shutil.which("docker"):
                    raise GovernanceError("Docker verifier mode requested but docker is unavailable")
                image = os.environ.get("AMAURA_VERIFIER_IMAGE", "python:3.11-slim").strip() or "python:3.11-slim"
                # The worktree is the only host mount. Network is disabled and the
                # container is resource bounded. Dependencies must already exist in
                # the image/worktree; verification never installs from the network.
                launch = [
                    "docker", "run", "--rm", "--network=none", "--cpus=2", "--memory=2g", "--pids-limit=256",
                    "--security-opt", "no-new-privileges", "-v", f"{repo}:/workspace:rw", "-w", "/workspace",
                    image, *argv,
                ]
                cwd = repo
                isolation = f"docker:{image}"
                network_disabled = True
            else:  # defensive
                raise GovernanceError(f"Unsupported verifier mode: {mode}")

            try:
                completed = subprocess.run(
                    launch,
                    cwd=cwd,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise GovernanceError(f"Independent verifier timed out: {command}") from exc
            return VerificationResult(
                command=command,
                argv=argv,
                exit_code=completed.returncode,
                passed=completed.returncode == 0,
                stdout_tail=redact_sensitive_text((completed.stdout or "")[-6000:]),
                stderr_tail=redact_sensitive_text((completed.stderr or "")[-6000:]),
                isolation=isolation,
                network_disabled=network_disabled,
            )

    def run_all(self, repository: str | Path, commands: Iterable[str], *, timeout_seconds: int = 300) -> list[dict]:
        results: list[dict] = []
        for command in commands:
            result = self.run(repository, str(command), timeout_seconds=timeout_seconds)
            record = result.to_dict()
            results.append(record)
            if not result.passed:
                raise GovernanceError(
                    f"Independent verification failed: {command} (exit {result.exit_code})"
                )
        if not results:
            raise GovernanceError("Autonomous repository success requires at least one independently rerun verifier command")
        return results


__all__ = ["SecureVerifierRunner", "VerificationResult"]
