#!/usr/bin/env python3
"""Read-only final-target preflight for the single persistent ARCH runtime.

This script never starts, stops, installs, or mutates ARCH. It verifies the
exact checkout, private environment permissions, launchd ownership, health/PID
and source-tree agreement, absence of the legacy company daemon, idle RSS, and
*operational* hosted cognition redundancy. Provider credentials are never
printed. Provider probes use tiny read-only inference requests with SDK retries
disabled and bounded timeouts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from jarvis.amaura.runtime import load_amaura_env


def _run(command: list[str], *, cwd: Path | None = None, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False, timeout=timeout)


def _git_value(repo_root: Path, expression: str) -> str:
    result = _run(["git", "rev-parse", expression], cwd=repo_root)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _check(name: str, ok: bool, detail: Any) -> dict[str, Any]:
    return {"name": name, "status": "PASS" if ok else "FAIL", "detail": detail}


def _health(url: str) -> dict[str, Any]:
    headers: dict[str, str] = {}
    api_key = os.environ.get("JARVIS_API_KEY", "").strip()
    if api_key:
        # The value is used only for the loopback request and is never included
        # in the report. This also works when desktop bootstrap protection is
        # enabled on the shared health endpoint.
        headers["X-Jarvis-Key"] = api_key
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 - caller defaults to fixed loopback URL
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
        return {"_error": f"{type(exc).__name__}: {exc}"}


def _launchd_state(label: str) -> dict[str, Any]:
    if sys.platform != "darwin":
        return {"available": False, "state": "unsupported", "pid": 0, "raw": "not macOS"}
    service = f"gui/{os.getuid()}/{label}"
    result = _run(["launchctl", "print", service])
    if result.returncode != 0:
        return {"available": True, "state": "missing", "pid": 0, "raw": result.stderr.strip()[:1000]}
    state_match = re.search(r"^\s*state\s*=\s*(\S+)", result.stdout, re.MULTILINE)
    pid_match = re.search(r"^\s*pid\s*=\s*(\d+)", result.stdout, re.MULTILINE)
    return {
        "available": True,
        "state": state_match.group(1) if state_match else "unknown",
        "pid": int(pid_match.group(1)) if pid_match else 0,
        "raw": "",
    }


def _rss_kb(pid: int) -> int:
    if pid <= 0:
        return 0
    result = _run(["ps", "-o", "rss=", "-p", str(pid)])
    try:
        return int(result.stdout.strip()) if result.returncode == 0 else 0
    except ValueError:
        return 0


def _legacy_processes() -> list[str]:
    result = _run(["ps", "-axo", "pid=,command="])
    if result.returncode != 0:
        return ["process inspection failed"]
    markers = ("jarvis.amaura.company_daemon", "amaura-company")
    return [line.strip() for line in result.stdout.splitlines() if any(marker in line for marker in markers)]


def _probe_hosted_providers(*, timeout_seconds: float, total_budget_seconds: float) -> list[dict[str, Any]]:
    """Prove configured emergency providers can complete one tiny request.

    This deliberately bypasses the primary OmniRoute gateway: the purpose of
    this check is to establish that ARCH has independently reachable hosted
    escape routes if the primary gateway is unavailable. No credential value is
    returned or logged.
    """
    from openai import OpenAI

    from jarvis.arch_provider_resilience import _compact_reason, _fallback_specs

    results: list[dict[str, Any]] = []
    started = time.monotonic()
    for provider, base_url, key, model in _fallback_specs():
        remaining = total_budget_seconds - (time.monotonic() - started)
        if remaining < 1.0:
            results.append(
                {
                    "provider": provider,
                    "model": model,
                    "ok": False,
                    "error": "provider probe total budget exhausted",
                    "credentials_printed": False,
                }
            )
            continue
        timeout = min(timeout_seconds, remaining)
        kwargs: dict[str, Any] = {"api_key": key, "timeout": timeout, "max_retries": 0}
        if base_url:
            kwargs["base_url"] = base_url
        probe_started = time.monotonic()
        try:
            client = OpenAI(**kwargs)
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Reply with exactly OK."}],
                temperature=0,
                max_tokens=4,
            )
            text = str(response.choices[0].message.content or "").strip()
            if not text:
                raise RuntimeError("empty completion")
            results.append(
                {
                    "provider": provider,
                    "model": str(getattr(response, "model", "") or model),
                    "ok": True,
                    "latency_ms": int((time.monotonic() - probe_started) * 1000),
                    "credentials_printed": False,
                }
            )
        except Exception as exc:  # noqa: BLE001 - qualification records a redacted provider failure
            results.append(
                {
                    "provider": provider,
                    "model": model,
                    "ok": False,
                    "latency_ms": int((time.monotonic() - probe_started) * 1000),
                    "error": _compact_reason(exc),
                    "credentials_printed": False,
                }
            )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only final ARCH target preflight")
    parser.add_argument("--env-file", default=".env.amaura")
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--health-url", default="http://127.0.0.1:8000/api/health")
    parser.add_argument("--service-label", default="com.amaura.arch")
    parser.add_argument("--max-idle-rss-mb", type=int, default=2048)
    parser.add_argument("--require-python-313", action="store_true")
    parser.add_argument(
        "--minimum-operational-fallbacks",
        type=int,
        default=2,
        help="Distinct hosted emergency providers that must complete a tiny live probe (default: 2).",
    )
    parser.add_argument("--provider-probe-timeout-seconds", type=float, default=12.0)
    parser.add_argument("--provider-probe-total-budget-seconds", type=float, default=30.0)
    parser.add_argument(
        "--skip-provider-probe",
        action="store_true",
        help="Diagnostic only: list configured providers without proving reachability; cannot pass the final redundancy gate.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    env_file = Path(args.env_file).expanduser().resolve()
    checks: list[dict[str, Any]] = []

    actual_sha = _git_value(repo_root, "HEAD")
    tree_sha = _git_value(repo_root, "HEAD^{tree}")
    checks.append(_check("exact_sha", actual_sha == args.expected_sha, {"expected": args.expected_sha, "actual": actual_sha}))

    dirty_result = _run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo_root)
    dirty = dirty_result.returncode != 0 or bool(dirty_result.stdout.strip())
    checks.append(_check("tracked_tree_clean", not dirty, dirty_result.stdout.strip()))

    env_ok = env_file.is_file()
    mode = stat.S_IMODE(env_file.stat().st_mode) if env_ok else 0
    checks.append(_check("private_env_permissions", env_ok and mode == 0o600, {"path": str(env_file), "mode": oct(mode)}))
    if env_ok:
        load_amaura_env(env_file, override=True, require_private_permissions=True)

    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    supported = (3, 11) <= sys.version_info[:2] < (3, 15)
    if args.require_python_313:
        supported = supported and sys.version_info[:2] == (3, 13)
    checks.append(_check("target_python", supported, python_version))

    launchd = _launchd_state(args.service_label)
    service_ok = launchd.get("state") == "running" and int(launchd.get("pid") or 0) > 0
    checks.append(_check("single_arch_launchd_service", service_ok, launchd))
    service_pid = int(launchd.get("pid") or 0)

    health = _health(args.health_url)
    health_pid = int(health.get("pid") or 0) if isinstance(health, dict) else 0
    health_ok = health.get("status") == "online" and health_pid > 0 and health_pid == service_pid
    checks.append(
        _check(
            "health_pid_matches_launchd",
            health_ok,
            {
                "status": health.get("status"),
                "health_pid": health_pid,
                "launchd_pid": service_pid,
                "tools_total": (health.get("tools") or {}).get("total") if isinstance(health.get("tools"), dict) else None,
                "version": health.get("version"),
                "build_id": health.get("build_id"),
            },
        )
    )

    # Development health exposes the Git tree hash as build_id. Bind that
    # value to the exact checked-out source tree so an old launchd process
    # cannot accidentally qualify merely because it is healthy.
    health_build_id = str(health.get("build_id") or "").strip()
    provenance_ok = tree_sha != "unknown" and health_build_id == tree_sha
    checks.append(
        _check(
            "running_source_tree_matches_checkout",
            provenance_ok,
            {
                "commit_sha": actual_sha,
                "checkout_tree_sha": tree_sha,
                "health_build_id": health_build_id,
                "bootstrap_proof": health.get("bootstrap_proof", ""),
                "service_proof": health.get("service_proof", ""),
            },
        )
    )

    legacy = _legacy_processes()
    checks.append(_check("no_legacy_company_daemon", not legacy, legacy))

    rss_kb = _rss_kb(service_pid)
    max_rss_kb = max(128, args.max_idle_rss_mb) * 1024
    checks.append(
        _check(
            "idle_rss_budget",
            rss_kb > 0 and rss_kb <= max_rss_kb,
            {"rss_kb": rss_kb, "rss_mb": round(rss_kb / 1024, 2), "limit_mb": args.max_idle_rss_mb},
        )
    )

    provider_results: list[dict[str, Any]] = []
    configured_provider_names: list[str] = []
    if env_ok:
        from jarvis.arch_provider_resilience import _fallback_specs

        configured_provider_names = [provider for provider, *_ in _fallback_specs()]
        if not args.skip_provider_probe:
            provider_results = _probe_hosted_providers(
                timeout_seconds=max(3.0, min(float(args.provider_probe_timeout_seconds), 30.0)),
                total_budget_seconds=max(6.0, min(float(args.provider_probe_total_budget_seconds), 60.0)),
            )
    operational = sorted({str(item["provider"]) for item in provider_results if item.get("ok")})
    minimum_fallbacks = max(1, min(int(args.minimum_operational_fallbacks), 4))
    redundancy_ok = not args.skip_provider_probe and len(operational) >= minimum_fallbacks
    checks.append(
        _check(
            "hosted_emergency_provider_redundancy",
            redundancy_ok,
            {
                "configured_providers": configured_provider_names,
                "operational_providers": operational,
                "required_operational_providers": minimum_fallbacks,
                "probe_skipped": bool(args.skip_provider_probe),
                "probes": provider_results,
                "credentials_printed": False,
            },
        )
    )

    passed = all(item["status"] == "PASS" for item in checks)
    report = {
        "qualification": "ARCH_FINAL_PREFLIGHT",
        "status": "PASS" if passed else "FAIL",
        "candidate_sha": actual_sha,
        "candidate_tree_sha": tree_sha,
        "checks": checks,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
