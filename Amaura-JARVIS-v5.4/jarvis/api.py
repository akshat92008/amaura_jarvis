"""
NVIDIA API client — OpenAI-compatible wrapper for integrate.api.nvidia.com
Adapted from Nexus for Jarvis with 3-Key NVIDIA Failover, Groq, and Ollama Local Fallback.
"""

import hashlib
import json
import os
import re
import ssl
import time

import certifi
import httpx
from openai import BadRequestError, OpenAI

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

ESSENTIAL_TOOL_NAMES = {"write_file", "edit_file", "read_file", "list_directory", "run_command", "git_status"}

AMAURA_TOOL_NAMES = {
    "amaura_company_status",
    "amaura_company_blueprint",
    "amaura_resource_inventory",
    "amaura_list_agents",
    "amaura_create_program",
    "amaura_list_tasks",
    "amaura_task_packet",
    "amaura_run_task",
    "amaura_review_task",
    "amaura_pending_approvals",
    "amaura_pause_agent",
    "amaura_record_decision",
    "amaura_daily_briefing",
}

AMAURA_INTENT_TERMS = {
    "amaura",
    "company",
    "workforce",
    "programme",
    "program",
    "founder briefing",
    "approval",
    "proposal",
    "lead qualification",
    "software delivery",
    "content campaign",
    "research experiment",
    "employee",
    "department",
}


_env_loaded = False


def _load_env_file():
    """Load only the explicitly governed ``.env.amaura`` configuration."""
    global _env_loaded
    if _env_loaded:
        return
    _env_loaded = True
    from jarvis.amaura.runtime import load_amaura_env

    load_amaura_env()


RESEARCH_TOOL_NAMES = {"web_search", "deep_research", "summarize_url", "read_pdf", "save_research"}
RESEARCH_INTENT_TERMS = {"search", "web", "research", "browse", "url", "pdf", "find online", "lookup", "google", "ddg", "intelligence"}

DESKTOP_TOOL_NAMES = {
    "get_system_info",
    "get_situational_context",
    "list_running_apps",
    "open_app",
    "close_app",
    "set_volume",
    "take_screenshot",
    "add_reminder",
    "add_calendar_event",
    "send_imessage",
}
DESKTOP_INTENT_TERMS = {"system", "mac", "cpu", "memory", "ram", "disk", "hardware", "process", "app", "window", "battery", "volume", "screenshot", "reminder", "calendar", "message"}

FLEET_TOOL_NAMES = {
    "activate_house_party_protocol",
    "generate_morning_briefing",
    "check_system_watchdog",
    "manage_daemon",
}
FLEET_INTENT_TERMS = {"suit", "fleet", "house party", "protocol", "mark", "veronica", "igor", "centurion", "heartbreaker", "briefing", "watchdog", "daemon"}

KNOWLEDGE_TOOL_NAMES = {
    "add_knowledge_entity",
    "add_knowledge_relation",
    "query_knowledge",
    "search_knowledge_graph",
    "search_lessons",
    "store_memory",
    "search_memory",
}
KNOWLEDGE_INTENT_TERMS = {"remember", "recall", "knowledge", "graph", "relation", "lesson", "memory", "entity", "connection"}


def _filter_essential_tools(tools: list[dict] | None, messages: list[dict] | None = None) -> list[dict]:
    """Select a compact intent-aware tool profile for providers with schema limits."""
    if not tools:
        return []
    latest_user = ""
    for message in reversed(messages or []):
        if message.get("role") == "user":
            latest_user = str(message.get("content", "")).lower()
            break
    selected_names = set(ESSENTIAL_TOOL_NAMES)
    if any(term in latest_user for term in AMAURA_INTENT_TERMS):
        selected_names.update(AMAURA_TOOL_NAMES)
    if any(term in latest_user for term in RESEARCH_INTENT_TERMS):
        selected_names.update(RESEARCH_TOOL_NAMES)
    if any(term in latest_user for term in DESKTOP_INTENT_TERMS):
        selected_names.update(DESKTOP_TOOL_NAMES)
    if any(term in latest_user for term in FLEET_INTENT_TERMS):
        selected_names.update(FLEET_TOOL_NAMES)
    if any(term in latest_user for term in KNOWLEDGE_INTENT_TERMS):
        selected_names.update(KNOWLEDGE_TOOL_NAMES)
    essential = [t for t in tools if t.get("function", {}).get("name") in selected_names]
    return essential if essential else tools[:6]


