# Amaura JARVIS v4.1 changelog

- Added a single `ExecutiveKernel` so chat, status, memory and missions share one founder-facing cognition route.
- Enabled validated LLM planning automatically when configured models are available; deterministic planning remains fail-safe fallback.
- Replaced retry-only failure handling with structural DAG mutation, dependency rewiring and persisted plan revision history.
- Added `UnifiedMemoryService`, persistent `WorldModel`, and ambient `ProactiveCognition`.
- Strengthened Noryx to an exact v2 evidence contract with independent Git delta/diff verification and secret-isolated subprocess environment.
- Routed continuous utterance voice/PTT into actual JARVIS cognition with barge-in and measured latency; token-level streaming is not claimed.
- Added a private cognition + real-repository Noryx benchmark harness for unseen qualification packs.
- Unified the desktop UX around JARVIS conversation, with Activity, Memory, Company, Approvals and Status secondary surfaces.
- Preserved all previous Company OS, governance, approval, evidence, integration, security, resource-control and autopilot capabilities.
- Re-generated root release evidence for v4.1 and archived pre-v4.1 reports under `docs/release-history/`.
