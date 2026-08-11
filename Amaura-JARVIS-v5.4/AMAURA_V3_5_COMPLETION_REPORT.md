# Amaura Company OS v3.5.0 — Governed Autonomy Completion Report

> **Historical report:** retained for traceability. It does not represent the current production-readiness verdict.


**Release date:** 2026-08-06  
**Source baseline:** Amaura Company OS v3.4.0  
**Release objective:** Preserve the complete Amaura workforce and feature surface while eliminating alternate authority paths, strengthening external-action durability, and making source certification reproducible.

## Executive result

Amaura Company OS v3.5.0 is a complete hardened source release for founder-controlled autonomous operation. CRM, email, iMessage, publishing, Git delivery, ventures, reminders, calendar, company planning, model routing, evidence, approvals, desktop control, and all existing workforce functions remain present.

Consequential actions now converge on a governed execution architecture:

```text
Founder objective / authenticated operator request
                    ↓
             typed command bus
                    ↓
       policy + exact payload classification
                    ↓
    worker evidence + independent review
                    ↓
      founder approval when policy requires
                    ↓
       durable outbox / governed executor
                    ↓
 provider receipt + requested/actual provenance
                    ↓
 reconciliation + signed evidence + audit chain
```

The source is certified by automated and adversarial gates. **Production readiness is intentionally target-machine specific** and remains false until the deployed Mac/runtime passes `amaura doctor` with real secrets, models, sandbox, provider credentials, external trust storage, and live evaluation evidence. This prevents a source archive from falsely declaring an unconfigured machine production-ready.

## Remediation delivered

### 1. One authority boundary

- Replaced prefix-based `amaura_*` access with explicit tool authority classes.
- Default legacy tool mode is disabled.
- Read-only mode contains only enumerated pure-read tools.
- Full legacy mode requires a separate break-glass flag.
- CRM and iMessage are preserved but execute through typed commands and the durable provider outbox.
- External publishing, email, CRM, iMessage, Git delivery, and venture actions retain approval, idempotency, receipt, evidence, and reconciliation controls.

### 2. Cryptographic identity separation

- Reviewer identity is derived from a reviewer-specific key, never from request-body text.
- Reviewer IDs and keys must be unique.
- Worker, reviewer, operator, approval, evidence, audit, provider-receipt, and evaluation keys are independently validated.
- Review attestations bind requested model, actual model, provider, worker evidence, decision, and submission hash.

### 3. Single runtime configuration boundary

- Removed active credential discovery from legacy `~/Desktop/JARVIS` and `aimodel/config.json` locations.
- `.env.amaura` is the canonical runtime configuration source.
- Runtime templates are fail-closed and require distinct production secrets.
- Audit checkpoints and backups can be required on storage separate from the live database.

### 4. Exact model and provider provenance

- Local, balanced, and cloud routes use explicit model identifiers.
- Restricted data remains local.
- Cloud-only and reviewer routes cannot silently fall back.
- Receipts record requested and actual provider/model, fallback reason, usage, latency, provider request identifiers, and a non-secret credential fingerprint.
- Reviewer execution fails closed when provider/model independence is not proven.

### 5. Behavioral model certification

- Added HMAC-authenticated private evaluation packs.
- Production mode can require at least 20 private cases.
- Evaluation checks semantic requirements, forbidden behavior, structural tool calls, argument validity, route provenance, and safety failures.
- Cloud evaluations use the exact deployed provider/model with fallback disabled.
- Public built-in cases remain a development smoke test, not production certification.

### 6. Durable communications and CRM

- Added renewable Gmail OAuth refresh-token support.
- Hardened n8n transport with explicit enablement, bounded payloads, redirect denial, DNS-pinned public transport, and signed response contracts.
- CRM and iMessage use signed exact-payload provider receipts.
- Ambiguous external outcomes enter reconciliation rather than automatic replay.
- AppleScript user content is passed as arguments instead of interpolated into executable source.
- Calendar and Reminders now preserve requested time, duration, notes, and content.

### 7. Crash and poison-event containment

- Added bounded cycle exception handling.
- Added durable consecutive-failure state.
- Added exponential backoff and a crash-loop circuit breaker.
- Deterministic poison events disable autopilot and escalate instead of repeatedly restarting.
- The verified test runner launches actual per-shard pytest operating-system processes and terminates timed-out process groups.

### 8. Trust and evidence isolation

- Audit checkpoints are database-specific.
- Cross-run checkpoint collision is eliminated.
- Signed audit entries and external head checkpoints remain enforced.
- Evidence references bind bytes and signed provenance metadata.
- Production readiness can require trust checkpoints and backups outside the live data directory.

### 9. Sandbox and desktop completion

- Added immutable Docker image-digest support.
- Added bounded container start and cleanup commands.
- Completed missing Electron renderer, icon, and entitlement assets.
- Enabled renderer sandboxing.
- Denied external navigation, new windows, and permission requests.
- Kept API secrets in the main process and exposed a constrained authenticated IPC bridge.
- Added backend restart backoff and circuit breaking.

