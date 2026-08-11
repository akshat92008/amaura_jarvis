# Amaura JARVIS v5.0 changelog

## Executive autonomy
- Added persistent `MissionRunner`; normal mission submission is durable/background by default.
- Fixed plan-only autonomy: hierarchy/tasks are `DRAFT` and globally unclaimable until explicit activation.
- Hard-held Antigravity missions and fail-closed executor handling prevent internal fallback.
- Added activate/resume, pause and cancel mission lifecycle APIs and natural-language mission control.
- Added late-result rejection for paused/cancelled in-flight workers.
- Added consistent dynamic hierarchy roll-up.

## Cognition
- Unified normal conversation, status, memory, missions and mission control through `ExecutiveKernel`.
- Added reference resolution over persisted work with optional model-assisted selection from bounded candidates.
- Added exact `CognitiveModelGateway` for OpenRouter/OpenAI/Anthropic/NVIDIA/Groq/Ollama.
- Added model-assisted memory consolidation and optional semantic reranking without elevating model-generated memory to founder authority.
- Added provenance/trust-labelled memory, temporal supersession history, entity/relation indexing and graph context.
- Expanded persistent world state with history/trends and proactive correlated-failure/stale-work detection.
- Hardened planner and memory prompts against instruction injection from internal/untrusted context.

## Engineering
- Strengthened Noryx `amaura.noryx-result.v2` validation.
- Added independent re-execution of Noryx-declared passing test commands.
- Added secret-minimized independent verification environment.
- Added external executor/model provenance for strict independent review.
- Preserved legacy Nexus compatibility without treating it as the canonical engineering backend.

## Desktop / API
- Mission UI now uses Activate/Pause/Resume/Cancel lifecycle instead of synchronous manual `/run` execution.
- Added background Activity/approval/proactive polling.
- Added MissionRunner status to system status view.
- Backend/desktop package version upgraded to 5.0.0.

## Qualification
- Added v5 contract tests for autonomy holds, persistent mission queuing, independent Noryx verification, provider routing, memory provenance graph, reference-based mission control, hierarchy roll-up and external-executor model provenance.
- Full collection: 327 tests.
