#!/usr/bin/env python3
"""Bootstrap a hosted-only production profile for Amaura JARVIS.

This migration intentionally removes the legacy Nova/Ollama worker from the
production path. It preserves independent authority secrets, imports an already
exported NVIDIA key into the private Amaura env file, configures distinct hosted
worker/reviewer models, selects the native macOS verifier by default, and creates
an HMAC-authenticated private evaluation pack outside the repository.
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
from jarvis.amaura.runtime import load_amaura_env

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.amaura"
HOSTED_WORKER_MODEL = "meta/llama-3.3-70b-instruct"
HOSTED_REVIEWER_MODEL = "nvidia/nemotron-3-super-120b-a12b"


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
        rendered.append("# Hosted-only production profile (managed by bootstrap_hosted_production.py)")
        for key, value in remaining.items():
            rendered.append(f"{key}={value}")
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


def main() -> int:
    if not ENV_FILE.is_file():
        raise SystemExit(".env.amaura is missing; run ./Install_Amaura.command first")
    ENV_FILE.chmod(0o600)

    # Preserve non-empty process credentials. This matters on a fresh clone where
    # the generated env file intentionally contains no provider secret yet.
    load_amaura_env(ENV_FILE, override=False, require_private_permissions=True)
    current = _read_assignments(ENV_FILE)

    nvidia_key = os.environ.get("NVIDIA_API_KEY", "").strip() or current.get("NVIDIA_API_KEY", "").strip()
    if not nvidia_key:
        raise SystemExit(
            "Hosted production requires NVIDIA_API_KEY. Export the existing key in this terminal and rerun; "
            "JARVIS will not fall back to Nova/Ollama."
        )

    evaluation_key = os.environ.get("AMAURA_EVALUATION_PACK_HMAC_KEY", "").strip()
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
        # Hosted-only Company OS routing.
        "AMAURA_MODEL_MODE": "cloud",
        "AMAURA_LOCAL_MODEL": "",
        "AMAURA_LOCAL_REVIEW_MODEL": "",
        "AMAURA_CLOUD_WORKER_MODEL": HOSTED_WORKER_MODEL,
        "AMAURA_REVIEW_MODE": "cloud",
        "AMAURA_CLOUD_REVIEW_MODEL": HOSTED_REVIEWER_MODEL,
        "AMAURA_DISABLE_CLOUD": "0",
        "NVIDIA_API_KEY": nvidia_key,
        # Hosted executive cognition; no local fallback/probe.
        "AMAURA_JARVIS_PROVIDER": "nvidia",
        "AMAURA_JARVIS_MODEL": HOSTED_WORKER_MODEL,
        "AMAURA_NVIDIA_MODEL": HOSTED_WORKER_MODEL,
        "AMAURA_JARVIS_ALLOW_OLLAMA": "0",
        "AMAURA_JARVIS_OLLAMA_PROBE": "0",
        # Native macOS isolation is the default target-machine verifier.
        "AMAURA_SANDBOX_MODE": "auto",
        "AMAURA_VERIFIER_MODE": "auto",
        # Restore/lock the fail-closed launch posture even if an old env drifted.
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

    # Re-load our persisted profile so evaluation_pack_status sees the exact file
    # values that launchd/doctor will use later.
    load_amaura_env(ENV_FILE, override=True, require_private_permissions=True)
    pack = _ensure_private_eval_pack(eval_path, evaluation_key)

    report = {
        "ok": True,
        "profile": "hosted_nvidia",
        "worker_model": HOSTED_WORKER_MODEL,
        "reviewer_model": HOSTED_REVIEWER_MODEL,
        "local_model_enabled": False,
        "sandbox_mode": "auto",
        "audit_checkpoint": str(checkpoint_path),
        "backup_dir": str(backup_dir),
        "private_evaluation_pack": pack,
        "nvidia_key_persisted": True,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
