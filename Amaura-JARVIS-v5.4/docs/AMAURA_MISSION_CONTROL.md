# Amaura Mission Control v2.1.0

Mission Control converts founder-approved goals into bounded recurring company programmes. It is deliberately more conservative than a general autonomous agent: it can plan, research, draft, execute sandboxed internal work, review evidence, and maintain company state, but it cannot silently publish, contact people, deploy to production, spend money, or make legal commitments.

## What changed in v2.1.0

- Persistent founder objectives with daily, weekly, monthly, or manual cadence.
- Distribution-first bootstrap for owned-audience content, product validation, and optional engineering improvement.
- Cross-process cadence claims: two workers cannot create the same recurring programme.
- Durable daily autopilot budget accounting across restarts.
- Per-objective active-programme caps and workflow budget gates.
- Founder kill switch that pauses planning and execution.
- Content-addressed completion receipts and exactly-once objective progress credit.
- Automatic target completion when evidenced progress reaches the founder-defined metric.
- Objective portfolio included in the daily founder briefing.

## First-run commands

```bash
amaura init
amaura doctor
amaura mission bootstrap-distribution --repository /absolute/path/to/amaura-or-nexus
amaura mission list
amaura autopilot --once --max-work-units 4 --max-new-programmes 2
```

Run `amaura doctor` until `production_ready` is true before enabling real providers or external actions.

## Operating model

1. The founder creates or bootstraps a measurable objective.
2. Mission Control determines whether the objective is due.
3. A unique cadence claim is committed in SQLite under a write transaction.
4. JARVIS creates a governed programme from one of the nine workflow templates.
5. The supervisor leases one task at a time, executes it through approved tools, stores evidence, and sends it to an independent reviewer.
6. High-risk or external actions stop at founder approval.
7. Parent project and programme states roll up only after every child completes.
8. Mission Control creates a content-addressed completion receipt and credits the objective exactly once.

## Recommended first objectives

- Weekly build-in-public long-form content package with reusable shorts and social assets.
- Monthly evidence-backed AI product opportunity decision.
- Weekly bounded Nexus/Amaura engineering improvement, when a repository path is supplied.

## Boundaries

The system is sufficient to coordinate an early-stage AI-native company, but it is not a substitute for founder judgment. Product direction, public claims, pricing, partnerships, payments, legal decisions, credentials, and production releases remain human-authorized. Live autonomy also requires a configured model provider or local model, a distinct reviewer model, secure keys, and Docker sandboxing.
