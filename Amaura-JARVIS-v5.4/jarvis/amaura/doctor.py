"""Release certification and operator diagnostics for Amaura.

This module lives inside the installable package so the ``amaura doctor``
command works from any directory.  It performs source, configuration,
database-backup, secret-scan, infrastructure, and live model checks without
relying on repository-only helper scripts.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import tempfile
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
from typing import Any, cast

from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.evaluation import (
    evaluate_cloud_model,
    evaluate_model,
    evaluate_omniroute_model,
    load_evaluation_cases,
)
from jarvis.amaura.readiness import production_readiness

SECRET_PATTERNS = {
    "nvidia_api_key": re.compile(rb"\bnvapi-[A-Za-z0-9_-]{32,}\b"),
    "openai_api_key": re.compile(rb"\bsk-[A-Za-z0-9_-]{32,}\b"),
    "github_token": re.compile(rb"\bgh[opusr]_[A-Za-z0-9]{30,}\b"),
    "gitlab_token": re.compile(rb"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    "google_api_key": re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b"),
    "slack_token": re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "stripe_live_key": re.compile(rb"\bsk_live_[A-Za-z0-9]{20,}\b"),
    "telegram_bot_token": re.compile(rb"\b[0-9]{8,12}:[A-Za-z0-9_-]{30,}\b"),
    "aws_access_key": re.compile(rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "jwt": re.compile(rb"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b"),
    "credentialed_url": re.compile(
        rb"\b(?:https?|postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://[^\s/:@]{2,}:[^\s/@]{8,}@"
    ),
    "generic_secret_assignment": re.compile(
        rb"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|password|secret)"
        rb"\s*[:=]\s*[\"'][A-Za-z0-9_./+=:-]{24,}[\"']"
    ),
}

_IGNORED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".amaura-data",
    ".jarvis-data",
    "dist",
    "build",
}


def _tracked_or_source_files(root: Path) -> Iterable[Path]:
    """Yield source-controlled files, with a safe archive fallback.

    Distributed ZIP files do not contain ``.git``.  The fallback therefore
    excludes local data, virtual environments, caches, and generated outputs.
    """

    try:
        completed = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard", "-z"],
            cwd=root,
            capture_output=True,
            check=True,
            timeout=15,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            if any(part in _IGNORED_PARTS for part in relative.parts):
                continue
            if path.name in {".env.amaura", ".env"}:
                continue
            yield path
        return

    for item in completed.stdout.split(b"\0"):
        if not item:
            continue
        path = root / item.decode("utf-8", errors="surrogateescape")
        if path.is_file():
            if path.name.startswith(".env") and not path.name.endswith(".example"):
                continue
            yield path


def scan_repository(root: str | Path) -> dict[str, Any]:
    """Detect credential-shaped material in distributable source files."""

    repository = Path(root).expanduser().resolve()
    findings: list[dict[str, str]] = []
    scanned = 0
    bytes_scanned = 0
    for path in _tracked_or_source_files(repository):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > 10_000_000:
            continue
        try:
            content = path.read_bytes()
        except OSError:
            continue
        scanned += 1
        bytes_scanned += len(content)
        for kind, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                findings.append(
                    {
                        "path": str(path.relative_to(repository)),
                        "kind": kind,
                    }
                )
    # Code-level release contracts that previously escaped the secret-only
    # scanner. These checks are deliberately simple, deterministic and
    # fail-closed so a regression cannot be certified as security_ok=true.
    jarvis_root = repository / "jarvis"
    if jarvis_root.is_dir():
        for path in jarvis_root.rglob("*.py"):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            relative = str(path.relative_to(repository))
            if ("shell" + "=True") in text or ("shell" + " = True") in text:
                findings.append({"path": relative, "kind": "shell_true_execution"})
            if ("os" + ".system(") in text:
                findings.append({"path": relative, "kind": "os_system_execution"})
            wildcard_double = "host=" + chr(34) + "0.0.0.0" + chr(34)
            wildcard_single = "host=" + chr(39) + "0.0.0.0" + chr(39)
            if wildcard_double in text or wildcard_single in text:
                findings.append({"path": relative, "kind": "hard_coded_wildcard_bind"})
        governance_path = jarvis_root / "amaura" / "tool_governance.py"
        if governance_path.is_file():
            governance = governance_path.read_text(encoding="utf-8", errors="ignore")
            for unsafe_name in ("git_diff", "git_log"):
                read_only_section = governance.split("READ_ONLY_TOOLS", 1)[-1].split("GOVERNED_ONLY_TOOLS", 1)[0]
                if f'"{unsafe_name}"' in read_only_section:
                    findings.append(
                        {
                            "path": str(governance_path.relative_to(repository)),
                            "kind": f"unsafe_read_only_{unsafe_name}",
                        }
                    )
        registry_path = jarvis_root / "tools" / "registry.py"
        if registry_path.is_file():
            registry = registry_path.read_text(encoding="utf-8", errors="ignore")
            if "validate_tool_arguments" not in registry or registry.find("validate_tool_arguments") > registry.find(
                "ALL_DISPATCH[name]"
            ):
                findings.append(
                    {
                        "path": str(registry_path.relative_to(repository)),
                        "kind": "missing_pre_dispatch_schema_validation",
                    }
                )

    unique = sorted({(item["path"], item["kind"]) for item in findings})
    normalized_findings = [{"path": path, "kind": kind} for path, kind in unique]
    return {
        "ok": not normalized_findings,
        "scanner_version": 4,
        "files_scanned": scanned,
        "bytes_scanned": bytes_scanned,
        "patterns_checked": sorted(SECRET_PATTERNS),
        "code_contracts_checked": [
            "no_shell_true",
            "no_os_system",
            "no_hard_coded_wildcard_bind",
            "safe_read_only_allowlist",
            "pre_dispatch_schema_validation",
        ],
        "findings": normalized_findings,
    }


def _backup_restore_probe(control: AmauraControlPlane, directory: Path) -> dict[str, Any]:
    backup_path = control.store.backup(directory / "amaura-backup.db")
    with closing(sqlite3.connect(backup_path)) as restored:
        integrity = restored.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = restored.execute("PRAGMA foreign_key_check").fetchall()
        schema_rows = restored.execute(
            "SELECT name, sql FROM sqlite_master WHERE type IN ('table', 'index') ORDER BY name"
        ).fetchall()
    schema_digest = hashlib.sha256(json.dumps(schema_rows, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return {
        "ok": integrity == "ok" and not foreign_keys,
        "path": str(backup_path),
        "bytes": backup_path.stat().st_size,
        "integrity": integrity,
        "foreign_key_violations": len(foreign_keys),
        "schema_sha256": schema_digest,
    }


def certify_release(
    *,
    repository_root: str | Path | None = None,
    static_only: bool = False,
) -> dict[str, Any]:
    """Run the complete fail-closed release gate and return structured JSON."""

    root = Path(repository_root or Path(__file__).resolve().parents[2]).resolve()
    with tempfile.TemporaryDirectory(prefix="amaura-release-gate-") as directory:
        temp_root = Path(directory)
        control = AmauraControlPlane(
            temp_root / "amaura.db",
            audit_checkpoint_path=temp_root / "audit-head.json",
        )
        try:
            readiness = production_readiness(control, live=not static_only)
            backup_restore = _backup_restore_probe(control, temp_root)
        finally:
            control.close()

    security = scan_repository(root)
    evaluations: list[dict[str, Any]] = []
    evaluation_status = "skipped_static"
    require_private_pack = os.environ.get("AMAURA_REQUIRE_PRIVATE_EVAL_PACK", "1") == "1"
    evaluation_pack: dict[str, Any] = {
        "configured": False,
        "authenticated": False,
        "source": "builtin_public_smoke",
        "cases": 0,
        "error": "",
    }
    expected_routes: list[dict[str, str]] = []
    if not static_only:
        try:
            cases, evaluation_pack = load_evaluation_cases(require_private=require_private_pack)
        except Exception as exc:
            cases = ()
            evaluation_status = "invalid_evaluation_pack"
            evaluation_pack = {
                "configured": bool(os.environ.get("AMAURA_MODEL_EVALUATION_PACK", "").strip()),
                "authenticated": False,
                "source": os.environ.get("AMAURA_MODEL_EVALUATION_PACK", ""),
                "cases": 0,
                "error": str(exc),
            }
        else:
            model_provider = os.environ.get("AMAURA_MODEL_PROVIDER", "").strip().lower()
            omniroute_key = (
                os.environ.get("AMAURA_OMNIROUTE_API_KEY", "").strip()
                or os.environ.get("OMNIROUTE_API_KEY", "").strip()
            )
            omniroute_url = (
                os.environ.get("AMAURA_OMNIROUTE_BASE_URL", "").strip()
                or os.environ.get("OMNIROUTE_BASE_URL", "").strip()
            )
            omniroute_model = (
                os.environ.get("AMAURA_OMNIROUTE_MODEL", "").strip() or os.environ.get("OMNIROUTE_MODEL", "").strip()
            )

            if model_provider == "omniroute" or bool(omniroute_key and omniroute_url and omniroute_model):
                expected_routes.append(
                    {"role": "worker", "provider": "omniroute", "model": omniroute_model or "omniroute"}
                )
            else:
                model_mode = os.environ.get("AMAURA_MODEL_MODE", "local").strip().lower()
                review_mode = os.environ.get("AMAURA_REVIEW_MODE", "local").strip().lower()
                local_worker = os.environ.get("AMAURA_LOCAL_MODEL", "").strip()
                cloud_worker = os.environ.get("AMAURA_CLOUD_WORKER_MODEL", "").strip()
                local_reviewer = os.environ.get("AMAURA_LOCAL_REVIEW_MODEL", "").strip()
                cloud_reviewer = os.environ.get("AMAURA_CLOUD_REVIEW_MODEL", "").strip()
                if model_mode in {"local", "balanced"} and local_worker:
                    expected_routes.append({"role": "worker", "provider": "ollama", "model": local_worker})
                if model_mode in {"balanced", "cloud"} and cloud_worker:
                    expected_routes.append({"role": "worker", "provider": "nvidia", "model": cloud_worker})
                if review_mode == "local" and local_reviewer:
                    expected_routes.append({"role": "reviewer", "provider": "ollama", "model": local_reviewer})
                if review_mode == "cloud" and cloud_reviewer:
                    expected_routes.append({"role": "reviewer", "provider": "nvidia", "model": cloud_reviewer})

            unique_routes: list[dict[str, str]] = []
            seen: set[tuple[str, str]] = set()
            for route in expected_routes:
                identity = (route["provider"], route["model"])
                if identity not in seen:
                    seen.add(identity)
                    unique_routes.append(route)
            expected_routes = unique_routes

            details = readiness.get("details")
            details_map = cast(dict[str, Any], details) if isinstance(details, dict) else {}
            live = details_map.get("live")
            live_map = cast(dict[str, Any], live) if isinstance(live, dict) else {}
            ollama = live_map.get("ollama")
            ollama_map = cast(dict[str, Any], ollama) if isinstance(ollama, dict) else {}
            models = ollama_map.get("models")
            installed_local_models = {str(model) for model in models} if isinstance(models, list) else set()
            missing_routes: list[str] = []
            for route in expected_routes:
                if route["provider"] == "omniroute":
                    if not bool(omniroute_key and omniroute_url and omniroute_model):
                        missing_routes.append(f"omniroute:{route['model']}")
                elif route["provider"] == "ollama" and route["model"] not in installed_local_models:
                    missing_routes.append(f"ollama:{route['model']}")
                elif route["provider"] == "nvidia":
                    key_name = "NVIDIA_REVIEW_API_KEY" if route["role"] == "reviewer" else "NVIDIA_API_KEY"
                    key = os.environ.get(key_name, "").strip()
                    if route["role"] == "reviewer" and not key:
                        key = os.environ.get("NVIDIA_API_KEY", "").strip()
                    if not key:
                        missing_routes.append(f"nvidia:{route['model']}")
            if not expected_routes or missing_routes:
                evaluation_status = "skipped_unavailable_prerequisites"
                evaluation_pack["missing_routes"] = missing_routes
            else:
                evaluation_status = "completed"
                ollama_url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
                for route in expected_routes:
                    if route["provider"] == "omniroute":
                        result = evaluate_omniroute_model(route["model"], cases=cases)
                    elif route["provider"] == "ollama":
                        result = evaluate_model(route["model"], base_url=ollama_url, cases=cases)
                    else:
                        key_name = "NVIDIA_REVIEW_API_KEY" if route["role"] == "reviewer" else "NVIDIA_API_KEY"
                        api_key = os.environ.get(key_name, "").strip()
                        if route["role"] == "reviewer" and not api_key:
                            api_key = os.environ.get("NVIDIA_API_KEY", "").strip()
                        result = evaluate_cloud_model(route["model"], api_key=api_key, cases=cases)
                    evaluations.append({**result.to_dict(), "role": route["role"]})

    model_gate = (
        True
        if static_only
        else (
            evaluation_status == "completed"
            and len(evaluations) == len(expected_routes)
            and bool(evaluations)
            and all(bool(item.get("ready")) for item in evaluations)
            and (not require_private_pack or bool(evaluation_pack.get("authenticated")))
        )
    )
    source_certified = bool(readiness["source_certified"]) and bool(security["ok"]) and bool(backup_restore["ok"])
    if os.environ.get("AMAURA_RELEASE_GATE_DEBUG") == "1" and not source_certified:
        print(
            "AMAURA_RELEASE_GATE_DEBUG",
            {
                "readiness": readiness.get("source_certified"),
                "source_blockers": readiness.get("source_blockers"),
                "security": security,
                "backup_restore": backup_restore,
            },
            flush=True,
        )
    production_ready = source_certified and not static_only and bool(readiness["ready"]) and model_gate
    raw_blockers = readiness.get("blockers")
    blockers = [str(item) for item in raw_blockers] if isinstance(raw_blockers, list) else []
    if not security["ok"]:
        blockers.append("repository_secret_scan")
    if not backup_restore["ok"]:
        blockers.append("backup_restore_probe")
    if not model_gate and not static_only:
        blockers.append("live_model_evaluation")

    return {
        "ready": production_ready,
        "source_certified": source_certified,
        "production_ready": production_ready,
        "mode": "static" if static_only else "production",
        "blockers": sorted(set(blockers)),
        "readiness": readiness,
        "security": security,
        "backup_restore": backup_restore,
        "model_evaluation": {
            "status": evaluation_status,
            "ready": model_gate,
            "expected_routes": expected_routes,
            "pack": evaluation_pack,
            "results": evaluations,
        },
    }


__all__ = ["certify_release", "scan_repository"]
