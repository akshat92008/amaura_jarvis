"""Truthful static and live readiness checks for the Amaura workforce."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jarvis.amaura.capabilities import EXECUTABLE_EMPLOYEE_TOOLS
from jarvis.amaura.prompts import load_prompt_catalogue
from jarvis.amaura.registry import ALL_AGENTS
from jarvis.amaura.resources import CapabilityRouter
from jarvis.amaura.review_routing import effective_review_mode, omniroute_review_route
from jarvis.amaura.workflows import WORKFLOWS
from jarvis.network_security import MIN_API_KEY_LENGTH, is_loopback_host

if TYPE_CHECKING:
    from jarvis.amaura.control_plane import AmauraControlPlane


@dataclass(frozen=True, slots=True)
class Integration:
    name: str
    kind: str
    probe: str
    configured: bool = False


OPTIONAL_INTEGRATIONS = (
    Integration("PydanticAI", "python", "pydantic_ai"),
    Integration("LangGraph", "python", "langgraph"),
    Integration("DBOS", "python", "dbos"),
    Integration("LiteLLM", "python", "litellm"),
    Integration("OpenTelemetry", "python", "opentelemetry"),
    Integration("FFmpeg", "binary", "ffmpeg"),
    Integration("Crawl4AI", "python", "crawl4ai"),
    Integration("OBS", "binary", "obs"),
    Integration("Promptfoo", "binary", "promptfoo"),
)


def _integration_status(integration: Integration) -> dict[str, object]:
    available = (
        importlib.util.find_spec(integration.probe) is not None
        if integration.kind == "python"
        else shutil.which(integration.probe) is not None
    )
    return {**asdict(integration), "available": available}


def _configured_secret(name: str, *, minimum: int = 32) -> bool:
    value = os.environ.get(name, "")
    placeholders = (
        "replace-",
        "changeme",
        "example",
        "your-",
    )
    return len(value.encode()) >= minimum and not value.lower().startswith(placeholders)


def _probe_ollama(
    base_url: str,
    *,
    worker_model: str,
    reviewer_model: str,
) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/tags",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=2.0) as response:
            payload = json.loads(response.read(1_000_000).decode())
        names = {
            str(item.get("name", "")).split(":latest", 1)[0]
            for item in payload.get("models", [])
            if isinstance(item, dict)
        }
        return {
            "reachable": True,
            "worker_model_installed": worker_model in names,
            "reviewer_model_installed": reviewer_model in names,
            "models": sorted(names),
            "error": "",
        }
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        urllib.error.URLError,
    ) as exc:
        return {
            "reachable": False,
            "worker_model_installed": False,
            "reviewer_model_installed": False,
            "models": [],
            "error": type(exc).__name__,
        }


def _probe_omniroute() -> dict[str, Any]:
    """Safe OmniRoute health probe — never exposes API keys in returned data."""
    import time as _time

    key = os.environ.get("AMAURA_OMNIROUTE_API_KEY", "").strip() or os.environ.get("OMNIROUTE_API_KEY", "").strip()
    base_url = (
        os.environ.get("AMAURA_OMNIROUTE_BASE_URL", "").strip() or os.environ.get("OMNIROUTE_BASE_URL", "").strip()
    ).rstrip("/")
    model = os.environ.get("AMAURA_OMNIROUTE_MODEL", "").strip() or os.environ.get("OMNIROUTE_MODEL", "").strip()
    fallback = os.environ.get("AMAURA_OMNIROUTE_FALLBACK_MODEL", "").strip()

    if not key or not base_url:
        return {
            "configured": False,
            "reachable": False,
            "status": "BLOCKED",
            "reason": "AMAURA_OMNIROUTE_API_KEY or AMAURA_OMNIROUTE_BASE_URL not set",
            "model": model or "(unset)",
            "fallback_model": fallback or "none",
            "latency_ms": 0,
            "error": "missing_configuration",
        }

    endpoint = f"{base_url}/models"
    req = urllib.request.Request(
        endpoint,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "User-Agent": "Amaura-JARVIS/5.4.3-preflight",
        },
        method="GET",
    )
    t0 = _time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            latency_ms = int((_time.monotonic() - t0) * 1000)
            raw = resp.read(65536).decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
            available_models = [
                str(m.get("id") or m.get("name") or "") for m in (data.get("data") or []) if isinstance(m, dict)
            ]
        except (json.JSONDecodeError, AttributeError):
            available_models = []
        return {
            "configured": True,
            "reachable": True,
            "status": "READY",
            "reason": "",
            "model": model or "(unset)",
            "fallback_model": fallback or "none",
            "latency_ms": latency_ms,
            "available_models": available_models[:20],
            "error": "",
        }
    except urllib.error.HTTPError as exc:
        latency_ms = int((_time.monotonic() - t0) * 1000)
        code = exc.code
        if code in (401, 403):
            error = "authentication_failure"
        elif code == 429:
            error = "rate_limited"
        elif code in (502, 503, 504):
            error = "provider_unavailable"
        else:
            error = f"http_{code}"
        return {
            "configured": True,
            "reachable": code not in (401, 403),
            "status": "BLOCKED",
            "reason": error,
            "model": model or "(unset)",
            "fallback_model": fallback or "none",
            "latency_ms": latency_ms,
            "error": error,
        }
    except Exception as exc:
        latency_ms = int((_time.monotonic() - t0) * 1000)
        return {
            "configured": True,
            "reachable": False,
            "status": "BLOCKED",
            "reason": type(exc).__name__,
            "model": model or "(unset)",
            "fallback_model": fallback or "none",
            "latency_ms": latency_ms,
            "error": type(exc).__name__,
        }


def _probe_docker(image: str) -> dict[str, Any]:
    binary = shutil.which("docker")
    if not binary:
        return {
            "installed": False,
            "healthy": False,
            "image_available": False,
            "image_smoke": False,
            "error": "not_installed",
        }
    try:
        daemon = subprocess.run(
            [binary, "info", "--format", "{{json .ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "installed": True,
            "healthy": False,
            "image_available": False,
            "image_smoke": False,
            "error": type(exc).__name__,
        }
    if daemon.returncode != 0:
        return {
            "installed": True,
            "healthy": False,
            "image_available": False,
            "image_smoke": False,
            "error": "daemon_unavailable",
        }
    try:
        inspected = subprocess.run(
            [binary, "image", "inspect", image],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if inspected.returncode != 0:
            return {
                "installed": True,
                "healthy": True,
                "image_available": False,
                "image_smoke": False,
                "error": "sandbox_image_missing",
            }
        smoke = subprocess.run(
            [
                binary,
                "run",
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=128m",
                image,
                "sh",
                "-lc",
                (
                    "python --version && python -m pytest --version && "
                    "ruff --version && mypy --version && node --version && "
                    "npm --version && git --version && rg --version"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "installed": True,
            "healthy": True,
            "image_available": True,
            "image_smoke": False,
            "error": type(exc).__name__,
        }
    return {
        "installed": True,
        "healthy": True,
        "image_available": True,
        "image_smoke": smoke.returncode == 0,
        "error": "" if smoke.returncode == 0 else "sandbox_image_smoke_failed",
        "smoke_stdout": smoke.stdout[-2000:],
        "smoke_stderr": smoke.stderr[-2000:],
    }


def production_readiness(
    control: AmauraControlPlane,
    *,
    live: bool = True,
) -> dict[str, object]:
    operator_key = os.environ.get("AMAURA_OPERATOR_KEY", "")
    approval_key = os.environ.get("AMAURA_APPROVAL_KEY", "")
    host = os.environ.get("JARVIS_HOST", "127.0.0.1")
    jarvis_key = os.environ.get("JARVIS_API_KEY", "")
    model_mode = os.environ.get("AMAURA_MODEL_MODE", "local").strip().lower()
    worker_model = os.environ.get("AMAURA_LOCAL_MODEL", "").strip()
    cloud_worker_model = os.environ.get("AMAURA_CLOUD_WORKER_MODEL", "").strip()
    cloud_worker_key = (
        os.environ.get("NVIDIA_WORKER_API_KEY", "").strip() or os.environ.get("NVIDIA_API_KEY", "").strip()
    )
    reviewer_model = os.environ.get("AMAURA_LOCAL_REVIEW_MODEL", "").strip()
    review_mode = effective_review_mode()
    cloud_review_model = os.environ.get("AMAURA_CLOUD_REVIEW_MODEL", "").strip()
    cloud_review_key = (
        os.environ.get("NVIDIA_REVIEW_API_KEY", "").strip() or os.environ.get("NVIDIA_API_KEY", "").strip()
    )
    sandbox_mode = os.environ.get("AMAURA_SANDBOX_MODE", "docker").strip().lower()
    sandbox_digest = os.environ.get("AMAURA_SANDBOX_IMAGE_DIGEST", "").strip().lower()
    data_dir = Path(os.environ.get("AMAURA_DATA_DIR", str(control.store.db_path.parent))).expanduser().resolve()
    checkpoint_value = os.environ.get("AMAURA_AUDIT_CHECKPOINT_PATH", "").strip()
    checkpoint_path = Path(checkpoint_value).expanduser().resolve() if checkpoint_value else None
    telegram_user = os.environ.get("TELEGRAM_USER_ID", "").strip()
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    from jarvis.amaura.auth import reviewer_credentials
    from jarvis.amaura.models import GovernanceError

    try:
        reviewer_key_items = reviewer_credentials()
        reviewer_key_config_valid = bool(reviewer_key_items)
    except GovernanceError:
        reviewer_key_items = ()
        reviewer_key_config_valid = False
    prompts = load_prompt_catalogue()
    database = control.store.integrity_check()
    static_dir = Path(__file__).resolve().parents[1] / "static"
    app_js = (static_dir / "app.js").read_text(encoding="utf-8") if (static_dir / "app.js").is_file() else ""
    index_html = (
        (static_dir / "index.html").read_text(encoding="utf-8") if (static_dir / "index.html").is_file() else ""
    )
    dockerfile = Path(__file__).resolve().parents[2] / "docker" / "amaura-sandbox.Dockerfile"
    dockerfile_text = dockerfile.read_text(encoding="utf-8") if dockerfile.is_file() else ""

    declared_tools = {tool for agent in ALL_AGENTS for tool in agent.tools}
    from jarvis.amaura.tool_governance import legacy_tool_mode, unsafe_legacy_tools_exposed
    from jarvis.tools.registry import ALL_TOOL_DEFINITIONS

    tool_schema_names = [definition["function"]["name"] for definition in ALL_TOOL_DEFINITIONS]
    resource_inventory = CapabilityRouter().inventory()
    missing_tools = sorted(declared_tools - EXECUTABLE_EMPLOYEE_TOOLS)
    duplicate_agents = len(ALL_AGENTS) != len({agent.agent_id for agent in ALL_AGENTS})
    invalid_reviewers = sorted(
        agent.agent_id
        for agent in ALL_AGENTS
        if agent.agent_id != "jarvis" and agent.reviewer_id not in {"founder", *{item.agent_id for item in ALL_AGENTS}}
    )
    from jarvis.amaura.policy import PolicyEngine

    invalid_permission_agents = [
        agent.agent_id for agent in ALL_AGENTS if not PolicyEngine.validate_employee_permissions(agent.agent_id).allowed
    ]
    source_checks = {
        "database_integrity": bool(database["ok"]),
        "tamper_evident_audit_chain": bool(database["audit_chain"]["ok"]),
        "workforce_registry": len(ALL_AGENTS) >= 57 and not duplicate_agents,
        "workforce_tool_contract": not missing_tools,
        "workforce_permission_contract": not invalid_permission_agents,
        "reviewer_contract": not invalid_reviewers,
        "workflow_catalogue": {
            "client_acquisition",
            "content_factory",
            "software_delivery",
            "company_operating_review",
            "product_discovery",
            "incident_response",
        }.issubset(WORKFLOWS)
        and len(WORKFLOWS) >= 21,
        "founder_prompt_catalogue": len(prompts) >= 57 and all(len(prompt) > 500 for prompt in prompts.values()),
        "durable_supervisor_store": isinstance(
            control.store.execution_status(),
            dict,
        ),
        "unique_tool_schemas": len(tool_schema_names) == len(set(tool_schema_names)),
        "free_first_resource_catalogue": any(
            item["key"] == "nvidia_api" and item["tier"] == "free_api" for item in resource_inventory
        )
        and any(item["key"] == "antigravity" and item["mode"] == "manual_handoff" for item in resource_inventory),
        "legacy_direct_execution_disabled": (
            os.environ.get("JARVIS_ENABLE_LEGACY_DIRECT_TOOLS", "0") != "1"
            and legacy_tool_mode() != "full"
            and not unsafe_legacy_tools_exposed(tool_schema_names)
        ),
        "single_configuration_boundary": all(
            marker not in (Path(__file__).resolve().parents[1] / "api.py").read_text(encoding="utf-8")
            for marker in ("~/Desktop/JARVIS", "aimodel/config.json")
        ),
        "governed_crm_outbox": (
            hasattr(control.acquisition, "update_crm")
            and "enqueue_outbox_event" in Path(__file__).with_name("pipeline.py").read_text(encoding="utf-8")
        ),
        "leased_outbox_delivery": all(
            hasattr(control.store, name)
            for name in (
                "claim_outbox_events",
                "recover_expired_outbox_events",
                "resolve_outbox_reconciliation",
            )
        ),
        "provenance_bound_evidence": control.evidence.root.is_dir() and hasattr(control.evidence, "_manifest_path"),
        "hud_assets_packaged": all((static_dir / name).is_file() for name in ("index.html", "app.js", "styles.css")),
        "hud_xss_hardened": "marked.parse(content)" not in app_js
        and "renderSafeMarkdown(content)" in app_js
        and "https://cdn.jsdelivr.net" not in index_html,
        "dns_pinned_transport": "_PinnedHTTPSConnection"
        in Path(__file__).with_name("network.py").read_text(encoding="utf-8"),
        "durable_telemetry": isinstance(control.telemetry.snapshot(), dict),
        "sandbox_fail_closed": sandbox_mode in {"docker", "native", "macos", "auto"}
        or (sandbox_mode == "host" and os.environ.get("AMAURA_ALLOW_HOST_EXECUTION") == "1"),
        "sandbox_toolchain_contract": all(
            token in dockerfile_text
            for token in (
                "python:3.12-slim-bookworm",
                "node:22-bookworm-slim",
                "git",
                "ripgrep",
                "pytest==",
                "ruff==",
                "mypy==",
                "USER 10001:10001",
            )
        ),
    }
    nvidia_worker_key = bool(os.environ.get("NVIDIA_API_KEY", "").strip())
    balanced_worker_key = bool(nvidia_worker_key or os.environ.get("GROQ_API_KEY", "").strip())
    omniroute_key_present = bool(
        os.environ.get("AMAURA_OMNIROUTE_API_KEY", "").strip() or os.environ.get("OMNIROUTE_API_KEY", "").strip()
    )
    model_routing_valid = (
        (model_mode == "local" and bool(worker_model))
        or (model_mode == "balanced" and bool(worker_model) and bool(cloud_worker_model) and balanced_worker_key)
        or (model_mode == "cloud" and bool(cloud_worker_model) and nvidia_worker_key)
        or (
            omniroute_key_present
            and bool(
                os.environ.get("AMAURA_OMNIROUTE_BASE_URL", "").strip()
                or os.environ.get("OMNIROUTE_BASE_URL", "").strip()
            )
        )
    )
    from jarvis.amaura.evaluation import evaluation_pack_status

    require_private_eval = os.environ.get("AMAURA_REQUIRE_PRIVATE_EVAL_PACK", "1") == "1"
    private_eval_status = (
        evaluation_pack_status()
        if require_private_eval
        else {"authenticated": True, "configured": False, "cases": len(())}
    )
    gmail_static = bool(os.environ.get("AMAURA_GMAIL_ACCESS_TOKEN", "").strip())
    gmail_refresh = all(
        bool(os.environ.get(name, "").strip())
        for name in ("AMAURA_GMAIL_CLIENT_ID", "AMAURA_GMAIL_CLIENT_SECRET", "AMAURA_GMAIL_REFRESH_TOKEN")
    )
    n8n_enabled = os.environ.get("AMAURA_ENABLE_N8N", os.environ.get("USE_N8N", "0")) == "1"
    omniroute_review = omniroute_review_route()
    omniroute_review_independent = bool(omniroute_review["independent"]) and os.environ.get(
        "AMAURA_STRICT_REVIEW", "0"
    ) == "1"

    configuration_checks = {
        "model_routing_valid": model_routing_valid,
        "review_mode_valid": review_mode in {"local", "cloud", "omniroute"},
        "distinct_reviewer_model": (
            omniroute_review_independent
            if review_mode == "omniroute"
            else (
                bool(reviewer_model) and reviewer_model != worker_model
                if review_mode == "local"
                else bool(
                    cloud_review_model
                    and cloud_review_key
                    and cloud_review_model not in {cloud_worker_model, worker_model}
                )
            )
        ),
        "reviewer_route_independence": (
            omniroute_review_independent
            if review_mode == "omniroute"
            else True
        ),
        "operator_key": _configured_secret("AMAURA_OPERATOR_KEY", minimum=24),
        "approval_key": _configured_secret("AMAURA_APPROVAL_KEY", minimum=24),
        "reviewer_identity_keys": reviewer_key_config_valid,
        "review_attestation_key": _configured_secret("AMAURA_REVIEW_ATTESTATION_KEY"),
        "provider_receipt_key": _configured_secret("AMAURA_PROVIDER_RECEIPT_KEY"),
        "audit_hmac_key": _configured_secret("AMAURA_AUDIT_HMAC_KEY"),
        "evidence_hmac_key": _configured_secret("AMAURA_EVIDENCE_HMAC_KEY"),
        "evaluation_pack_hmac_key": (not require_private_eval or _configured_secret("AMAURA_EVALUATION_PACK_HMAC_KEY")),
        "private_model_evaluation_pack": (not require_private_eval or bool(private_eval_status.get("authenticated"))),
        "audit_checkpoint_path": checkpoint_path is not None,
        "audit_checkpoint_separated": (
            checkpoint_path is not None and checkpoint_path != data_dir and data_dir not in checkpoint_path.parents
        ),
        "keys_are_separate": len(
            {
                operator_key,
                approval_key,
                os.environ.get("AMAURA_REVIEW_ATTESTATION_KEY", ""),
                os.environ.get("AMAURA_PROVIDER_RECEIPT_KEY", ""),
                os.environ.get("AMAURA_AUDIT_HMAC_KEY", ""),
                os.environ.get("AMAURA_EVIDENCE_HMAC_KEY", ""),
                os.environ.get("AMAURA_EVALUATION_PACK_HMAC_KEY", "") if require_private_eval else "",
                *[item.key for item in reviewer_key_items],
            }
            - {""}
        )
        == (7 if require_private_eval else 6) + len(reviewer_key_items),
        "loopback_binding": is_loopback_host(host),
        "remote_api_auth": is_loopback_host(host) or len(jarvis_key) >= MIN_API_KEY_LENGTH,
        "telegram_founder_bound": not telegram_token or bool(telegram_user),
        "experimental_langgraph_disabled": os.environ.get("AMAURA_ENABLE_EXPERIMENTAL_LANGGRAPH", "0") != "1",
        "strict_evidence_mode": os.environ.get("AMAURA_STRICT_EVIDENCE", "0") == "1",
        "strict_evidence_signatures": os.environ.get("AMAURA_STRICT_EVIDENCE_SIGNATURES", "0") == "1",
        "strict_audit_signatures": os.environ.get("AMAURA_STRICT_AUDIT_SIGNATURES", "0") == "1",
        "strict_audit_checkpoint": os.environ.get("AMAURA_STRICT_AUDIT_CHECKPOINT", "0") == "1",
        "local_tool_api_auth": (
            os.environ.get("JARVIS_REQUIRE_LOCAL_AUTH", "1") == "1" and len(jarvis_key) >= MIN_API_KEY_LENGTH
        ),
        "strict_review_mode": os.environ.get("AMAURA_STRICT_REVIEW", "0") == "1",
        "strict_git_mode": os.environ.get("AMAURA_STRICT_GIT", "0") == "1",
        "post_merge_validation": bool(os.environ.get("AMAURA_POST_MERGE_COMMAND", "").strip()),
        "sandbox_image_pinned": (
            True
            if sandbox_mode in {"native", "macos"} or (sandbox_mode == "auto" and sys.platform == "darwin")
            else (
                sandbox_digest.startswith("sha256:")
                and len(sandbox_digest) == 71
                and all(character in "0123456789abcdef" for character in sandbox_digest[7:])
            )
        ),
        "outbox_attempt_policy": int(os.environ.get("AMAURA_OUTBOX_MAX_ATTEMPTS", "3")) >= 1,
        "gmail_adapter": (os.environ.get("AMAURA_ENABLE_GMAIL") != "1" or gmail_static or gmail_refresh),
        "imessage_adapter": (
            os.environ.get("AMAURA_ENABLE_IMESSAGE") != "1"
            or (
                sys.platform == "darwin"
                and shutil.which("osascript") is not None
                and os.environ.get("AMAURA_IMESSAGE_PROVIDER", "local").strip().lower() == "local"
            )
        ),
        "n8n_adapter": (
            not n8n_enabled
            or bool(
                os.environ.get("N8N_BASE_URL", "").strip()
                and os.environ.get("N8N_API_KEY", "").strip()
                and os.environ.get("N8N_WEBHOOK_CRM", "").strip()
            )
        ),
        "private_publication_adapter": (
            os.environ.get("AMAURA_ENABLE_PUBLICATION") != "1"
            or bool(
                os.environ.get("AMAURA_PUBLICATION_ENDPOINT", "")
                and os.environ.get("AMAURA_PUBLICATION_ACCESS_TOKEN", "")
            )
        ),
        "public_publication_adapter": (
            os.environ.get("AMAURA_ENABLE_PUBLIC_PUBLISH") != "1"
            or (
                os.environ.get("AMAURA_ENABLE_PUBLICATION") == "1"
                and bool(
                    os.environ.get("AMAURA_PUBLIC_PUBLISH_ENDPOINT", "")
                    and os.environ.get("AMAURA_PUBLIC_PUBLISH_ACCESS_TOKEN", "")
                )
            )
        ),
    }

    backup_dir = Path(
        os.environ.get(
            "AMAURA_BACKUP_DIR",
            str(control.store.db_path.parent / "backups"),
        )
    ).expanduser()
    backup_parent = backup_dir if backup_dir.exists() else backup_dir.parent
    configuration_checks["backup_destination_writable"] = backup_parent.exists() and os.access(backup_parent, os.W_OK)
    resolved_backup_dir = backup_dir.resolve()
    configuration_checks["backup_destination_separated"] = (
        resolved_backup_dir != data_dir and data_dir not in resolved_backup_dir.parents
    )

    omniroute_key = (
        os.environ.get("AMAURA_OMNIROUTE_API_KEY", "").strip() or os.environ.get("OMNIROUTE_API_KEY", "").strip()
    )
    omniroute_url = (
        os.environ.get("AMAURA_OMNIROUTE_BASE_URL", "").strip() or os.environ.get("OMNIROUTE_BASE_URL", "").strip()
    )
    omniroute_model = (
        os.environ.get("AMAURA_OMNIROUTE_MODEL", "").strip() or os.environ.get("OMNIROUTE_MODEL", "").strip()
    )
    omniroute_configured = bool(omniroute_key and omniroute_url and omniroute_model)

    live_details: dict[str, Any]
    if live:
        ollama = _probe_ollama(
            os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"),
            worker_model=worker_model,
            reviewer_model=reviewer_model,
        )
        docker = _probe_docker(sandbox_digest or os.environ.get("AMAURA_SANDBOX_IMAGE", "amaura-sandbox:3.6.0"))
        verifier_mode = os.environ.get("AMAURA_VERIFIER_MODE", "auto").strip().lower()
        if verifier_mode == "auto":
            effective_verifier = (
                "macos_native"
                if (sys.platform == "darwin" and shutil.which("sandbox-exec"))
                else ("docker" if shutil.which("docker") else "host")
            )
        else:
            effective_verifier = verifier_mode

        docker["effective_verifier"] = effective_verifier
        docker["required"] = sandbox_mode == "docker" or verifier_mode == "docker"

        native_verifier_healthy = bool(sys.platform == "darwin" and shutil.which("sandbox-exec"))
        effective_verifier_healthy = (
            docker["healthy"]
            if effective_verifier == "docker"
            else (
                native_verifier_healthy
                if effective_verifier in {"native", "macos_native", "macos"}
                else (os.environ.get("AMAURA_ALLOW_HOST_EXECUTION") == "1")
            )
        )

        omniroute = (
            _probe_omniroute()
            if omniroute_configured
            else {
                "configured": False,
                "reachable": False,
                "status": "BLOCKED",
                "reason": "not_configured",
                "model": omniroute_model or "(unset)",
                "fallback_model": "none",
                "latency_ms": 0,
                "error": "missing_configuration",
            }
        )
        live_checks = {
            "ollama_reachable": ollama["reachable"]
            if model_mode in {"local", "balanced"} and not omniroute_configured
            else True,
            "worker_model_installed": (
                True
                if omniroute_configured
                else (ollama["worker_model_installed"] if model_mode in {"local", "balanced"} else True)
            ),
            "reviewer_model_installed": (
                True
                if omniroute_configured
                else (ollama["reviewer_model_installed"] if review_mode == "local" else True)
            ),
            "cloud_worker_configured": (
                True
                if (model_mode == "local" or omniroute_configured)
                else bool(cloud_worker_model and cloud_worker_key)
            ),
            "cloud_reviewer_configured": (
                True
                if (review_mode == "local" or omniroute_configured)
                else bool(cloud_review_model and cloud_review_key)
            ),
            "docker_healthy": docker["healthy"]
            if (sandbox_mode == "docker" or verifier_mode == "docker")
            else effective_verifier_healthy,
            "sandbox_image_available": docker["image_available"]
            if (sandbox_mode == "docker" or verifier_mode == "docker")
            else True,
            "sandbox_image_smoke": docker["image_smoke"]
            if (sandbox_mode == "docker" or verifier_mode == "docker")
            else True,
        }
        live_details = {"ollama": ollama, "docker": docker, "omniroute": omniroute}
    else:
        live_checks = {}
        live_details = {"skipped": True}

    all_checks = {
        **source_checks,
        **configuration_checks,
        **live_checks,
    }
    blockers = [name for name, passed in all_checks.items() if not passed]
    source_blockers = [name for name, passed in source_checks.items() if not passed]
    from jarvis.amaura.antigravity_bridge import AntigravityDeliveryAdapter

    antigravity_status = AntigravityDeliveryAdapter().readiness()
    return {
        "ready": not blockers,
        "production_ready": not blockers,
        "source_certified": not source_blockers,
        "source_ready": not source_blockers,
        "core_operational": all(
            source_checks[name]
            for name in (
                "database_integrity",
                "tamper_evident_audit_chain",
                "workforce_registry",
                "workforce_tool_contract",
                "reviewer_contract",
                "workflow_catalogue",
                "founder_prompt_catalogue",
                "durable_supervisor_store",
                "leased_outbox_delivery",
            )
        ),
        "checks": all_checks,
        "source_checks": source_checks,
        "configuration_checks": configuration_checks,
        "live_checks": live_checks,
        "blockers": blockers,
        "source_blockers": source_blockers,
        "details": {
            "missing_employee_tools": missing_tools,
            "invalid_reviewers": invalid_reviewers,
            "live": live_details,
            "resources": resource_inventory,
            "antigravity_governed_backend": antigravity_status,
            "invalid_permission_agents": invalid_permission_agents,
            "private_evaluation_pack": private_eval_status,
            "reviewer_route": omniroute_review if review_mode == "omniroute" else {"mode": review_mode},
        },
        "optional_integrations": [_integration_status(item) for item in OPTIONAL_INTEGRATIONS],
        "note": (
            "Optional adapters are reported separately. Production readiness "
            "passes only when source, configuration, models, and isolation are real."
        ),
    }


INTEGRATIONS = OPTIONAL_INTEGRATIONS

__all__ = ["INTEGRATIONS", "OPTIONAL_INTEGRATIONS", "production_readiness"]