def _parse_failed_generation(err: Exception) -> tuple[str | None, str | None]:
    """Parse XML function generation from Groq BadRequestError e.g. <function=name>{json}</function>."""
    try:
        body = getattr(err, "body", {})
        if isinstance(body, dict):
            failed_gen = body.get("error", {}).get("failed_generation", "")
            if failed_gen:
                m = re.search(r"<function=(\w+)>(.*?)(?:</function>|$)", failed_gen, re.DOTALL)
                if m:
                    func_name = m.group(1)
                    raw_args = m.group(2).strip()
                    try:
                        parsed = json.loads(raw_args, strict=False)
                        return func_name, json.dumps(parsed)
                    except Exception:
                        path_m = re.search(r'"path"\s*:\s*"([^"]+)"', raw_args)
                        content_m = re.search(r'"content"\s*:\s*"(.*)"', raw_args, re.DOTALL)
                        if path_m and content_m:
                            return func_name, json.dumps({"path": path_m.group(1), "content": content_m.group(1)})
    except Exception:
        pass
    return None, None


class SyntheticResponse:
    """Mock ChatCompletion structure when recovering from failed_generation."""

    def __init__(self, func_name: str, func_args: str):
        class Function:
            def __init__(self, name, arguments):
                self.name = name
                self.arguments = arguments

        class ToolCall:
            def __init__(self, id, name, arguments):
                self.id = id
                self.type = "function"
                self.function = Function(name, arguments)

        class Message:
            def __init__(self, name, arguments):
                self.content = None
                self.tool_calls = [ToolCall("call_recovered_" + str(int(time.time())), name, arguments)]
                self.role = "assistant"

        class Choice:
            def __init__(self, name, arguments):
                self.finish_reason = "tool_calls"
                self.index = 0
                self.message = Message(name, arguments)

        self.id = "chatcmpl-recovered-" + str(int(time.time()))
        self.choices = [Choice(func_name, func_args)]


def _stream_adapter(response):
    """Adapt a non-streaming ChatCompletion response into an iterable of streaming chunks."""
    choice = response.choices[0] if response and response.choices else None
    if not choice:
        return
    msg = choice.message
    if getattr(msg, "reasoning_content", None):
        yield type("Chunk", (), {
            "choices": [type("Choice", (), {
                "delta": type("Delta", (), {
                    "content": None,
                    "tool_calls": None,
                    "reasoning_content": msg.reasoning_content,
                })(),
                "finish_reason": None,
                "index": 0,
            })()],
            "usage": getattr(response, "usage", None),
        })()
    if msg.content:
        yield type("Chunk", (), {
            "choices": [type("Choice", (), {
                "delta": type("Delta", (), {
                    "content": msg.content,
                    "tool_calls": None,
                    "reasoning_content": None,
                })(),
                "finish_reason": choice.finish_reason or "stop",
                "index": 0,
            })()],
            "usage": getattr(response, "usage", None),
        })()
    if msg.tool_calls:
        for idx, tc in enumerate(msg.tool_calls):
            yield type("Chunk", (), {
                "choices": [type("Choice", (), {
                    "delta": type("Delta", (), {
                        "content": None,
                        "tool_calls": [type("ToolCall", (), {
                            "index": idx,
                            "id": tc.id,
                            "function": type("Function", (), {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            })(),
                        })()],
                        "reasoning_content": None,
                    })(),
                    "finish_reason": "tool_calls",
                    "index": 0,
                })()],
                "usage": getattr(response, "usage", None),
            })()


