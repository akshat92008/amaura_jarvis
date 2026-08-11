# Amaura Ventures v5.4 — Closed-Loop Cash-Flow Portfolio

Amaura Ventures is the governed revenue branch inside JARVIS. Its purpose is to fund Amaura Labs with owned, low-capital products and repeatable cash-flow experiments while protecting founder time and keeping consequential external actions approval-gated.

It does **not** guarantee income and it does not convert Amaura Labs into an agency.

## Revenue lanes

The portfolio engine understands:

- `kdp_book` — original books, guides and workbooks prepared for KDP-style publishing;
- `digital_download` — original downloadable resources;
- `template_pack` — templates, spreadsheets, Notion-style systems and reusable packs;
- `content_asset` — owned content products and durable educational/media assets;
- `affiliate_content` — useful content with disclosed affiliate monetisation where permitted;
- `newsletter` — audience + sponsorship/subscription experiments;
- `micro_saas`, `web_app`, `browser_extension`, `developer_tool`, `ai_utility`, `mobile_app`.

The older Venture Studio product types remain compatible.

## Operating loop

```text
public evidence
    ↓
venture opportunity
    ↓
deterministic venture score
    ↓
cash-flow ranking
    ↓
founder selects/activates stream
    ↓
JARVIS action queue → canonical approval (when required) → durable mission
    ├─ demand research
    ├─ saleable asset/prototype
    ├─ listing/distribution draft
    ├─ conversion review
    ├─ retention review
    ├─ pricing recommendation
    └─ organic distribution asset
    ↓
founder gate for publish/spend/pricing/account actions
    ↓
source-backed revenue/cost ledger
    ↓
portfolio ranking / pause / retire / double-down decision
```

## Cash-flow ranking

`CashflowEngine.rank_opportunity()` combines:

- original Venture opportunity score;
- estimated time-to-cash;
- automation potential;
- capital efficiency;
- margin potential;
- build speed;
- founder-time fit.

The ranking is intentionally biased toward small, testable, low-capital streams instead of idea volume.

## Financial truth

Financial events support `revenue`, `refund`, `fee`, `cost`, `cogs`, `marketing`, `tax`, and `payout`.

Financial trust is explicit:

- `provider_verified` requires a valid independent `ProviderReceipt` plus the exact provider payload it authenticates; the provider outcome must be successful/confirmed and amount/type/currency must match.
- `founder_manual` requires founder authority, `founder_attestation=true`, and a stable `manual_event_id`.
- ordinary EvidenceVault records may be attached as supporting evidence but cannot promote themselves to provider-verified financial truth.

Provider and founder-manual identities are idempotent and conflicting replay fails closed. A stream cannot mix currencies. Payout transfer records are kept separate from earned revenue. Economics distinguish provider-verified revenue, founder-certified revenue, refunds, COGS, fees, marketing, taxes, operating costs, gross/contribution/net margins, units and CAC.

## Founder attention

Environment controls:

```dotenv
AMAURA_VENTURE_FOUNDER_WEEKLY_MINUTES=60
AMAURA_VENTURE_MAX_FOUNDER_MINUTES_WEEKLY=180
AMAURA_VENTURE_MAX_LIVE_STREAMS=4
```

The cap is portfolio-wide. A new stream is rejected when it would exceed the configured founder-attention budget.

## Integrity policy

Amaura Ventures rejects or stops strategies involving:

- plagiarism/copyright infringement;
- fake reviews;
- spam or mass unsolicited DMs;
- impersonation;
- bypassing platform enforcement;
- unsupported guaranteed-income claims;
- hidden account/spend/publishing actions.

The system may prepare original assets and exact approval payloads. It does not silently perform consequential platform actions.

## JARVIS integration

The GoalCompiler includes a dedicated `ventures` domain. Founder instructions containing explicit Ventures/cash-flow/side-hustle/KDP/monetisation intent route to Venture agents rather than generic revenue or software workers.

The Company OS includes a recurring `venture_cashflow_cycle` workflow:

1. reconcile active streams and financial evidence;
2. refresh low-capital opportunity evidence;
3. rank by time-to-cash and founder-time efficiency;
4. prepare one reversible internal revenue asset;
5. present one exact founder decision for any consequential next step.

## Closed-loop mission execution

`CashflowEngine.tick()` does more than create queue rows. Reversible actions are materialized into durable JARVIS missions. Approval-sensitive actions create a canonical Company OS approval first. Mission results are reconciled back into the action with evidence; cancelled actions cancel linked missions; failed actions can be retried with a new mission while retaining the old mission in audit history.

The desktop/server runtime also starts Company Autopilot by default. Desktop and daemon processes share a cross-process leader lock, so only one company cycle mutates state at a time. `/api/amaura/runtime/status` exposes live heartbeat/status/error information.

## Desktop

The `VENTURES` view shows:

- active/live stream counts;
- gross and net cash flow by currency;
- founder minutes/week;
- action queue;
- ranked opportunities;
- founder approve/cancel controls for approval-sensitive actions.

## CLI

```bash
amaura ventures status
amaura ventures cashflow-status
amaura ventures cashflow-tick
amaura ventures cashflow-stream-add --help
amaura ventures cashflow-finance --help
amaura ventures cashflow-stream-status --help
amaura ventures cashflow-action --help
```

## API

Read/operator surfaces:

- `GET /api/amaura/ventures/cashflow`
- `POST /api/amaura/ventures/cashflow/tick`
- `POST /api/amaura/ventures/cashflow/financial-events`
- `POST /api/amaura/ventures/cashflow/actions`

Founder approval surfaces:

- `POST /api/amaura/ventures/cashflow/founder/streams`
- `POST /api/amaura/ventures/cashflow/founder/stream-status`
- `POST /api/amaura/ventures/cashflow/founder/actions`

## Practical boundary

The cash-flow engine is source/regression qualified in the v5.4 release. Real KDP/store/payment/social accounts, platform-specific permissions, tax/compliance details, payout reconciliation and unattended publishing must still be qualified on the founder's actual accounts before those external actions can be labelled production-proven.
