"""Budget-, privacy-, and mode-aware model routing for company employees."""

from __future__ import annotations

import json as _json
import os
import threading as _threading
import time as _time
import urllib.error as _urlerror
import urllib.request as _urlrequest
from collections.abc import Callable as _Callable
from dataclasses import asdict, dataclass
from dataclasses import dataclass as _dataclass
from typing import Any as _Any

from jarvis.amaura.models import GovernanceError, RiskLevel
from jarvis.amaura.registry import get_agent


@dataclass(frozen=True, slots=True)
class ModelRoute:
    model_key: str
    provider: str
    privacy: str
    estimated_cost_cents: int
    fallback_model_key: str | None
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


class ModelGateway:
    """Select an explicit configured model without broadening data authority."""

    def route(
        self,
        agent_id: str,
        *,
        risk: str = "low",
        sensitivity: str = "internal",
        estimated_tokens: int = 4000,
        remaining_budget_cents: int,
        needs_vision: bool = False,
    ) -> ModelRoute:
        agent = get_agent(agent_id)
        estimated_tokens = max(1, int(estimated_tokens))
        mode = os.environ.get("AMAURA_MODEL_MODE", "local").strip().lower()
        provider_env = os.environ.get("AMAURA_MODEL_PROVIDER", "").strip().lower()
        if mode not in {"local", "balanced", "cloud", "omniroute"} and provider_env != "omniroute":
            raise GovernanceError("AMAURA_MODEL_MODE must be local, balanced, cloud, or omniroute")

        if provider_env == "omniroute" or mode == "omniroute":
            omni_model = (
                os.environ.get("AMAURA_OMNIROUTE_MODEL", "").strip()
                or os.environ.get("OMNIROUTE_MODEL", "").strip()
                or os.environ.get("AMAURA_CLOUD_WORKER_MODEL", "").strip()
            )
            if not omni_model:
                raise GovernanceError("AMAURA_OMNIROUTE_MODEL is required when provider is omniroute")
            route = ModelRoute(
                model_key=omni_model,
                provider="omniroute",
                privacy="cloud_approved",
                estimated_cost_cents=max(1, estimated_tokens // 4000),
                fallback_model_key=os.environ.get("AMAURA_OMNIROUTE_FALLBACK_MODEL", "").strip() or None,
                reason="Governed task is routed through the OmniRoute cognition gateway.",
            )
            if route.estimated_cost_cents > remaining_budget_cents:
                raise GovernanceError(
                    f"Estimated model cost {route.estimated_cost_cents}c exceeds remaining task budget {remaining_budget_cents}c"
                )
            return route

        local_model = os.environ.get("AMAURA_LOCAL_MODEL", "nova:3b").strip()
        cloud_model = (
            os.environ.get("AMAURA_CLOUD_WORKER_MODEL", "").strip()
            or os.environ.get("AMAURA_OMNIROUTE_MODEL", "").strip()
            or os.environ.get("OMNIROUTE_MODEL", "").strip()
        )
        vision_model = os.environ.get("AMAURA_CLOUD_VISION_MODEL", "").strip() or cloud_model
        restricted = sensitivity in {"client_confidential", "secret", "restricted"}

        if restricted or mode == "local":
            if not local_model:
                raise GovernanceError("AMAURA_LOCAL_MODEL is required for local or restricted work")
            route = ModelRoute(
                model_key=local_model,
                provider="local",
                privacy="device_only",
                estimated_cost_cents=0,
                fallback_model_key=None,
                reason=(
                    "Restricted data is routed to the configured device-only model with no cloud fallback."
                    if restricted
                    else "Local mode routes all work to the configured device-only model."
                ),
            )
        else:
            selected = vision_model if needs_vision else cloud_model
            if not selected:
                variable = (
                    "AMAURA_CLOUD_VISION_MODEL or AMAURA_CLOUD_WORKER_MODEL"
                    if needs_vision
                    else "AMAURA_CLOUD_WORKER_MODEL"
                )
                raise GovernanceError(f"{variable} is required for cloud-routed work")
            complexity_multiplier = (
                2
                if (
                    needs_vision
                    or agent.model_policy == "balanced"
                    or RiskLevel(risk) in {RiskLevel.HIGH, RiskLevel.CRITICAL}
                )
                else 1
            )
            route = ModelRoute(
                model_key=selected,
                provider="nvidia",
                privacy="cloud_approved",
                estimated_cost_cents=max(1, complexity_multiplier * estimated_tokens // 4000),
                fallback_model_key=local_model if mode == "balanced" and local_model else None,
                reason=(
                    "Vision work uses the explicitly configured cloud vision model."
                    if needs_vision
                    else "Cloud-approved work uses the explicitly configured worker model."
                ),
            )

        if route.estimated_cost_cents > remaining_budget_cents:
            raise GovernanceError(
                f"Estimated model cost {route.estimated_cost_cents}c exceeds remaining task budget {remaining_budget_cents}c"
            )
        return route


# ── Executive cognition gateway ──────────────────────────────────────────────
# The employee ModelGateway above routes governed Company OS worker tasks.  The
# executive gateway below is deliberately separate: it gives intent/planning/
# reference-resolution one source of truth for both provider availability and
# actual provider execution.


@_dataclass(frozen=True, slots=True)
class CognitiveModelSelection:
    provider: str
    model: str


@_dataclass(frozen=True, slots=True)
class CognitiveModelResult:
    text: str
    provider: str
    model: str
    requested_model: str = ""
    resolved_provider: str = ""
    resolved_model: str = ""
    fallback_used: bool = False
    fallback_reason: str = ""
    request_id: str = ""
    latency_ms: int = 0
    ttft_ms: int = 0
    gateway: str = ""


class CognitiveModelGateway:
    """Exact provider detection + execution for the JARVIS executive brain.

    Provider detection and invocation live in this same class, preventing the
    v4.1 failure mode where an OpenRouter/OpenAI key could make planning appear
    available while the code actually instantiated the NVIDIA-only path.
    """

    PROVIDERS = ("omniroute", "openrouter", "openai", "anthropic", "nvidia", "groq", "ollama")
    _pooled_client: _Any = None
    _pooled_client_lock = _threading.Lock()
    _circuit_lock = _threading.Lock()
    _circuit_failures: dict[str, int] = {}
    _circuit_open_until: dict[str, float] = {}

    @classmethod
    def _circuit_key(cls, provider: str) -> str:
        if provider == "omniroute":
            return "omniroute:" + (
                os.environ.get("AMAURA_OMNIROUTE_BASE_URL", "").strip()
                or os.environ.get("OMNIROUTE_BASE_URL", "").strip()
            )
        return provider

    @classmethod
    def _circuit_is_open(cls, provider: str) -> bool:
        key = cls._circuit_key(provider)
        now = _time.monotonic()
        with cls._circuit_lock:
            until = cls._circuit_open_until.get(key, 0.0)
            if until and until <= now:
                cls._circuit_open_until.pop(key, None)
                return False
            return until > now

    @classmethod
    def reset_circuits(cls) -> None:
        with cls._circuit_lock:
            cls._circuit_failures.clear()
            cls._circuit_open_until.clear()

    @classmethod
    def _record_provider_success(cls, provider: str) -> None:
        key = cls._circuit_key(provider)
        with cls._circuit_lock:
            cls._circuit_failures.pop(key, None)
            cls._circuit_open_until.pop(key, None)
            cls._circuit_failures.pop(provider, None)
            cls._circuit_open_until.pop(provider, None)

    @classmethod
    def _record_provider_failure(cls, provider: str) -> None:
        key = cls._circuit_key(provider)
        threshold = max(1, min(int(os.environ.get("AMAURA_PROVIDER_CIRCUIT_FAILURES", "2")), 10))
        cooldown = max(5.0, min(float(os.environ.get("AMAURA_PROVIDER_CIRCUIT_COOLDOWN_SECONDS", "30")), 300.0))
        with cls._circuit_lock:
            failures = cls._circuit_failures.get(key, 0) + 1
            cls._circuit_failures[key] = failures
            if failures >= threshold:
                cls._circuit_open_until[key] = _time.monotonic() + cooldown

    @staticmethod
    def _interactive_budget(purpose: str) -> tuple[float | None, int | None]:
        if purpose not in {"general", "intent", "reference", "memory"}:
            return None, None
        seconds = max(5.0, min(float(os.environ.get("AMAURA_JARVIS_INTERACTIVE_DEADLINE_SECONDS", "45")), 90.0))
        retries = max(0, min(int(os.environ.get("AMAURA_JARVIS_INTERACTIVE_MAX_RETRIES", "0")), 1))
        return _time.monotonic() + seconds, retries

    @classmethod
    def _http_client(cls):
        """Process-wide keep-alive pool for executive provider traffic."""
        with cls._pooled_client_lock:
            if cls._pooled_client is None or cls._pooled_client.is_closed:
                try:
                    import httpx
                except ImportError as exc:
                    raise GovernanceError("httpx is required for pooled cognition requests") from exc
                cls._pooled_client = httpx.Client(
                    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                    headers={"User-Agent": "Amaura-JARVIS/5.4.3"},
                )
            return cls._pooled_client

    @staticmethod
    def _model_for(provider: str, purpose: str = "general") -> str:
        if provider == "omniroute":
            purpose_key = {
                "planner": "AMAURA_OMNIROUTE_PLANNER_MODEL",
                "intent": "AMAURA_OMNIROUTE_INTENT_MODEL",
                "reference": "AMAURA_OMNIROUTE_REFERENCE_MODEL",
                "memory": "AMAURA_OMNIROUTE_MEMORY_MODEL",
                "general": "AMAURA_OMNIROUTE_CHAT_MODEL",
            }.get(purpose, "AMAURA_OMNIROUTE_MODEL")
            specific = os.environ.get(purpose_key, "").strip()
            if specific and specific.lower() not in {"auto", "on", "true", "1"}:
                return specific
            omni_model = (
                os.environ.get("AMAURA_OMNIROUTE_MODEL", "").strip() or os.environ.get("OMNIROUTE_MODEL", "").strip()
            )
            if omni_model:
                return omni_model
            general = os.environ.get("AMAURA_JARVIS_MODEL", "").strip()
            if general:
                return general
            return ""

        purpose_key = {
            "planner": "AMAURA_JARVIS_PLANNER_MODEL",
            "intent": "AMAURA_JARVIS_INTENT_MODEL",
            "reference": "AMAURA_JARVIS_REFERENCE_MODEL",
            "memory": "AMAURA_JARVIS_MEMORY_MODEL",
        }.get(purpose, "AMAURA_JARVIS_MODEL")
        specific = os.environ.get(purpose_key, "").strip()
        if specific and specific.lower() not in {"auto", "on", "true", "1"}:
            return specific
        general = os.environ.get("AMAURA_JARVIS_MODEL", "").strip()
        if general:
            return general
        provider_specific = os.environ.get(f"AMAURA_{provider.upper()}_MODEL", "").strip()
        if provider_specific:
            return provider_specific
        if provider == "ollama":
            # Executive cognition must use the same small local model chosen for
            # the Company OS, not the legacy global DEFAULT_MODEL (which may be a
            # 70B cloud identifier and impossible on an 8 GB Mac).
            return os.environ.get("AMAURA_LOCAL_MODEL", "nova:3b").strip()
        defaults = {
            "nvidia": "meta/llama-3.3-70b-instruct",
            "openai": "gpt-4o-mini",
            "anthropic": "claude-3-5-sonnet-20241022",
            "groq": "llama-3.3-70b-versatile",
            "openrouter": "meta-llama/llama-3.3-70b-instruct",
        }
        return defaults.get(provider, "")

    @classmethod
    def _provider_available(cls, provider: str, *, purpose: str = "general") -> bool:
        if cls._circuit_is_open(provider):
            return False
        if not cls._model_for(provider, purpose):
            return False
        if provider == "omniroute":
            key = (
                os.environ.get("AMAURA_OMNIROUTE_API_KEY", "").strip()
                or os.environ.get("OMNIROUTE_API_KEY", "").strip()
            )
            url = (
                os.environ.get("AMAURA_OMNIROUTE_BASE_URL", "").strip()
                or os.environ.get("OMNIROUTE_BASE_URL", "").strip()
            )
            return bool(key and url)
        if provider == "openrouter":
            return bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
        if provider == "openai":
            return bool(os.environ.get("OPENAI_API_KEY", "").strip())
        if provider == "anthropic":
            return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
        if provider == "nvidia":
            return bool(
                os.environ.get("NVIDIA_API_KEY", "").strip()
                or os.environ.get("NVIDIA_API_KEY_1", "").strip()
                or os.environ.get("NVIDIA_API_KEY_2", "").strip()
                or os.environ.get("NVIDIA_API_KEY_3", "").strip()
            )
        if provider == "groq":
            return bool(os.environ.get("GROQ_API_KEY", "").strip())
        if provider == "ollama":
            if os.environ.get("AMAURA_JARVIS_ALLOW_OLLAMA", "1") != "1":
                return False
            if os.environ.get("AMAURA_JARVIS_OLLAMA_PROBE", "1") == "0":
                return True
            base = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
            try:
                request = _urlrequest.Request(f"{base}/api/tags", method="GET")
                with _urlrequest.urlopen(request, timeout=1.5) as response:
                    payload = _json.loads(response.read().decode("utf-8"))
                wanted = cls._model_for("ollama", purpose)
                names = {
                    str(item.get("name") or item.get("model") or "")
                    for item in payload.get("models", [])
                    if isinstance(item, dict)
                }
                # Ollama may expose either `name` or `model`; exact tag match is
                # required so the UI cannot claim cognition is active when the
                # requested model is absent.
                return wanted in names
            except Exception:
                return False
        return False

    @classmethod
    def select(cls, *, purpose: str = "general") -> CognitiveModelSelection | None:
        requested = (
            os.environ.get("AMAURA_MODEL_PROVIDER", "").strip().lower()
            or os.environ.get("AMAURA_JARVIS_PROVIDER", "auto").strip().lower()
            or "auto"
        )
        if requested != "auto":
            if requested not in cls.PROVIDERS:
                raise GovernanceError(f"Unsupported AMAURA_JARVIS_PROVIDER: {requested}")
            if not cls._provider_available(requested, purpose=purpose):
                return None
            return CognitiveModelSelection(requested, cls._model_for(requested, purpose))
        order = [
            item.strip().lower()
            for item in os.environ.get(
                "AMAURA_JARVIS_PROVIDER_ORDER",
                "omniroute,openrouter,openai,anthropic,nvidia,groq,ollama",
            ).split(",")
            if item.strip()
        ]
        for provider in order:
            if provider in cls.PROVIDERS and cls._provider_available(provider, purpose=purpose):
                return CognitiveModelSelection(provider, cls._model_for(provider, purpose))
        return None

    @classmethod
    def available(cls, *, purpose: str = "general") -> bool:
        return cls.select(purpose=purpose) is not None

    @classmethod
    def status(cls, *, purpose: str = "general") -> dict[str, str | bool]:
        selection = cls.select(purpose=purpose)
        if selection is None:
            requested = (
                os.environ.get("AMAURA_MODEL_PROVIDER", "").strip().lower()
                or os.environ.get("AMAURA_JARVIS_PROVIDER", "auto").strip().lower()
                or "auto"
            )
            order = (
                [requested]
                if requested != "auto"
                else [
                    item.strip().lower()
                    for item in os.environ.get(
                        "AMAURA_JARVIS_PROVIDER_ORDER",
                        "omniroute,openrouter,openai,anthropic,nvidia,groq,ollama",
                    ).split(",")
                    if item.strip()
                ]
            )
            circuit_open = any(p in cls.PROVIDERS and cls._circuit_is_open(p) for p in order)
            reason = (
                "[CIRCUIT_OPEN] Provider circuit breaker is open"
                if circuit_open
                else "[ROUTER_NO_PROVIDER] No cognition provider configured or available"
            )
            return {
                "available": False,
                "provider": "deterministic-fallback",
                "model": "",
                "purpose": purpose,
                "gateway": "none",
                "status": "BLOCKED",
                "reason": reason,
            }
        if selection.provider == "omniroute":
            key = (
                os.environ.get("AMAURA_OMNIROUTE_API_KEY", "").strip()
                or os.environ.get("OMNIROUTE_API_KEY", "").strip()
            )
            url = (
                os.environ.get("AMAURA_OMNIROUTE_BASE_URL", "").strip()
                or os.environ.get("OMNIROUTE_BASE_URL", "").strip()
            )
            configured = bool(key and url)
            fallback = os.environ.get("AMAURA_OMNIROUTE_FALLBACK_MODEL", "").strip() or "none"
            return {
                "available": configured,
                "provider": "omniroute",
                "model": selection.model,
                "purpose": purpose,
                "gateway": "OmniRoute",
                "status": "READY" if configured else "BLOCKED",
                "reason": "" if configured else "authentication or base URL missing",
                "requested_model": selection.model,
                "resolved_provider": "omniroute",
                "resolved_model": selection.model,
                "fallback": fallback,
            }
        return {
            "available": True,
            "provider": selection.provider,
            "model": selection.model,
            "purpose": purpose,
            "gateway": selection.provider,
            "status": "READY",
            "requested_model": selection.model,
            "resolved_provider": selection.provider,
            "resolved_model": selection.model,
            "fallback": "none",
        }

    @staticmethod
    def _redact_secrets(text: str) -> str:
        clean = str(text)
        keys_to_hide = [
            os.environ.get("AMAURA_OMNIROUTE_API_KEY", "").strip(),
            os.environ.get("OMNIROUTE_API_KEY", "").strip(),
            os.environ.get("OPENROUTER_API_KEY", "").strip(),
            os.environ.get("OPENAI_API_KEY", "").strip(),
            os.environ.get("ANTHROPIC_API_KEY", "").strip(),
            os.environ.get("NVIDIA_API_KEY", "").strip(),
            os.environ.get("GROQ_API_KEY", "").strip(),
        ]
        for key in keys_to_hide:
            if key and len(key) >= 6:
                clean = clean.replace(key, "[REDACTED]")
        return clean

    @classmethod
    def _omniroute(
        cls,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        requested_model: str | None = None,
        fallback_reason: str = "",
        deadline_monotonic: float | None = None,
        max_retries_override: int | None = None,
    ) -> CognitiveModelResult:
        key = os.environ.get("AMAURA_OMNIROUTE_API_KEY", "").strip() or os.environ.get("OMNIROUTE_API_KEY", "").strip()
        base_url = (
            os.environ.get("AMAURA_OMNIROUTE_BASE_URL", "").strip() or os.environ.get("OMNIROUTE_BASE_URL", "").strip()
        ).rstrip("/")
        if not key or not base_url:
            raise GovernanceError("OmniRoute is not properly configured: API key and Base URL are required")

        if not (base_url.startswith("http://") or base_url.startswith("https://")):
            raise GovernanceError("OmniRoute base URL must start with http:// or https://")

        timeout_sec = max(2.0, min(float(os.environ.get("AMAURA_OMNIROUTE_TIMEOUT_SECONDS", "8")), 300.0))
        max_retries = (
            max_retries_override
            if max_retries_override is not None
            else max(0, min(int(os.environ.get("AMAURA_OMNIROUTE_MAX_RETRIES", "0")), 5))
        )
        fallback_model = os.environ.get("AMAURA_OMNIROUTE_FALLBACK_MODEL", "").strip()

        if base_url.endswith("/chat/completions"):
            endpoint = base_url
        elif base_url.endswith("/v1"):
            endpoint = f"{base_url}/chat/completions"
        else:
            endpoint = f"{base_url}/v1/chat/completions" if "/v1/" not in base_url else f"{base_url}/chat/completions"

        target_model = model
        original_model = requested_model or model
        fallback_used = model != original_model
        last_error_class = "unknown_error"

        for attempt in range(max_retries + 1):
            remaining = deadline_monotonic - _time.monotonic() if deadline_monotonic is not None else timeout_sec
            if remaining <= 0:
                last_error_class = "PROVIDER_TIMEOUT"
                break
            attempt_timeout = max(0.5, min(timeout_sec, remaining))
            t0 = _time.monotonic()
            payload = {
                "model": target_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
                "Accept": "application/json",
            }
            try:
                response = cls._http_client().post(
                    endpoint,
                    json=payload,
                    headers=headers,
                    timeout=attempt_timeout,
                )
                response.raise_for_status()
                latency_ms = int((_time.monotonic() - t0) * 1000)
                raw_text = response.text
                headers = {k.lower(): v for k, v in response.headers.items()}

                request_id = str(headers.get("x-request-id") or headers.get("x-omniroute-request-id") or "")
                resolved_provider = str(
                    headers.get("x-resolved-provider")
                    or headers.get("x-provider")
                    or headers.get("x-omniroute-provider")
                    or "omniroute"
                )
                resolved_model = str(
                    headers.get("x-resolved-model") or headers.get("x-omniroute-model") or target_model
                )
                text = ""
                try:
                    resp_data = _json.loads(raw_text)
                    if isinstance(resp_data, dict):
                        request_id = str(resp_data.get("id") or "") or request_id
                        resolved_provider = str(
                            resp_data.get("provider") or resp_data.get("resolved_provider") or resolved_provider
                        )
                        resolved_model = str(resp_data.get("model") or resolved_model)
                        choices = resp_data.get("choices") or []
                        if choices and isinstance(choices, list) and isinstance(choices[0], dict):
                            msg = choices[0].get("message") or {}
                            text = str(msg.get("content") or "")
                except (_json.JSONDecodeError, AttributeError):
                    chunks: list[str] = []
                    for line in raw_text.splitlines():
                        line = line.strip()
                        if line.startswith("data:") and line != "data: [DONE]":
                            try:
                                chunk_data = _json.loads(line[5:].strip())
                                if isinstance(chunk_data, dict):
                                    request_id = request_id or str(chunk_data.get("id") or "")
                                    choices = chunk_data.get("choices") or []
                                    if choices and isinstance(choices, list) and isinstance(choices[0], dict):
                                        delta = choices[0].get("delta") or choices[0].get("message") or {}
                                        content = delta.get("content")
                                        if content:
                                            chunks.append(str(content))
                            except _json.JSONDecodeError:
                                continue
                    text = "".join(chunks)

                # Some upstream routes acknowledge a request with HTTP 200 but
                # send only an empty SSE terminator.  Treat that as a failed
                # completion so the configured fallback can answer instead of
                # making the founder-facing UI look mysteriously unavailable.
                if not text.strip():
                    last_error_class = "MODEL_RESPONSE_EMPTY"
                    if fallback_model and target_model != fallback_model:
                        fallback_deadline = (
                            max(deadline_monotonic, _time.monotonic() + timeout_sec)
                            if deadline_monotonic is not None
                            else None
                        )
                        return cls._omniroute(
                            model=fallback_model,
                            messages=messages,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            requested_model=original_model,
                            fallback_reason="empty_response",
                            deadline_monotonic=fallback_deadline,
                            max_retries_override=max_retries_override,
                        )
                    cls._record_provider_failure("omniroute")
                    raise GovernanceError(
                        cls._redact_secrets(f"OmniRoute returned an empty completion for model {target_model}")
                    )
                cls._record_provider_success("omniroute")
                return CognitiveModelResult(
                    text=text,
                    provider="omniroute",
                    model=resolved_model,
                    requested_model=original_model,
                    resolved_provider=resolved_provider,
                    resolved_model=resolved_model,
                    fallback_used=fallback_used,
                    fallback_reason=fallback_reason,
                    request_id=request_id,
                    latency_ms=latency_ms,
                    gateway="omniroute",
                )
            except Exception as exc:
                try:
                    import httpx
                except ImportError:
                    httpx = None
                latency_ms = int((_time.monotonic() - t0) * 1000)
                if httpx is None or not isinstance(exc, (httpx.HTTPStatusError, httpx.RequestError)):
                    raise
                code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else 0
                if isinstance(exc, httpx.RequestError):
                    last_error_class = (
                        "PROVIDER_TIMEOUT" if isinstance(exc, httpx.TimeoutException) else "PROVIDER_HTTP_ERROR"
                    )
                    # A pooled connection can become stale after a server or
                    # route restart. Recreate the pool before the next attempt.
                    with cls._pooled_client_lock:
                        if cls._pooled_client is not None:
                            cls._pooled_client.close()
                            cls._pooled_client = None
                if code in (401, 403):
                    last_error_class = "PROVIDER_UNAVAILABLE"
                    break  # Don't retry auth errors
                elif code == 429:
                    last_error_class = "PROVIDER_UNAVAILABLE"
                elif code == 400:
                    last_error_class = "PROVIDER_HTTP_ERROR"
                    break
                elif code in (502, 503, 504):
                    last_error_class = "PROVIDER_UNAVAILABLE"
                elif code:
                    last_error_class = "PROVIDER_HTTP_ERROR"

                if attempt < max_retries and last_error_class in {
                    "PROVIDER_UNAVAILABLE",
                    "PROVIDER_HTTP_ERROR",
                    "PROVIDER_TIMEOUT",
                }:
                    _time.sleep(0.5 * (2**attempt))
                    continue

        # If primary model failed and fallback model is configured
        if fallback_model and model != fallback_model:
            reason_str = (
                "provider_unavailable"
                if last_error_class == "PROVIDER_UNAVAILABLE"
                else ("empty_response" if last_error_class == "MODEL_RESPONSE_EMPTY" else last_error_class.lower())
            )
            fallback_deadline = (
                max(deadline_monotonic, _time.monotonic() + timeout_sec)
                if deadline_monotonic is not None
                else None
            )
            return cls._omniroute(
                model=fallback_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                requested_model=original_model,
                fallback_reason=reason_str,
                deadline_monotonic=fallback_deadline,
                max_retries_override=max_retries_override,
            )

        cls._record_provider_failure("omniroute")
        raise GovernanceError(cls._redact_secrets(f"OmniRoute request failed [{last_error_class}] for model {model}"))

    @staticmethod
    def _openai_compatible(
        *,
        provider: str,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> CognitiveModelResult:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise GovernanceError("The openai package is required for the configured cognition provider") from exc
        if provider == "openrouter":
            key = os.environ.get("OPENROUTER_API_KEY", "").strip()
            client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=key, timeout=60.0)
        elif provider == "openai":
            key = os.environ.get("OPENAI_API_KEY", "").strip()
            client = OpenAI(api_key=key, timeout=60.0)
        elif provider == "nvidia":
            key = (
                os.environ.get("NVIDIA_API_KEY", "").strip()
                or os.environ.get("NVIDIA_API_KEY_1", "").strip()
                or os.environ.get("NVIDIA_API_KEY_2", "").strip()
                or os.environ.get("NVIDIA_API_KEY_3", "").strip()
            )
            client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=key, timeout=60.0)
        elif provider == "groq":
            key = os.environ.get("GROQ_API_KEY", "").strip()
            client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=key, timeout=60.0)
        elif provider == "ollama":
            base = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
            client = OpenAI(base_url=f"{base}/v1", api_key="ollama", timeout=60.0)
        else:
            raise GovernanceError(f"Unsupported OpenAI-compatible provider: {provider}")
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return CognitiveModelResult(
            text=str(response.choices[0].message.content or ""),
            provider=provider,
            model=str(getattr(response, "model", "") or model),
            requested_model=model,
            resolved_provider=provider,
            resolved_model=str(getattr(response, "model", "") or model),
            gateway=provider,
        )

    @staticmethod
    def _anthropic(
        *, model: str, messages: list[dict[str, str]], temperature: float, max_tokens: int
    ) -> CognitiveModelResult:
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        body_messages = [m for m in messages if m.get("role") in {"user", "assistant"}]
        payload: dict[str, _Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": body_messages,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        request = _urlrequest.Request(
            "https://api.anthropic.com/v1/messages",
            data=_json.dumps(payload).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with _urlrequest.urlopen(request, timeout=60) as response:
                parsed = _json.loads(response.read().decode("utf-8"))
        except (_urlerror.URLError, _urlerror.HTTPError, ValueError) as exc:
            raise GovernanceError(f"Anthropic cognition request failed: {exc}") from exc
        text = "".join(str(item.get("text") or "") for item in parsed.get("content", []) if isinstance(item, dict))
        return CognitiveModelResult(
            text=text,
            provider="anthropic",
            model=str(parsed.get("model") or model),
            requested_model=model,
            resolved_provider="anthropic",
            resolved_model=str(parsed.get("model") or model),
            gateway="anthropic",
        )

    @classmethod
    def generate(
        cls,
        *,
        messages: list[dict[str, str]],
        purpose: str = "general",
        temperature: float = 0.1,
        max_tokens: int = 4000,
    ) -> CognitiveModelResult:
        selection = cls.select(purpose=purpose)
        if selection is None:
            raise GovernanceError(f"No configured cognition model is available for {purpose}")
        if selection.provider == "omniroute":
            deadline, retry_override = cls._interactive_budget(purpose)
            return cls._omniroute(
                model=selection.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                deadline_monotonic=deadline,
                max_retries_override=retry_override,
            )
        if selection.provider == "anthropic":
            return cls._anthropic(
                model=selection.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        return cls._openai_compatible(
            provider=selection.provider,
            model=selection.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    @classmethod
    def generate_stream(
        cls,
        *,
        messages: list[dict[str, str]],
        on_token: _Callable[[str], None],
        purpose: str = "general",
        temperature: float = 0.1,
        max_tokens: int = 4000,
    ) -> CognitiveModelResult:
        """Stream OmniRoute SSE deltas; other providers retain safe buffering."""
        selection = cls.select(purpose=purpose)
        if selection is None:
            raise GovernanceError(f"No configured cognition model is available for {purpose}")
        if selection.provider != "omniroute":
            result = cls.generate(
                messages=messages,
                purpose=purpose,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if result.text:
                on_token(result.text)
            return result

        key = os.environ.get("AMAURA_OMNIROUTE_API_KEY", "").strip() or os.environ.get("OMNIROUTE_API_KEY", "").strip()
        base_url = (
            os.environ.get("AMAURA_OMNIROUTE_BASE_URL", "").strip() or os.environ.get("OMNIROUTE_BASE_URL", "").strip()
        ).rstrip("/")
        if not key or not base_url or not base_url.startswith(("http://", "https://")):
            raise GovernanceError("OmniRoute is not properly configured for streaming")
        endpoint = (
            base_url
            if base_url.endswith("/chat/completions")
            else f"{base_url}/chat/completions"
            if base_url.endswith("/v1") or "/v1/" in base_url
            else f"{base_url}/v1/chat/completions"
        )
        deadline, retry_override = cls._interactive_budget(purpose)
        timeout_sec = max(2.0, min(float(os.environ.get("AMAURA_OMNIROUTE_TIMEOUT_SECONDS", "8")), 300.0))
        if deadline is not None:
            timeout_sec = max(0.5, min(timeout_sec, deadline - _time.monotonic()))
        payload = {
            "model": selection.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "Accept": "text/event-stream",
        }
        started = _time.monotonic()
        chunks: list[str] = []
        request_id = ""
        resolved_provider = "omniroute"
        resolved_model = selection.model
        ttft_ms = 0
        try:
            with cls._http_client().stream(
                "POST",
                endpoint,
                json=payload,
                headers=headers,
                timeout=timeout_sec,
            ) as response:
                response.raise_for_status()
                headers = {k.lower(): v for k, v in response.headers.items()}
                request_id = str(headers.get("x-request-id") or headers.get("x-omniroute-request-id") or "")
                resolved_provider = str(headers.get("x-resolved-provider") or headers.get("x-provider") or "omniroute")
                resolved_model = str(
                    headers.get("x-resolved-model") or headers.get("x-omniroute-model") or selection.model
                )
                for raw_line in response.iter_lines():
                    line = raw_line.strip()
                    if not line.startswith("data:") or line == "data: [DONE]":
                        continue
                    try:
                        data = _json.loads(line[5:].strip())
                    except _json.JSONDecodeError:
                        continue
                    request_id = request_id or str(data.get("id") or "")
                    resolved_model = str(data.get("model") or resolved_model)
                    choices = data.get("choices") or []
                    if choices and isinstance(choices[0], dict):
                        delta = choices[0].get("delta") or {}
                        token = str(delta.get("content") or "")
                        if token:
                            if not chunks:
                                ttft_ms = int((_time.monotonic() - started) * 1000)
                            chunks.append(token)
                            on_token(token)
        except Exception as exc:
            if chunks:
                raise GovernanceError("OmniRoute stream interrupted after output began") from exc
            result = cls._omniroute(
                model=selection.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                deadline_monotonic=deadline,
                max_retries_override=retry_override,
            )
            if result.text:
                on_token(result.text)
            return result
        cls._record_provider_success("omniroute")
        return CognitiveModelResult(
            text="".join(chunks),
            provider="omniroute",
            model=resolved_model,
            requested_model=selection.model,
            resolved_provider=resolved_provider,
            resolved_model=resolved_model,
            request_id=request_id,
            latency_ms=int((_time.monotonic() - started) * 1000),
            ttft_ms=ttft_ms,
            gateway="omniroute",
        )

    @classmethod
    def generate_json(
        cls,
        *,
        prompt: str,
        purpose: str,
        max_tokens: int = 4000,
    ) -> tuple[dict[str, _Any], CognitiveModelResult]:
        result = cls.generate(
            messages=[
                {"role": "system", "content": "Return exactly one valid JSON object. Do not reveal hidden reasoning."},
                {"role": "user", "content": prompt},
            ],
            purpose=purpose,
            temperature=0.1,
            max_tokens=max_tokens,
        )
        candidate = result.text.strip()
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            raise GovernanceError("[MODEL_RESPONSE_INVALID] Cognition model returned no JSON object")
        try:
            value = _json.loads(candidate[start : end + 1])
        except _json.JSONDecodeError as exc:
            raise GovernanceError("[EXECUTIVE_PARSE_ERROR] Cognition model returned malformed JSON") from exc
        if not isinstance(value, dict):
            raise GovernanceError("[MODEL_RESPONSE_INVALID] Cognition model JSON must be an object")
        return value, result

    @classmethod
    def probe_interactive_cognition(cls, *, timeout_seconds: float = 6.0) -> dict[str, _Any]:
        """Bounded live completion probe for production interactive cognition."""
        st = cls.status(purpose="general")
        if not st.get("available"):
            return {
                "ready": False,
                "provider": str(st.get("provider") or "none"),
                "requested_model": str(st.get("requested_model") or ""),
                "actual_model": "",
                "latency_ms": 0,
                "error": str(st.get("reason") or "no_provider_available"),
            }
        t0 = _time.monotonic()
        try:
            res = cls.generate(
                messages=[{"role": "user", "content": "Respond with exactly the word ONLINE."}],
                purpose="general",
                temperature=0.0,
                max_tokens=10,
            )
            latency_ms = int((_time.monotonic() - t0) * 1000)
            text = res.text.strip()
            if not text:
                return {
                    "ready": False,
                    "provider": res.provider or str(st.get("provider") or ""),
                    "requested_model": res.requested_model or str(st.get("requested_model") or ""),
                    "actual_model": res.model or "",
                    "latency_ms": latency_ms,
                    "error": "empty_completion",
                }
            return {
                "ready": True,
                "provider": res.provider,
                "requested_model": res.requested_model,
                "actual_model": res.model,
                "latency_ms": latency_ms,
                "error": "",
            }
        except Exception as exc:
            latency_ms = int((_time.monotonic() - t0) * 1000)
            err_msg = cls._redact_secrets(str(exc))
            return {
                "ready": False,
                "provider": str(st.get("provider") or "unavailable"),
                "requested_model": str(st.get("requested_model") or ""),
                "actual_model": "",
                "latency_ms": latency_ms,
                "error": err_msg,
            }
