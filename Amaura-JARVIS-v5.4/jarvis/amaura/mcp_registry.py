"""Founder-owned registry for approved MCP stdio servers.

AI capability requests refer only to a ``server_id``. Executable paths, hashes,
arguments, environment exposure, tool allowlists and sandbox policy live in a
0600 operator configuration outside the workspace by default.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jarvis.amaura.models import GovernanceError


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def registry_path() -> Path:
    raw = os.environ.get("AMAURA_MCP_REGISTRY_PATH", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".config" / "amaura" / "mcp_servers.json").resolve()


@dataclass(frozen=True, slots=True)
class MCPServerSpec:
    server_id: str
    executable: Path
    sha256: str
    args: tuple[str, ...]
    env_keys: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    allow_tool_calls: bool
    ai_list_tools: bool
    timeout_seconds: int
    network: str

    def child_env(self) -> dict[str, str]:
        safe = {
            key: value
            for key in ("PATH", "HOME", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "LC_CTYPE")
            if (value := os.environ.get(key))
        }
        for key in self.env_keys:
            value = os.environ.get(key)
            if value is None:
                raise GovernanceError(f"Approved MCP server '{self.server_id}' is missing required environment: {key}")
            safe[key] = value
        return safe

    def command_argv(self) -> tuple[str, list[str], list[Path]]:
        """Return sandbox wrapper command/args and temporary files to clean up."""
        cleanup: list[Path] = []
        executable = str(self.executable)
        args = list(self.args)
        if self.network == "none":
            if sys.platform == "darwin":
                sandbox = shutil.which("sandbox-exec")
                if not sandbox:
                    raise GovernanceError("MCP network=none requires sandbox-exec on macOS")
                profile = """(version 1)\n(allow default)\n(deny network*)\n(deny file-write*)\n(allow file-write* (subpath \"/private/tmp\"))\n(allow file-write* (subpath \"/tmp\"))\n"""
                fd, name = tempfile.mkstemp(prefix="amaura-mcp-", suffix=".sb")
                os.close(fd)
                path = Path(name)
                path.write_text(profile, encoding="utf-8")
                path.chmod(0o600)
                cleanup.append(path)
                return sandbox, ["-f", str(path), executable, *args], cleanup
            bwrap = shutil.which("bwrap")
            if bwrap:
                return bwrap, [
                    "--unshare-net", "--die-with-parent", "--new-session",
                    "--ro-bind", "/", "/", "--tmpfs", "/tmp",
                    executable, *args,
                ], cleanup
            raise GovernanceError("MCP network=none requires sandbox-exec (macOS) or bwrap (Linux)")
        if self.network != "public":
            raise GovernanceError(f"Unsupported MCP network policy: {self.network}")
        # Public-network MCP servers are operator-only; the registry still pins executable/hash/env.
        return executable, args, cleanup


def _validate_registry_permissions(path: Path) -> None:
    if os.name != "posix":
        return
    info = path.stat()
    if info.st_uid != os.getuid():
        raise GovernanceError("MCP registry must be owned by the current operator")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise GovernanceError("MCP registry permissions must be 0600 (not group/world accessible)")


def load_server(server_id: str, *, for_ai_list: bool = False) -> MCPServerSpec:
    server_id = str(server_id).strip()
    if not server_id or len(server_id) > 128:
        raise GovernanceError("MCP server_id is required")
    path = registry_path()
    if not path.is_file():
        raise GovernanceError(f"Founder MCP registry is not configured: {path}")
    _validate_registry_permissions(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GovernanceError("Founder MCP registry is invalid JSON") from exc
    servers = payload.get("servers") if isinstance(payload, dict) else None
    raw = servers.get(server_id) if isinstance(servers, dict) else None
    if not isinstance(raw, dict):
        raise GovernanceError(f"MCP server_id is not approved: {server_id}")

    command = Path(str(raw.get("command", ""))).expanduser()
    if not command.is_absolute() or not command.is_file():
        raise GovernanceError("Approved MCP command must be an existing absolute executable path")
    if not os.access(command, os.X_OK):
        raise GovernanceError("Approved MCP command is not executable")
    expected_hash = str(raw.get("sha256", "")).strip().lower()
    if len(expected_hash) != 64 or any(ch not in "0123456789abcdef" for ch in expected_hash):
        raise GovernanceError("Approved MCP server must declare an exact executable sha256")
    actual_hash = _sha256(command)
    if actual_hash != expected_hash:
        raise GovernanceError("Approved MCP executable hash does not match registry")

    args_raw = raw.get("args", [])
    env_raw = raw.get("env_keys", [])
    tools_raw = raw.get("allowed_tools", [])
    if not isinstance(args_raw, list) or len(args_raw) > 32:
        raise GovernanceError("MCP registry args must be a list of at most 32 strings")
    if not isinstance(env_raw, list) or len(env_raw) > 16:
        raise GovernanceError("MCP registry env_keys must be a list of at most 16 names")
    if not isinstance(tools_raw, list) or len(tools_raw) > 128:
        raise GovernanceError("MCP registry allowed_tools must be a list")
    env_keys: list[str] = []
    for value in env_raw:
        key = str(value).strip()
        if not key or key.upper() != key or not key.replace("_", "A").isalnum():
            raise GovernanceError(f"Invalid MCP registry environment key: {key}")
        env_keys.append(key)
    allowed_tools = tuple(str(value).strip() for value in tools_raw if str(value).strip())
    spec = MCPServerSpec(
        server_id=server_id,
        executable=command.resolve(),
        sha256=expected_hash,
        args=tuple(str(value) for value in args_raw),
        env_keys=tuple(env_keys),
        allowed_tools=allowed_tools,
        allow_tool_calls=bool(raw.get("allow_tool_calls", False)),
        ai_list_tools=bool(raw.get("ai_list_tools", False)),
        timeout_seconds=max(3, min(int(raw.get("timeout_seconds", 30)), 120)),
        network=str(raw.get("network", "none")).strip().lower(),
    )
    if for_ai_list and (not spec.ai_list_tools or spec.network != "none"):
        raise GovernanceError("AI list_tools is allowed only for registry entries with ai_list_tools=true and network=none")
    return spec


__all__ = ["MCPServerSpec", "load_server", "registry_path"]
