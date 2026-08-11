# Amaura JARVIS v4.1 — Executive Cognition Layer

Amaura JARVIS v4.1 keeps the complete Company OS and upgrades the founder-facing cognition path.

## One assistant

Every founder message can enter `ExecutiveKernel`. It classifies the request as conversation, status, memory, or governed mission. Ordinary conversation never receives unrestricted mutation tools. Executable work is converted to a typed `GoalRequest` and enters the existing policy, supervisor, evidence, review, approval, outbox and audit infrastructure.

## Adaptive planning

`GoalCompiler` uses a configured model automatically when model credentials are available and validates the resulting DAG against registered agents, budget limits, risk limits and an allowed action vocabulary. The deterministic planner remains a fail-safe fallback. External consequences such as publication, payments, destructive actions and production deployment are not invented by the dynamic planner; they remain behind explicit governed workflows.

## Structural replanning

Failed tasks are preserved as immutable history. A replan adds diagnostic/replacement nodes, can change owner/backend/decomposition, and rewires downstream dependencies to the replacement terminal node. Plan revisions are persisted in the goal metadata and audit/event streams.

## Unified executive memory and world model

`UnifiedMemoryService` is the executive retrieval/write facade. CompanyStore is canonical for new personal/project/episodic memories. Legacy UserMemory, ConversationMemory, vector-memory and old v4 namespaces are read as secondary sources so older context remains available. `WorldModel` persists the current programmes/tasks/approvals/alerts snapshot; `ProactiveCognition` continuously derives bounded insights while the server runs. Optional internal investigations can be enabled with `AMAURA_JARVIS_PROACTIVE_INVESTIGATIONS=1`.

## Noryx engineering backend

Noryx must return the exact `amaura.noryx-result.v2` schema. A successful result requires changed-file manifest, structured passing test evidence, evidence items and a non-empty summary. Amaura independently verifies the Git delta and diff hash, rejects secret leakage through the subprocess environment, and then sends the task through independent Company OS review. `NexusDeliveryAdapter` remains a compatibility alias for older callers.

Real Noryx coding quality still has to be qualified against an installed Noryx build and unseen repositories; bridge/unit tests prove the contract and governance plumbing, not Claude-Code-class engineering intelligence.

## Voice

The voice engine now routes wake-word/push-to-talk utterances into the same ExecutiveKernel, uses continuous utterance STT when SpeechRecognition/PyAudio are available, supports interruptible TTS/barge-in, and reports measured cognition latency. It intentionally does **not** claim token-level streaming STT/TTS. Mission execution through a backend voice session requires an authenticated Amaura operator session.

## Desktop

The Electron app is still sandboxed (`contextIsolation`, `nodeIntegration=false`, Electron sandbox, denied permission requests) and now opens on the unified JARVIS conversation view. Activity remains available for inspecting mission plans, execution state and evidence.

## Safe defaults

- `AMAURA_JARVIS_LLM_PLANNER=auto`
- `AMAURA_JARVIS_INTENT_MODEL=auto`
- `AMAURA_JARVIS_PROACTIVE=1`
- `AMAURA_JARVIS_PROACTIVE_INVESTIGATIONS=0`
- legacy direct tools remain disabled
- external consequences retain existing approval boundaries

## Qualification boundary

Source regression tests can prove repository-level reliability contracts. Production readiness additionally requires the target Mac, installed providers/Noryx, macOS permissions, pinned sandbox image, real credentials, private evaluation pack and soak testing.
