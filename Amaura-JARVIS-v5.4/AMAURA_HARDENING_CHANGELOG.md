# Amaura Hardening Changelog


## 2026-08-06 — Security Boundary Remediation v3.5.2

- Closed the read-only Git command-injection vulnerability.
- Removed all `shell=True` execution from the packaged Python source.
- Added strict runtime tool-schema validation and adversarial argument tests.
- Gated direct REST and desktop command execution behind authenticated break-glass controls.
- Replaced unsupported autonomy/operational UI claims with readiness-gated language.
- Replaced placeholder test generation with executable interface-contract tests.
- Corrected secure environment generation, separated default trust/backup paths, and persisted the sandbox digest.
- Expanded the SPDX SBOM to exact locked third-party components.
- Added source-security regression checks to the certification scanner.

## 2026-08-06 — Security and Reliability Remediation v3.5.1

- Unified fail-closed external-operation replay policy and reconciliation.
- Removed legacy filesystem and network bypasses.
- Added typed tool results, strict audit corruption handling, authenticated desktop child startup, deterministic release artifacts, SBOM/provenance generation, immutable CI action pins, and expanded secret scanning.
- Added blocker-specific regression coverage and isolated process-sharded verification.

# Amaura Company OS Hardening Changelog

## 2026-08-06 — Governed Autonomy Completion v3.5.0

- Replaced prefix-based legacy tool access with explicit immutable authority classes; legacy tools are disabled by default and full mode requires a deliberate break-glass flag.
- Preserved CRM, email, iMessage, publishing, Git delivery, ventures, reminders, calendar, and all workforce capabilities while moving consequential effects behind typed commands, approval policy, durable outbox dispatch, exact receipts, reconciliation, and signed evidence.
- Made manual reviewer identity cryptographically key-bound and removed request-body identity fallback.
- Removed legacy Desktop/JARVIS credential discovery and established `.env.amaura` as the single runtime configuration boundary.
- Added requested-versus-actual provider/model provenance, credential fingerprints, fallback reasons, and fail-closed cloud/reviewer routing.
- Rebuilt model routing for explicit local, balanced, and cloud modes and added authenticated private behavioral evaluation packs with structural tool-call scoring.
- Added renewable Gmail OAuth, hardened n8n transport, exact signed CRM/iMessage receipts, and ambiguity quarantine.
- Replaced interpolated AppleScript with argument-bound execution; calendar and reminder actions now preserve their full requested contract.
- Added poison-event containment, exponential backoff, crash-loop circuit breaking, and durable autopilot failure state.
- Isolated audit checkpoints per database and added production checks for externally separated trust checkpoints and backup destinations.
- Added immutable sandbox-image digest support and bounded container lifecycle commands.
- Completed and sandboxed the Electron source surface with constrained IPC, denied navigation/windows/permissions, and backend restart containment.
- Added a clean allowlisted release builder that excludes databases, evidence, secrets, caches, bytecode, keys, logs, and generated state.
- Expanded adversarial regression coverage for authority bypass, reviewer forgery, provider fallback, private evaluation integrity, AppleScript injection, desktop boundaries, crash loops, and release contamination.

## 2026-08-06 — Trust Boundary Remediation v3.4.0

- Made audit appends cross-process atomic with signed entries and external head checkpoints.
- Added HMAC detection for offline audit-history recomputation.
- Replaced byte-only evidence references with signed provenance manifests binding source, capture time, media type, worker, task, and retrieval metadata.
- Pinned outbound HTTP(S) connections to validated public IP addresses to prevent DNS rebinding.
- Escaped model Markdown before rendering and added a strict Content Security Policy.
- Required operator authentication for all Amaura API reads and founder keys for irreversible mutations.
- Enforced database-atomic Amaura Ventures sprint slots.
- Packaged the complete HUD and 59 employee prompt profiles in the wheel.
- Added deterministic database lifecycle cleanup and server lifespan shutdown.
- Added a guarded strict-warning test runner and independent trust-foundation stress harness.

## 2026-08-06 — Trust Foundation v3.2.0

