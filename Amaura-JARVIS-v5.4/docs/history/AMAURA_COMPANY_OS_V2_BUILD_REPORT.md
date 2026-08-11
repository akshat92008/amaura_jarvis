# Amaura Company OS v2.1.0 — Verified Build Report

## Delivery verdict

The repository has been upgraded from the audited JARVIS prototype into a governed, free-first company operating kernel for Amaura Labs. The source is certified and the internal autonomous cadence is operational. Live production mode remains intentionally fail-closed until deployment-specific secrets, reviewer-model separation, strict modes, NVIDIA/local model routing and the Docker sandbox are configured and verified on the target MacBook.

## Implemented

- 52 governed AI employees across 13 operational departments.
- Nine durable, dependency-ordered company workflows.
- Safe autonomous company cadence with idempotent weekly operating reviews and founder briefings.
- Free-first capability router covering built-in, open-source, free API, existing-subscription and paid-API tiers.
- MacBook M3 8GB resource profile with on-demand heavy workers and two recommended concurrent executions.
- Founder-controlled Antigravity engineering handoffs and Google Flow scene-production handoffs.
- NVIDIA API resource adapter as the default configured cloud-intelligence option.
- Company blueprint, department missions, daily/weekly/monthly cadence and autonomy boundaries.
- New strategy, product discovery, operations, finance, security, legal, customer success, community and distribution employees.
- Unique tool-schema enforcement and read-only legacy tool mode by default.
- Direct WebSocket tool execution removed and `/api/tool` disabled by default.
- Remote sensitive HTTP reads protected; WebSocket origins allowlisted; sessions bounded.
- Legacy Fable API/dashboard disabled by default.
- Legacy workspace execution constrained against absolute paths, traversal, symlink escape, shell chaining and non-allowlisted executables.
- Full Python compilation now includes the previously omitted `aimodel` directory.
- Corrected signed-receipt fixture in the adversarial stress harness.
- Updated documentation, system map, quick start and MIT licence.

## Verification evidence

### Compilation

`python3 -m compileall -q jarvis aimodel scripts tests` — passed.

### Regression suite

167 tests passed.

### Adversarial concurrency stress

- 1,000 leads ingested.
- 32 concurrent workers.
- 100 adversarial inputs detected.
- 60 provider-confirmed messages.
- 20 over-limit sends blocked.
- 500 duplicate-race attempts produced one record.
- SQLite integrity: `ok`.
- Foreign-key violations: zero.
- Journal mode: WAL.

### Release gate

- Static source certification: passed.
- Security scan: passed with no findings.
- Backup/restore integrity: passed.
- Live production readiness: not yet passed, by design.

## Deployment blockers that remain

These are environment and operations requirements, not hidden source failures:

- Generate separate operator and founder approval keys.
- Configure provider receipt and reviewer-attestation signing keys.
- Configure distinct worker and reviewer models.
- Enable strict evidence, review and Git modes.
- Configure post-merge validation.
- Configure NVIDIA API and/or a verified local zero-cost routing fallback.
- Install and validate Docker for governed code execution.
- Add external platform credentials only through approved adapters.

## Honest operating boundary

This system can coordinate research, planning, product discovery, engineering tasks, content pipelines, internal reporting and controlled business workflows. It does not independently make payments, accept legal commitments, publish externally, send mass outreach, grant credentials, delete production data or change company strategy. Those actions remain founder-controlled.
