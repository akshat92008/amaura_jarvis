# Amaura JARVIS v5.2 — Execution Boundary Hardened

v5.2 keeps the v5.1 ExecutiveKernel, Company OS, persistent MissionRunner, memory/world model, structural replanning, approvals/evidence and Antigravity-first strategy. It concentrates on the trust boundary between an autonomous coding agent and the founder's Mac.

## Critical invariants

1. Founder coding requests route to Antigravity by default; missing/unsafe Antigravity is a visible blocked configuration, not a silent internal-code fallback.
2. `plan_only`, pause and cancel are enforced at low-level task claim/review/execution boundaries.
3. Active Antigravity execution is physically terminated on pause/cancel, not merely ignored afterward.
4. Repository hooks and executable Git configuration cannot execute during Amaura-managed Git lifecycle operations.
5. Repository tests are never treated as safe merely because their launcher is `pytest`/`npm`/`cargo`; verification uses an isolation runner before and after merge.
6. Antigravity global settings, project-scoped permissions and executable global/workspace customizations are all part of the security preflight.
7. Founder-trusted memory can only be mutated with founder/operator authority.
8. Antigravity consumes Amaura's heavyweight-resource budget and process-tree memory is monitored.
9. Unreconciled executor-start records fail closed after a crash instead of blindly duplicating the engineering job.
10. Evidence records the real executive/model provenance and Antigravity executor model provenance.

This is a source/regression-qualified release candidate, not a claim of production-proven autonomous AGI.
