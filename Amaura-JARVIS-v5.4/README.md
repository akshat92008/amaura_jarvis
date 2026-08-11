# Amaura JARVIS v5.4

Amaura JARVIS v5.4 is a founder-facing AI executive built on the governed Amaura Company OS. The user-facing model is one assistant: tell JARVIS an outcome; it resolves context, plans and persists a mission, delegates company work or repository engineering, observes evidence, verifies results independently, replans around failure, and stops at real approval boundaries.

This release is **Antigravity-first for software engineering**. Noryx remains experimental and disabled by default.

```text
Founder / chat / voice / events
            ↓
      ExecutiveKernel
   ┌────────┼─────────────┐
 Intent   Memory   Reference resolution
   └────────┼─────────────┘
            ↓
       World Model
            ↓
    Adaptive Goal Planner
            ↓
   Persistent MissionRunner
            ↓
      Amaura Supervisor
   ┌────────┼────────────────┐
 Company  Antigravity CLI  Specialist agents
 workers      (`agy`)       / research
   └────────┼────────────────┘
            ↓
      Evidence + Git delta
            ↓
  Isolated independent verifier
            ↓
    Independent reviewer
            ↓
    Policy / approval gate
            ↓
          Action
            ↓
     Observe / remember
```

## v5.4 — Closed-Loop Ventures Trust Hardening

v5.4 keeps the v5.2/v5.3 architecture and closes the defects found in the fresh Ventures audit. It does not broaden external authority.

### Amaura Ventures v5.4

- **Action → mission closure**: reversible cash-flow actions now materialize into durable JARVIS missions and mission results/evidence reconcile back into the action.
- **Canonical approvals**: founder-sensitive actions use the normal Company OS payload-hash approval engine; mutation after approval request fails closed.
- **Verified financial truth**: automated money claims require an independent signed `ProviderReceipt` plus the exact authenticated provider payload. Arbitrary receipt strings and provider-looking EvidenceVault labels cannot create verified revenue.
- **Founder manual ledger**: manual transactions require founder authority, explicit attestation and a stable `manual_event_id`; conflicting retries fail closed.
- **Unit economics**: revenue/refund/fee/COGS/marketing/tax/operating-cost/payout events feed gross profit, contribution profit, net cash flow, units, CAC and margin layers.
- **Adaptive ranking**: bounded lane priors are blended with actual historical time-to-cash, profitability, margins and founder-attention outcomes.
- **Atomic portfolio caps**: founder-time admission and live-stream activation are transactionally enforced across processes.
- **Unified continuous runtime**: desktop/server Company Autopilot and daemon Autopilot share a single-writer leader lock; runtime status exposes heartbeat/error state.
- **Retry correctness**: failed cash-flow actions archive the prior mission and create a fresh mission instead of getting stuck on an old `mission_id`.
- **External-action boundary preserved**: publishing, paid spend, live pricing, accounts, contact/deployment and other consequential effects remain separately governed and founder-approved.
- **Integrity policy preserved**: plagiarism, fake reviews, spam/mass unsolicited outreach, impersonation, unsupported income guarantees and platform-bypass behaviour remain prohibited.

The v5.3 lane catalogue remains: KDP books, digital downloads, template packs, content assets, affiliate-content experiments, newsletters, micro-SaaS, web apps, browser extensions, developer tools, AI utilities and mobile apps.

The v5.2 security/execution contracts below remain in force:

- **Antigravity is the public default everywhere**: chat, voice, explicit goal API, ExecutiveKernel, and desktop controls. A founder coding mission no longer silently falls back to Amaura's internal coder when `agy` is unavailable.
- **Monitored streaming Antigravity jobs**: Amaura launches `agy` in structured `stream-json` mode, persists execution phases, monitors process-tree memory, streams throttled progress into task metadata, and terminates the real process tree on pause/cancel/timeout/memory pressure.
- **Effective Antigravity security preflight**: global settings are not considered sufficient. Amaura also inspects project-scoped permission/settings files plus global/workspace executable customizations (hooks/plugins/MCP). Unknown executable customizations fail closed by default.
- **Git host-execution hardening**: every Amaura-managed Git operation disables repository hooks and ignores user-global Git config. Repository-local clean/smudge/process filters, custom merge/diff drivers, textconv, and active fsmonitor are rejected before autonomous Git operations.
- **One verifier boundary**: post-merge validation uses the same isolated `SecureVerifierRunner`; it no longer executes repository test commands directly on the founder's host.
- **Tighter macOS verifier profile**: native verification is deny-by-default and explicitly grants only the runtime/workspace paths needed for a test. Docker remains an alternate isolation mode. Host verification is explicit break-glass/testing only.
- **Founder-memory authority**: founder-trusted memory writes/deletes require the Amaura operator credential. Ordinary assistant access cannot poison future planning by creating `trust=founder` facts.
- **Mission generation protection**: low-level task claiming, review, execution and structural replanning respect mission generation/lifecycle. Stale workers cannot win after pause/cancel.
- **Cross-process MissionRunner leadership**: mission-level advancement uses a durable file lock in addition to atomic task claiming, reducing duplicate mission mutation if two local runner processes are started.
- **Execution provenance**: founder-facing responses record the actual executive provider/model and whether legacy fallback was used. Antigravity success requires executor-model provenance by default.
- **Resource admission**: Antigravity reserves the heavy-worker budget and its complete process tree is monitored against Amaura's memory policy.
- **Crash safety**: an unresolved `executor_started` receipt fails closed rather than blindly invoking the same engineering mission again.

