"""
Safety Layer — permission system for dangerous operations.
Classifies operations as SAFE, WARN, DANGEROUS, or BLOCKED.
Adapted from Nexus with Jarvis-specific extensions.
"""

import re
from dataclasses import dataclass
from enum import Enum


class SafetyLevel(str, Enum):
    SAFE = "safe"
    WARN = "warn"
    DANGEROUS = "dangerous"
    BLOCKED = "blocked"


@dataclass
class SafetyCheck:
    """Result of a safety evaluation."""
    level: SafetyLevel
    operation: str
    reason: str
    details: str = ""
    requires_confirmation: bool = False
    confirmed: bool = False

    @property
    def is_allowed(self) -> bool:
        if self.level == SafetyLevel.BLOCKED:
            return False
        if self.level == SafetyLevel.DANGEROUS and not self.confirmed:
            return False
        return True

    def format_warning(self) -> str:
        icons = {
            SafetyLevel.SAFE: "✅",
            SafetyLevel.WARN: "⚠️",
            SafetyLevel.DANGEROUS: "🛑",
            SafetyLevel.BLOCKED: "🚫",
        }
        icon = icons.get(self.level, "❓")
        msg = f"{icon} [{self.level.value.upper()}] {self.reason}"
        if self.details:
            msg += f"\n   {self.details}"
        return msg


# ── Dangerous Command Patterns ───────────────────────────────────────────────

_COMMAND_PATTERNS: list[tuple[str, SafetyLevel, str]] = [
    # BLOCKED — never allow
    (r"\brm\s+-rf\s+/\s*$", SafetyLevel.BLOCKED, "Recursive deletion of root filesystem"),
    (r"\brm\s+-rf\s+/\w+\s*$", SafetyLevel.BLOCKED, "Recursive deletion of top-level directory"),
    (r"\b(mkfs|fdisk|dd\s+if=)\b", SafetyLevel.BLOCKED, "Disk formatting/overwriting"),
    (r"\b:\(\)\{.*\}\s*;", SafetyLevel.BLOCKED, "Fork bomb detected"),
    (r"\b(chmod|chown)\s+.*-R\s+/\s*$", SafetyLevel.BLOCKED, "Recursive permission change on root"),
    (r"\bcurl\b.*\|\s*(bash|sh|zsh)", SafetyLevel.BLOCKED, "Piping remote script directly to shell"),
    (r"\bwget\b.*\|\s*(bash|sh|zsh)", SafetyLevel.BLOCKED, "Piping remote script directly to shell"),
    (r"\bshutdown\b", SafetyLevel.DANGEROUS, "System shutdown requested"),
    (r"\breboot\b", SafetyLevel.DANGEROUS, "System reboot requested"),

    # DANGEROUS — require confirmation
    (r"\brm\s+-rf\b", SafetyLevel.DANGEROUS, "Recursive file deletion"),
    (r"\brm\s+-r\b", SafetyLevel.DANGEROUS, "Recursive file deletion"),
    (r"\brm\s+.*\*", SafetyLevel.DANGEROUS, "Wildcard file deletion"),
    (r"\bgit\s+push\s+.*--force\b", SafetyLevel.DANGEROUS, "Force push (may overwrite remote history)"),
    (r"\bgit\s+push\s+.*-f\b", SafetyLevel.DANGEROUS, "Force push (may overwrite remote history)"),
    (r"\bgit\s+reset\s+--hard\b", SafetyLevel.DANGEROUS, "Hard reset (discards uncommitted changes)"),
    (r"\bgit\s+clean\s+-fd\b", SafetyLevel.DANGEROUS, "Git clean (removes untracked files)"),
    (r"\bDROP\s+(TABLE|DATABASE|SCHEMA)\b", SafetyLevel.DANGEROUS, "Database DROP operation"),
    (r"\bTRUNCATE\s+TABLE\b", SafetyLevel.DANGEROUS, "Database TRUNCATE operation"),
    (r"\bDELETE\s+FROM\b(?!.*WHERE)", SafetyLevel.DANGEROUS, "DELETE without WHERE clause"),

    # WARN — log but proceed
    (r"\bsudo\b", SafetyLevel.WARN, "Running with elevated privileges"),
    (r"\bcurl\b.*-[oO]", SafetyLevel.WARN, "Downloading file from the internet"),
    (r"\bpip\s+install\b", SafetyLevel.WARN, "Installing Python package"),
    (r"\bnpm\s+install\b", SafetyLevel.WARN, "Installing npm package"),
    (r"\bbrew\s+install\b", SafetyLevel.WARN, "Installing Homebrew package"),
]

