"""Free-first capability catalogue and deterministic provider routing.

The catalogue describes *capabilities*, not privileged shortcuts.  A resource is
usable only when its executable or explicit configuration is present.  Consumer
subscriptions are represented as founder-approved handoffs unless an official
CLI/API adapter is configured.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
from dataclasses import asdict, dataclass
from enum import IntEnum, StrEnum
from typing import Any

from jarvis.amaura.models import GovernanceError


class ResourceTier(IntEnum):
    BUILTIN = 0
    OPEN_SOURCE = 10
    FREE_API = 20
    EXISTING_SUBSCRIPTION = 30
    PAID_API = 40


class ExecutionMode(StrEnum):
    BUILTIN = "builtin"
    LOCAL = "local"
    API = "api"
    MANUAL_HANDOFF = "manual_handoff"
    CONFIGURED_CLI = "configured_cli"


@dataclass(frozen=True, slots=True)
class CompanyResource:
    key: str
    name: str
    capabilities: tuple[str, ...]
    tier: ResourceTier
    mode: ExecutionMode
    description: str
    executable: str = ""
    python_module: str = ""
    required_env: tuple[str, ...] = ()
    optional: bool = True
    local_ram_mb: int = 0
    licence_note: str = ""

    def status(self) -> dict[str, Any]:
        missing_env = [name for name in self.required_env if not os.environ.get(name)]
        executable_path = shutil.which(self.executable) if self.executable else ""
        module_available = False
        if self.python_module:
            try:
                module_available = importlib.util.find_spec(self.python_module) is not None
            except (ImportError, ModuleNotFoundError, AttributeError, ValueError):
                module_available = False
        if self.mode is ExecutionMode.BUILTIN:
            available = True
            reason = "built into Amaura OS"
        elif self.mode is ExecutionMode.LOCAL:
            runtime_available = bool(executable_path) if self.executable else module_available
            available = runtime_available and not missing_env
            if available:
                reason = "available"
            elif missing_env:
                reason = f"missing configuration: {', '.join(missing_env)}"
            elif self.executable:
                reason = f"missing executable: {self.executable}"
            else:
                reason = f"missing Python module: {self.python_module}"
        elif self.mode is ExecutionMode.API:
            available = not missing_env
            reason = "configured" if available else f"missing configuration: {', '.join(missing_env)}"
        elif self.mode is ExecutionMode.CONFIGURED_CLI:
            available = bool(executable_path) and not missing_env
            reason = "configured" if available else "official/configured CLI is unavailable"
        else:
            available = not missing_env
            reason = "founder handoff enabled" if available else f"missing configuration: {', '.join(missing_env)}"
        result = asdict(self)
        result["tier"] = self.tier.name.lower()
        result["mode"] = self.mode.value
        result["available"] = available
        result["reason"] = reason
        result["executable_path"] = executable_path
        result["module_available"] = module_available
        result["missing_env"] = missing_env
        return result


RESOURCE_CATALOG: tuple[CompanyResource, ...] = (
    CompanyResource(
        "amaura_builtin",
        "Amaura governed runtime",
        ("orchestration", "approvals", "audit", "task_queue", "company_memory", "reporting"),
        ResourceTier.BUILTIN,
        ExecutionMode.BUILTIN,
        "Durable company control plane, policy engine, evidence vault and supervisor.",
        optional=False,
    ),
    CompanyResource(
        "sqlite",
        "SQLite",
        ("structured_storage", "company_memory", "crm", "finance_ledger"),
        ResourceTier.BUILTIN,
        ExecutionMode.BUILTIN,
        "Embedded durable database used by the local-first control plane.",
        optional=False,
        licence_note="Public domain",
    ),
    CompanyResource(
        "git",
        "Git",
        ("version_control", "engineering_workspace", "rollback"),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.LOCAL,
        "Versioned engineering delivery and auditable rollback.",
        executable="git",
        optional=False,
        local_ram_mb=50,
        licence_note="GPL-2.0",
    ),
    CompanyResource(
        "playwright",
        "Playwright",
        ("browser_extract", "browser_screenshot", "browser_validation"),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.LOCAL,
        "Deterministic browser automation used before agentic browsing.",
        python_module="playwright",
        local_ram_mb=650,
        licence_note="Apache-2.0",
    ),
    CompanyResource(
        "crawl4ai",
        "Crawl4AI",
        ("web_crawl", "research_extract", "website_markdown"),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.LOCAL,
        "Bounded web crawling and structured research extraction.",
        python_module="crawl4ai",
        local_ram_mb=850,
        licence_note="Apache-2.0",
    ),
    CompanyResource(
        "browser_use",
        "Browser Use",
        ("agentic_browser_research",),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.LOCAL,
        "Read-only agentic browser research fallback with explicit domain allowlists.",
        python_module="browser_use",
        local_ram_mb=1400,
        licence_note="MIT",
    ),
    CompanyResource(
        "searxng",
        "SearXNG",
        ("metasearch", "private_search"),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.API,
        "Self-hostable metasearch backend using the JSON search API.",
        required_env=("SEARXNG_URL",),
        local_ram_mb=250,
        licence_note="AGPL-3.0-or-later",
    ),
    CompanyResource(
        "docling",
        "Docling",
        ("document_understanding", "document_to_markdown", "table_extraction"),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.LOCAL,
        "Primary rich document understanding pipeline, spawned only when needed.",
        python_module="docling",
        local_ram_mb=1800,
        licence_note="MIT",
    ),
    CompanyResource(
        "pymupdf",
        "PyMuPDF",
        ("pdf_text", "pdf_render"),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.LOCAL,
        "Lightweight PDF text extraction and page rendering.",
        python_module="fitz",
        local_ram_mb=300,
        licence_note="AGPL-3.0/commercial dual licence",
    ),
    CompanyResource(
        "paddleocr",
        "PaddleOCR",
        ("ocr", "document_ocr"),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.LOCAL,
        "OCR specialist fallback using CPU-friendly settings on small Macs.",
        python_module="paddleocr",
        local_ram_mb=1700,
        licence_note="Apache-2.0",
    ),
    CompanyResource(
        "llamaindex",
        "LlamaIndex Core",
        ("rag_chunking", "knowledge_ingestion"),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.LOCAL,
        "Optional RAG document/node utilities without replacing Amaura orchestration.",
        python_module="llama_index.core",
        local_ram_mb=350,
        licence_note="MIT",
    ),
    CompanyResource(
        "qdrant_fastembed",
        "Qdrant + FastEmbed",
        ("vector_memory", "semantic_search", "local_embeddings", "knowledge_base"),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.LOCAL,
        "Local semantic memory with lightweight ONNX embeddings; remote Qdrant remains optional.",
        python_module="qdrant_client",
        local_ram_mb=650,
        licence_note="Apache-2.0",
    ),
    CompanyResource(
        "faster_whisper",
        "faster-whisper",
        ("transcription", "captions", "speech_analysis"),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.LOCAL,
        "Memory-efficient Whisper implementation used as the preferred transcription backend.",
        python_module="faster_whisper",
        local_ram_mb=1600,
        licence_note="MIT",
    ),
    CompanyResource(
        "kokoro",
        "Kokoro TTS",
        ("text_to_speech", "voiceover"),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.LOCAL,
        "Lightweight local voice generation for approved content production.",
        python_module="kokoro",
        local_ram_mb=900,
        licence_note="Apache-2.0",
    ),
    CompanyResource(
        "remotion",
        "Remotion",
        ("programmatic_video", "reel_render", "video_template"),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.LOCAL,
        "Programmatic video renderer executed inside an already-installed Remotion project.",
        executable="node",
        local_ram_mb=1800,
        licence_note="Check Remotion licence for organisation usage",
    ),
    CompanyResource(
        "image_tools",
        "ImageMagick/libvips",
        ("image_resize", "thumbnail", "image_transform"),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.LOCAL,
        "Cheap deterministic image transforms before invoking generative models.",
        executable="magick",
        local_ram_mb=300,
        licence_note="ImageMagick licence / LGPL libvips",
    ),
    CompanyResource(
        "yt_dlp",
        "yt-dlp",
        ("media_metadata", "approved_media_ingest"),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.LOCAL,
        "Governed media metadata/ingest utility for media the operator is authorised to use.",
        python_module="yt_dlp",
        local_ram_mb=250,
        licence_note="Unlicense; source-site terms and media rights still apply",
    ),
    CompanyResource(
        "comfyui",
        "ComfyUI",
        ("image_generation", "image_workflow"),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.API,
        "Optional heavy image-generation server; recommended remote/on-demand on 8 GB Macs.",
        required_env=("COMFYUI_URL",),
        local_ram_mb=5000,
        licence_note="GPL-3.0 code; model licences vary",
    ),
    CompanyResource(
        "mcp",
        "Model Context Protocol",
        ("external_tool_protocol", "capability_bridge"),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.LOCAL,
        "Standard protocol bridge for explicitly configured external tools and servers.",
        python_module="mcp",
        local_ram_mb=250,
        licence_note="MIT",
    ),
    CompanyResource(
        "langfuse",
        "Langfuse",
        ("agent_observability", "trace", "evaluation_telemetry"),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.API,
        "Optional observability and evaluation telemetry; the core audit log remains authoritative.",
        required_env=("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"),
        local_ram_mb=120,
        licence_note="MIT SDK / self-hosted components",
    ),
    CompanyResource(
        "ffmpeg",
        "FFmpeg",
        ("video_editing", "audio_processing", "caption_rendering", "media_validation"),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.LOCAL,
        "Primary free media assembly and validation engine.",
        executable="ffmpeg",
        local_ram_mb=500,
        licence_note="LGPL/GPL depending on build",
    ),
    CompanyResource(
        "whisper",
        "Whisper CLI",
        ("transcription", "captions", "speech_analysis"),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.LOCAL,
        "Local transcription for captions and repurposing.",
        executable="whisper",
        local_ram_mb=1800,
        licence_note="MIT",
    ),
    CompanyResource(
        "ollama",
        "Ollama",
        ("local_llm", "private_reasoning", "fallback_inference"),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.LOCAL,
        "Optional local inference for private or zero-cost tasks.",
        executable="ollama",
        local_ram_mb=4500,
        licence_note="MIT",
    ),
    CompanyResource(
        "docker",
        "Docker",
        ("sandbox", "isolated_execution", "reproducible_builds"),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.LOCAL,
        "Hardened execution boundary for code and experiments.",
        executable="docker",
        local_ram_mb=1200,
        licence_note="Apache-2.0 components / Docker Desktop terms may apply",
    ),
    CompanyResource(
        "n8n",
        "n8n",
        ("workflow_automation", "integrations", "webhooks"),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.API,
        "Optional self-hosted business automation bridge.",
        required_env=("N8N_BASE_URL", "N8N_API_KEY"),
        local_ram_mb=700,
        licence_note="Sustainable Use License / Enterprise License",
    ),
    CompanyResource(
        "qdrant",
        "Qdrant",
        ("vector_memory", "semantic_search", "knowledge_base"),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.API,
        "Optional semantic company-memory backend; SQLite remains the minimum baseline.",
        required_env=("QDRANT_URL",),
        local_ram_mb=500,
        licence_note="Apache-2.0",
    ),
    CompanyResource(
        "twenty_crm",
        "Twenty CRM",
        ("crm", "sales_pipeline", "relationship_memory"),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.API,
        "Optional CRM integration; the internal lead ledger remains the fallback.",
        required_env=("TWENTY_BASE_URL", "TWENTY_API_KEY"),
        local_ram_mb=1500,
        licence_note="AGPL-3.0",
    ),
    CompanyResource(
        "posthog",
        "PostHog",
        ("product_analytics", "growth_analytics", "experiments"),
        ResourceTier.OPEN_SOURCE,
        ExecutionMode.API,
        "Optional product and growth analytics provider.",
        required_env=("POSTHOG_HOST", "POSTHOG_API_KEY"),
        licence_note="MIT core with separate enterprise features",
    ),
    CompanyResource(
        "nvidia_api",
        "NVIDIA API / NIM",
        ("general_reasoning", "coding_reasoning", "vision", "tool_calling", "cloud_llm"),
        ResourceTier.FREE_API,
        ExecutionMode.API,
        "Default cloud intelligence when an NVIDIA key is configured.",
        required_env=("NVIDIA_API_KEY",),
    ),
    CompanyResource(
        "antigravity",
        "Google Antigravity",
        ("senior_coding", "repository_refactor", "browser_testing", "engineering_artifacts"),
        ResourceTier.EXISTING_SUBSCRIPTION,
        ExecutionMode.MANUAL_HANDOFF,
        "Founder-approved engineering handoff. Automation requires an official CLI/SDK adapter.",
        required_env=("AMAURA_ANTIGRAVITY_ENABLED",),
    ),
    CompanyResource(
        "google_flow",
        "Google Flow",
        ("cinematic_video", "storyboard_realisation", "premium_visuals"),
        ResourceTier.EXISTING_SUBSCRIPTION,
        ExecutionMode.MANUAL_HANDOFF,
        "Founder-approved creative handoff; Flow is not treated as the only media engine.",
        required_env=("AMAURA_GOOGLE_FLOW_ENABLED",),
    ),
    CompanyResource(
        "gemini_video_api",
        "Gemini video API",
        ("programmatic_video", "premium_visuals"),
        ResourceTier.PAID_API,
        ExecutionMode.API,
        "Optional programmatic video generation, kept separate from the Flow subscription.",
        required_env=("GEMINI_API_KEY", "AMAURA_ALLOW_PAID_MEDIA"),
    ),
)

RESOURCES_BY_KEY = {resource.key: resource for resource in RESOURCE_CATALOG}


@dataclass(frozen=True, slots=True)
class CapabilityRoute:
    capability: str
    provider_key: str
    provider_name: str
    tier: str
    mode: str
    reason: str
    fallback_keys: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["fallback_keys"] = list(self.fallback_keys)
        return result


class CapabilityRouter:
    """Choose an available provider with a strict free-first default."""

    def route(
        self,
        capability: str,
        *,
        allow_subscription: bool = True,
        allow_paid: bool = False,
        preferred: str = "",
    ) -> CapabilityRoute:
        candidates = [resource for resource in RESOURCE_CATALOG if capability in resource.capabilities]
        if not candidates:
            raise GovernanceError(f"No registered resource provides capability '{capability}'")

        allowed: list[CompanyResource] = []
        for resource in candidates:
            if resource.tier is ResourceTier.EXISTING_SUBSCRIPTION and not allow_subscription:
                continue
            if resource.tier is ResourceTier.PAID_API and not allow_paid:
                continue
            if resource.status()["available"]:
                allowed.append(resource)

        if preferred:
            preferred_resource = RESOURCES_BY_KEY.get(preferred)
            if preferred_resource in allowed and capability in preferred_resource.capabilities:
                selected = preferred_resource
                reason = f"Explicitly preferred configured provider '{preferred}'."
            else:
                raise GovernanceError(f"Preferred provider '{preferred}' is unavailable or lacks '{capability}'")
        elif allowed:
            selected = sorted(allowed, key=lambda item: (item.tier, item.key))[0]
            reason = "Selected the lowest-cost available tier under the free-first policy."
        else:
            statuses = {resource.key: resource.status()["reason"] for resource in candidates}
            raise GovernanceError(f"No available provider for '{capability}': {statuses}")

        fallbacks = tuple(
            item.key
            for item in sorted(allowed, key=lambda resource: (resource.tier, resource.key))
            if item.key != selected.key
        )
        return CapabilityRoute(
            capability=capability,
            provider_key=selected.key,
            provider_name=selected.name,
            tier=selected.tier.name.lower(),
            mode=selected.mode.value,
            reason=reason,
            fallback_keys=fallbacks,
        )

    def inventory(self) -> list[dict[str, Any]]:
        return [resource.status() for resource in RESOURCE_CATALOG]

    def mac_8gb_profile(self) -> dict[str, Any]:
        always_on = ["amaura_builtin", "sqlite", "git"]
        on_demand = ["playwright", "crawl4ai", "searxng", "pymupdf", "qdrant_fastembed", "ffmpeg", "yt_dlp", "faster_whisper", "kokoro", "docling", "paddleocr", "remotion", "docker", "ollama", "comfyui"]
        return {
            "strategy": "control-plane-local-heavy-work-on-demand",
            "always_on": always_on,
            "on_demand": on_demand,
            "normal_target_mb": int(os.environ.get("AMAURA_RAM_NORMAL_TARGET_MB", "1500")),
            "burst_limit_mb": int(os.environ.get("AMAURA_RAM_BURST_LIMIT_MB", "2500")),
            "absolute_limit_mb": int(os.environ.get("AMAURA_RAM_ABSOLUTE_LIMIT_MB", "3000")),
            "pressure_limit_mb": int(os.environ.get("AMAURA_RAM_PRESSURE_LIMIT_MB", "1000")),
            "heavy_workers_max": 1,
            "idle_heavy_services": 0,
            "avoid_simultaneous": ["ollama", "docker", "playwright", "crawl4ai", "browser_use", "faster_whisper", "docling", "paddleocr", "remotion", "comfyui", "local_video_generation"],
            "recommended_concurrent_agent_runs": 2,
            "reason": "The control plane stays resident; heavy capabilities are disposable, pressure-aware and serialized. Local LLM + browser/media/model jobs should not overlap on 8 GB.",
        }


__all__ = [
    "CapabilityRoute",
    "CapabilityRouter",
    "CompanyResource",
    "ExecutionMode",
    "RESOURCE_CATALOG",
    "RESOURCES_BY_KEY",
    "ResourceTier",
]
