> **Historical v4.0 artifact.** Current release documentation is `README.md`, `AMAURA_JARVIS_V4_1.md`, `V4_1_CHANGELOG.md`, and `V4_1_VALIDATION.json`.

# Amaura JARVIS v4.0 — Implementation Changelog

## Executive result

This build keeps the v3.6.1 Company OS and adds a general founder-facing assistant layer instead of replacing the existing governance substrate.

## Added

- `jarvis/amaura/brain.py`: GoalRequest/GoalPlan schemas, deterministic + optional model planner, dynamic DAG materialization, persistent world-model memory, status, bounded replanning and supervised execution.
- `jarvis/amaura/noryx_bridge.py`: first-class Noryx bridge with strict JSON task/result contract and environment allowlist.
- Desktop Mission Control: Mission, Chat, Memory, Company, Approvals, Status.
- macOS desktop install/launch commands.
- v4 API routes for goals, goal execution/status, memory and Antigravity handoffs.
- v4 regression tests.

## Hardened

- Retry/replan context is carried into canonical task packets.
- Noryx runs inside Amaura's existing Git worktree path and returns evidence into the existing review chain.
- Legacy Nexus receipt identity is retained for old queued events/integrations.
- Antigravity is fail-honest: a handoff is created, but the system never marks external work complete without evidence.
- Knowledge values now deserialize into their original JSON types for useful world-model context.
- Desktop approval requests can carry the existing dedicated approval credential.
- Desktop backend identity check upgraded to v4 and development launch prefers `.venv/bin/python`.

## Verification

Final tree: 306/306 collected tests passed across isolated bounded pytest groups. Python compileall passed. Electron main/renderer syntax checks passed.

## Qualification boundary

This is not labeled production-ready solely from container tests. Live providers, Noryx executable compatibility, Electron installation, macOS automation permissions and long-duration target-machine soak still need to be validated on the deployment Mac.
