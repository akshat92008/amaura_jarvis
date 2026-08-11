# Amaura JARVIS v5.2 Changelog

## Security / execution hardening

- Disabled untrusted repository Git hooks for all Amaura-managed Git operations.
- Rejected repository-local executable clean/smudge/process filters, merge drivers, external diff/textconv commands and active fsmonitor.
- Routed post-merge validation through `SecureVerifierRunner`; removed direct host test execution.
- Tightened the native macOS verifier to a deny-by-default sandbox profile and redacted verifier output before persistence.
- Expanded Antigravity security preflight from global settings to effective project permissions plus global/workspace hooks/plugins/MCP customizations.
- Added explicit project selection to autonomous `agy` calls.
- Converted Antigravity from blocking `subprocess.run` to supervised `Popen` with `stream-json` progress, cancellation, timeout, memory-pressure termination and heavy-worker admission.
- Persisted Antigravity execution phases/PID/base commit and fail closed on unreconciled prior starts.
- Added low-level founder/operator authority for founder-trusted memory writes/deletes.
- Added cross-process MissionRunner leader locking.

## Product correctness

- Changed public chat, voice, explicit-goal API, agent, ExecutiveKernel and desktop defaults to Antigravity.
- Removed the normal silent fallback from unavailable Antigravity to internal coding.
- Updated desktop backend terminology and Antigravity mission activation semantics.
- Added executive provider/model/fallback provenance to founder-facing responses.
- Added durable, throttled Antigravity progress metadata for Activity/mission inspection.

## Testing

- Added `tests/test_amaura_jarvis_v52.py` with adversarial coverage for public defaults, memory authority, Git hooks, executable Git config, Antigravity project/workspace policy, physical process cancellation and desktop defaults.
- Final collection: 342 application tests + 5 coding-engine tests = 347 tests.