- Made audit-chain append and checkpoint updates atomic across processes.
- Added HMAC-authenticated audit entries and external signed head checkpoints.
- Replaced byte-only evidence references with signed provenance manifests.
- Added public-source retrieval, excerpt verification, prompt-injection scanning and independent source requirements for Ventures.
- Ignored caller-supplied opportunity scores; qualification now uses deterministic verified-evidence scoring and founder review.
- Added IP-pinned HTTP/TLS transport to prevent DNS rebinding and blocked redirects.
- Removed executable raw HTML/Markdown rendering and introduced strict CSP/security headers.
- Required authentication for all Amaura API reads and mutations, including local access.
- Added database-enforced Venture sprint slots to remove count-then-insert races.
- Included HUD assets and employee prompts in the wheel.
- Switched installation documentation to frozen dependency resolution.
- Closed SQLite backup/verification connections explicitly.
- Added exploit-specific multi-process, tamper, provenance, DNS, HUD and API regression tests.

# Amaura launch-candidate hardening changelog

## Release objective

Convert the internal Amaura workforce from a supervised prototype into a fail-closed local launch candidate with recoverable task execution, criterion-bound verification, safe repository delivery, crash-safe provider dispatch, and one canonical operator interface.

## Core additions

### Governed Git delivery

Added `jarvis/amaura/gitops.py` with:

- Exact base branch and base commit capture
- Clean-repository requirement
- Isolated task branches and worktrees
- Validated Git command return codes
- Immutable base-relative diffs
- No-change task rejection
- Exclusive cross-process repository merge locks
- Reviewed-commit and target-head checks
- Allowlisted post-merge validation
- Automatic validation rollback
- Compensating rollback when durable task completion fails
- Recoverable worktree cleanup events

### Strict evidence and independent review

Enhanced `jarvis/amaura/evidence.py`, `executor.py`, and `control_plane.py` with:

- Content-addressed evidence enforcement
- Exact acceptance-criterion coverage
- Evidence references bound to each criterion
- Vault integrity verification
- Worker/reviewer model separation
- Signed review attestations
- Submission hash binding and replay prevention
- Founder approval payloads bound to the exact Git snapshot

### Durable provider outbox

Enhanced `jarvis/amaura/store.py` and `supervisor.py` with:

- Worker-owned outbox leases
- Lease expiry and recovery
- Bounded attempts and exponential backoff
- Persisted provider receipts
- Dead-letter-style reconciliation state
- Conservative email handling: ambiguous sends are never automatically replayed
- Founder-only reconciliation through the CLI and authenticated API
- Exact signed-receipt binding to recipient, subject, body, operation, and idempotency key
- Atomic linked-message and outbox state transitions for completed, failed, and requeued operations

### Atomic founder decisions

Founder approval resolution, task completion, merge receipt persistence, event publication, and audit records now commit together. A failed merge or persistence step leaves the operation recoverable instead of consuming the approval and stranding the task.

### Canonical local operator CLI

Added `jarvis/amaura/cli.py` and the `amaura` console command:

- `amaura init`
- `amaura build-sandbox`
- `amaura doctor`
- `amaura status`
- `amaura worker`
- `amaura backup`
- `amaura reconcile`
- `amaura create-program`

The legacy `scripts/amaura_local.py` is now only a compatibility wrapper.
`Launch_Amaura.command` starts the loopback API/HUD and durable supervisor as
one local stack and shuts both down together.

### Local runtime controls

Added or hardened:

- Strict `.env.amaura` parser that never executes shell syntax
- Private `0600` secret-file permissions
- Five independently generated keys
- Absolute private data/evidence/backup paths
- Docker sandbox launch gate
- Distinct local worker/reviewer model gate
- Backup-and-restore certification
- Experimental LangGraph disabled by default
- Mac double-click installer and launcher
- Separate runtime setup/certification command so source installation is reproducible before Docker/Ollama setup
- Complete verification script

## Experimental orchestration

The incomplete LangGraph supervisor no longer silently falls back to an unrelated workflow. It remains disabled unless explicitly enabled and should not be enabled for company operations until its nodes and interfaces are completed and separately certified.

## Test coverage added

Added adversarial tests for:

