# Amaura Company OS v3.6.1 — Resource & Security Hardening Report

## Executive verdict

Amaura v3.6.1 replaces the v3.6.0 5.6 GB estimate-only scheduling profile with a pressure-aware 8 GB Mac control-plane profile and hardens the highest-risk OSS execution boundaries discovered in the v3.6.0 audit.

This source state is **source-qualified, not production-configured**. The code/test/security gates pass, but the deployment gate correctly remains false until founder/operator keys, strict evidence/audit settings, reviewer/model routing, sandbox image pinning, backup separation and other target-machine settings are configured.

## 8 GB Mac resource policy

Default policy:

- normal Amaura target: **1500 MB**
- ordinary burst limit: **2500 MB**
- absolute local Amaura burst ceiling: **3000 MB**
- pressure-mode admission target: **1000 MB**
- maximum simultaneous heavy capability workers: **1**
- always-resident heavyweight services: **0**
- heavyweight capabilities: **on demand, disposable, terminate after completion**

The scheduler no longer treats a single estimated number as a hard memory limit. It now combines:

1. a cross-process reservation ledger;
2. live host memory/swap pressure;
3. actual child-process-tree RSS monitoring;
4. a hard worker RSS kill ceiling;
5. swap-growth abort handling;
6. red-pressure abort handling;
7. pressure-aware admission control.

On macOS, native `memory_pressure`, `sysctl` and `ps` telemetry are used when available. `psutil` is opportunistic only and is **not** a new required core dependency. Linux has `/proc`/`ps` fallbacks.

## Heavy capability lifecycle

Heavy Python/browser workers are isolated into disposable subprocesses. Worker environments are allowlisted rather than copied from the parent process, preventing unrelated Gmail/GitHub/model/signing credentials from being inherited by Whisper, OCR, document, browser and other OSS workers.

Playwright, Crawl4AI, Browser Use, Docling, PaddleOCR, Qdrant/FastEmbed, faster-whisper and Kokoro are treated as isolated/on-demand Python capability paths. FFmpeg/Remotion and other subprocess-based capabilities are monitored by the same process-tree resource enforcement.

## Browser hardening

### Playwright

- HTTPS-only navigation for governed public research.
- Public-network URL resolution before navigation.
- Amaura egress proxy pins a validated public IP.
- Private, loopback, link-local and metadata destinations are rejected.
- WebSocket requests are blocked.
- downloads disabled.
- service workers blocked.
- final navigation URL revalidated.
- response-size ceiling enforced.
- Chromium runs in a disposable capability worker.

### Crawl4AI

- HTTPS-only.
- public-only egress proxy.
- fails closed if the installed Crawl4AI API cannot accept the expected proxy/security configuration.
- final URL revalidated.
- disposable worker lifecycle.

### Browser Use

- remains disabled by default.
- fails closed unless the installed Browser Use version exposes the expected restricted-session APIs.
- interactive/form/file/JavaScript actions are excluded programmatically rather than relying only on a system prompt.
- explicit domain allowlist and IP blocking.
- downloads disabled.
- no persistent user-data directory.
- one action per model step.
- remote/free providers are preferred; paid routing requires an explicit operator gate.

## MCP hardening

AI-controlled MCP requests no longer accept arbitrary `command`, `args` or `env_keys`.

MCP now accepts a `server_id` resolved through a founder-owned registry containing:

- absolute executable path;
- executable SHA-256;
- fixed arguments;
- fixed environment allowlist;
- allowed tools;
- whether tool calls are enabled;
- whether AI roles may list tools;
- timeout;
- network policy.

The registry must be owned by the current user and mode `0600` on POSIX. Executable hashes are checked at execution time. Network-disabled servers run through a fail-closed OS sandbox path where supported.

## Remotion hardening

Production rendering no longer accepts an arbitrary employee-selected project/entry boundary.

- immutable Amaura template ID;
- template source SHA-256 manifest;
- approved composition IDs only;
- validated JSON props;
- package-lock hash verification;
- local project CLI only;
- renderer sandbox with network disabled by default;
- fail closed when the required renderer sandbox is unavailable in strict mode.

## Remote ComfyUI lifecycle

The adapter now supports a full remote flow:

