"""Budget-, privacy-, and mode-aware model routing for company employees."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass

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
            omni_model = os.environ.get("AMAURA_OMNIROUTE_MODEL", "").strip() or os.environ.get("OMNIROUTE_MODEL", "").strip() or os.environ.get("AMAURA_CLOUD_WORKER_MODEL", "").strip()
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
                variable = "AMAURA_CLOUD_VISION_MODEL or AMAURA_CLOUD_WORKER_MODEL" if needs_vision else "AMAURA_CLOUD_WORKER_MODEL"
                raise GovernanceError(f"{variable} is required for cloud-routed work")
            complexity_multiplier = 2 if (
                needs_vision
                or agent.model_policy == "balanced"
                or RiskLevel(risk) in {RiskLevel.HIGH, RiskLevel.CRITICAL}
            ) else 1
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

from dataclasses import dataclass as _dataclass
import json as _json
import time as _time
import urllib.error as _urlerror
import urllib.request as _urlrequest
from typing import Any as _Any


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
    gateway: str = ""


class CognitiveModelGateway:
    """Exact provider detection + execution for the JARVIS executive brain.

    Provider detection and invocation live in this same class, preventing the
    v4.1 failure mode where an OpenRouter/OpenAI key could make planning appear
    available while the code actually instantiated the NVIDIA-only path.
    """

    PROVIDERS = ("omniroute", "openrouter", "openai", "anthropic", "nvidia", "groq", "ollama")

    @staticmethod
    def _model_for(provider: str, purpose: str = "general") -> str:
        if provider == "omniroute":
            purpose_key = {
                "planner": "AMAURA_OMNIROUTE_PLANNER_MODEL",
                "intent": "AMAURA_OMNIROUTE_INTENT_MODEL",
                "reference": "AMAURA_OMNIROUTE_REFERENCE_MODEL",
                "memory": "AMAURA_OMNIROUTE_MEMORY_MODEL",
            }.get(purpose, "AMAURA_OMNIROUTE_MODEL")
            specific = os.environ.get(purpose_key, "").strip()
            if specific and specific.lower() not in {"auto", "on", "true", "1"}:
                return specific
            omni_model = os.environ.get("AMAURA_OMNIROUTE_MODEL", "").strip() or os.environ.get("OMNIROUTE_MODEL", "").strip()
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
        # Cloud providers require an explicit model. Silent provider/model
        # mismatches are worse than a visible deterministic fallback.
        return ""

    @classmethod
    def _provider_available(cls, provider: str, *, purpose: str = "general") -> bool:
        if not cls._model_for(provider, purpose):
            return False
        if provider == "omniroute":
            key = os.environ.get("AMAURA_OMNIROUTE_API_KEY", "").strip() or os.environ.get("OMNIROUTE_API_KEY", "").strip()
            url = os.environ.get("AMAURA_OMNIROUTE_BASE_URL", "").strip() or os.environ.get("OMNIROUTE_BASE_URL", "").strip()
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
                    for item in payload.get("models", []) if isinstance(item, dict)
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
            return {
                "available": False,
                "provider": "deterministic-fallback",
                "model": "",
                "purpose": purpose,
                "gateway": "none",
                "status": "BLOCKED",
                "reason": "No cognition provider configured or available",
            }
        if selection.provider == "omniroute":
            key = os.environ.get("AMAURA_OMNIROUTE_API_KEY", "").strip() or os.environ.get("OMNIROUTE_API_KEY", "").strip()
            url = os.environ.get("AMAURA_OMNIROUTE_BASE_URL", "").strip() or os.environ.get("OMNIROUTE_BASE_URL", "").strip()
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
    ) -> CognitiveModelResult:
        key = os.environ.get("AMAURA_OMNIROUTE_API_KEY", "").strip() or os.environ.get("OMNIROUTE_API_KEY", "").strip()
        base_url = (os.environ.get("AMAURA_OMNIROUTE_BASE_URL", "").strip() or os.environ.get("OMNIROUTE_BASE_URL", "").strip()).rstrip("/")
        if not key or not base_url:
            raise GovernanceError("OmniRoute is not properly configured: API key and Base URL are required")

        if not (base_url.startswith("http://") or base_url.startswith("https://")):
            raise GovernanceError("OmniRoute base URL must start with http:// or https://")

        timeout_sec = max(5.0, min(float(os.environ.get("AMAURA_OMNIROUTE_TIMEOUT_SECONDS", "60")), 300.0))
        max_retries = max(0, min(int(os.environ.get("AMAURA_OMNIROUTE_MAX_RETRIES", "2")), 5))
        fallback_model = os.environ.get("AMAURA_OMNIROUTE_FALLBACK_MODEL", "").strip()

        if base_url.endswith("/chat/completions"):
            endpoint = base_url
        elif base_url.endswith("/v1"):
            endpoint = f"{base_url}/chat/completions"
        else:
            endpoint = f"{base_url}/v1/chat/completions" if "/v1/" not in base_url else f"{base_url}/chat/completions"

        target_model = model
        fallback_used = False
        fallback_reason = ""
        last_error_class = "unknown_error"

        for attempt in range(max_retries + 1):
            t0 = _time.monotonic()
            payload = {
                "model": target_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            req_data = _json.dumps(payload).encode("utf-8")
            request = _urlrequest.Request(
                endpoint,
                data=req_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {key}",
                    "Accept": "application/json",
                    "User-Agent": "Amaura-JARVIS/5.4.1",
                },
                method="POST",
            )
            try:
                with _urlrequest.urlopen(request, timeout=timeout_sec) as response:
                    latency_ms = int((_time.monotonic() - t0) * 1000)
                    raw_text = response.read().decode("utf-8", errors="replace")
                    headers = {k.lower(): v for k, v in response.headers.items()}
                
                request_id = str(
                    headers.get("x-request-id")
                    or headers.get("x-omniroute-request-id")
                    or ""
                )
                resolved_provider = str(
                    headers.get("x-resolved-provider")
                    or headers.get("x-provider")
                    or headers.get("x-omniroute-provider")
                    or "omniroute"
                )
                resolved_model = str(
                    headers.get("x-resolved-model")
                    or headers.get("x-omniroute-model")
                    or target_model
                )
                text = ""
                try:
                    resp_data = _json.loads(raw_text)
                    if isinstance(resp_data, dict):
                        request_id = str(resp_data.get("id") or "") or request_id
                        resolved_provider = str(resp_data.get("provider") or resp_data.get("resolved_provider") or resolved_provider)
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

                return CognitiveModelResult(
                    text=text,
                    provider="omniroute",
                    model=resolved_model,
                    requested_model=model,
                    resolved_provider=resolved_provider,
                    resolved_model=resolved_model,
                    fallback_used=fallback_used,
                    fallback_reason=fallback_reason,
                    request_id=request_id,
                    latency_ms=latency_ms,
                    gateway="omniroute",
                )
            except _urlerror.HTTPError as exc:
                latency_ms = int((_time.monotonic() - t0) * 1000)
                code = exc.code
                if code in (401, 403):
                    last_error_class = "authentication_failure"
                    break  # Don't retry auth errors
                elif code == 429:
                    last_error_class = "rate_limit"
                elif code == 400:
                    last_error_class = "context_length_failure"
                    break
                elif code in (502, 503, 504):
                    last_error_class = "provider_unavailable"
                else:
                    last_error_class = "invalid_response"
                
                if attempt < (max_retries - 1) and last_error_class in {"rate_limit", "provider_unavailable", "invalid_response"}:
                    _time.sleep(0.5 * (2 ** attempt))
                    continue
            except (_urlerror.URLError, TimeoutError, OSError) as exc:
                latency_ms = int((_time.monotonic() - t0) * 1000)
                last_error_class = "timeout" if isinstance(exc, TimeoutError) else "network_error"
                if attempt < (max_retries - 1):
                    _time.sleep(0.5 * (2 ** attempt))
                    continue
            except _json.JSONDecodeError:
                last_error_class = "structured_output_failure"
                if attempt < (max_retries - 1):
                    _time.sleep(0.5)
                    continue

        # If primary model failed and fallback model is configured
        if fallback_model and model != fallback_model:
            return cls._omniroute(
                model=fallback_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        raise GovernanceError(
            cls._redact_secrets(f"OmniRoute request failed [{last_error_class}] for model {model}")
        )

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
        text = "".join(
            str(item.get("text") or "") for item in parsed.get("content", []) if isinstance(item, dict)
        )
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
            return cls._omniroute(
                model=selection.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
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
            raise GovernanceError("Cognition model returned no JSON object")
        try:
            value = _json.loads(candidate[start : end + 1])
        except _json.JSONDecodeError as exc:
            raise GovernanceError("Cognition model returned malformed JSON") from exc
        if not isinstance(value, dict):
            raise GovernanceError("Cognition model JSON must be an object")
        return value, result
