# Amaura Company OS v3.6.0

Amaura Company OS is a governed autonomous workforce for operating Amaura Labs and Amaura Ventures. It coordinates objectives, programmes, specialist agents, independent reviews, founder approvals, CRM, communications, publishing, delivery, evidence, costs, backups, and company-level operating cadence.

## Reliability model

Every consequential action follows one authority path:

```text
Objective → Programme → Task → Worker → Evidence → Independent Review
→ Founder Approval (when required) → Durable Outbox → Provider Receipt
→ Reconciliation → Audit Chain
```

CRM synchronization, email, iMessage, content publication, deployment, spending, deletion, and strategic commitments are preserved. They are not directly callable from ordinary chat. They execute through typed commands, exact payload hashes, leases, idempotency keys, signed receipts, ambiguity quarantine, and reconciliation.

## v3.6.0 free-first operating boundary

- Strict closed-schema tool validation; read-only mode excludes Git diff/history and all legacy direct tools remain disabled by default
- Cryptographically bound reviewer identities; no request-body identity fallback
- Single `.env.amaura` runtime configuration boundary
- Actual provider/model provenance and fail-closed cloud reviewer routing
- Governed CRM and iMessage outbox paths
- Gmail OAuth refresh-token support
- DNS-pinned and receipt-bound n8n transport
- Autopilot crash containment, exponential backoff, and circuit breaker
- Clean release builder that excludes databases, evidence, caches, bytecode, and secrets
- Production checks require audit checkpoints and verified backups outside the primary data directory
- Optional private HMAC-authenticated model evaluation pack to prevent public-suite overfitting
- Isolated test shards to prevent leaked resources from hanging the release gate
- Completed, sandboxed Electron desktop source with a main-process authenticated API bridge
- Shell-free argument-vector execution across packaged legacy Git, command, testing, linting, formatting, dependency, environment, desktop, and generated-agent paths
- Security gate regression detection for shell execution, unsafe read-only tools, and missing schema validation
- Truthful interface status copy derived from readiness boundaries rather than autonomy claims
- Complete locked-component SPDX inventory sourced from `uv.lock`

- Free public-business discovery and robots-aware website enrichment
- Gmail and signed Meta inbox ingestion with approval-queued replies
- Assisted LinkedIn, Instagram, Facebook and WhatsApp outreach packets that never auto-send
- Founder-approved Calendar, Drive, GitHub, analytics, Telegram, social publishing and Nexus actions
- Local invoice/UPI workflow, provider circuit breakers and atomic cross-process publication dispatch

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install ./jarvis-3.6.0-py3-none-any.whl
amaura init
amaura doctor --static
```

`amaura init` now works from the installed wheel, generates distinct authority keys, creates a private `0600` environment file, and chooses separate default trust and backup paths. Configure two distinct worker/reviewer models, create a signed private 20+ case evaluation pack, build and pin the Docker image, then run:

```bash
amaura doctor
python -m jarvis.server
```

For the Docker sandbox:

```bash
docker build -f docker/amaura-sandbox.Dockerfile -t amaura-sandbox:3.6.0 .
```

## Verification

```bash
python -m compileall -q jarvis aimodel scripts tests
python scripts/run_verified_tests.py
python scripts/release_gate.py --static-only
python scripts/stress_amaura.py
python scripts/stress_trust_foundation.py
python scripts/build_release.py
```

The source can be verified without live provider credentials. Production readiness remains environment-specific and requires the target Mac, Docker, installed local models, real provider credentials, signed-key separation, macOS automation permissions, and a live soak test.

## Safe operating posture

Start in shadow mode. Enable one provider at a time, verify exact signed receipts, test token renewal and provider ambiguity, then progressively increase autonomy. Never enable `JARVIS_LEGACY_TOOL_MODE=full` except as a time-bounded founder-controlled break-glass procedure.
