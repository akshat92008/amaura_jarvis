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
import sys
import tempfile
from dataclasses import asdict, dataclass
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
        # Keep only the trusted executable directory of the interpreter running
        # JARVIS plus the sanitized inherited PATH.  This is essential when
        # JARVIS itself runs from a project virtualenv: allowlisted commands such
        # as pytest/ruff/mypy live beside sys.executable and must remain
        # discoverable after environment sanitization.  User-supplied executable
        # paths are still rejected by parse_command(), so this does not weaken
        # the command-name allowlist.
        runtime_bin = str(Path(sys.executable).resolve().parent)
        inherited_path = env.get("PATH", "")
        env["PATH"] = runtime_bin + (os.pathsep + inherited_path if inherited_path else "")
        env.update({"HOME": temp_home, "TMPDIR": temp_home, "TEMP": temp_home, "TMP": temp_home})
        # Prevent common language tooling from inheriting user-global config.
        env.update({
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPYCACHEPREFIX": str(Path(temp_home) / "pycache"),
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            # GUI/game test suites must remain headless inside the verifier.
            # On macOS SDL can abort the process (SIGABRT/-6) while probing
            # CoreAudio or Cocoa even when individual tests set only the video
            # driver. These deterministic dummy backends prevent that without
            # weakening process, filesystem, or network isolation.
            "SDL_VIDEODRIVER": "dummy",
            "SDL_AUDIODRIVER": "dummy",
            "SDL_RENDER_DRIVER": "software",
            "PYGAME_HIDE_SUPPORT_PROMPT": "1",
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
            Path(sys.prefix),
            Path(sys.executable).parent,
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

    @staticmethod
    def _host_fallback_after_sandbox_abort_enabled() -> bool:
        return (
            os.environ.get("AMAURA_VERIFIER_HOST_FALLBACK_ON_SANDBOX_ABORT", "0") == "1"
            and os.environ.get("AMAURA_ALLOW_HOST_VERIFICATION", "0") == "1"
        )

    @staticmethod
    def _looks_like_macos_sandbox_abort(completed: subprocess.CompletedProcess[str]) -> bool:
        return completed.returncode in {-6, 134}

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
            if (
                mode == "native"
                and self._looks_like_macos_sandbox_abort(completed)
                and self._host_fallback_after_sandbox_abort_enabled()
            ):
                try:
                    host_completed = subprocess.run(
                        resolved_argv,
                        cwd=repo,
                        env=env,
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        check=False,
                    )
                except subprocess.TimeoutExpired as exc:
                    raise GovernanceError(f"Independent verifier timed out after sandbox abort: {command}") from exc
                return VerificationResult(
                    command=command,
                    argv=argv,
                    exit_code=host_completed.returncode,
                    passed=host_completed.returncode == 0,
                    stdout_tail=redact_sensitive_text((host_completed.stdout or "")[-6000:]),
                    stderr_tail=redact_sensitive_text((host_completed.stderr or "")[-6000:]),
                    isolation="host-breakglass-after-macos-sandbox-abort",
                    network_disabled=False,
                )
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
