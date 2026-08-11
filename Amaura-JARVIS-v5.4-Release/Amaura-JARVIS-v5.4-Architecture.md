# Amaura JARVIS v5.4 — Closed-Loop Ventures Trust Hardening

v5.4 is a focused hardening release on top of v5.3. It does not add another agent framework or broaden external authority. It closes the trust and execution gaps found in the fresh v5.3 audit so Amaura Ventures can move from a portfolio/action dashboard toward a durable, governed cash-flow operating loop.

## What changed

### CashflowAction → JARVIS mission closure

Every executable Ventures action can now be linked to a durable JARVIS goal/mission. Internal reversible actions are automatically materialized into missions; founder-sensitive actions first use the canonical Company OS approval boundary. Mission completion/failure is reconciled back into the action with task summaries/evidence. Failed action retries archive the prior mission and create a fresh mission, bounded by `AMAURA_VENTURE_ACTION_MAX_RETRIES`.

### One approval authority

Founder-sensitive Ventures actions no longer rely on a separate weak approval concept. A canonical Company OS approval is created with a payload hash that binds the exact action, payload and stream context. Payload/stream mutation after request fails closed. Approval through either the Ventures surface or the normal Company OS approvals surface is authoritative.

### Financial truth boundary

The ledger distinguishes two trusted classes:

- `provider_verified` — requires a valid `ProviderReceipt` signed with the independent provider-receipt credential and the exact provider payload it authenticates. The receipt must represent a successful/confirmed provider outcome and amount/type/currency must match the ledger entry.
- `founder_manual` — requires founder authority, explicit `founder_attestation=true`, and a stable `manual_event_id` so retries/annotation changes cannot double-count a transaction.

An EvidenceVault manifest may support a financial event but **cannot** promote itself to provider-verified merely by claiming `source=provider:*` or `financial_trust=provider_verified`. EvidenceVault proves what Amaura stored; ProviderReceipt proves that a qualified provider adapter observed an external provider outcome.

### Better unit economics and learning

Financial events now include revenue, refund, fee, cost, COGS, marketing, tax and payout. Stream economics separate gross profit, contribution profit, net cash flow, units, CAC and margin layers. Cash-flow ranking still starts from bounded lane priors, but now blends in historical lane outcomes so future ranking learns from actual time-to-cash, profitability, founder attention and margin history rather than remaining permanently heuristic.

### Atomic portfolio admission

Founder-time and live-stream caps are checked and mutated inside SQLite `BEGIN IMMEDIATE` transactions. Concurrent processes cannot both observe the same free slot and exceed portfolio limits.

### Unified runtime

The desktop/server process can run the same Company Autopilot used by the daemon. A cross-process file lock keeps the company cycle single-writer. Runtime status exposes Company Autopilot configured/enabled state plus live heartbeat/status/error information, alongside MissionRunner, proactive cognition, Antigravity readiness and provider-receipt configuration.

## Authority invariant

v5.4 still does not silently publish, spend money, create accounts, contact people, deploy, change live prices or bypass platform rules. Ventures missions prepare/verify reversible internal work; consequential effects continue through explicit governed Company OS integrations and founder approval.

## Qualification boundary

Source/regression qualification cannot prove actual KDP/store/payment accounts, tax/platform rules, authenticated Antigravity behaviour, target-Mac sandboxing/resources, payouts or real commercial outcomes. Those remain target-environment qualification items and `production_ready` must stay false until they are demonstrated.
