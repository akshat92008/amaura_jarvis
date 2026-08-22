"""ARCH-only hosted cognition resilience.

The generic cognition gateway intentionally respects an explicitly selected
provider. ARCH, however, is an always-on founder-facing product and must remain
useful when its primary interactive gateway times out. This adapter adds a
small, bounded *hosted-only* fallback for interactive cognition. It never uses
Ollama/local models and does not alter governed employee model routing.
"""

from __future__ import annotations

import os
import time
from typing import Any

from jarvis.amaura.model_gateway import CognitiveModelGateway, CognitiveModelResult
from jarvis.amaura.models import GovernanceError

_INSTALLED = False
_ORIGINAL_GENERATE: Any = None
_ORIGINAL_GENERATE_STREAM: Any = None


def _enabled_for(purpose: str) -> bool:
    if os.environ.get("ARCH_RUNTIME", "0") != "1":
        return False
    if os.environ.get("AMAURA_ARCH_HOSTED_COGNITION_FAILOVER", "1") != "1":
        return False
    allowed = {
        item.strip().lower()
        for item in os.environ.get(
            "AMAURA_ARCH_HOSTED_COGNITION_PURPOSES",
            "general,intent,reference,memory",
        ).split(",")
        if item.strip()
    }
    return purpose.lower() in allowed


