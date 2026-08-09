# Amaura OSS Capability Layer

Amaura keeps governance, approvals, durable state, evidence and audit in its own control plane. Open-source projects are replaceable workers behind `CapabilityRuntime`; they do not become a second orchestration system.

## Integrated adapters

- Playwright: rendered-page extraction and screenshots.
- Crawl4AI: bounded website crawling to structured Markdown.
- Browser Use: opt-in read-only browser research fallback with domain restrictions, public-only egress proxy and dangerous tools removed in code. Disabled by default.
- SearXNG: configured self-hosted metasearch JSON API.
- Docling: rich document conversion.
- PyMuPDF: lightweight PDF text/render fast path.
- PaddleOCR: OCR fallback.
- LlamaIndex Core: chunking/node preparation only; it does not replace Amaura workflows.
- Qdrant + FastEmbed: lightweight semantic company memory, local by default unless `QDRANT_URL` is configured.
- faster-whisper: CPU/int8 transcription.
- Kokoro: local TTS/voiceover.
- FFmpeg: probe/transcode/subtitles/concat plus narration/video muxing.
- Remotion: bootstrap a pinned Amaura video template and render Reels/Shorts/landscape compositions with a local install.
- ImageMagick/libvips: deterministic image resizing/thumbnail transforms.
- yt-dlp: metadata inspection plus explicit, rights-confirmed media ingestion; downloads are disabled by default.
- ComfyUI: optional HTTP API for pre-approved API-format workflows; recommended remote/on-demand on 8 GB machines.
- MCP: stdio client for founder-owned registry entries only. AI requests use `server_id`; executable path/hash, args, env exposure, tools and sandbox/network policy are operator-pinned.
- Langfuse: optional observability mirror. Amaura's audit/evidence store remains authoritative.
- Antigravity: first-class governed engineering handoff packet while no official automatable interface is assumed.

## 8 GB Mac policy

`v3.6.1` uses a pressure-aware policy instead of a 5.6 GB reservation: normal capability target 1500 MB, temporary burst 2500 MB, absolute child-tree ceiling 3000 MB, and pressure mode 1000 MB. Playwright, Crawl4AI, Browser Use, Docling, PaddleOCR, Qdrant/FastEmbed, faster-whisper and Kokoro run in disposable subprocesses; Remotion is an external child process. Heavy jobs are host-wide serialized through a durable reservation ledger, and actual child-tree RSS plus swap growth can terminate a runaway job.

ComfyUI is treated as an external API service, and localhost ComfyUI is disabled by default on the 8 GB profile. Large image/video models should normally run remotely or only when Amaura is otherwise idle. The capability registry never starts ComfyUI, Qdrant, SearXNG or Langfuse servers automatically.

## Install

Light/normal Mac profile:

```bash
python scripts/setup_oss_capabilities.py browser memory media observability media-system
```

Add document AI only if you need it:

```bash
python scripts/setup_oss_capabilities.py documents
```

Check without installing:

```bash
python scripts/setup_oss_capabilities.py --check
```

## Environment

Configure only services you actually run:

```bash
AMAURA_RAM_NORMAL_TARGET_MB=1500
AMAURA_RAM_BURST_LIMIT_MB=2500
AMAURA_RAM_ABSOLUTE_LIMIT_MB=3000
AMAURA_RAM_PRESSURE_LIMIT_MB=1000
AMAURA_BROWSER_USE_AGENT_ENABLED=0
SEARXNG_URL=http://127.0.0.1:8080
AMAURA_QDRANT_PATH=.amaura-qdrant
QDRANT_URL=
QDRANT_API_KEY=
COMFYUI_URL=
AMAURA_ALLOW_LOCAL_COMFYUI=0
AMAURA_MEDIA_DOWNLOADS_ENABLED=0
AMAURA_MCP_TOOL_CALLS_ENABLED=0
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_BASE_URL=
AMAURA_ANTIGRAVITY_ENABLED=1
AMAURA_REMOTION_VERSION=4.0.477
```

## Recommended routing

- Web/lead research: SearXNG -> Crawl4AI -> Playwright -> Browser Use fallback.
- Documents: PyMuPDF fast path -> Docling rich path -> PaddleOCR scan fallback -> LlamaIndex chunking -> Qdrant/FastEmbed.
- Reels/video: Kokoro -> ImageMagick/libvips -> pinned Remotion template -> FFmpeg narration mux/validation. ComfyUI is optional for generated visuals.
- Media ingest: yt-dlp metadata is available when installed; downloads require both `AMAURA_MEDIA_DOWNLOADS_ENABLED=1` and explicit `rights_confirmed=true`.
- Engineering: Amaura creates a structured Antigravity handoff; founder remains in the loop.

Use `amaura_capability_plan` for deterministic pipeline recommendations, `amaura_capability_health` for availability, and `amaura_execute_capability` for governed execution.


## Safety defaults

- Agentic Browser Use is opt-in; deterministic Playwright/Crawl4AI are preferred.
- Arbitrary MCP tool calls are not executable by AI employee roles; direct operator calls require an explicit environment gate and founder approval.
- yt-dlp downloading is off by default and intended only for media you are authorized to use.
- Local ComfyUI is off by default on the 8 GB Mac profile.
- Antigravity remains a founder-reviewed handoff boundary; Amaura does not pretend to control an undocumented interface.
