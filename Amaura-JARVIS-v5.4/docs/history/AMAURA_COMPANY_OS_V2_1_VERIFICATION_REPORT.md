# Amaura Company OS v2.1.0 — Independent Verification and Next-Phase Report

**Verification date:** 2026-08-05  
**Source audited:** `Amaura-Company-OS-v2.0.0.zip`  
**Resulting release:** Amaura Company OS v2.1.0 — Objective-Driven Mission Control

## Executive verdict

The uploaded v2.0.0 repository was a credible governed task-execution kernel, but it was not yet a proactive company autopilot. Its original autonomous loop created a weekly operating review and advanced governed tasks, but it did not persist founder goals, schedule recurring cross-department programmes, enforce a durable portfolio budget, or automatically credit completed work to measurable company objectives.

v2.1.0 closes that gap. It can now operate as a **governed autonomous internal workforce for an early-stage Amaura Labs** when a supported NVIDIA/local model and the required runtime controls are configured. It can maintain founder objectives, generate bounded programmes, execute internal work, independently review evidence, recover failures, stop at founder authority boundaries, and maintain progress records.

It is **not** an unrestricted autonomous company controller. Public publishing, external outreach, production deployment, product investment, payments, legal commitments, credentials, and destructive actions remain founder-approved by design.

## Next phase implemented: Objective-Driven Mission Control

- Persistent founder objectives with daily, weekly, monthly, and manual cadences.
- Distribution-first bootstrap for Amaura's owned audience, product validation, and optional engineering delivery.
- Cross-process exactly-once cadence claims using SQLite transactional uniqueness.
- Durable daily autopilot budget accounting across process restarts.
- Per-objective active-programme caps and workflow budget validation.
- Founder kill switch for all autonomous planning and execution.
- Automatic programme scheduling from the existing nine governed workflows.
- Evidence-backed, exactly-once objective progress reconciliation.
- Automatic objective completion when the founder-defined target is reached.
- Objective portfolio and autopilot state in daily founder briefings.
- New Mission Control CLI commands.

## End-to-end autonomy test

A synthetic product-discovery mission was executed through the complete control path:

1. A persistent founder objective was created.
2. Mission Control scheduled the due product-discovery programme.
3. JARVIS autonomously completed and independently reviewed all low-risk internal research and product-planning stages.
4. The final high-risk product-investment action stopped in the founder approval queue.
5. The programme remained incomplete and the objective received no progress credit before approval.
6. After an authenticated founder approval, parent states rolled up to completed.
7. Mission Control generated a content-addressed completion receipt and credited the objective exactly once.

This confirms that the system can autonomously operate within its delegated authority without silently crossing the founder boundary.

## Verification results

| Verification | Result |
|---|---:|
| Full Python compilation | Passed |
| Hermetic regression/integration/security suite | **167 passed, 0 failed** |
| Mission Control focused tests | **11 passed** |
| Cross-connection duplicate cadence race | Exactly one programme |
| Objective progress reconciliation | Exactly once with evidence |
| Adversarial workers | 32 |
| Leads ingested under stress | 1,000 |
| Adversarial inputs detected | 100 |
| Confirmed simulated provider sends | 60 |
| Over-limit sends blocked | 20 |
| Duplicate race attempts | 500 |
| Duplicate records produced | 1 |
| SQLite integrity | `ok` |
| Foreign-key violations | 0 |
| Audit-chain verification | Passed |
| Repository secret scan | Passed; no findings |
| Static source certification | Passed |
| Wheel build | Passed |
| Offline wheel code/CLI isolation check | Passed |

## What is genuinely operational

- 52 governed employee definitions across 13 departments.
- Nine durable workflow templates.
- Persistent tasks, leases, retries, recovery, evidence, audits, budgets, approvals, and outbox reconciliation.
- Goal-driven daily/weekly/monthly programme planning.
- Independent review boundaries and founder authority gates.
- Free-first resource catalogue and NVIDIA/local routing architecture.
- Research, engineering, content, acquisition, operating review, incident, and product-discovery workflows.
- MacBook-friendly orchestration: the laptop runs coordination and storage while remote models perform heavy inference.

## What still requires configuration on Akshat's Mac

The build environment intentionally contained no production credentials or external services, so these were not live-certified:

- `NVIDIA_API_KEY`, or installed local worker and reviewer models.
- Two distinct worker/reviewer models.
- Independent operator, founder approval, review-attestation, and provider-receipt keys.
- Docker and the hardened Amaura sandbox image.
- Strict evidence, review, Git, and post-merge validation modes.
- YouTube, GitHub, Gmail, Telegram, CRM, analytics, and other optional credentials.
- Real external-provider latency, rate limits, and output quality.

Run `amaura init`, configure the generated private environment, then run `amaura doctor`. External autonomous operation should begin only when it reports `production_ready: true`.

## Suitability for running Amaura Labs

The system is sufficient as the internal operating layer for an early-stage, founder-controlled AI research/product company. It can organize research, product decisions, engineering, content production, distribution planning, CRM, operations, finance reporting, and controlled external actions.

Its limiting factors are now mostly outside orchestration:

- quality and reliability of the selected NVIDIA/local models;
- platform credentials and supported APIs;
- real audience and customer feedback;
- founder strategy and approval speed;
- production deployment infrastructure;
- the actual quality of generated media and software.

The correct operating description is:

> **A governed AI workforce that can run recurring internal company operations and prepare external actions for founder authorization—not a fully unsupervised replacement for the founder.**

## Recommended first deployment

1. Run locally in shadow mode for one week.
2. Bootstrap only the owned-audience and product-validation objectives.
3. Use NVIDIA for worker inference and a distinct local/NVIDIA reviewer model.
4. Keep publishing, outreach, deployment, and spending approval-gated.
5. Review the daily briefing and approval queue manually.
6. Increase `max_work_units` and daily budget only after measured success rates are stable.

