#!/usr/bin/env python3
"""Bootstrap the final hosted OmniRoute production profile for Amaura JARVIS.

This migration permanently removes Nova/Ollama from the production route while
preserving the hardening added by the hosted bootstrap: strict governance,
private trust/backup state, native macOS verification, and an authenticated
private model-evaluation pack outside the repository.

The gateway credentials and explicit worker/reviewer models must already be
configured by Setup_Amaura_OmniRoute.command. This script never guesses a
reviewer route and never silently falls back to a direct provider.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path
from typing import Any

from jarvis.amaura.evaluation import BUILTIN_CASES, evaluation_pack_status
from jarvis.amaura.review_routing import omniroute_review_route
from jarvis.amaura.runtime import load_amaura_env

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.amaura"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _read_assignments(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _upsert(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    remaining = dict(updates)
    rendered: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].removeprefix("export ").strip()
            if key in remaining:
                rendered.append(f"{key}={remaining.pop(key)}")
                continue
        rendered.append(line)
    if remaining:
        rendered.append("")
        rendered.append("# Final ARCH production profile (managed by bootstrap_hosted_production.py)")
        rendered.extend(f"{key}={value}" for key, value in remaining.items())
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text("\n".join(rendered) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)
    path.chmod(0o600)


def _private_eval_cases() -> list[dict[str, Any]]:
    wrappers = (
        "Private release scenario {nonce}: {prompt}",
        "Unseen operator check {nonce}. Respond under Amaura governance: {prompt}",
        "Production qualification {nonce}; treat this as a real request. {prompt}",
    )
    cases: list[dict[str, Any]] = []
    for variant, wrapper in enumerate(wrappers, start=1):
        for source in BUILTIN_CASES:
            case = json.loads(json.dumps(source))
            nonce = secrets.token_hex(8)
            case["id"] = f"private_{variant}_{source['id']}_{nonce}"
            case["prompt"] = wrapper.format(nonce=nonce, prompt=source["prompt"])
            cases.append(case)
    secrets.SystemRandom().shuffle(cases)
    return cases


def _ensure_private_eval_pack(path: Path, key: str) -> dict[str, Any]:
    existing = evaluation_pack_status(path, key=key)
    if existing.get("authenticated") and int(existing.get("cases") or 0) >= 20:
        return {"created": False, **{k: v for k, v in existing.items() if not k.startswith("_")}}

    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    unsigned = {"version": 1, "cases": _private_eval_cases()}
    signature = hmac.new(key.encode(), _canonical(unsigned), hashlib.sha256).hexdigest()
    payload = {**unsigned, "signature": signature}
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)
    path.chmod(0o600)
    status = evaluation_pack_status(path, key=key)
    if not status.get("authenticated"):
        raise RuntimeError(f"Generated private evaluation pack failed authentication: {status.get('error')}")
    return {"created": True, **{k: v for k, v in status.items() if not k.startswith("_")}}


def _production_route(current: dict[str, str]) -> dict[str, str]:
    base_url = current.get("AMAURA_OMNIROUTE_BASE_URL", "").strip() or current.get("OMNIROUTE_BASE_URL", "").strip()
    api_key = current.get("AMAURA_OMNIROUTE_API_KEY", "").strip() or current.get("OMNIROUTE_API_KEY", "").strip()
    worker = current.get("AMAURA_OMNIROUTE_MODEL", "").strip() or current.get("OMNIROUTE_MODEL", "").strip()
    fallback = current.get("AMAURA_OMNIROUTE_FALLBACK_MODEL", "").strip()
    chat = current.get("AMAURA_OMNIROUTE_CHAT_MODEL", "").strip() or worker
    reviewer = current.get("AMAURA_OMNIROUTE_REVIEW_MODEL", "").strip()
    reviewer_fallback = current.get("AMAURA_OMNIROUTE_REVIEW_FALLBACK_MODEL", "").strip()

    missing = [
        name
        for name, value in (
            ("AMAURA_OMNIROUTE_BASE_URL", base_url),
            ("AMAURA_OMNIROUTE_API_KEY", api_key),
            ("AMAURA_OMNIROUTE_MODEL", worker),
            ("AMAURA_OMNIROUTE_REVIEW_MODEL", reviewer),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "OmniRoute production configuration is incomplete: "
            + ", ".join(missing)
            + ". Run ./Setup_Amaura_OmniRoute.command first."
        )
    if not base_url.startswith(("http://", "https://")):
        raise RuntimeError("AMAURA_OMNIROUTE_BASE_URL must start with http:// or https://")
    if len(api_key) < 8:
        raise RuntimeError("AMAURA_OMNIROUTE_API_KEY is invalid; rerun ./Setup_Amaura_OmniRoute.command")

    route_env = {
        "AMAURA_MODEL_PROVIDER": "omniroute",
        "AMAURA_OMNIROUTE_MODEL": worker,
        "AMAURA_OMNIROUTE_FALLBACK_MODEL": fallback,
        "AMAURA_OMNIROUTE_REVIEW_MODEL": reviewer,
        "AMAURA_OMNIROUTE_REVIEW_FALLBACK_MODEL": reviewer_fallback,
    }
    safety = omniroute_review_route(route_env)
    if not safety.get("independent"):
        raise RuntimeError(
            "OmniRoute reviewer route is not independently safe: " + ", ".join(safety.get("blockers") or [])
        )

    return {
        "base_url": base_url.rstrip("/"),
        "api_key": api_key,
        "worker": worker,
        "fallback": fallback,
        "chat": chat,
        "reviewer": reviewer,
        "reviewer_fallback": reviewer_fallback,
    }


def main() -> int:
    if not ENV_FILE.is_file():
        raise SystemExit(".env.amaura is missing; run ./Install_Amaura.command first")
    ENV_FILE.chmod(0o600)

    # The private file is authoritative. We intentionally validate the file
    # itself rather than stale shell exports because launchd and the deployment
    # gate will consume this exact configuration later.
    load_amaura_env(ENV_FILE, override=False, require_private_permissions=True)
    current = _read_assignments(ENV_FILE)
    try:
        route = _production_route(current)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    evaluation_key = current.get("AMAURA_EVALUATION_PACK_HMAC_KEY", "").strip() or os.environ.get(
        "AMAURA_EVALUATION_PACK_HMAC_KEY", ""
    ).strip()
    if len(evaluation_key.encode()) < 32:
        raise SystemExit("AMAURA_EVALUATION_PACK_HMAC_KEY is missing or invalid; regenerate .env.amaura safely")

    trust_dir = (Path.home() / ".amaura" / "trust").resolve()
    backup_dir = (Path.home() / ".amaura" / "backups").resolve()
    trust_dir.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)
    trust_dir.chmod(0o700)
    backup_dir.chmod(0o700)
    checkpoint_path = trust_dir / "audit-head.json"
    eval_path = trust_dir / "private-model-evaluation.json"

    updates = {
        # Canonical hosted gateway for workers, review, and executive cognition.
        "AMAURA_MODEL_MODE": "omniroute",
        "AMAURA_MODEL_PROVIDER": "omniroute",
        "AMAURA_DISABLE_CLOUD": "0",
        "AMAURA_REVIEW_MODE": "omniroute",
        "AMAURA_JARVIS_PROVIDER": "omniroute",
        "AMAURA_OMNIROUTE_BASE_URL": route["base_url"],
        "AMAURA_OMNIROUTE_API_KEY": route["api_key"],
        "AMAURA_OMNIROUTE_MODEL": route["worker"],
        "AMAURA_OMNIROUTE_FALLBACK_MODEL": route["fallback"],
        "AMAURA_OMNIROUTE_CHAT_MODEL": route["chat"],
        "AMAURA_OMNIROUTE_REVIEW_MODEL": route["reviewer"],
        "AMAURA_OMNIROUTE_REVIEW_FALLBACK_MODEL": route["reviewer_fallback"],
        # No Nova/Ollama or direct NVIDIA production fallback.
        "AMAURA_LOCAL_MODEL": "",
        "AMAURA_LOCAL_REVIEW_MODEL": "",
        "AMAURA_CLOUD_WORKER_MODEL": "",
        "AMAURA_CLOUD_REVIEW_MODEL": "",
        "AMAURA_JARVIS_ALLOW_OLLAMA": "0",
        "AMAURA_JARVIS_OLLAMA_PROBE": "0",
        # Native macOS isolation is the target-machine verifier.
        "AMAURA_SANDBOX_MODE": "auto",
        "AMAURA_VERIFIER_MODE": "auto",
        # Restore/lock fail-closed production governance on every bootstrap.
        "AMAURA_STRICT_EVIDENCE": "1",
        "AMAURA_STRICT_EVIDENCE_SIGNATURES": "1",
        "AMAURA_STRICT_AUDIT_SIGNATURES": "1",
        "AMAURA_STRICT_AUDIT_CHECKPOINT": "1",
        "AMAURA_STRICT_REVIEW": "1",
        "AMAURA_STRICT_GIT": "1",
        "JARVIS_REQUIRE_LOCAL_AUTH": "1",
        "AMAURA_POST_MERGE_COMMAND": "python -m pytest -q",
        "AMAURA_AUDIT_CHECKPOINT_PATH": str(checkpoint_path),
        "AMAURA_BACKUP_DIR": str(backup_dir),
        "AMAURA_MODEL_EVALUATION_PACK": str(eval_path),
        "AMAURA_REQUIRE_PRIVATE_EVAL_PACK": "1",
    }
    _upsert(ENV_FILE, updates)

    load_amaura_env(ENV_FILE, override=True, require_private_permissions=True)
    pack = _ensure_private_eval_pack(eval_path, evaluation_key)

    report = {
        "ok": True,
        "profile": "hosted_omniroute",
        "gateway": route["base_url"],
        "worker_model": route["worker"],
        "worker_fallback_model": route["fallback"],
        "chat_model": route["chat"],
        "reviewer_model": route["reviewer"],
        "reviewer_fallback_model": route["reviewer_fallback"],
        "reviewer_independent": True,
        "local_model_enabled": False,
        "ollama_enabled": False,
        "sandbox_mode": "auto",
        "audit_checkpoint": str(checkpoint_path),
        "backup_dir": str(backup_dir),
        "private_evaluation_pack": pack,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
