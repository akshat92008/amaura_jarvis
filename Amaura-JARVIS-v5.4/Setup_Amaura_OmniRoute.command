#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Secure production setup assistant for Amaura JARVIS OmniRoute.

This is the canonical model-routing setup for ARCH. It configures OmniRoute for
executive cognition, governed Company OS workers, and an explicit independent
reviewer. Local Nova/Ollama routing is removed from the production profile.
"""

from __future__ import annotations

import datetime
import getpass
import json
import os
import pathlib
import shutil
import sys
import time
import urllib.error
import urllib.request

BANNER = r"""
  ┌──────────────────────────────────────────────────────────┐
  │  Amaura JARVIS — OmniRoute Production Setup              │
  │  API keys are hidden and stored only in private files.   │
  └──────────────────────────────────────────────────────────┘
"""


def _colour(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text


OK = lambda t: _colour(t, "32")
ERR = lambda t: _colour(t, "31")
HEAD = lambda t: _colour(t, "36;1")
DIM = lambda t: _colour(t, "2")

_DYNAMIC_REVIEW_SELECTORS = {"auto", "best", "default", "router"}
_DYNAMIC_REVIEW_PREFIXES = ("auto/", "best/", "default/")


def _prompt(label: str, default: str = "", secret: bool = False) -> str:
    display = f"{label} [{default}]: " if default and not secret else f"{label}: "
    try:
        value = getpass.getpass(display) if secret else input(display).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(0)
    return value or default


def _redact(key: str, text: str) -> str:
    if key and len(key) >= 3:
        text = text.replace(key, "[REDACTED]")
    return text


def _probe_omniroute(base_url: str, api_key: str) -> dict:
    endpoint = base_url.rstrip("/") + "/models"
    req = urllib.request.Request(
        endpoint,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "Amaura-JARVIS/5.5-production-setup",
        },
        method="GET",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=8.0) as response:
            latency_ms = int((time.monotonic() - started) * 1000)
            raw = response.read(262144).decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
            models = [
                str(item.get("id") or item.get("name") or "").strip()
                for item in (data.get("data") or [])
                if isinstance(item, dict)
            ]
            models = [model for model in models if model]
        except Exception:
            models = []
        return {"ok": True, "latency_ms": latency_ms, "models": models[:100], "error": ""}
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "models": [],
            "error": _redact(api_key, f"HTTP {exc.code}: {exc.reason}"),
        }
    except urllib.error.URLError as exc:
        return {
            "ok": False,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "models": [],
            "error": _redact(api_key, f"URLError: {getattr(exc, 'reason', exc)}"),
        }
    except Exception as exc:
        return {
            "ok": False,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "models": [],
            "error": _redact(api_key, f"{type(exc).__name__}: {exc}"),
        }


def _detect_jarvis_dir() -> pathlib.Path:
    candidates = [
        pathlib.Path(__file__).resolve().parent,
        pathlib.Path.cwd(),
        pathlib.Path.home() / "Desktop" / "amaura_jarvis" / "Amaura-JARVIS-v5.4",
    ]
    for candidate in candidates:
        if (candidate / "pyproject.toml").exists() and (candidate / "jarvis").is_dir():
            return candidate
    return pathlib.Path(__file__).resolve().parent


def _backup_existing(jarvis_dir: pathlib.Path) -> None:
    env_path = jarvis_dir / ".env.amaura"
    if not env_path.exists():
        return
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = pathlib.Path.home() / ".amaura" / "config-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(backup_dir, 0o700)
    backup = backup_dir / f"{jarvis_dir.name}.env.amaura.{stamp}.bak"
    shutil.copy2(env_path, backup)
    os.chmod(backup, 0o600)
    print(DIM(f"  ↳ Backed up existing private config → {backup}"))


def _write_env(jarvis_dir: pathlib.Path, values: dict[str, str]) -> pathlib.Path:
    env_path = jarvis_dir / ".env.amaura"
    existing: dict[str, str] = {}
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                existing[key.strip()] = value.strip()
    existing.update(values)
    lines = [
        "# Amaura JARVIS private production configuration",
        f"# Updated by Setup_Amaura_OmniRoute.command on {datetime.datetime.now().isoformat()}",
        "# chmod 0600 — never share or commit this file.",
        "",
    ]
    lines.extend(f"{key}={value}" for key, value in existing.items())
    lines.append("")
    temporary = env_path.with_name(f".{env_path.name}.tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, env_path)
    os.chmod(env_path, 0o600)
    return env_path


def _dynamic_selector(model: str) -> bool:
    normalized = model.strip().lower()
    return normalized in _DYNAMIC_REVIEW_SELECTORS or normalized.startswith(_DYNAMIC_REVIEW_PREFIXES)


def _concrete_models(models: list[str]) -> list[str]:
    return [model for model in models if not _dynamic_selector(model)]


def _print_model_choices(models: list[str]) -> None:
    print(DIM("  Concrete model IDs exposed by this gateway:"))
    for index, model in enumerate(models, start=1):
        print(DIM(f"    {index:>3}. {model}"))


def _resolve_model_choice(value: str, models: list[str]) -> str:
    choice = value.strip()
    if choice.isdigit():
        index = int(choice)
        if 1 <= index <= len(models):
            return models[index - 1]
    if choice in models:
        return choice
    return ""


def _choose_model(label: str, models: list[str], *, default: str = "") -> str:
    while True:
        raw = _prompt(f"  {label} (number or exact ID)", default=default)
        selected = _resolve_model_choice(raw, models)
        if selected:
            return selected
        print(ERR("  ✗ Choose one of the numbered concrete model IDs shown above."))


def _choose_optional_model(label: str, models: list[str]) -> str:
    while True:
        raw = _prompt(f"  {label} (optional; number/exact ID, blank for none)")
        if not raw:
            return ""
        selected = _resolve_model_choice(raw, models)
        if selected:
            return selected
        print(ERR("  ✗ Choose one of the numbered concrete model IDs shown above, or leave blank."))


def main() -> int:
    print(BANNER)
    jarvis_dir = _detect_jarvis_dir()
    print(HEAD(f"JARVIS directory: {jarvis_dir}"))
    print()

    print(HEAD("Step 1/5 — Backing up existing private config"))
    _backup_existing(jarvis_dir)
    print(OK("  ✓ Done"))
    print()

    print(HEAD("Step 2/5 — OmniRoute gateway"))
    base_url = _prompt("  OmniRoute Base URL", default="http://localhost:20128/v1").rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        print(ERR("  ✗ Base URL must start with http:// or https://"))
        return 1
    print(OK("  ✓ URL accepted"))
    print()

    print(HEAD("Step 3/5 — OmniRoute API key"))
    print(DIM("  Copy the client API key shown by the OmniRoute dashboard. Short local keys are valid."))
    print(DIM("  Do not reuse a credential that has ever appeared in Git history."))
    api_key = _prompt("  OmniRoute API Key (hidden)", secret=True)
    if not api_key:
        print(ERR("  ✗ API key is required. Open OmniRoute → Dashboard/Endpoints and copy the client key."))
        return 1
    print(OK("  ✓ Key accepted (not echoed)"))
    print()

    print(HEAD("Step 4/5 — Live gateway model discovery"))
    print(DIM(f"  Probing {base_url}/models …"))
    probe = _probe_omniroute(base_url, api_key)
    if not probe["ok"]:
        print(ERR(f"  ✗ OmniRoute is BLOCKED: {probe['error']}"))
        print(ERR("  Configuration was not changed. Ensure OmniRoute is running, then fix the URL/key and rerun."))
        return 1
    print(OK(f"  ✓ OmniRoute is reachable ({probe['latency_ms']}ms)"))

    models = probe["models"]
    if not models:
        print(ERR("  ✗ OmniRoute is reachable but advertises zero models."))
        print(ERR("  Open OmniRoute → Providers, connect at least one provider, confirm Models > 0, then rerun."))
        print(ERR("  Configuration was not changed."))
        return 1

    concrete = _concrete_models(models)
    print(DIM(f"  ↳ Gateway returned {len(models)} model entries in the bounded probe."))
    print(DIM(f"  ↳ {len(concrete)} are concrete model IDs eligible for governed production routing."))
    if len(concrete) < 2:
        print(ERR("  ✗ At least two concrete model IDs are required for worker/reviewer independence."))
        print(ERR("  Dynamic auto/best/default aliases cannot serve as the independent reviewer."))
        print(ERR("  Connect providers that expose concrete models, then rerun."))
        return 1
    _print_model_choices(concrete)
    print()

    print(HEAD("Step 5/5 — Production model routes"))
    print(DIM("  Select concrete routes by number. Worker and reviewer must be different."))
    primary_model = _choose_model("Primary worker/reasoning model", concrete)
    fallback_model = _choose_optional_model("Worker fallback model", concrete)
    chat_model = _choose_model("Fast chat model", concrete, default=primary_model)
    reviewer_model = _choose_model("Independent review model", concrete)

    if reviewer_model in {primary_model, fallback_model}:
        print(ERR("  ✗ Independent reviewer must differ from every worker route."))
        print(ERR("  Configuration was not changed. Rerun and choose a distinct reviewer model."))
        return 1
    if _dynamic_selector(reviewer_model):
        print(ERR("  ✗ Reviewer must be a concrete model, not auto/best/default/router."))
        return 1
    print(OK("  ✓ Independent routing contract is valid"))

    selected = [primary_model, chat_model, reviewer_model]
    if fallback_model:
        selected.append(fallback_model)
    missing = [model for model in selected if model not in models]
    if missing:
        print(ERR("  ✗ Selected route(s) disappeared from the live OmniRoute catalog:"))
        for model in missing:
            print(ERR(f"      - {model}"))
        print(ERR("  Configuration was not changed. Refresh OmniRoute providers and rerun."))
        return 1
    print(OK("  ✓ Every selected production route exists in the live gateway"))
    print()

    values = {
        "AMAURA_MODEL_MODE": "omniroute",
        "AMAURA_MODEL_PROVIDER": "omniroute",
        "AMAURA_DISABLE_CLOUD": "0",
        "AMAURA_REVIEW_MODE": "omniroute",
        "AMAURA_JARVIS_PROVIDER": "omniroute",
        "AMAURA_OMNIROUTE_BASE_URL": base_url,
        "AMAURA_OMNIROUTE_API_KEY": api_key,
        "AMAURA_OMNIROUTE_MODEL": primary_model,
        "AMAURA_OMNIROUTE_CHAT_MODEL": chat_model,
        "AMAURA_OMNIROUTE_REVIEW_MODEL": reviewer_model,
        "AMAURA_OMNIROUTE_FALLBACK_MODEL": fallback_model,
        "AMAURA_OMNIROUTE_REVIEW_FALLBACK_MODEL": "",
        "AMAURA_LOCAL_MODEL": "",
        "AMAURA_LOCAL_REVIEW_MODEL": "",
        "AMAURA_CLOUD_WORKER_MODEL": "",
        "AMAURA_CLOUD_REVIEW_MODEL": "",
        "AMAURA_JARVIS_ALLOW_OLLAMA": "0",
        "AMAURA_JARVIS_OLLAMA_PROBE": "0",
    }
    env_path = _write_env(jarvis_dir, values)

    print(OK(f"  ✓ Production config saved to {env_path} (chmod 0600)"))
    print()
    print(HEAD("═══ Production Route ═══"))
    print("  Gateway:              OmniRoute")
    print(f"  Worker:               {primary_model}")
    print(f"  Worker fallback:      {fallback_model or '(none)'}")
    print(f"  Fast chat:            {chat_model}")
    print(f"  Independent reviewer: {reviewer_model}")
    print("  Nova/Ollama:           DISABLED")
    print("  Status:                ROUTING READY ✓")
    print()
    print(DIM("  Next: ./Setup_Amaura_Antigravity.command"))
    print(DIM("        ./Setup_Amaura_Runtime.command"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
