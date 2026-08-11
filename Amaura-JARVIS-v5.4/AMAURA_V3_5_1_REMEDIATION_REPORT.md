# Amaura Company OS v3.5.1 — Security and Reliability Remediation

> **Historical report:** retained for traceability. It does not represent the current production-readiness verdict.


## Release purpose

v3.5.1 is a traceable security and reliability patch over v3.5.0. It preserves the governed workforce, CRM, messaging, publishing, Git delivery, venture, evidence, review, approval, desktop, and operating workflows while correcting the independent-audit blockers.

## Closed blockers

- All external or unknown outbox operations now fail closed to reconciliation after ambiguous lease expiry; iMessage, CRM, private drafts, email, and publishing cannot be silently replayed.
- Governed and legacy read-only tools share the same workspace-confinement, sensitive-path, and SSRF boundary.
- Tool outcomes use a typed result envelope, preventing JSON errors from being presented as successful work.
- Historical audit rows are never silently re-signed. Stripped or mixed integrity metadata faults the ledger and blocks new writes until an explicit controlled migration or recovery.
- Desktop startup uses an ephemeral loopback port, per-launch secret, HMAC challenge, expected child PID, and version verification before credentials are sent.
- Packaged desktop mode requires a self-contained backend sidecar; system Python is not trusted as a deployment dependency.
- The desktop source has a zero-dependency lockfile and a checksum-pinned Electron assembly path.
- Release wheels and source ZIPs are deterministic, and the release emits SHA-256 sums, SPDX SBOM, provenance, and optional detached Minisign signatures.
- CI uses immutable GitHub Action commit pins and validates the desktop secure-build contract.
- Personal machine paths and obsolete workforce, workflow, package, and test counts were removed from active documentation and tooling.
- The repository scanner now detects provider tokens, private keys, JWTs, credentialed URLs, and generic secret assignments.

## Verification contract

The release is accepted only when compilation, the isolated process-sharded regression suite, both concurrency/adversarial stress suites, static source certification, clean secret scanning, deterministic dual builds, wheel installation smoke, and desktop source validation pass.

## Deployment boundary

Source certification does not authorize unattended production. Real provider credentials, distinct worker/reviewer models, Docker/image digest validation, private evaluation packs, target-Mac desktop signing/notarization, backup drills, and live provider crash-injection certification remain mandatory deployment inputs. The runtime must continue to report `production_ready: false` until those environment-specific gates pass.
