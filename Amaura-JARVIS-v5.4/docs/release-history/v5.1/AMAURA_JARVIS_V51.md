# Amaura JARVIS v5.1 — Antigravity-First Executive Engineering

v5.1 keeps the v5 persistent ExecutiveKernel/Company OS architecture and replaces the unfinished-engineering assumption with a governed Antigravity CLI production path.

## Core architecture

```text
Founder
  ↓
ExecutiveKernel
  ├─ intent / reference resolution
  ├─ unified memory / world state
  └─ adaptive planner
        ↓
Persistent MissionRunner
        ↓
Amaura Supervisor
   ┌────┴───────────────┐
   │                    │
Company workers   Repository engineering
                         ↓
                 isolated Git worktree
                         ↓
                 Antigravity CLI (`agy`)
                         ↓
                 typed result contract
                         ↓
                 observed Git delta
                         ↓
              independent isolated tests
                         ↓
                 independent review
                         ↓
               policy / approval boundary
                         ↓
                    final action
```

## Security invariants

1. JARVIS never grants its conversational model unrestricted tool authority.
2. Antigravity is invoked without Amaura governance secrets or generic cloud-model credentials.
3. `--sandbox` is forced and the permission-bypass flag is forbidden.
4. Antigravity global settings are preflighted for safe unattended execution.
5. Repository output is verified from Git, not from the coding agent's narration.
6. Verification is a second execution boundary and does not trust Antigravity's test receipt.
7. Held/paused/cancelled/stale-generation missions are rejected by the low-level execution boundary.
8. Consequential external actions remain governed by the existing Amaura approval/outbox architecture.
9. Noryx is retained but disabled by default while it is experimental.

## What remains outside source certification

Source certification cannot establish the reliability of Google's installed CLI, its account state/model availability, target-Mac containment behavior, private unseen repository outcomes, or real external integrations. Those are target-environment qualification requirements and keep `production_ready=false` in v5.1.