- Strict environment-file parsing and permissions
- Criterion/evidence coverage
- Wrong-worker outbox completion
- Expired email lease reconciliation
- Ambiguous email non-replay
- Founder reconciliation with exact provider receipts
- Forged or mismatched receipt rejection
- Linked outbox/message failure and requeue consistency
- Exact reviewed Git merges
- Base-branch drift rejection
- Validation rollback
- Review-attestation replay protection

## Verification result in the build environment

- Full repository suite: **144 passed**
- Python compile check: passed
- Static source release gate: passed
- Repository security gate: passed

Live production readiness remains machine-specific and must be confirmed with `amaura doctor` after Docker, Ollama, the two distinct models, and local credentials are configured. Telegram founder binding is required only when the Telegram bot is enabled.

## 2026-08-05 — Company OS v2.0.0 verification

- Expanded the governed workforce to 57 governed roles across 13 departments.
- Registered nine durable company workflows and a safe founder-controlled autopilot cadence.
- Added free-first capability routing plus NVIDIA, Antigravity and Google Flow handoff adapters.
- Disabled direct legacy tool execution and the Fable dashboard by default.
- Added remote read authentication, WebSocket origin controls and bounded sessions.
- Constrained legacy workspace execution against absolute paths, traversal, symlink escape, shell chaining and non-allowlisted executables.
- Corrected whole-tree compilation and adversarial stress verification.
- Full repository suite: **167 passed**.
- Static source certification and repository security scan: passed.
- Adversarial stress: passed with 1,000 leads, 32 workers and one record after 500 duplicate-race attempts.

Live production readiness remains machine-specific and must be confirmed with `amaura doctor` after required secrets, strict modes, provider routing, distinct models and Docker are configured.


## 2026-08-05 — Mission Control v2.1.0

- Added persistent founder objectives and daily/weekly/monthly programme planning.
- Added distribution-first objective bootstrap.
- Added cross-process exactly-once cadence claims.
- Added durable daily autopilot budget enforcement and active-programme caps.
- Added founder autopilot kill switch.
- Added evidence-backed, exactly-once completion credit to objective metrics.
- Added Mission Control CLI commands and founder-briefing portfolio data.
- Expanded the hermetic suite to 166 passing tests.

## 2026-08-05 — Distribution Control Plane v2.2.0

- Added immutable, content-hash-bound publication packages.
- Added founder-specific approval tasks for every public action.
- Added scheduled publication queue and autopilot due-work dispatch.
- Added official/publication bridge contract with idempotency and payload-digest echoes.
- Added signed publication receipts and exact payload verification.
- Added quarantine and founder reconciliation for ambiguous public side effects.
- Added distribution dashboard, CLI, metrics ingestion and evidence-backed content lessons.
- Expanded regression suite from 167 to 174 passing tests.

## 2026-08-05 — Autonomous Company Runtime v3.0.0

- Expanded the governed workflow catalogue from 9 to 18 company workflows.
- Added 12 persistent founder objectives spanning every core Amaura department.
- Added durable company signals, exactly-once claims, signal budgets and response programmes.
- Added autonomous self-observation for security alerts, failed work, content underperformance and cost pressure.
- Added department circuit breakers and a founder company-wide kill switch.
- Added durable autonomy-run ledgers and evidence-backed objective reconciliation.
- Added NVIDIA cloud review with worker-model independence enforcement.
- Added verified automatic daily backups with retention.
- Replaced the basic worker launch with the full company autopilot runtime.
- Added credential-free macOS LaunchAgent installation and removal scripts.
- Added API and CLI controls for company status, signals, departments and autonomy state.

## 2026-08-05 — Amaura Ventures v3.1.0

- Added a separate startup-studio department so revenue work does not dilute Amaura Labs' research mission.
- Added five governed venture employees and three end-to-end workflows.
- Added deterministic opportunity scoring and source-backed opportunity records.
- Added fourteen-day validation experiments, one-active-sprint and one-active-build constraints.
- Added sourced metric events and threshold-based continue / kill / iterate / double-down recommendations.
- Added founder-only validation, launch, pricing, scale and shutdown boundaries.
- Added secure CLI, API and governed agent tools for the venture portfolio.
- Added two recurring company objectives: opportunity pipeline and portfolio discipline.
