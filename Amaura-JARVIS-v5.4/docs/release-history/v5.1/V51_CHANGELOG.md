# Amaura JARVIS v5.1 Changelog

## Antigravity-first coding

- Added `AntigravityDeliveryAdapter` using official `agy` headless print mode.
- Added strict `amaura.antigravity-result.v1` structured result contract.
- Forced Antigravity sandbox mode; permission bypass is forbidden.
- Added Antigravity CLI version gate (`>=1.1.8`).
- Added safe unattended settings preflight and setup utility.
- Added Git delta/diff verification and post-verifier integrity verification.
- Added independent verifier execution in a separate isolation boundary.
- New executive coding requests default to Antigravity.
- Preserved compatibility-only manual Antigravity handoff mode.
- Noryx is now experimental/disabled by default and never selected by the normal Antigravity-first path.

## Mission authority and reliability

- Enforced dynamic-mission authority inside low-level task claiming.
- Pausing freezes review/approval candidates as well as assigned work.
- Added mission-generation tokens to reject stale workers and stale replans.
- Added additional pause/cancel authority checks before coding-result commit/submission.
- Split dynamic mission advancement from unrelated global outbox dispatch.
- Added MissionRunner failure classification, exponential backoff, and configuration/provider waiting states.

## Cognition

- Fixed Ollama executive fallback to use `AMAURA_LOCAL_MODEL` rather than an unrealistic global 70B default.
- Added Ollama model/server availability probing for normal automatic routing.
- Founder conversation now uses `CognitiveModelGateway` first, aligning it with planning/reference/memory routing.

## Verification and installation

- Added `SecureVerifierRunner` with fail-closed production isolation.
- Rejected executable path aliases, inline Python, and shell operators in verifier commands.
- Standard installer now installs the optional voice dependency group.
- Added `Setup_Amaura_Antigravity.command`.
- Added engineering-readiness API/status information for Antigravity, Noryx, cognition, and verifier mode.
- Updated desktop status polling and version contract to 5.1.0.

## Regression

- 334 application/JARVIS/Company OS tests pass.
- 5 coding-engine tests pass.
- Total: **339/339**.
- Python compilation passes.
- Electron main/preload/HUD syntax checks pass.
