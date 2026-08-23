"""Founder-facing one-command certification and launch for Amaura JARVIS."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = REPOSITORY_ROOT / ".env.amaura"
_CACHE_SCHEMA_VERSION = 2
_CACHE_FILENAME = "runtime-certification-v1.json"


def _emit(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed with exit {completed.returncode}: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    return completed.stdout.strip()


def _runtime_fingerprint() -> str:
    distributions: list[str] = []
    for dist in importlib.metadata.distributions():
        name = str(dist.metadata["Name"] or "").strip().lower()
        if name:
            distributions.append(f"{name}=={dist.version}")
    payload = {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "executable": str(Path(sys.executable).resolve()),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "distributions": sorted(set(distributions)),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _certification_inputs(env_path: Path) -> dict[str, Any]:
    from jarvis.amaura.local_certification import runtime_worktree_status

    worktree = runtime_worktree_status(REPOSITORY_ROOT)
    return {
        "head": _git("rev-parse", "HEAD"),
        "git_toplevel": str(worktree["checkout_root"]),
        "worktree_clean": worktree["worktree_clean"],
        "runtime_relative_path": worktree["runtime_relative_path"],
        "runtime_dirty_entries": worktree["runtime_dirty_entries"],
        "outside_runtime_dirty_entries": worktree["outside_runtime_dirty_entries"],
        "env_sha256": _sha256_file(env_path),
        "runtime_sha256": _runtime_fingerprint(),
    }


def _cache_path() -> Path:
    configured = os.environ.get("AMAURA_DATA_DIR", "").strip()
    if configured:
        base = Path(configured).expanduser()
        if not base.is_absolute():
            base = REPOSITORY_ROOT / base
    else:
        base = REPOSITORY_ROOT / ".amaura-data"
    return base.resolve() / _CACHE_FILENAME


def _cache_key() -> bytes:
    key = os.environ.get("AMAURA_AUDIT_HMAC_KEY", "").strip()
    if len(key) < 32:
        raise RuntimeError("AMAURA_AUDIT_HMAC_KEY must be configured before readiness can be cached")
    return key.encode("utf-8")


def _signed_payload(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(_cache_key(), encoded, hashlib.sha256).hexdigest()
    return {**payload, "signature": signature}


def _write_cache(env_path: Path, report: dict[str, Any]) -> dict[str, Any]:
    inputs = _certification_inputs(env_path)
    if inputs.get("worktree_clean") is not True:
        raise RuntimeError(
            "Refusing to cache readiness for changes inside the certified JARVIS runtime tree: "
            f"{inputs.get('runtime_dirty_entries') or []}"
        )
    payload = {
        "schema_version": _CACHE_SCHEMA_VERSION,
        "ready": True,
        "verdict": "READY_FOR_DAILY_USE",
        "certified_at": datetime.now(UTC).isoformat(),
        **inputs,
        "production_ready": report.get("production_gate", {}).get("production_ready") is True,
        "real_pty": {
            "overall": report.get("real_pty", {}).get("overall"),
            "single_mission_continuity": report.get("real_pty", {}).get("single_mission_continuity"),
            "result_consistency": report.get("real_pty", {}).get("result_consistency"),
            "multi_mission_continuity": report.get("real_pty", {}).get("multi_mission_continuity"),
            "restart_test": report.get("real_pty", {}).get("restart_test"),
        },
    }
    signed = _signed_payload(payload)
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(signed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if os.name == "posix":
        temporary.chmod(0o600)
    os.replace(temporary, path)
    if os.name == "posix":
        path.chmod(0o600)
    return signed


def _load_valid_cache(env_path: Path) -> tuple[dict[str, Any] | None, str]:
    path = _cache_path()
    if not path.is_file():
        return None, "cache_missing"
    try:
        if os.name == "posix" and path.stat().st_mode & 0o077:
            return None, "cache_permissions_not_private"
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None, "cache_invalid_shape"
        signature = str(raw.pop("signature", ""))
        encoded = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
        expected = hmac.new(_cache_key(), encoded, hashlib.sha256).hexdigest()
        if not signature or not hmac.compare_digest(signature, expected):
            return None, "cache_signature_invalid"
        if raw.get("schema_version") != _CACHE_SCHEMA_VERSION:
            return None, "cache_schema_changed"
        if raw.get("ready") is not True or raw.get("verdict") != "READY_FOR_DAILY_USE":
            return None, "cache_not_ready"

        current = _certification_inputs(env_path)
        if current.get("worktree_clean") is not True:
            return None, "worktree_dirty"
        for key in ("head", "git_toplevel", "runtime_relative_path", "env_sha256", "runtime_sha256"):
            if raw.get(key) != current.get(key):
                return None, f"cache_{key}_changed"
        return raw, "cache_valid"
    except Exception as exc:
        return None, f"cache_error:{type(exc).__name__}"


def _remove_cache() -> None:
    try:
        _cache_path().unlink(missing_ok=True)
    except OSError:
        pass


def _build_jarvis_argv(args: argparse.Namespace) -> list[str]:
    argv = [sys.executable, "-m", "jarvis.runtime_entry"]
    argv.append("--web" if args.web else "--no-web")
    if args.voice:
        argv.append("--voice")
    if args.telegram:
        argv.append("--telegram")
    if args.model:
        argv.extend(["--model", args.model])
    if args.working_dir:
        argv.extend(["--working-dir", str(Path(args.working_dir).expanduser().resolve())])
    if args.prompt:
        argv.append(args.prompt)
    return argv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jarvis-ready",
        description=(
            "Launch Amaura JARVIS from a commit/env/runtime-bound readiness certificate. "
            "The expensive authoritative qualification runs only when the certificate is missing or invalidated."
        ),
    )
    parser.add_argument("prompt", nargs="?", help="Optional single prompt to run after readiness validation")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="Private Amaura environment file")
    parser.add_argument("--check-only", action="store_true", help="Validate readiness without launching JARVIS")
    parser.add_argument(
        "--recertify",
        action="store_true",
        help="Force the full authoritative doctor + real PTY qualification and refresh the certificate",
    )
    parser.add_argument("--full-report", action="store_true", help="Print the complete qualification report")
    parser.add_argument("--web", action="store_true", help="Launch the JARVIS web interface instead of CLI-only mode")
    parser.add_argument("--voice", action="store_true", help="Enable voice mode")
    parser.add_argument("--telegram", action="store_true", help="Start Telegram mode")
    parser.add_argument("--model", default="", help="Override the configured interactive model")
    parser.add_argument("--working-dir", default="", help="Founder working directory for the session")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env_path = Path(args.env_file).expanduser().resolve()
    if not env_path.is_file():
        _emit(
            {
                "ready": False,
                "verdict": "NOT_READY_FOR_DAILY_USE",
                "error": "amaura_environment_missing",
                "env_file": str(env_path),
                "next": "Run: amaura init --build-sandbox",
            }
        )
        return 2

    try:
        from jarvis.amaura.runtime import load_amaura_env

        loaded = load_amaura_env(env_path, override=True, require_private_permissions=True)
        if loaded is None:
            raise RuntimeError(f"Could not load Amaura environment: {env_path}")

        cached: dict[str, Any] | None = None
        cache_reason = "forced_recertification" if args.recertify else ""
        if not args.recertify:
            cached, cache_reason = _load_valid_cache(env_path)

        report: dict[str, Any] | None = None
        if cached is None:
            from jarvis.amaura.local_certification import certify_local_runtime

            report = certify_local_runtime(REPOSITORY_ROOT)
            if report.get("ready") is not True:
                _remove_cache()
                _emit(report)
                return 1
            cached = _write_cache(env_path, report)
            mode = "fresh_certification"
        else:
            mode = "cached_certification"
    except Exception as exc:
        _emit(
            {
                "ready": False,
                "verdict": "NOT_READY_FOR_DAILY_USE",
                "error": type(exc).__name__,
                "message": str(exc),
            }
        )
        return 1

    if args.full_report and report is not None:
        _emit(report)
    else:
        _emit(
            {
                "ready": True,
                "verdict": "READY_FOR_DAILY_USE",
                "mode": mode,
                "cache_reason": cache_reason,
                "head": cached.get("head"),
                "certified_at": cached.get("certified_at"),
                "cache_file": str(_cache_path()),
                "outside_runtime_dirty_entries": cached.get("outside_runtime_dirty_entries", []),
            }
        )

    if args.check_only:
        return 0

    jarvis_argv = _build_jarvis_argv(args)
    os.execv(sys.executable, jarvis_argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
