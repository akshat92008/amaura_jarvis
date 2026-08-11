"""
NVIDIA API client — OpenAI-compatible wrapper for integrate.api.nvidia.com
Adapted from Nexus for Jarvis with 3-Key NVIDIA Failover, Groq, and Ollama Local Fallback.
"""

import hashlib
import json
import os
import re
import time
import certifi
import httpx
try:
    from openai import OpenAI, BadRequestError
except ImportError:  # Optional until a cloud/local OpenAI-compatible provider is used.
    OpenAI = None  # type: ignore[assignment]

    class BadRequestError(Exception):
        pass

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

ESSENTIAL_TOOL_NAMES = {
    "write_file", "edit_file", "read_file", "list_directory", "run_command", "git_status"
}

AMAURA_TOOL_NAMES = {
    "amaura_company_status", "amaura_company_blueprint", "amaura_resource_inventory", "amaura_list_agents", "amaura_create_program", "amaura_list_tasks",
    "amaura_task_packet", "amaura_run_task", "amaura_review_task", "amaura_pending_approvals",
    "amaura_pause_agent", "amaura_record_decision", "amaura_daily_briefing",
}

AMAURA_INTENT_TERMS = {
    "amaura", "company", "workforce", "programme", "program", "founder briefing",
    "approval", "proposal", "lead qualification", "software delivery", "content campaign",
    "research experiment", "employee", "department",
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


def _filter_essential_tools(tools: list[dict] | None, messages: list[dict] | None = None) -> list[dict] | None:
    """Select a compact intent-aware tool profile for providers with schema limits."""
    if not tools:
        return None
    latest_user = ""
    for message in reversed(messages or []):
        if message.get("role") == "user":
            latest_user = str(message.get("content", "")).lower()
            break
    selected_names = set(ESSENTIAL_TOOL_NAMES)
    if any(term in latest_user for term in AMAURA_INTENT_TERMS):
        selected_names.update(AMAURA_TOOL_NAMES)
    essential = [t for t in tools if t.get("function", {}).get("name") in selected_names]
    return essential if essential else tools[:6]


def _parse_failed_generation(err: Exception) -> tuple[str | None, str | None]:
    """Parse XML function generation from Groq BadRequestError e.g. <function=name>{json}</function>."""
    try:
        body = getattr(err, "body", {})
        if isinstance(body, dict):
            failed_gen = body.get("error", {}).get("failed_generation", "")
            if failed_gen:
                m = re.search(r'<function=(\w+)>(.*?)(?:</function>|$)', failed_gen, re.DOTALL)
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


class NvidiaClient:
    """OpenAI-compatible client with 3-key NVIDIA failover, Groq, and Ollama support."""

    _nvidia_disabled_until: float = 0.0

    def __init__(self, api_key: str | None = None, *, allow_fallbacks: bool = True):
        _load_env_file()
        self.allow_fallbacks = bool(allow_fallbacks)
        self.last_execution_metadata: dict[str, object] = {}
        self.all_keys = []

        primary_key = api_key or os.getenv("NVIDIA_API_KEY", "")
        if primary_key:
            self.all_keys.append(primary_key)

        for k in sorted(os.environ.keys()):
            if (k.startswith("NVIDIA_API_KEY") or k.startswith("NVIDIA_FALLBACK_API_KEY") or k.startswith("NVIDIA_KEY")) and os.environ[k]:
                val = os.environ[k]
                if val not in self.all_keys:
                    self.all_keys.append(val)

        self.current_key_idx = 0
        self.client = None
        nv_timeout = float(os.getenv("AMAURA_NVIDIA_TIMEOUT", os.getenv("NVIDIA_TIMEOUT", "60.0")))
        nv_connect_timeout = float(os.getenv("AMAURA_NVIDIA_CONNECT_TIMEOUT", "10.0"))
        if self.all_keys and OpenAI is not None:
            self.client = OpenAI(
                base_url=NVIDIA_BASE_URL,
                api_key=self.all_keys[0],
                http_client=httpx.Client(
                    verify=certifi.where(),
                    timeout=httpx.Timeout(nv_timeout, connect=nv_connect_timeout),
                ),
            )

        groq_key = os.getenv("GROQ_API_KEY", "")
        self.groq_client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=groq_key,
            http_client=httpx.Client(
                verify=certifi.where(),
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
        ) if groq_key and OpenAI is not None else None

        ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.ollama_client = (OpenAI(
            base_url=f"{ollama_url}/v1",
            api_key="ollama",
            http_client=httpx.Client(
                timeout=httpx.Timeout(120.0, connect=5.0),
            )
        ) if OpenAI is not None else None)

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
        self.last_execution_metadata = {
            "requested_provider": "nvidia",
            "actual_provider": provider,
            "requested_model": requested_model,
            "actual_model": actual_model,
            "fallback_reason": fallback_reason,
            "credential_id": credential_id,
        }
        return response

    def switch_to_fallback(self) -> bool:
        """Switch to the next available NVIDIA API key."""
        if len(self.all_keys) <= 1:
            return False
        self.current_key_idx = (self.current_key_idx + 1) % len(self.all_keys)
        new_key = self.all_keys[self.current_key_idx]
        if OpenAI is None:
            return False
        nv_timeout = float(os.getenv("AMAURA_NVIDIA_TIMEOUT", os.getenv("NVIDIA_TIMEOUT", "60.0")))
        nv_connect_timeout = float(os.getenv("AMAURA_NVIDIA_CONNECT_TIMEOUT", "10.0"))
        self.client = OpenAI(
            base_url=NVIDIA_BASE_URL,
            api_key=new_key,
            http_client=httpx.Client(
                verify=certifi.where(),
                timeout=httpx.Timeout(nv_timeout, connect=nv_connect_timeout),
            )
        )
        return True

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

        # ── 1. TRY NVIDIA API KEYS FIRST (If Circuit Breaker isn't tripped) ────
        if self.client and self.all_keys and time.time() >= NvidiaClient._nvidia_disabled_until:
            nvidia_model_map = {
                "gcp-vertex/gemini-2.0-flash-thinking": "meta/llama-3.3-70b-instruct",
                "jarvis-coder-7b-v1": "meta/llama-3.3-70b-instruct",
                "deepseek-ai/deepseek-v4-pro": "meta/llama-3.3-70b-instruct",
                "deepseek-ai/deepseek-v4-flash": "meta/llama-3.3-70b-instruct",
                "z-ai/glm-5.2": "z-ai/glm-5.2",
                "moonshotai/kimi-k2.6": "moonshotai/kimi-k2.6",
                "codestral": "mistralai/codestral-22b-instruct-v0.1",
                "meta/llama-3.3-70b-instruct": "meta/llama-3.3-70b-instruct",
            }
            target_nvidia_model = nvidia_model_map.get(model_id, model_id)

            nv_kwargs = dict(kwargs)
            nv_kwargs["model"] = target_nvidia_model
            if tools:
                # Filter tools for NVIDIA NIM to avoid parameter size overload error
                nv_kwargs["tools"] = _filter_essential_tools(tools, messages) if len(tools) > 10 else tools

            nvidia_error = ""
            for attempt in range(len(self.all_keys)):
                try:
                    response = self.client.chat.completions.create(**nv_kwargs)
                    return self._record_response(
                        response, provider="nvidia", requested_model=model_id,
                        actual_model=target_nvidia_model,
                        fallback_reason="" if attempt == 0 else "primary NVIDIA credential failed",
                    )
                except Exception as exc:
                    nvidia_error = type(exc).__name__
                    if attempt + 1 < len(self.all_keys):
                        self.switch_to_fallback()
            NvidiaClient._nvidia_disabled_until = time.time() + 120.0

        if not self.allow_fallbacks:
            raise RuntimeError(
                "The configured NVIDIA provider failed and provider fallback is disabled"
            )

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
                    response, provider="groq", requested_model=model_id,
                    actual_model=target_groq_model,
                    fallback_reason="NVIDIA unavailable or failed",
                )
            except BadRequestError as bre:
                func_name, func_args = _parse_failed_generation(bre)
                if func_name and func_args:
                    response = SyntheticResponse(func_name, func_args)
                    return self._record_response(
                        response, provider="groq", requested_model=model_id,
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
                ollama_kwargs["tools"] = _filter_essential_tools(tools, messages)[:16]
            response = self.ollama_client.chat.completions.create(**ollama_kwargs)
            return self._record_response(
                response, provider="ollama", requested_model=model_id,
                actual_model=str(ollama_kwargs["model"]),
                fallback_reason="cloud providers unavailable or failed",
            )
        except Exception:
            try:
                ollama_kwargs.pop("tools", None)
                response = self.ollama_client.chat.completions.create(**ollama_kwargs)
                return self._record_response(
                    response, provider="ollama", requested_model=model_id,
                    actual_model=str(ollama_kwargs["model"]),
                    fallback_reason="cloud providers failed; local tools disabled after retry",
                )
            except Exception:
                pass

        raise RuntimeError("All AI model backend providers (NVIDIA NIM, Groq, Ollama) failed. Please check network connection and API key configurations.")

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
