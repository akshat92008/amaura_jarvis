"""
Model registry & Smart Hybrid Router — all top-tier models and GCP fine-tuned endpoint router.
"""


MODELS = {
    # ── GCP Fable 5 Adaptive Reasoning ─────────────────────────────
    "fable-5-reasoning": {
        "id": "gcp-vertex/gemini-2.0-flash-thinking",
        "name": "JARVIS Fable 5 Engine (GCP)",
        "category": "reasoning",
        "context": 1048576,
        "description": "Claude Fable 5 level adaptive thinking & reasoning powered by GCP Vertex AI & DeepSeek R1",
        "supports_tools": True,
    },
    # ── Custom Fine-Tuned GCP Model ───────────────────────────────────
    "jarvis-coder-7b": {
        "id": "jarvis-coder-7b-v1",
        "name": "JARVIS Coder 32B (GCP Hosted)",
        "category": "coding",
        "context": 131072,
        "description": "Custom fine-tuned Qwen 2.5 Coder 32B hosted on GCP Compute Engine GPU VM ($300 Credit)",
        "supports_tools": True,
    },
    # ── Flagship Reasoning & Coding ──────────────────────────────────
    "llama-3.3-70b": {
        "id": "meta/llama-3.1-70b-instruct",
        "name": "Llama 3.3 70B",
        "category": "coding",
        "context": 128000,
        "description": "Meta's flagship 70B — super fast, elite tool calling & agentic coding",
        "supports_tools": True,
    },
    "deepseek-v4": {
        "id": "deepseek-ai/deepseek-v4-pro",
        "name": "DeepSeek V4 Pro",
        "category": "reasoning",
        "context": 131072,
        "description": "DeepSeek flagship MoE — 128k context, top-tier reasoning & code",
        "supports_tools": True,
    },
    "deepseek-flash": {
        "id": "deepseek-ai/deepseek-v4-flash",
        "name": "DeepSeek V4 Flash",
        "category": "coding",
        "context": 131072,
        "description": "Ultra-fast DeepSeek MoE for rapid code generation & tool use",
        "supports_tools": True,
    },
    "glm-5.2": {
        "id": "z-ai/glm-5.2",
        "name": "GLM 5.2",
        "category": "reasoning",
        "context": 131072,
        "description": "Flagship agentic & reasoning LLM by Zhipu AI",
        "supports_tools": True,
    },
    "kimi-k2.6": {
        "id": "moonshotai/kimi-k2.6",
        "name": "Kimi K2.6",
        "category": "coding",
        "context": 131072,
        "description": "Multimodal MoE by Moonshot AI — optimized for coding & tool use",
        "supports_tools": True,
    },
    "codestral": {
        "id": "mistralai/codestral-22b-instruct-v0.1",
        "name": "Codestral 22B",
        "category": "coding",
        "context": 32768,
        "description": "Mistral AI's specialized model for code generation & editing",
        "supports_tools": True,
    },
    "llama-vision": {
        "id": "meta/llama-3.2-90b-vision-instruct",
        "name": "Llama 3.2 90B Vision",
        "category": "vision",
        "context": 128000,
        "description": "Multimodal vision flagship model for UI inspection and image perception",
        "supports_tools": True,
    }
}

ALIASES = {
    "fable": "fable-5-reasoning",
    "fable5": "fable-5-reasoning",
    "fable-5-engine": "fable-5-reasoning",
    "fable5-engine": "fable-5-reasoning",
    "mythos": "fable-5-reasoning",
    "aimodel": "fable-5-reasoning",
    "gcp": "fable-5-reasoning",
    "llama": "llama-3.3-70b",
    "llama3": "llama-3.3-70b",
    "deepseek": "deepseek-v4",
    "ds": "deepseek-v4",
    "flash": "deepseek-flash",
    "glm": "glm-5.2",
    "kimi": "kimi-k2.6",
    "code": "codestral",
    "vision": "llama-vision",
}

DEFAULT_MODEL = "llama-3.3-70b"


class SmartHybridModelRouter:
    """Intelligent query classification & multi-modal model selection engine."""
    
    @staticmethod
    def classify_intent(prompt: str) -> str:
        p = prompt.lower()
        if any(w in p for w in ["screenshot", "webcam", "image", "visual", "look at", "see user", "ui layout", "inspect ui"]):
            return "vision"
        if any(w in p for w in ["browser", "navigate", "click", "web page", "scrape", "url", "playwright"]):
            return "browser"
        if any(w in p for w in ["architecture", "refactor", "system design", "security review", "audit", "math", "proof", "fable"]):
            return "reasoning"
        if any(w in p for w in ["speak", "listen", "voice", "duplex", "barge in"]):
            return "voice"
        if any(w in p for w in ["plan", "roadmap", "repository plan", "tdd"]):
            return "planning"
        if any(w in p for w in ["summarize", "briefing", "summary"]):
            return "summarization"
        return "coding"

    @classmethod
    def route_query(cls, prompt: str) -> str:
        intent = cls.classify_intent(prompt)
        
        if intent == "vision":
            return "llama-vision"
        elif intent in ["reasoning", "coding", "planning"]:
            return "fable-5-reasoning"
        elif intent in ["browser", "summarization"]:
            return "llama-3.3-70b"
        
        return DEFAULT_MODEL


def resolve_model(key: str) -> dict | None:
    """Resolve a model key or alias to its config dict."""
    key = key.lower().strip()
    if key in MODELS:
        return MODELS[key]
    if key in ALIASES:
        return MODELS[ALIASES[key]]
    for name, cfg in MODELS.items():
        if key in name or key in str(cfg.get("name", "")).lower():
            return cfg
    return None


def list_models() -> list[dict]:
    """Return all models as a list of dicts with key included."""
    result = []
    for key, cfg in MODELS.items():
        entry = dict(cfg)
        entry["key"] = key
        result.append(entry)
    return result

