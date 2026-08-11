# Amaura JARVIS v5.4 Changelog

## Ventures execution closure

- Added durable CashflowAction → `GoalRequest`/JARVIS mission bridge.
- Added mission→action reconciliation with durable task summaries/evidence.
- Added bounded failed-action retry with old mission archival and fresh mission creation.
- Made Company Autopilot continuously advance the Ventures cash-flow loop.

## Canonical founder authority

- Bound founder-sensitive Ventures actions to normal Company OS approvals.
- Added immutable Ventures action payload hashes and approval/task linkage.
- Reject action or stream-context mutation after approval request.
- Central approvals UI decisions now synchronize back into Ventures.
- Cancelling a Ventures action cancels its linked mission.

## Financial integrity

- Removed arbitrary receipt-string acceptance for automated revenue.
- Provider-verified money requires a valid independent `ProviderReceipt` and exact authenticated payload.
- Reject failed/unconfirmed provider receipts.
- EvidenceVault provider-looking labels can no longer mint provider-verified revenue.
- Founder-manual events require explicit founder attestation plus stable `manual_event_id`.
- Added replay/conflict detection for provider and founder-manual transactions.
- Added COGS, marketing and tax financial event types and richer unit economics.
- Separate provider-verified and founder-certified revenue in economics/dashboard data.

## Portfolio correctness

- Made founder-time stream admission atomic across processes.
- Made live-stream activation cap atomic across processes.
- Added historical lane outcome learning to opportunity ranking.
- Expanded anti-abuse concept checks while preserving Company OS policy as the consequential execution boundary.

## Runtime / product

- Unified desktop/server and daemon Company Autopilot through a cross-process leader lock.
- Added live Company Autopilot heartbeat/error information to `/api/amaura/runtime/status`.
- Added founder-only manual financial-event API path.
- Updated desktop System Status to show unified runtime state.
- Updated Ventures CLI help for closed-loop dispatch and financial evidence requirements.
