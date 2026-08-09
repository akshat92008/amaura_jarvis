# Amaura Company OS v2.2.0 — Independent Build and Verification Report

**Build date:** 2026-08-05  
**Baseline:** Amaura Company OS v2.1.0  
**Result:** v2.2.0 Distribution Control Plane

## Verdict

The uploaded v2.1.0 archive was independently extracted and retested before modification. Its 167-test baseline passed. v2.2.0 adds the missing operational layer between content production and real distribution.

The system is suitable as a **governed autonomous internal workforce for early-stage Amaura Labs**. It can now maintain founder objectives, execute internal company programmes, stage immutable content packages, wait for founder authority, automatically enqueue approved due publications, verify exact provider receipts, quarantine ambiguous public side effects, and feed measured performance back into future content decisions.

It is not an unrestricted autonomous company. Public publishing, outreach, deployments, spending, legal commitments, credentials and destructive production actions remain founder-controlled.

## Phase built

- Immutable publication packages bound to approved content asset SHA-256 hashes.
- Founder approval tasks containing the exact title, body, platform, timing and asset set.
- Timezone-aware scheduling and automatic due-publication enqueue from autopilot.
- Official provider/self-hosted bridge contract with idempotency-key and payload-digest echoes.
- Signed provider receipt verification against the exact approved payload.
- No blind replay after ambiguous timeouts; events enter reconciliation quarantine.
- Cross-worker exactly-once outbox enqueue for the same publication.
- Distribution queue and CLI operations.
- 24h, 72h, 7d and 30d analytics windows.
- Evidence-backed deterministic lessons for hooks, packaging and controlled experiments.

## Verification

| Check | Result |
|---|---:|
| Baseline v2.1 suite before changes | 167 passed |
| Final complete suite | **174 passed, 0 failed** |
| Distribution-focused suite | **7 passed** |
| Full source compilation | Passed |
| Repository secret scan | Passed; no findings |
| Static source certification | Passed |
| SQLite backup and restore | Passed |
| Adversarial stress | Passed |
| Concurrent workers | 32 |
| Leads processed | 1,000 |
| Prompt-injection inputs detected | 100 |
| Over-limit sends blocked | 20 |
| Duplicate race attempts | 500; one record |
| Wheel build | Passed |
| Offline wheel code/CLI import | Passed |

Ruff was not installed in the build environment, so no Ruff result is claimed. Compilation and the complete automated test suite passed.

## External operation boundary

No real YouTube, Instagram, LinkedIn, X, GitHub, blog, NVIDIA, Ollama or Docker credentials/services were available in the build container. Therefore live external quality, rate limits, OAuth behavior and provider-side idempotency were not certified here.

Before production use, run `amaura init`, configure distinct worker/reviewer models, secure keys, Docker, strict modes, and an official publishing endpoint, then require `amaura doctor` to report `production_ready: true`.