def _bounded_float(name: str, *, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def _timeout_seconds() -> float:
    """Per-provider hosted fallback timeout.

    Six seconds proved too aggressive for a cold hosted 70B endpoint on the
    target Mac qualification. Keep each attempt bounded, but allow enough time
    for a real cloud provider to establish a connection and answer.
    """
    return _bounded_float(
        "AMAURA_ARCH_HOSTED_FALLBACK_TIMEOUT_SECONDS",
        default=12.0,
        minimum=3.0,
        maximum=20.0,
    )


def _total_budget_seconds() -> float:
    """Maximum wall-clock time ARCH may spend across all emergency providers."""
    return _bounded_float(
        "AMAURA_ARCH_HOSTED_FALLBACK_BUDGET_SECONDS",
        default=24.0,
        minimum=6.0,
        maximum=30.0,
    )


def _first_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _fallback_specs() -> list[tuple[str, str, str, str]]:
    """Return configured hosted fallbacks as (provider, base_url, key, model).

    ARCH-specific model overrides win, then the normal provider-specific model
    already used by the executive gateway. Provider names are safe to expose in
    diagnostics; credentials are never returned separately or logged.
    """
    order = [
        item.strip().lower()
        for item in os.environ.get(
            "AMAURA_ARCH_HOSTED_FALLBACK_ORDER",
            "nvidia,groq,openrouter,openai",
        ).split(",")
        if item.strip()
    ]
    specs: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()
    for provider in order:
        if provider in seen:
            continue
        seen.add(provider)
        if provider == "nvidia":
            key = _first_env("NVIDIA_API_KEY", "NVIDIA_API_KEY_1", "NVIDIA_API_KEY_2", "NVIDIA_API_KEY_3")
            model = _first_env("AMAURA_ARCH_NVIDIA_FALLBACK_MODEL", "AMAURA_NVIDIA_MODEL") or (
                "meta/llama-3.3-70b-instruct"
            )
            if key and model:
                specs.append((provider, "https://integrate.api.nvidia.com/v1", key, model))
        elif provider == "groq":
            key = os.environ.get("GROQ_API_KEY", "").strip()
            model = _first_env("AMAURA_ARCH_GROQ_FALLBACK_MODEL", "AMAURA_GROQ_MODEL") or (
                "llama-3.3-70b-versatile"
            )
            if key and model:
                specs.append((provider, "https://api.groq.com/openai/v1", key, model))
        elif provider == "openrouter":
            key = os.environ.get("OPENROUTER_API_KEY", "").strip()
            model = _first_env("AMAURA_ARCH_OPENROUTER_FALLBACK_MODEL", "AMAURA_OPENROUTER_MODEL")
            if key and model:
                specs.append((provider, "https://openrouter.ai/api/v1", key, model))
        elif provider == "openai":
            key = os.environ.get("OPENAI_API_KEY", "").strip()
            model = _first_env("AMAURA_ARCH_OPENAI_FALLBACK_MODEL", "AMAURA_OPENAI_MODEL")
            if key and model:
                specs.append((provider, "", key, model))
    return specs


def _compact_reason(exc: BaseException) -> str:
    text = CognitiveModelGateway._redact_secrets(f"{type(exc).__name__}: {exc}")
    return " ".join(text.split())[:320]


def _hosted_fallback(
    *,
    messages: list[dict[str, str]],
    purpose: str,
    temperature: float,
    max_tokens: int,
    primary_error: BaseException,
    requested_model: str,
) -> CognitiveModelResult:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise GovernanceError("ARCH hosted cognition fallback requires the openai package") from exc

    specs = _fallback_specs()
    errors: list[str] = []
    primary_reason = _compact_reason(primary_error)
    started = time.monotonic()
    total_budget = _total_budget_seconds()

    for provider, base_url, key, model in specs:
        elapsed = time.monotonic() - started
        remaining = total_budget - elapsed
        if remaining < 2.0:
            errors.append(f"{provider}=skipped: fallback wall-clock budget exhausted")
            break

        provider_timeout = min(_timeout_seconds(), remaining)
        try:
            # Disable SDK retries. ARCH owns retry/failover policy so a hidden
            # client retry cannot consume the entire founder-facing deadline.
            kwargs: dict[str, Any] = {
                "api_key": key,
                "timeout": provider_timeout,
                "max_retries": 0,
            }
            if base_url:
                kwargs["base_url"] = base_url
            client = OpenAI(**kwargs)
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            text = str(response.choices[0].message.content or "").strip()
            if not text:
                raise RuntimeError("empty completion")
            actual_model = str(getattr(response, "model", "") or model)
            CognitiveModelGateway._record_provider_success(provider)
            return CognitiveModelResult(
                text=text,
                provider=provider,
                model=actual_model,
                requested_model=requested_model,
                resolved_provider=provider,
                resolved_model=actual_model,
                fallback_used=True,
                fallback_reason=f"primary cognition failed: {primary_reason}",
                latency_ms=int((time.monotonic() - started) * 1000),
                gateway=f"arch-hosted-fallback:{provider}",
            )
        except Exception as exc:
            CognitiveModelGateway._record_provider_failure(provider)
            errors.append(f"{provider}={_compact_reason(exc)}")

    configured = ",".join(provider for provider, *_rest in specs) or "none"
    detail = "; ".join(errors) if errors else "no configured hosted fallback provider"
    raise GovernanceError(
        CognitiveModelGateway._redact_secrets(
            f"[ARCH_HOSTED_FALLBACK_EXHAUSTED] configured={configured}; primary={primary_reason}; {detail}"
        )
    ) from primary_error


def install_arch_provider_resilience() -> None:
    """Install ARCH-only interactive hosted failover exactly once."""
    global _INSTALLED, _ORIGINAL_GENERATE, _ORIGINAL_GENERATE_STREAM
    if _INSTALLED:
        return

    _ORIGINAL_GENERATE = getattr(CognitiveModelGateway.generate, "__func__", CognitiveModelGateway.generate)
    _ORIGINAL_GENERATE_STREAM = getattr(
        CognitiveModelGateway.generate_stream, "__func__", CognitiveModelGateway.generate_stream
    )

    def resilient_generate(
        cls,
        *,
        messages: list[dict[str, str]],
        purpose: str = "general",
        temperature: float = 0.1,
        max_tokens: int = 4000,
    ) -> CognitiveModelResult:
        selection = cls.select(purpose=purpose)
        requested_model = selection.model if selection is not None else ""
        try:
            return _ORIGINAL_GENERATE(
                cls,
                messages=messages,
                purpose=purpose,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            if not _enabled_for(purpose):
                raise
            return _hosted_fallback(
                messages=messages,
                purpose=purpose,
                temperature=temperature,
                max_tokens=max_tokens,
                primary_error=exc,
                requested_model=requested_model,
            )

    def resilient_generate_stream(
        cls,
        *,
        messages: list[dict[str, str]],
        on_token,
        purpose: str = "general",
        temperature: float = 0.1,
        max_tokens: int = 4000,
    ) -> CognitiveModelResult:
        selection = cls.select(purpose=purpose)
        requested_model = selection.model if selection is not None else ""
        emitted = False

        def tracking_token(token: str) -> None:
            nonlocal emitted
            if token:
                emitted = True
            on_token(token)

        try:
            return _ORIGINAL_GENERATE_STREAM(
                cls,
                messages=messages,
                on_token=tracking_token,
                purpose=purpose,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            # Never append a second provider after any primary token reached the
            # founder; that would create a corrupted mixed-provider answer.
            if emitted or not _enabled_for(purpose):
                raise
            result = _hosted_fallback(
                messages=messages,
                purpose=purpose,
                temperature=temperature,
                max_tokens=max_tokens,
                primary_error=exc,
                requested_model=requested_model,
            )
            if result.text:
                on_token(result.text)
            return result

    # Intentional runtime monkey-patch: ARCH installs this wrapper only inside
    # its own process, leaving generic Company OS model routing untouched.
    type.__setattr__(CognitiveModelGateway, "generate", classmethod(resilient_generate))
    type.__setattr__(CognitiveModelGateway, "generate_stream", classmethod(resilient_generate_stream))
    type.__setattr__(CognitiveModelGateway, "_arch_provider_resilience_installed", True)
    _INSTALLED = True


__all__ = [
    "_enabled_for",
    "_fallback_specs",
    "_hosted_fallback",
    "_timeout_seconds",
    "_total_budget_seconds",
    "install_arch_provider_resilience",
]
