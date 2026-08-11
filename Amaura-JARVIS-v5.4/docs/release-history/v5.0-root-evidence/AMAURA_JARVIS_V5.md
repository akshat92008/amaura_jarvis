# Amaura JARVIS v5 — Practical JARVIS Executive Runtime

v5 converts the v4.1 cognition layer into a durable executive runtime. The Company OS remains the governed execution substrate; JARVIS is the founder-facing intelligence that resolves context, maintains continuity, creates/controls missions, delegates engineering and company work, observes evidence and stops at authority boundaries.

## Core components

- `jarvis/amaura/cognition.py` — ExecutiveKernel, intent, reference resolution, unified memory, memory consolidation, world model and proactive cognition.
- `jarvis/amaura/brain.py` — typed founder goals, adaptive plans, dynamic DAGs, structural replanning and lifecycle transitions.
- `jarvis/amaura/mission_runner.py` — persistent background mission advancement independent of the initiating HTTP request.
- `jarvis/amaura/model_gateway.py` — one provider-selection/invocation layer for executive cognition.
- `jarvis/amaura/noryx_bridge.py` — strict autonomous engineering bridge plus independent test verification.
- `jarvis/amaura/executor.py` — governed employee/Noryx execution, evidence, cancellation checks and external-executor provenance.
- `jarvis/server.py` — unified chat/voice/mission APIs and background runtime startup.
- `desktop-app/` — JARVIS UI plus Activity, Memory, Company, Approvals and Status.

## Founder interaction target

```text
Founder: "JARVIS, fix the Noryx release lifecycle problems, verify it and prepare the release. Don't deploy."

ExecutiveKernel
  → resolves Noryx/project context
  → creates a bounded engineering mission
  → queues it durably
MissionRunner
  → advances the DAG
Supervisor
  → analysis / architecture / Noryx engineering
Noryx
  → code + its own test evidence
Amaura
  → Git verification + independent test rerun + review
JARVIS
  → replans if necessary
  → prepares the release
  → stops before production deployment
Founder
  → sees result / approval requirement
```

## Authority rule

JARVIS is powerful because it coordinates governed capabilities, not because the conversational language model receives unrestricted shell/browser/company credentials. Founder authority remains explicit for consequential operations.