## Install on macOS

```bash
./Install_Amaura.command
./Setup_Amaura_Antigravity.command
./Install_Amaura_Desktop.command
./Launch_Amaura_Desktop.command
```

`Setup_Amaura_Antigravity.command` expects the official `agy` CLI to be installed and authenticated. It backs up global Antigravity settings, applies Amaura's baseline unattended sandbox policy, then runs Amaura's own readiness check for global settings, project permissions, and global executable customizations. Repository-specific `.agents` customizations are checked again immediately before each coding mission.

Baseline policy:

- `toolPermission = proceed-in-sandbox`
- `artifactReviewPolicy = always-proceed`
- `allowNonWorkspaceAccess = false`
- `enableTerminalSandbox = true`
- no broad `unsandboxed(...)`, all-file, all-web, or all-MCP allow grants
- workspace/global executable hooks/plugins/MCP require explicit qualification

## Engineering configuration

```dotenv
AMAURA_ANTIGRAVITY_COMMAND=agy
AMAURA_ANTIGRAVITY_MODE=cli
AMAURA_ANTIGRAVITY_PROJECT_ID=default-cli-project
AMAURA_ANTIGRAVITY_REQUIRE_AUTONOMY_SETTINGS=1
AMAURA_ANTIGRAVITY_REQUIRE_MODEL_PROVENANCE=1
AMAURA_ANTIGRAVITY_ALLOW_UNRESOLVED_PROJECT_SETTINGS=0
AMAURA_ANTIGRAVITY_ALLOW_WORKSPACE_EXECUTABLE_CUSTOMIZATIONS=0
AMAURA_ANTIGRAVITY_ALLOW_GLOBAL_EXECUTABLE_CUSTOMIZATIONS=0
AMAURA_ANTIGRAVITY_RESERVATION_MB=1800

# Noryx stays out of the default path while it is unfinished.
AMAURA_ENABLE_EXPERIMENTAL_NORYX=0

# auto = isolated native macOS verifier when available, otherwise Docker.
AMAURA_VERIFIER_MODE=auto
AMAURA_ALLOW_HOST_VERIFICATION=0
```

## Amaura Ventures quick start

```bash
amaura ventures cashflow-status
amaura ventures cashflow-tick
```

From chat, the intended interaction is simply:

```text
JARVIS, run Amaura Ventures. Find the best low-capital cash-flow opportunities,
protect my study time, advance reversible internal work, and only ask me when a
publish/spend/pricing/account decision genuinely needs founder approval.
```

JARVIS can research and prepare KDP/digital-product/content/software opportunities, but v5.4 deliberately does not fake unattended platform publishing where a safe qualified API/CLI/account boundary has not been proven.

## Example

```text
JARVIS, build the client dashboard we discussed. Preserve the existing API,
add tests, repair anything you break, and prepare it for staging. Do not deploy.
```

Normal path:

```text
ExecutiveKernel
→ resolve project/context
→ persist bounded mission
→ MissionRunner
→ isolated Git worktree
→ effective Antigravity security preflight
→ supervised `agy --sandbox --output-format stream-json`
→ actual Git-delta validation
→ isolated independent test rerun
→ hook/config-safe Git commit
→ independent review
→ replan/repair on failure
→ stop at deployment approval
```

## Mission lifecycle

```text
plan_only
   ↓
 DRAFT ──activate──→ RUNNABLE
                       ↓
                  MissionRunner
                       ↓
              execution / review
                 │          │
               pause      cancel
                 ↓          ↓
                HELD    CANCELLED
                 │
               resume
```

Pause/cancel changes the mission generation, prevents stale result acceptance, and terminates an active Antigravity process tree.

## Verification baseline

The current v5.4.1 source collects **398 tests**. Release evidence must be regenerated from the exact final tree; older v5.4.0 reports do not certify this source.

The release qualification runs modules in isolated pytest processes because several legacy tests intentionally exercise multiprocessing/background runtimes. Python compilation and Electron JavaScript syntax checks are required before publishing.

Passing tests establish source/regression contracts. They do **not** prove a real authenticated Antigravity account will solve every unseen repository task.

## Production qualification boundary

`production_ready` intentionally remains **false** until this exact v5.4 build is qualified on the target Mac with:

- real authenticated Antigravity CLI and effective project permissions;
- malicious-repository sandbox fixtures;
- private unseen repository tasks + hidden acceptance tests;
- long-duration mission/pause/cancel/restart/resource soak;
- real configured executive cognition provider(s);
- desktop/microphone permissions if enabled;
- external integration credentials and provider receipts;
- real KDP/store/payment/social accounts, payout reconciliation and platform-specific publishing permissions;
- objective-completion, founder-intervention and real cash-flow outcome measurements across long-running company and Ventures missions.

The goal is evidence-backed autonomy, not a version number claiming fictional AGI.
