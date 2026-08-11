# Amaura Company OS v3.5.2 — Qualification Report

## Decision

**Source-qualified and ready for local development, synthetic-data testing, and controlled shadow-mode staging. Not yet certified for autonomous production.**

The release fixes the source-code and packaging defects identified in the v3.5.1 audit, including the P0 read-only command-injection path. Production remains fail-closed until the target-machine `amaura doctor` gate verifies real models, providers, keys, Docker, external trust storage, and live operational evidence.

## Verified evidence

- **242/242 pytest nodes passed** across six isolated operating-system shards, with warnings treated as errors and plugin autoload disabled.
- Security scanner v3 passed with zero findings across shell execution, `os.system`, read-only allowlist, secret patterns, and pre-dispatch schema-validation contracts.
- Acquisition stress passed: 32 workers, 1,000 leads, 100 adversarial inputs detected, 500 duplicate attempts collapsed to one record, and daily-limit enforcement passed.
- Trust stress passed: 640 signed audit entries, history-rewrite detection, one-winner venture leasing, provenance separation, and tamper detection.
- Environment bootstrap passed: private `0600` env file, independent authority keys, generated reviewer binding, separated checkpoint/backup defaults, and sandbox digest field.
- Desktop JavaScript and desktop build scripts passed syntax compilation.

## Major remediations

1. Removed `git_diff` and `git_log` from read-only mode.
2. Replaced every packaged `shell=True` invocation with argument-vector execution.
3. Added strict closed-schema validation before tool dispatch, rejecting wrong types, unknown fields, path escapes, unsafe Git refs, and shell operators.
4. Locked direct REST/desktop legacy execution behind authenticated three-switch break-glass mode.
5. Replaced hard-coded autonomy/operational claims with readiness-aware status.
6. Replaced placeholder test generation with executable interface-contract tests or fail-closed refusal.
7. Corrected authority bootstrap and embedded initialization resources in the wheel.
8. Added exact locked third-party components and available hashes to the SPDX SBOM.

## Allowed now

- Local development with legacy mode disabled.
- Synthetic-data qualification.
- Controlled shadow-mode staging after reviewing the local doctor report.

## Still blocked

Do not use real customer data, real company credentials, autonomous outbound communications, public publishing, payments, deployments, or unattended remote operation until the target machine reports `production_ready: true`.

## External qualification still required

- Distinct installed worker and reviewer models and a signed private unseen evaluation pack.
- Live provider authentication, refresh, idempotency, ambiguity, and crash-recovery tests.
- Docker build and immutable digest pinning on the deployment host.
- macOS desktop build, execution, signing, notarization, and permissions validation.
- Detached release-owner signature tied to a known Git commit.
- Independently controlled checkpoint/backup storage, a current dependency advisory scan, and a multi-day fault-injection soak.

## Tooling limitation

The audit host could not obtain the locked Ruff and mypy executables from its package mirror, and Docker/macOS were unavailable. This is recorded as an environment limitation, not represented as a pass. The Docker sandbox definition is aligned to the locked quality-tool versions.