class NvidiaClient:
    """OpenAI-compatible client with 3-key NVIDIA failover, Groq, and Ollama support."""

    _nvidia_disabled_until: float = 0.0
    _omniroute_disabled_until: float = 0.0

    def __init__(self, api_key: str | None = None, *, allow_fallbacks: bool = True):
        _load_env_file()
        self.allow_fallbacks = bool(allow_fallbacks)
        self.last_execution_metadata: dict[str, object] = {}
        self.all_keys = []

        primary_key = api_key or os.getenv("NVIDIA_API_KEY", "")
        if primary_key:
            self.all_keys.append(primary_key)

        for k in sorted(os.environ.keys()):
            if (
                k.startswith("NVIDIA_API_KEY") or k.startswith("NVIDIA_FALLBACK_API_KEY") or k.startswith("NVIDIA_KEY")
            ) and os.environ[k]:
                val = os.environ[k]
                if val not in self.all_keys:
                    self.all_keys.append(val)

        self.current_key_idx = 0
        self.client = None
        self.nv_timeout = max(
            5.0,
            min(
                float(os.getenv("AMAURA_NVIDIA_TIMEOUT", os.getenv("NVIDIA_TIMEOUT", "25.0"))),
                120.0,
            ),
        )
        self.nv_connect_timeout = max(
            2.0,
            min(float(os.getenv("AMAURA_NVIDIA_CONNECT_TIMEOUT", "8.0")), self.nv_timeout),
        )
        self.nv_total_timeout = max(
            self.nv_timeout,
            min(float(os.getenv("AMAURA_NVIDIA_TOTAL_TIMEOUT", "45.0")), 180.0),
        )
        configured_attempts = max(
            1,
            min(int(os.getenv("AMAURA_NVIDIA_MAX_KEY_ATTEMPTS", "2")), 8),
        )
        self.nv_max_key_attempts = min(configured_attempts, max(1, len(self.all_keys)))
        if self.all_keys and OpenAI is not None:
            self.client = OpenAI(
                base_url=NVIDIA_BASE_URL,
                api_key=self.all_keys[0],
                http_client=httpx.Client(
                    verify=ssl.create_default_context(cafile=certifi.where()),
                    timeout=httpx.Timeout(self.nv_timeout, connect=self.nv_connect_timeout),
                ),
            )

        groq_key = os.getenv("GROQ_API_KEY", "")
        self.groq_client = (
            OpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=groq_key,
                http_client=httpx.Client(
                    verify=ssl.create_default_context(cafile=certifi.where()),
                    timeout=httpx.Timeout(60.0, connect=10.0),
                ),
            )
            if groq_key and OpenAI is not None
            else None
        )

        ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.ollama_client = (
            OpenAI(
                base_url=f"{ollama_url}/v1",
                api_key="ollama",
                http_client=httpx.Client(
                    timeout=httpx.Timeout(120.0, connect=5.0),
                ),
            )
            if OpenAI is not None
            else None
        )

        self.omniroute_base_url = (
            os.getenv("AMAURA_OMNIROUTE_BASE_URL", "").strip()
            or os.getenv("OMNIROUTE_BASE_URL", "").strip()
        )
        self.omniroute_api_key = (
            os.getenv("AMAURA_OMNIROUTE_API_KEY", "").strip()
            or os.getenv("OMNIROUTE_API_KEY", "").strip()
            or "omniroute"
        )
        self.omniroute_timeout = max(
            10.0,
            min(float(os.getenv("AMAURA_OMNIROUTE_TIMEOUT_SECONDS", "60.0")), 180.0),
        )
        self.omniroute_client = None
        if self.omniroute_base_url and OpenAI is not None:
            self.omniroute_client = OpenAI(
                base_url=self.omniroute_base_url,
                api_key=self.omniroute_api_key,
                http_client=httpx.Client(
                    verify=ssl.create_default_context(cafile=certifi.where()),
                    timeout=httpx.Timeout(self.omniroute_timeout, connect=self.nv_connect_timeout),
                ),
            )

    def _record_response(
        self,
        response,
        *,
        provider: str,
        requested_model: str,
        actual_model: str,
        fallback_reason: str = "",
    ):
        credential_id = ""
        if provider == "nvidia" and self.all_keys:
            credential_id = hashlib.sha256(self.all_keys[self.current_key_idx].encode()).hexdigest()[:12]
        elif provider == "omniroute":
            credential_id = "omniroute"
        self.last_execution_metadata = {
            "requested_provider": "omniroute" if provider == "omniroute" else "nvidia",
            "actual_provider": provider,
            "requested_model": requested_model,
            "actual_model": actual_model,
            "fallback_reason": fallback_reason,
            "credential_id": credential_id,
        }
        return response

    def switch_to_fallback(self) -> bool:
        """Switch to the next available tier or API key."""
        now = time.time()
        if self.omniroute_client and now >= NvidiaClient._omniroute_disabled_until:
            NvidiaClient._omniroute_disabled_until = now + 60.0
            return True

        if len(self.all_keys) > 1:
            self.current_key_idx = (self.current_key_idx + 1) % len(self.all_keys)
            new_key = self.all_keys[self.current_key_idx]
            if OpenAI is None:
                return False
            self.client = OpenAI(
                base_url=NVIDIA_BASE_URL,
                api_key=new_key,
                http_client=httpx.Client(
                    verify=ssl.create_default_context(cafile=certifi.where()),
                    timeout=httpx.Timeout(self.nv_timeout, connect=self.nv_connect_timeout),
                ),
            )
            return True
        return False

    def chat(
        self,
        model_id: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 16384,
        stream: bool = False,
    ):
        """Unified chat completion with multi-tier failover."""
        kwargs = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

        # ── 0. TRY OMNIROUTE FIRST (If configured and requested or in omniroute mode) ────
        should_try_omniroute = (
            self.omniroute_client is not None
            and time.time() >= NvidiaClient._omniroute_disabled_until
            and (
                model_id.startswith(("antigravity/", "agy/", "auto/", "claude", "aug/", "tllm/", "kmc/", "mcode/", "ddgw/"))
                or os.getenv("AMAURA_MODEL_MODE", "").strip().lower() == "omniroute"
                or not (self.client and self.all_keys)
            )
        )
        if should_try_omniroute:
            fallback_model = (
                os.getenv("AMAURA_OMNIROUTE_FALLBACK_MODEL", "").strip()
                or os.getenv("AMAURA_CLOUD_REVIEW_MODEL", "").strip()
                or "auto/claude-sonnet"
            )
            candidates = [model_id]
            if fallback_model and fallback_model not in candidates:
                candidates.append(fallback_model)
            for healthy_cand in (
                "agy/gemini-2.5-flash",
                "mistral/codestral-latest",
                "mistral/ministral-8b-latest",
                "antigravity/gemini-2.5-flash",
                "auto/claude-sonnet",
            ):
                if healthy_cand not in candidates:
                    candidates.append(healthy_cand)

            is_streaming = kwargs.get("stream", False)
            has_tool_messages = any(m.get("role") in ("tool", "function") for m in messages)

            for cand_idx, cand_model in enumerate(candidates):
                try:
                    omni_kwargs = dict(kwargs)
                    omni_kwargs["model"] = cand_model
                    if tools:
                        omni_kwargs["tools"] = _filter_essential_tools(tools, messages) if len(tools) > 10 else tools
                    cand_timeout = min(15.0, self.omniroute_timeout)

                    if is_streaming and has_tool_messages and cand_model.startswith("auto/"):
                        # Proxy models often do not emit SSE chunks when processing tool messages; use sync + stream adapter
                        omni_kwargs["stream"] = False
                        sync_resp = self.omniroute_client.chat.completions.create(
                            **omni_kwargs,
                            timeout=cand_timeout,
                        )
                        self._record_response(
                            sync_resp,
                            provider="omniroute",
                            requested_model=model_id,
                            actual_model=cand_model,
                            fallback_reason="" if cand_model == model_id else f"{model_id} timed out or failed",
                        )
                        return _stream_adapter(sync_resp)

                    response = self.omniroute_client.chat.completions.create(
                        **omni_kwargs,
                        timeout=cand_timeout,
                    )
                    return self._record_response(
                        response,
                        provider="omniroute",
                        requested_model=model_id,
                        actual_model=cand_model,
                        fallback_reason="" if cand_model == model_id else f"{model_id} timed out or failed",
                    )
                except Exception as e:
                    # If provider/proxy rejected OpenAI tools schema (e.g. 502 empty content), retry this candidate without tools
                    if "tools" in omni_kwargs and ("502" in str(e) or "empty content" in str(e).lower()):
                        try:
                            retry_kwargs = dict(omni_kwargs)
                            retry_kwargs.pop("tools", None)
                            response = self.omniroute_client.chat.completions.create(
                                **retry_kwargs,
                                timeout=cand_timeout,
                            )
                            return self._record_response(
                                response,
                                provider="omniroute",
                                requested_model=model_id,
                                actual_model=cand_model,
                                fallback_reason="omniroute_tool_schema_adapted",
                            )
                        except Exception:
                            pass
                    import sys
                    print(f"[OMNIROUTE CANDIDATE '{cand_model}' FAILED: {type(e).__name__}: {e}]", file=sys.stderr)
                    if cand_idx + 1 < len(candidates):
                        continue
                    # All OmniRoute candidates exhausted; trip circuit breaker
                    NvidiaClient._omniroute_disabled_until = time.time() + 15.0
                    print("[OMNIROUTE EXHAUSTED — Tripping circuit breaker for 15s, falling back to NVIDIA/Groq...]", file=sys.stderr)
                    if not self.allow_fallbacks:
                        raise

        # ── 1. TRY NVIDIA API KEYS FIRST (If Circuit Breaker isn't tripped) ────
        if self.client and self.all_keys and time.time() >= NvidiaClient._nvidia_disabled_until:
            nvidia_default = os.getenv("AMAURA_NVIDIA_MODEL", "meta/llama-3.2-11b-vision-instruct")
            nvidia_model_map = {
                "gcp-vertex/gemini-2.0-flash-thinking": nvidia_default,
                "jarvis-coder-7b-v1": nvidia_default,
                "deepseek-ai/deepseek-v4-pro": nvidia_default,
                "deepseek-ai/deepseek-v4-flash": nvidia_default,
                "z-ai/glm-5.2": nvidia_default,
                "moonshotai/kimi-k2.6": nvidia_default,
                "codestral": "mistralai/codestral-22b-instruct-v0.1",
                "meta/llama-3.3-70b-instruct": nvidia_default,
                "meta/llama-3.1-70b-instruct": nvidia_default,
                "meta/llama-3.2-11b-vision-instruct": "meta/llama-3.2-11b-vision-instruct",
                "meta/llama-3.2-90b-vision-instruct": "meta/llama-3.2-90b-vision-instruct",
                "agy/gemini-2.5-flash": nvidia_default,
                "antigravity/gemini-2.5-flash": nvidia_default,
                "antigravity/claude-sonnet-4-6": nvidia_default,
                "auto/claude-sonnet": nvidia_default,
                "auto/claude-opus": nvidia_default,
                "auto/best-coding": nvidia_default,
                "auto/best-fast": nvidia_default,
            }
            target_nvidia_model = nvidia_model_map.get(model_id, model_id)
            if not target_nvidia_model or not target_nvidia_model.startswith(("meta/", "mistralai/", "deepseek-ai/", "nvidia/")):
                target_nvidia_model = nvidia_default

            nv_kwargs = dict(kwargs)
            nv_kwargs["model"] = target_nvidia_model
            if tools:
                # Filter tools for NVIDIA NIM to avoid parameter size overload error
                nv_kwargs["tools"] = _filter_essential_tools(tools, messages) if len(tools) > 10 else tools

            attempt_limit = min(len(self.all_keys), self.nv_max_key_attempts)
            deadline = time.monotonic() + self.nv_total_timeout
            for attempt in range(attempt_limit):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                request_timeout = max(1.0, min(self.nv_timeout, remaining))
                try:
                    response = self.client.chat.completions.create(
                        **nv_kwargs,
                        timeout=request_timeout,
                    )
                    recorded = self._record_response(
                        response,
                        provider="nvidia",
                        requested_model=model_id,
                        actual_model=target_nvidia_model,
                        fallback_reason="" if attempt == 0 else "primary NVIDIA credential failed",
                    )
                    self.last_execution_metadata["credential_attempts"] = attempt + 1
                    self.last_execution_metadata["request_budget_seconds"] = self.nv_total_timeout
                    return recorded
                except Exception as exc:
                    import sys
                    print(f"[NVIDIA ATTEMPT {attempt+1} FAILED: {type(exc).__name__}: {exc}]", file=sys.stderr)
                    if attempt + 1 < attempt_limit and (deadline - time.monotonic()) > 0:
                        self.switch_to_fallback()
            NvidiaClient._nvidia_disabled_until = time.time() + 15.0

        if not self.allow_fallbacks:
            raise RuntimeError("The configured NVIDIA provider failed and provider fallback is disabled")

        # ── 2. GROQ AS SECOND TIER FALLBACK ─────────────────────────────────
        if self.groq_client:
            groq_model_map = {
                "gcp-vertex/gemini-2.0-flash-thinking": "llama-3.3-70b-versatile",
                "jarvis-coder-7b-v1": "llama-3.3-70b-versatile",
                "meta/llama-3.3-70b-instruct": "llama-3.3-70b-versatile",
                "meta/llama-3.1-70b-instruct": "llama-3.3-70b-versatile",
                "deepseek-ai/deepseek-v4-pro": "llama-3.3-70b-versatile",
                "deepseek-ai/deepseek-v4-flash": "llama-3.3-70b-versatile",
                "z-ai/glm-5.2": "llama-3.3-70b-versatile",
                "moonshotai/kimi-k2.6": "llama-3.3-70b-versatile",
                "mistralai/codestral-22b-instruct-v0.1": "llama-3.3-70b-versatile",
            }
            target_groq_model = groq_model_map.get(model_id, "llama-3.3-70b-versatile")

            groq_kwargs = dict(kwargs)
            groq_kwargs["model"] = target_groq_model
            groq_kwargs["max_tokens"] = max_tokens

            if tools:
                groq_kwargs["tools"] = _filter_essential_tools(tools, messages)

            try:
                response = self.groq_client.chat.completions.create(**groq_kwargs)
                return self._record_response(
                    response,
                    provider="groq",
                    requested_model=model_id,
                    actual_model=target_groq_model,
                    fallback_reason="NVIDIA unavailable or failed",
                )
            except BadRequestError as bre:
                func_name, func_args = _parse_failed_generation(bre)
                if func_name and func_args:
                    response = SyntheticResponse(func_name, func_args)
                    return self._record_response(
                        response,
                        provider="groq",
                        requested_model=model_id,
                        actual_model=target_groq_model,
                        fallback_reason="Groq recovered malformed tool generation",
                    )
            except Exception:
                pass

        # ── 3. OLLAMA LOCAL FALLBACK ──────────────────────────────────────────
        try:
            ollama_kwargs = dict(kwargs)
            ollama_kwargs["model"] = "qwen2.5-coder:1.5b"
            if tools:
                ollama_kwargs["tools"] = _filter_essential_tools(tools or [], messages)[:16]
            if self.ollama_client is None:
                raise RuntimeError("Ollama fallback is not configured")
            response = self.ollama_client.chat.completions.create(**ollama_kwargs)
            return self._record_response(
                response,
                provider="ollama",
                requested_model=model_id,
                actual_model=str(ollama_kwargs["model"]),
                fallback_reason="cloud providers unavailable or failed",
            )
        except Exception:
            try:
                ollama_kwargs.pop("tools", None)
                if self.ollama_client is None:
                    raise RuntimeError("Ollama fallback is not configured")
                response = self.ollama_client.chat.completions.create(**ollama_kwargs)
                return self._record_response(
                    response,
                    provider="ollama",
                    requested_model=model_id,
                    actual_model=str(ollama_kwargs["model"]),
                    fallback_reason="cloud providers failed; local tools disabled after retry",
                )
            except Exception:
                pass

        raise RuntimeError(
            "All AI model backend providers (OmniRoute, NVIDIA NIM, Groq, Ollama) failed. Please check network connection and API key configurations."
        )

    def chat_sync(
        self,
        model_id: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 16384,
    ):
        """Non-streaming chat completion."""
        return self.chat(
            model_id=model_id,
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
        )
