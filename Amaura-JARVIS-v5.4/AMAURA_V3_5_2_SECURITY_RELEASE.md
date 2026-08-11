# Amaura Company OS v3.5.2 — Security Boundary Release

## Scope

v3.5.2 remediates the independent v3.5.1 audit findings that can be fixed in source code and packaging. It does not manufacture environment evidence: live provider authentication, private model performance, macOS permissions, external backup media, release-owner signing keys, and multi-day soak results must still be produced on the deployment machine.

## Security fixes

- Removed `git_diff` and `git_log` from conversational read-only mode.
- Replaced every packaged `shell=True` process call with explicit argument-vector execution.
- Added a restricted shell-free parser for the legacy `run_command` compatibility tool.
- Added strict pre-dispatch validation against every published tool schema.
- Tool contracts now reject incorrect JSON types, missing required fields, unknown properties, unsafe Git revisions, path escapes, and unsafe command operators.
- Direct REST tool and desktop execution now require authenticated, explicit three-switch break-glass mode.
- Extended the release security scanner to fail on shell execution regressions, unsafe read-only Git tools, `os.system`, or missing pre-dispatch schema validation.
- Added adversarial regression tests that reproduce the original injection shape and verify no host marker is created.

## Truth-integrity fixes

- Replaced hard-coded claims that all systems are operational or fully autonomous.
- Startup, voice, WebSocket, and fleet copy now distinguishes interface availability from environment-specific readiness.
- Test generation no longer writes `TODO` or `pass` skeletons; it emits executable interface-contract tests or refuses unsupported generation without creating placeholders.

## Deployment and supply-chain fixes

- Environment initialization now generates every authority secret independently, including reviewer and evaluation-pack keys.
- Default checkpoint and backup locations are separated from the primary data directory.
- Docker sandbox builds now capture the immutable image digest and write it back to the private environment file.
- The SPDX document now inventories exact locked third-party components and their available hashes from `uv.lock`, rather than recording only the Jarvis source package.
- The standalone wheel uses the canonical wheel filename through the rebuilt release bundle.
- The wheel embeds the environment template and sandbox Dockerfile, so `amaura init` no longer depends on a source checkout.
- Reviewer authority bootstrap now replaces embedded placeholders correctly and fails closed if any required authority is not generated.
- Static source certification can run before runtime initialization.

## Honest readiness boundary

This release is suitable for local development and synthetic-data shadow operation after its source gate passes. Real customer data, outbound communications, publishing, deployment, spending, or unattended autopilot remain blocked until `amaura doctor` returns `production_ready: true` on the target machine with real, distinct worker/reviewer routes and a signed private evaluation pack.
