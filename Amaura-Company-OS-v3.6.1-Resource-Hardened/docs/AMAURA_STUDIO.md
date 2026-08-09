# Amaura Studio Company OS

Amaura Studio is now a governed company operating system inside JARVIS. The authority chain is:

```text
Founder → JARVIS → Programme → Project → Milestone → Specialist task
                                                   ↓
                                      Independent reviewer
                                                   ↓
                                      Founder approval when required
```

JARVIS is the sole control plane. Specialist employees cannot create programmes, dispatch themselves, review their own work, exceed their tool or cost envelope, or complete external and medium/high-risk actions without the configured approval path.

## Governed workforce

The registry contains 52 roles across the control plane, revenue, delivery, product engineering, content/media, and research. The original 15-role operating kernel remains intact and is extended with dedicated acquisition and content-factory specialists.

- JARVIS
- Opportunity Scout
- Lead Qualification Agent
- Proposal Agent
- CRM Agent
- Client Communication Agent
- Product Manager
- Technical Architect
- Repository Intelligence Agent
- Builder Agent
- Patch Engineer
- QA Agent
- Content Strategy Agent
- Content Production Agent
- Research and Evaluation Agent

Every definition includes a department, objective, approved tools, permissions, data access, cost limit, maximum risk, reviewer, escalation destination, and performance objectives.

The five founder-approved revenue prompts are packaged and versioned for the Revenue Workforce Orchestrator, Chief Revenue Officer, Lead Discovery and Outreach, Senior Sales Closer, and Head of Marketing and Demand Generation roles.

## Included foundation

- SQLite task and hierarchy database
- Durable company event stream and audit log
- Versioned agent registry and 15 written policy families
- Workflow engine with dependencies and state transitions
- Evidence-based independent review
- Authenticated approval gateway
- Cost ledger and per-task/employee limits
- Privacy- and budget-aware model routing
- Institutional knowledge and decision records
- Daily founder briefing and executive dashboard
- Telegram approval cards and `/briefing`
- REST API and the Amaura panel in the JARVIS HUD

## Workflows

`lead_to_revenue` covers sourced opportunities, qualification, proposal, founder commitment approval, and CRM tracking.

`software_delivery` covers product requirements, architecture, repository intelligence, implementation, precision patching, independent QA, and founder release approval.

`content_campaign` covers evidence, master content, claim verification, and founder publication approval.

`research_experiment` requires a falsifiable hypothesis before it creates work, then versions the experiment, independently evaluates it, and gates model release.

`client_acquisition` is the full 16-stage evidence-governed pipeline: campaign, discovery, research, contact resolution, deterministic qualification, proof matching, opportunity analysis, outreach, compliance, founder approval, follow-up, replies, discovery, proposal, commercial approval, and delivery handoff.

`content_factory` is the full 12-stage production loop: research, strategy, script, product demonstration, voice, licensed assets, master render, media QA, repurposing, thumbnails/metadata, founder-approved private publication draft, and analytics learning.

## Configuration

```bash
export AMAURA_FOUNDER_NAME="Akshat"
export AMAURA_FOUNDER_ID="founder"
export AMAURA_DATA_DIR="$PWD/.amaura-data"
export AMAURA_APPROVAL_KEY="use-a-long-random-secret"
export AMAURA_OPERATOR_KEY="use-a-different-long-random-secret"
export TELEGRAM_USER_ID="your-telegram-user-id"
```

`AMAURA_OPERATOR_KEY` protects detailed reads and all ordinary company mutations. `AMAURA_APPROVAL_KEY` is a separate founder-only authority for final decisions. Protected REST calls use `X-Amaura-Operator-Key` or `X-Amaura-Approval-Key` respectively. Endpoints return `503` when the relevant key is not configured and `403` for an invalid key. Telegram approval buttons are disabled unless `TELEGRAM_USER_ID` is configured. The server binds to `127.0.0.1` by default; explicitly set `JARVIS_HOST` only when remote access has its own trusted network boundary.

## Operating from JARVIS

Use natural language, for example:

> Create an Amaura software-delivery programme to raise patch reliability from 46% to 65%, with regressions below 2%.

JARVIS calls the company tools to create the full hierarchy and returns task IDs. It can then issue or run only the first dependency-ready task. Employee output goes to the registered independent reviewer. A founder decision is requested when the workflow reaches a gated action.

Useful control surfaces:

- `/company` — executive dashboard
- `/briefing` — daily founder operating briefing
- `/approvals` — pending founder decisions
- `GET /api/amaura/dashboard`
- `GET /api/amaura/tasks`
- `GET /api/amaura/events`
- `GET /api/amaura/audit`
- `GET /api/amaura/briefing`

## Non-negotiable doctrine

1. No agent certifies its own work.
2. No public claim exists without evidence.
3. No external commitment occurs without authority.
4. No experiment runs without a hypothesis.
5. No project survives without measurable strategic value.
