# Amaura Company OS v3.5.1 Verification Report

Date: 2026-08-05

## Verdict

The complete source tree passes compilation, the 233-test isolated regression suite, adversarial concurrency stress, static source certification, repository secret scanning and SQLite backup/restore verification. It is a **source-certified, founder-controlled local operating system**, not an unconditional claim that every external integration is live.

External publishing, communication, production deployment, payments, legal commitments and high-risk changes remain approval-gated. Live production mode fails closed until the target Mac is configured and `amaura doctor` reports `production_ready: true`.

## Verified in the build environment

| Gate | Result |
| --- | --- |
| Complete repository test suite | **233 passed; 0 failed** |
| Full Python compile check | Passed for `jarvis`, `aimodel`, `scripts`, and `tests` |
| Static source certification | Passed; no source blockers |
| Repository credential scan | Passed; no findings |
| SQLite backup restoration | Passed; integrity `ok`, 0 foreign-key violations |
| Workforce contract | 57 governed roles across 13 departments; no missing tools or invalid reviewers |
| Workflow contract | 21 durable workflows registered |
| Legacy execution boundary | Direct privileged tools disabled by default; workspace and command escape regressions passed |
| Strict Git regression | Exact commit merge, drift rejection and rollback passed |
| Outbox regression | Leases, ownership and ambiguous-send reconciliation passed |
| Adversarial stress | 1,000 leads, 32 workers, 100 adversarial inputs, 500 duplicate-race attempts |
| Wheel build | Passed |

## Stress evidence

- 1,000 leads ingested.
- 32 concurrent workers.
- 100 adversarial inputs detected.
- 60 provider-confirmed messages.
- 20 over-limit sends blocked.
- 500 duplicate-race attempts created one record.
- SQLite integrity: `ok`.
- Foreign-key violations: zero.
- Journal mode: WAL.

## Controls exercised

- Durable task leases, heartbeats, bounded retries and crash recovery.
- Worker-owned provider outbox leases with retry and reconciliation states.
- Ambiguous external sends quarantined instead of automatically replayed.
- Independent reviewer assignment and distinct-model routing contracts.
- Content-addressed evidence and acceptance-criterion coverage.
- Founder approval bound to exact evidence, cost and Git state.
- Isolated Git workspaces, head-drift checks, post-merge validation and rollback.
- Prompt-injection quarantine, SSRF controls, path controls and credential redaction.
- Absolute-path, traversal, symlink-escape and shell-chaining rejection in legacy workspace execution.
- Transactionally consistent SQLite backups with restoration verification.
- Direct legacy REST/WebSocket tool execution disabled by default.
- Fable dashboard disabled by default and authenticated when explicitly enabled.

## Live certification still required

After local installation, run:

```bash
.venv/bin/amaura doctor
```

Production operation is allowed only when the output reports:

```json
{
  "production_ready": true
}
```

The live gate requires machine-specific secrets, strict evidence/review/Git modes, post-merge validation, Docker health, configured NVIDIA and/or verified local fallback routing, and distinct worker/reviewer models. External platform credentials must be added only through approved adapters.