# Jarvis-specific: dangerous desktop automation patterns
_DESKTOP_PATTERNS: list[tuple[str, SafetyLevel, str]] = [
    (r"\bosascript.*delete\b", SafetyLevel.DANGEROUS, "AppleScript delete operation"),
    (r"\bosascript.*quit\b", SafetyLevel.WARN, "AppleScript quit application"),
    (r"\bkillall\b", SafetyLevel.DANGEROUS, "Killing all instances of a process"),
    (r"\bpkill\b", SafetyLevel.DANGEROUS, "Process kill by pattern"),
]

_PROTECTED_PATHS = [
    "/System", "/Library", "/usr", "/bin", "/sbin", "/etc",
    "/private", "/var", "/dev", "/tmp",
]


class SafetyLayer:
    """Evaluates operations for safety before execution."""

    def __init__(self):
        self._custom_rules: list[tuple[str, SafetyLevel, str]] = []
        self._allowed_paths: list[str] = []
        self._blocked_paths: list[str] = list(_PROTECTED_PATHS)

    def configure_from_rules(self, config: dict):
        """Configure safety from project rules."""
        if "allowed_paths" in config:
            self._allowed_paths = config["allowed_paths"]
        if "blocked_commands" in config:
            for cmd in config["blocked_commands"]:
                self._custom_rules.append((re.escape(cmd), SafetyLevel.BLOCKED, f"Blocked by project rules: {cmd}"))

    def check_command(self, command: str) -> SafetyCheck:
        """Check if a shell command is safe to execute."""
        # Check custom rules first
        for pattern, level, reason in self._custom_rules:
            if re.search(pattern, command, re.IGNORECASE):
                return SafetyCheck(
                    level=level, operation="command", reason=reason,
                    details=f"Command: {command[:100]}",
                    requires_confirmation=level == SafetyLevel.DANGEROUS,
                )

        # Check built-in patterns
        all_patterns = _COMMAND_PATTERNS + _DESKTOP_PATTERNS
        for pattern, level, reason in all_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return SafetyCheck(
                    level=level, operation="command", reason=reason,
                    details=f"Command: {command[:100]}",
                    requires_confirmation=level == SafetyLevel.DANGEROUS,
                )

        return SafetyCheck(
            level=SafetyLevel.SAFE, operation="command",
            reason="Command appears safe",
        )

    def check_file_write(self, filepath: str, content: str = "") -> SafetyCheck:
        """Check if a file write operation is safe."""
        from pathlib import Path
        p = str(Path(filepath).resolve())

        for blocked in self._blocked_paths:
            if p.startswith(blocked):
                return SafetyCheck(
                    level=SafetyLevel.BLOCKED, operation="file_write",
                    reason=f"Writing to protected system path: {blocked}",
                    details=f"Path: {filepath}",
                )

        return SafetyCheck(
            level=SafetyLevel.SAFE, operation="file_write",
            reason="File write appears safe",
        )

    def check_git_operation(self, args: list[str]) -> SafetyCheck:
        """Check if a git operation is safe."""
        cmd = " ".join(args)
        return self.check_command(f"git {cmd}")

    def check_desktop_action(self, action: str, target: str = "") -> SafetyCheck:
        """Check if a desktop automation action is safe."""
        combined = f"{action} {target}"
        for pattern, level, reason in _DESKTOP_PATTERNS:
            if re.search(pattern, combined, re.IGNORECASE):
                return SafetyCheck(
                    level=level, operation="desktop",
                    reason=reason, details=f"Action: {action}, Target: {target}",
                    requires_confirmation=level == SafetyLevel.DANGEROUS,
                )
        return SafetyCheck(
            level=SafetyLevel.SAFE, operation="desktop",
            reason="Desktop action appears safe",
        )