### 10. Clean release engineering

- Added an allowlisted deterministic source builder.
- Excluded runtime databases, WAL files, evidence, caches, bytecode, secrets, private keys, logs, build state, and node modules.
- Added archive-member validation.
- Built and smoke-installed the Python wheel in an isolated target directory.
- Verified packaged HUD assets and all 59 prompt profiles.
- Added CI gates for Python 3.11/3.12, compilation, tests, static certification, security scan, stress tests, release building, and desktop source completeness.

## Independent verification executed

| Gate | Result |
|---|---:|
| Python compilation | Pass |
| Focused P0/security regressions | 62 passed |
| Full repository tests | **221/221 passed** |
| Warnings promoted to errors | Pass |
| Static source certification | Pass |
| Repository security scan | 269 files, 0 findings |
| Acquisition concurrency/adversarial stress | Pass |
| Leads ingested | 1,000 |
| Concurrent workers | 32 |
| Prompt-injection payloads detected | 100 |
| Provider-confirmed messages | 60 |
| Daily-limit sends blocked | 20 |
| Duplicate race attempts | 500 |
| Duplicate records created | 1 |
| Trust multi-process stress | Pass |
| Signed audit entries | 640 across 32 processes |
| Recomputed history detected | Pass |
| Venture admission race | 1 started, 31 blocked |
| Provenance tamper detection | Pass |
| Desktop JavaScript syntax | Pass |
| Clean wheel build and isolated install smoke | Pass during release build |

The 221 tests were executed in four deterministic ranges of 60, 60, 60, and 41 nodes because the interactive execution host imposes a per-command wall-time limit. Every collected node completed successfully with `PYTHONWARNINGS=error` and third-party pytest plugin autoload disabled.

## Feature-preservation statement

No major Amaura business capability was intentionally removed. The remediation changes **how high-impact capabilities are authorized and executed**, not whether they exist.

Preserved capabilities include:

- Autonomous objective and programme planning
- 57 governed employee roles across 14 departments
- 59 packaged role/specialist prompts
- 21 durable workflows and 14 default founder objectives
- Lead discovery, qualification, outreach, follow-up, CRM, and sales operations
- Email, iMessage, reminders, calendar, n8n, and private/publication adapters
- Product, coding, repository intelligence, QA, Git delivery, and rollback
- Content research, production, distribution, analytics, and feedback loops
- Amaura Ventures opportunity research, evidence scoring, experiments, and kill/continue decisions
- Finance, security, compliance, customer success, operations, and founder briefings
- Local, balanced, and cloud model routing
- Evidence vault, approvals, independent review, audit chain, backups, telemetry, and Mission Control
- Python API/HUD and Electron desktop control plane

## Target-machine production gate

Before enabling unattended external actions, the deployed machine must pass all of the following:

1. Generate unique production keys and reviewer bindings using the supplied setup flow.
2. Place the audit checkpoint and encrypted backup destination outside the live database directory, preferably on an independently synchronized or remote volume.
3. Pin the exact Docker sandbox image digest.
4. Install and verify the configured local models and/or exact cloud models.
5. Sign and configure a private 20+ case evaluation pack, then pass every required worker/reviewer route.
6. Configure real Gmail/n8n/iMessage/CRM credentials and verify exact provider receipts in sandbox or controlled test accounts.
7. Run `amaura doctor` until `production_ready` is true.
8. Complete a controlled live soak covering sleep/resume, reboot, provider expiry, provider ambiguity, Docker failure, network loss, database pressure, disk pressure, and kill-switch recovery.
9. Enable external action classes progressively, beginning with shadow/draft operation and founder approval.

## Environment-dependent validation not executed here

The source archive cannot supply or simulate these deployment facts:

- Real production credentials and reviewer keys
- A live macOS Messages/Calendar/Reminders environment
- Live Gmail OAuth refresh and provider delivery
- A live n8n/CRM deployment
- Docker daemon and the final pinned sandbox image
- Installed Ollama models or paid cloud model routes
- A private production evaluation pack
- Off-device backup/trust storage
- Code-signed/notarized Electron packaging
- A multi-day live soak on the target Mac

`ruff` and `mypy` are enforced in CI but were unavailable from the offline package index in this execution environment. Electron source syntax and security contracts were validated; a complete Electron package install/build was not possible because the available npm registry did not provide Electron.

## Final engineering verdict

Amaura Company OS v3.5.0 closes the critical source-level authority, reviewer-forgery, configuration, provider-provenance, communication durability, crash-loop, sandbox-pinning, desktop, and release-contamination defects identified in v3.4.0.

It is suitable as the hardened codebase for the full Amaura autonomous workforce. It should enter unattended production only after the target machine independently passes the included production doctor and live provider/soak gates. That remaining requirement is deployment certification, not missing source functionality.