`queue -> poll history -> identify outputs -> authenticated download -> validate image bytes -> save -> SHA-256 artifact registration`

Bearer-token authentication is supported through `COMFYUI_API_TOKEN`. Localhost remains disabled by default for the 8 GB profile.

## Capability health semantics

The previous package-presence Boolean has been expanded to distinguish:

- `installed`
- `configured`
- `healthy`
- `execution_ready`
- `verified_at`
- `version`

`--deep-check` performs explicit non-destructive execution probes where a safe cheap smoke test exists. Heavy/model-specific capabilities do not claim execution readiness merely because an import succeeds.

## Validation of this exact source state

- Python compilation: **PASS**
- isolated verifier suite: **301 / 301 PASS**
- warnings-as-errors verifier behavior: **PASS**
- security gate: **PASS — 0 findings**
- static source release gate: **source_certified = true**
- backup/restore gate inside static qualification: **PASS**
- frozen core installer dry-run: **PASS**
- wheel build: **PASS**
- wheel smoke import/version/resource-policy/MCP-contract: **PASS**

The verifier runs tests in isolated OS-process shards to avoid the shared-process lifecycle issue that affected older qualification runs.

## Production deployment gate

`production_ready` remains **false** with **24 deployment/configuration blockers**:

- approval_key
- audit_checkpoint_path
- audit_checkpoint_separated
- audit_hmac_key
- backup_destination_separated
- distinct_reviewer_model
- evaluation_pack_hmac_key
- evidence_hmac_key
- keys_are_separate
- local_tool_api_auth
- model_routing_valid
- operator_key
- post_merge_validation
- private_model_evaluation_pack
- provider_receipt_key
- review_attestation_key
- reviewer_identity_keys
- sandbox_image_pinned
- strict_audit_checkpoint
- strict_audit_signatures
- strict_evidence_mode
- strict_evidence_signatures
- strict_git_mode
- strict_review_mode

These are not being silently bypassed. Amaura must remain fail-closed until the target deployment is configured.

## Deliberately unresolved / not falsely certified

### 1. Full optional-OSS dependency lock

The v3.6.0 audit correctly identified that the new optional OSS packages were not represented by a complete reproducible lock/SBOM. A fresh trustworthy optional dependency lock could not be generated in the current build environment because its configured package registry could not resolve the dependency graph. The existing v3.6.0 qualification files therefore remain **historical v3.6.0 evidence**, not a new v3.6.1 supply-chain attestation.

The v3.6.1 core project does not add a new unlocked mandatory dependency, and `uv sync --frozen --extra dev --dry-run` succeeds. Before public/production distribution, generate exact per-profile locks plus hashes/SBOM from a functioning trusted registry and requalify them.

### 2. Physical M3 8 GB qualification

The resource implementation is designed for and contains native macOS telemetry paths, but this build environment is not the user's physical M3 8 GB Mac. Actual M3 memory-pressure/swap behavior must therefore be measured on that target before claiming hardware qualification.

### 3. Durable capability workload queue

v3.6.1 adds a **durable cross-process resource ledger** and longer bounded contention handling, but capability invocation remains synchronous at this layer. It is not being represented as a fully durable `queued -> leased -> running -> retry_wait -> completed` capability job queue. That can be added as a separate workload-orchestration release without weakening the current memory guardrails.

### 4. Kokoro / Python 3.13 compatibility

Current Kokoro packaging has a Python-version constraint that can conflict with Python 3.13. For local Kokoro use, operate the optional media profile under a compatible Python runtime (for example Python 3.12) or isolate Kokoro into a dedicated compatible environment. Amaura does not keep Kokoro resident; the capability remains on-demand.

## Operational recommendation for the user's Mac

Run Amaura as the command/control plane. Keep SQLite, governance, queues, approvals and lightweight adapters local. Start exactly one heavy local worker only when required and terminate it after the task. Keep local ComfyUI/SearXNG/Langfuse/Qdrant servers off unless explicitly needed; prefer remote/free endpoints for heavyweight generation/search/telemetry. Do not run Ollama plus a browser worker plus Whisper/Remotion simultaneously on the 8 GB machine.

## Release classification

**Amaura Company OS v3.6.1 Resource-Hardened — source-qualified hardening build; not yet production-configured or M3 hardware-qualified.**
