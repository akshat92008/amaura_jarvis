# Amaura Labs AI System Handbook

**Complete operating, administration, security, workflow, and recovery manual**

Version 1.0 · Source snapshot 2026-07-27 · Internal operations

This handbook is the practical source of truth for installing, accessing, operating, reviewing, securing, testing, backing up, and extending the Amaura AI Workforce inside JARVIS.

> **Authority statement:** The founder owns strategy, truth, money, legal commitments, public reputation, and production risk. JARVIS is the sole company orchestrator. Specialist employees operate only inside issued task packets and cannot certify their own work.

<!-- PAGEBREAK -->

## Document control

| Field | Value |
| --- | --- |
| Document owner | Amaura Labs founder / JARVIS operator |
| Applies to | The 57-role Amaura Workforce, 21 workflows, SQLite operating ledger, REST and JARVIS tool surfaces |
| Source of truth | `jarvis/amaura/`, `jarvis/server.py`, `jarvis/tools/amaura.py`, `.env.amaura.example`, and production verification artifacts |
| Review trigger | Any registry, workflow, policy, API, database, model-route, provider, or authority change |
| Verified baseline | 233 isolated tests passed; static checks, authenticated API smoke, deterministic wheel build, and 1,000-lead stress passed |
| Classification | Internal operations. Never place real secrets in this document. |

### How to use this handbook

- **New operator:** read Sections 1–5, then follow Sections 12–14 exactly.
- **Founder:** use Sections 4, 15, 18, and 22 for authority, daily decisions, incidents, and release gates.
- **Revenue team:** use Sections 8 and 16 plus the endpoint recipes in Section 20.
- **Content team:** use Sections 9 and 17 plus the asset-readiness rules in Section 10.
- **Engineer or administrator:** use Sections 6–7 and 18–23.
- In Word, open the Navigation Pane to jump through the real heading hierarchy. The Markdown file is searchable and friendly to version control.

## Contents

1. System purpose and operating status
2. Architecture and authority chain
3. Core concepts and terminology
4. Governance, risk, and founder authority
5. System components
6. Complete AI employee directory
7. Workflow engine and task lifecycle
8. Client-acquisition system
9. Amaura Content Factory
10. Data, evidence, and storage
11. Models, prompts, tools, and execution
12. Installation and first-time configuration
13. How to start and access the system
14. First-day acceptance procedure
15. Daily founder and operator routine
16. Running a client-acquisition campaign
17. Running a content campaign
18. Approvals, pauses, kill switches, and incidents
19. Monitoring, costs, backup, and recovery
20. REST API and command reference
21. Testing, stress testing, and release readiness
22. External integrations and rollout stages
23. Troubleshooting and maintenance
24. Operational checklists and glossary

<!-- PAGEBREAK -->

# Part I — Orientation and control

## 1. System purpose and operating status

### 1.1 What the system is

Amaura is a local-first, governed company operating kernel inside JARVIS. It converts a founder objective into a programme, project, milestone, and dependency-ordered specialist tasks. Every task has a named owner, independent reviewer, measurable exit criteria, budget, risk level, allowed tools, approved data, model route, evidence, audit entries, and—when required—a separately authenticated founder decision.

The system is not a collection of autonomous bots with unrestricted company access. It is an authority-controlled workflow engine whose AI employees are bounded by deterministic code and durable records.

### 1.2 What is production-ready today

- The local operating kernel: workforce registry, workflow creation, task dispatch, policy enforcement, independent review, approvals, events, audit logs, budgets, readiness checks, acquisition controls, content asset controls, SQLite persistence, backups, REST surfaces, and JARVIS tools.
- Authenticated operation on the local machine after three independent authority keys are configured.
- Device-only routing for restricted data through Ollama, with no silent cloud fallback.
- A 52-role registry and nine workflow templates, including the full 16-stage acquisition pipeline and 12-stage content factory.

### 1.3 What is not automatically active

Gmail sending, Telegram decisions, OBS recording, Postiz or YouTube publication, external sandboxes, contracts, payments, and production deployments are not active merely because the kernel exists. Those capabilities require real binaries, credentials or OAuth grants, provider adapters, least-privilege scopes, and provider-confirmed callbacks. Until then, the system prepares, governs, records, and verifies work but does not claim the external action occurred.

> **No-silent-success rule:** `/messages/{id}/sent` is a confirmation boundary, not an email client. Record a send only after an approved provider returns a real message identifier.

### 1.4 Verified release baseline

| Gate | Verified result |
| --- | --- |
| Repository tests | 63 passed, 0 failed |
| Static analysis | Focused Ruff passed; focused mypy passed on eight core modules |
| Packaging | Wheel built: `release/jarvis-3.5.1-py3-none-any.whl` |
| API security smoke | Authenticated routes passed; missing operator authority rejected with HTTP 403 |
| Stress run | 1,000 leads, 32 workers, 100/100 injections detected, 60 provider-confirmed sends, 20/20 cap violations blocked |
| Concurrency and idempotency | 500 simultaneous duplicate attempts produced one record |
| Storage | SQLite integrity `ok`, no foreign-key violations, WAL enabled |

## 2. Architecture and authority chain

### 2.1 Authority path

```text
Founder
  └── separately authenticated decisions and manual critical actions
      └── JARVIS — sole control plane
          ├── Programme → Project → Milestone → dependency-ordered Tasks
          ├── Policy Engine → tools, paths, commands, data, cost and risk
          ├── Model Gateway → privacy/budget-aware model route
          ├── Specialist Employee → evidence-bearing submission
          ├── Independent Reviewer → approve or return changes
          └── Founder Approval → consequential completion boundary
```

### 2.2 Runtime request path

```text
Browser / CLI / JARVIS chat / REST client
        │
        ▼
FastAPI server (loopback by default; restricted CORS)
        │  operator key or approval key
        ▼
AmauraControlPlane
        ├── CompanyStore (SQLite + WAL + foreign keys)
        ├── PolicyEngine
        ├── ModelGateway
        ├── GovernedTaskRunner
        ├── AcquisitionPipeline
        └── ContentFactory
```

### 2.3 Separation of responsibilities

| Layer | Owns | Must not do |
| --- | --- | --- |
| Founder | Strategy, final truth, external commitments, reputation, money, critical execution | Delegate irreversible authority to an unauthenticated agent |
| JARVIS | Programme creation, task packets, dispatch, orchestration, pause, escalation, briefing | Permit self-review or bypass the registered workflow |
| Specialist employee | One bounded task, approved tools/data, evidence-backed output | Expand scope, exceed budget, invent facts, certify itself |
| Independent reviewer | Acceptance criteria, evidence quality, defects and policy verification | Review its own work or approve without findings |
| Policy engine | Deterministic allow/deny and approval requirements | Treat model text as authority |
| External adapter | One provider action and provider-confirmed result | Claim success without provider evidence |

## 3. Core concepts and terminology

| Term | Meaning |
| --- | --- |
| Programme | Top-level founder outcome with a measurable success metric. |
| Project | A workflow instance used to deliver the programme. |
| Milestone | Completion boundary containing the workflow tasks. |
| Task packet | JARVIS-issued execution contract: objective, criteria, owner, reviewer, tools, data, budget, dependencies, model route, policies, workspace, and doctrine. |
| Evidence | A typed, stable reference supporting a completion claim—tool output digest, source URL/excerpt, artifact hash, test result, or provider identifier. |
| Action type | Business meaning of an action, used to load relevant policies and determine approval. |
| Risk level | Low, medium, high, or critical. It constrains ownership, review, approval, and manual execution. |
| Idempotency | Repeating the same request produces or returns the same governed resource instead of duplicating side effects. |
| Kill switch | Immediate acquisition control that blocks discovery and send confirmation while preserving state. |
| Readiness | Truthful configuration report: core checks, blockers, and optional adapter availability. |

## 4. Governance, risk, and founder authority

### 4.1 Non-negotiable doctrine

1. No employee certifies its own work.
2. No completion exists without evidence.
3. No public claim exists without source-linked support.
4. No external commitment occurs without the required authority.
5. No experiment runs without a falsifiable hypothesis, baseline, threshold, budget, and reproducibility data.
6. No employee exceeds its issued task packet, tool set, data scope, risk ceiling, or budget.
7. Critical actions are manual founder actions; an AI tool call cannot execute them autonomously.

### 4.2 Risk behavior

| Risk | Expected behavior | Completion authority |
| --- | --- | --- |
| Low | Specialist executes approved tools; independent reviewer verifies | Completes after successful review unless action type is externally gated |
| Medium | Tighter evidence and independent review | Founder approval after review |
| High | Consequential or reputational action; narrow authority | Founder approval required |
| Critical | Irreversible, financial, destructive, or production-critical | Manual founder execution; autonomous tool action denied |

### 4.3 Founder decision statuses

Allowed approval decisions are `approved`, `rejected`, `changes_requested`, `postponed`. A decision requires a reason. Approval completes the task; rejection or changes requested blocks it; postponement leaves it awaiting approval.

### 4.4 External action classes

The policy engine treats these action types as external or consequential: `client_commitment`, `contract_acceptance`, `external_outreach`, `external_proposal`, `model_release`, `payment`, `production_deployment`, `public_content`, `public_publish`, `refund`. The workflow can also require founder approval through a registered founder reviewer even when an action is otherwise internal.

### 4.5 Policy catalogue

#### 4.5.1 Core Authority

**Version:** 1.0 · **Applies to:** `*`

- The founder owns strategy, truth, financial/legal commitments, reputation, and production risk.
- JARVIS is the only company orchestrator and may pause any employee or workflow.
- No employee may certify its own work; completion requires evidence and the registered reviewer.
- Critical actions require explicit manual execution, not autonomous tool use.

#### 4.5.2 External Communication

**Version:** 1.0 · **Applies to:** `external_proposal`, `client_commitment`, `draft_external`

- Drafts must distinguish facts, assumptions, and recommendations.
- No price, deadline, scope, partnership, or outcome may be promised without founder approval.
- Client communication must use only the approved client record.

#### 4.5.3 Pricing And Discounts

**Version:** 1.0 · **Applies to:** `external_proposal`, `client_commitment`, `payment`, `refund`

- Pricing must include delivery effort, model/API cost, support burden, risk premium, and margin.
- Discounts and refunds require founder approval and a recorded rationale.

#### 4.5.4 Client Data

**Version:** 1.0 · **Applies to:** `client_commitment`, `repository_write`, `draft_external`

- Confidential client data stays on approved local models and stores.
- Grant least-privilege access for the shortest required duration.
- Never place credentials, personal data, or confidential code in prompts or logs.

#### 4.5.5 Licensing

**Version:** 1.0 · **Applies to:** `repository_write`, `research_compute`, `model_release`, `public_content`

- Record source and licence for code, datasets, models, and media.
- Reject incompatible or unknown licences.
- Model releases require a licence inventory.

#### 4.5.6 Public Claims

**Version:** 1.0 · **Applies to:** `public_content`, `public_publish`, `model_release`

- Every number, achievement, benchmark, date, and attribution must link to evidence.
- Preserve limitations and negative results.
- Client material requires documented permission.

#### 4.5.7 Model Evaluation

**Version:** 1.0 · **Applies to:** `research_compute`, `model_release`

- No experiment runs without a falsifiable hypothesis, baseline, regression threshold, and budget.
- Accept models only on recorded evaluation suites, never subjective impressions.
- Training and evaluation data must be checked for contamination.

#### 4.5.8 Production Deployment

**Version:** 1.0 · **Applies to:** `production_deployment`

- Production requires test evidence, migration check, health thresholds, and a tested rollback plan.
- Founder approval is mandatory.
- Roll back automatically when approved health thresholds fail.

#### 4.5.9 Security Incidents

**Version:** 1.0 · **Applies to:** `incident_response`

- Contain harm before diagnosis or public communication.
- Preserve logs and an incident timeline.
- Escalate suspected client-data or credential exposure immediately.

#### 4.5.10 Credentials

**Version:** 1.0 · **Applies to:** `*`

- Secrets belong in the configured secrets manager or environment, never source, prompts, artefacts, or logs.
- Rotate exposed credentials and record the incident.

#### 4.5.11 Data Retention

**Version:** 1.0 · **Applies to:** `*`

- Retain only data required for a documented company purpose.
- Deletion of material or client data is high risk and needs founder approval.
- Audit and decision records are immutable.

#### 4.5.12 Financial Spending

**Version:** 1.0 · **Applies to:** `research_compute`, `payment`, `refund`, `repository_write`

- Every cost must name a task, employee, category, amount, and units.
- Stop before the task or employee budget is exceeded.
- Money transfer requires explicit manual founder execution.

#### 4.5.13 Content Publication

**Version:** 1.0 · **Applies to:** `public_content`, `public_publish`

- Publishing requires verified sources, sensitivity review, platform policy check, and founder approval.
- Founder Voice content must not imply personal authorship or experience that did not occur.

#### 4.5.14 Conflicts Of Interest

**Version:** 1.0 · **Applies to:** `external_proposal`, `client_commitment`, `public_publish`

- Disclose material affiliations, incentives, and client conflicts before recommendation or publication.

#### 4.5.15 Agent Shutdown

**Version:** 1.0 · **Applies to:** `*`

- JARVIS may pause an employee on repeated failure, budget breach, policy violation, or unsafe behaviour.
- Shutdown preserves evidence, state, and audit history.
- Only the founder may restore an employee disabled for a critical violation.

# Part II — Components, employees, and workflows

## 5. System components

| Component | Primary file | Responsibility |
| --- | --- | --- |
| Control plane | `jarvis/amaura/control_plane.py` | Creates hierarchy, issues task packets, dispatches, reviews, approvals, costs, pauses, decisions, dashboard and rollups. |
| Workforce registry | `jarvis/amaura/registry.py` | 52 enforceable employee envelopes: mission, tools, permission, data, budget, risk, reviewer, metrics, prompt. |
| Workflow catalogue | `jarvis/amaura/workflows.py` | Six dependency graphs with owners, reviewers, budgets, risks, action types, and acceptance criteria. |
| Policy engine | `jarvis/amaura/policy.py` | Assignment and tool authorization, command/path checks, secret detection, approval and completion gates. |
| Written policies | `jarvis/amaura/policies.py` | 15 policy families loaded into institutional knowledge and attached to applicable task packets. |
| Execution runner | `jarvis/amaura/executor.py` | Runs one specialist, exposes only approved tools, captures evidence, records model cost, and submits for review. |
| Model gateway | `jarvis/amaura/model_gateway.py` | Selects local, hybrid, or approved cloud route by sensitivity, risk, capability, and remaining budget. |
| Company store | `jarvis/amaura/store.py` | Thread-safe SQLite ledger with WAL, foreign keys, audit, events, costs, acquisition and content records, backup and integrity check. |
| Acquisition pipeline | `jarvis/amaura/pipeline.py` | Evidence, scoring, stage transitions, outreach approvals, limits, opt-outs, idempotency, send confirmation and kill switch. |
| Content factory | `jarvis/amaura/content_factory.py` | Campaigns, hash-addressed assets, licensing, publication readiness and analytics windows. |
| Security boundary | `jarvis/amaura/security.py` | Injection scan, sensitive-data scan, untrusted-data isolation, redaction and content hashing. |
| Readiness service | `jarvis/amaura/readiness.py` | Reports actual core blockers and optional adapter availability without exposing secrets. |
| REST server | `jarvis/server.py` | Local UI, API, auth middleware, Amaura endpoints, JARVIS endpoints and WebSocket access. |
| JARVIS tool surface | `jarvis/tools/amaura.py` | Functions used by conversational JARVIS to operate the company OS. |

## 6. Complete AI employee directory

The live registry contains **52 unique employees**. Every entry below is generated from the implemented registry. Budget is a per-task maximum; model and tool costs are still checked against the task's remaining budget.

### 6.1 Workforce summary

| Department | Employees | Count |
| --- | --- | --- |
| Control plane | JARVIS, Human Approval Coordinator | 2 |
| Revenue and acquisition | Opportunity Scout, Lead Qualification Agent, Proposal Agent, CRM Agent, Client Communication Agent, Revenue Workforce Orchestrator, Chief Revenue Officer, Campaign Manager, Lead Scout, Prospect Research Analyst, Contact Resolver, Portfolio Matcher, Opportunity Analyst, Outreach Writer, Revenue Compliance and Quality Reviewer, Senior Sales Closer, Follow-up Agent, Reply Intelligence Agent, Discovery and Meeting Agent | 19 |
| Delivery | Won Project Handoff Agent | 1 |
| Product engineering | Product Manager, Technical Architect, Repository Intelligence Agent, Builder Agent, Patch Engineer, QA Agent | 6 |
| Growth and media | Content Strategy Agent, Content Production Agent, Head of Marketing and Demand Generation, Trend and Content Research Employee, Scriptwriting Employee, Product Demo Employee, Voice Production Employee, Media Asset and Licence Employee, Video Production Employee, Short-form Repurposing Employee, Thumbnail and Metadata Employee, Media QA and Claims Employee, Publishing and Scheduling Employee, Content Analytics and Learning Employee | 14 |
| AI research | Research and Evaluation Agent | 1 |

### 6.2 Control plane

#### 6.2.1 JARVIS (`jarvis`)

- **Mission:** Translate founder direction into measurable programmes and govern every agent.
- **Operating ceiling:** high risk; $50.00 per-task cost limit; model policy `balanced`.
- **Tools:** `amaura_create_program`, `amaura_company_status`, `amaura_task_packet`, `amaura_daily_briefing`.
- **Authority:** `plan`, `delegate`, `pause`, `escalate`, `request_approval`.
- **Approved data:** `company`, `products`, `clients`, `research`, `marketing`, `decisions`, `costs`.
- **Verification:** reviewer `founder`; escalation destination `jarvis`.
- **Performance measures:** programme outcome rate, blocked-task age, budget variance, founder decision latency.

#### 6.2.2 Human Approval Coordinator (`approval_coordinator`)

- **Mission:** Present complete approval cards and execute only the founder's authenticated decision.
- **Operating ceiling:** high risk; $1.00 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`.
- **Authority:** `request_approval`, `create_draft_after_approval`.
- **Approved data:** `qualified_leads`, `evidence`, `messages`, `approvals`.
- **Verification:** reviewer `founder`; escalation destination `jarvis`.
- **Performance measures:** approval packet completeness, stale approval rate, unauthorised action rate.

### 6.3 Revenue and acquisition

#### 6.3.1 Opportunity Scout (`opportunity_scout`)

- **Mission:** Discover evidence-backed commercial opportunities from approved sources.
- **Operating ceiling:** low risk; $3.00 per-task cost limit; model policy `balanced`.
- **Tools:** `web_search`, `web_fetch`, `read_file`.
- **Authority:** `research`, `draft`.
- **Approved data:** `public`, `approved_lead_sources`.
- **Verification:** reviewer `lead_qualification`; escalation destination `jarvis`.
- **Performance measures:** qualified opportunities, source coverage, false-positive rate.

#### 6.3.2 Lead Qualification Agent (`lead_qualification`)

- **Mission:** Reject poor-fit work and rank viable leads by value, risk, and strategic relevance.
- **Operating ceiling:** low risk; $2.50 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `vector_search`.
- **Authority:** `analyse`, `recommend`.
- **Approved data:** `leads`, `pricing_policy`, `client_history`.
- **Verification:** reviewer `jarvis`; escalation destination `jarvis`.
- **Performance measures:** accepted-lead win rate, bad-fit rejection rate.

#### 6.3.3 Proposal Agent (`proposal`)

- **Mission:** Draft specific proposals grounded in verified requirements and approved pricing policy.
- **Operating ceiling:** medium risk; $4.00 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `create_document`.
- **Authority:** `draft`.
- **Approved data:** `qualified_leads`, `proposal_templates`, `pricing_policy`.
- **Verification:** reviewer `jarvis`; escalation destination `jarvis`.
- **Performance measures:** proposal acceptance rate, unsupported-claim rate.

#### 6.3.4 CRM Agent (`crm`)

- **Mission:** Maintain lead state, communications, value, probability, follow-up, and next action.
- **Operating ceiling:** low risk; $1.50 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `write_file`.
- **Authority:** `read_crm`, `update_crm`.
- **Approved data:** `leads`, `client_communications`.
- **Verification:** reviewer `jarvis`; escalation destination `jarvis`.
- **Performance measures:** record completeness, overdue follow-ups.

#### 6.3.5 Client Communication Agent (`client_communication`)

- **Mission:** Draft accurate client replies and updates without making unapproved commitments.
- **Operating ceiling:** medium risk; $3.00 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `create_document`.
- **Authority:** `draft_external`.
- **Approved data:** `client_requirements`, `client_communications`, `project_status`.
- **Verification:** reviewer `jarvis`; escalation destination `jarvis`.
- **Performance measures:** draft approval rate, commitment violations.

#### 6.3.6 Revenue Workforce Orchestrator (`revenue_orchestrator`)

- **Mission:** Run an ethical, measurable loop from one campaign through won-project handoff.
- **Operating ceiling:** medium risk; $6.00 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `web_search`, `amaura_company_status`, `amaura_list_tasks`.
- **Authority:** `plan`, `delegate`, `recommend`, `request_approval`.
- **Approved data:** `campaigns`, `leads`, `evidence`, `messages`, `pipeline_metrics`, `portfolio`.
- **Verification:** reviewer `jarvis`; escalation destination `jarvis`.
- **Performance measures:** qualified pipeline value, positive reply rate, sales-cycle length, won revenue.

#### 6.3.7 Chief Revenue Officer (`chief_revenue_officer`)

- **Mission:** Create predictable, profitable project revenue without compromising Amaura's reputation.
- **Operating ceiling:** medium risk; $7.00 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `vector_search`, `amaura_company_status`, `amaura_list_tasks`.
- **Authority:** `analyse`, `prioritise`, `recommend_pricing`, `request_approval`.
- **Approved data:** `campaigns`, `leads`, `proposals`, `pricing_policy`, `portfolio`, `revenue_metrics`.
- **Verification:** reviewer `jarvis`; escalation destination `jarvis`.
- **Performance measures:** qualified reply rate, proposal conversion, average project value, recurring revenue.

#### 6.3.8 Campaign Manager (`campaign_manager`)

- **Mission:** Configure one bounded offer, segment, region, proof set, and daily operating envelope.
- **Operating ceiling:** low risk; $2.00 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `vector_search`.
- **Authority:** `plan`, `configure_campaign`.
- **Approved data:** `campaigns`, `portfolio`, `pricing_policy`.
- **Verification:** reviewer `chief_revenue_officer`; escalation destination `jarvis`.
- **Performance measures:** campaign completeness, target precision, limit compliance.

#### 6.3.9 Lead Scout (`lead_scout`)

- **Mission:** Discover public, campaign-fit businesses without restricted scraping or guessed contact data.
- **Operating ceiling:** low risk; $2.50 per-task cost limit; model policy `balanced`.
- **Tools:** `web_search`, `web_fetch`, `read_file`.
- **Authority:** `research`, `draft`.
- **Approved data:** `public`, `campaigns`, `lead_domains`.
- **Verification:** reviewer `prospect_research`; escalation destination `jarvis`.
- **Performance measures:** unique qualified discoveries, duplicate rate, source coverage.

#### 6.3.10 Prospect Research Analyst (`prospect_research`)

- **Mission:** Extract source-linked business evidence from the minimum necessary public pages.
- **Operating ceiling:** low risk; $2.50 per-task cost limit; model policy `balanced`.
- **Tools:** `web_fetch`, `read_file`.
- **Authority:** `research`, `extract`.
- **Approved data:** `public`, `campaigns`, `leads`.
- **Verification:** reviewer `compliance_reviewer`; escalation destination `jarvis`.
- **Performance measures:** evidence completeness, claim precision, pages per lead.

#### 6.3.11 Contact Resolver (`contact_resolver`)

- **Mission:** Locate verifiable public business contact routes and never infer private addresses.
- **Operating ceiling:** low risk; $1.50 per-task cost limit; model policy `balanced`.
- **Tools:** `web_fetch`, `read_file`.
- **Authority:** `research`, `recommend`.
- **Approved data:** `public`, `leads`.
- **Verification:** reviewer `compliance_reviewer`; escalation destination `jarvis`.
- **Performance measures:** verified contact rate, guessed-address rate.

#### 6.3.12 Portfolio Matcher (`portfolio_matcher`)

- **Mission:** Select at most two genuinely relevant Amaura proof assets for each prospect.
- **Operating ceiling:** low risk; $1.00 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `vector_search`.
- **Authority:** `analyse`, `recommend`.
- **Approved data:** `leads`, `portfolio`, `verified_evidence`.
- **Verification:** reviewer `opportunity_analyst`; escalation destination `jarvis`.
- **Performance measures:** proof relevance, unsupported proof rate.

#### 6.3.13 Opportunity Analyst (`opportunity_analyst`)

- **Mission:** Turn verified evidence into one specific, non-invented commercial opportunity.
- **Operating ceiling:** low risk; $1.80 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `vector_search`.
- **Authority:** `analyse`, `recommend`.
- **Approved data:** `leads`, `evidence`, `portfolio`.
- **Verification:** reviewer `compliance_reviewer`; escalation destination `jarvis`.
- **Performance measures:** observation acceptance, unsupported-claim rate.

#### 6.3.14 Outreach Writer (`outreach_writer`)

- **Mission:** Prepare concise, personalised, proof-based outreach for human approval.
- **Operating ceiling:** medium risk; $2.50 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `create_document`.
- **Authority:** `draft_external`.
- **Approved data:** `qualified_leads`, `evidence`, `portfolio`, `brand_policy`.
- **Verification:** reviewer `compliance_reviewer`; escalation destination `jarvis`.
- **Performance measures:** approval rate, qualified reply rate, rewrite rate.

#### 6.3.15 Revenue Compliance and Quality Reviewer (`compliance_reviewer`)

- **Mission:** Reject unsupported claims, spam, irrelevant proof, opt-out violations, and duplicate contact.
- **Operating ceiling:** low risk; $1.80 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `vector_search`.
- **Authority:** `analyse`, `approve_or_reject`.
- **Approved data:** `leads`, `evidence`, `messages`, `policies`.
- **Verification:** reviewer `jarvis`; escalation destination `jarvis`.
- **Performance measures:** false approvals, policy escape rate, review precision.

#### 6.3.16 Senior Sales Closer (`sales_closer`)

- **Mission:** Convert qualified replies into profitable, bounded paid milestones and retainers.
- **Operating ceiling:** medium risk; $4.50 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `create_document`, `vector_search`.
- **Authority:** `analyse`, `draft_external`, `recommend_pricing`.
- **Approved data:** `qualified_leads`, `communications`, `portfolio`, `pricing_policy`.
- **Verification:** reviewer `jarvis`; escalation destination `jarvis`.
- **Performance measures:** close rate, advance-payment rate, scope defects, recurring revenue.

#### 6.3.17 Follow-up Agent (`followup`)

- **Mission:** Prepare at most two relevant follow-ups and stop immediately on rejection or opt-out.
- **Operating ceiling:** medium risk; $1.20 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `create_document`.
- **Authority:** `draft_external`.
- **Approved data:** `messages`, `leads`, `evidence`.
- **Verification:** reviewer `compliance_reviewer`; escalation destination `jarvis`.
- **Performance measures:** follow-up reply rate, limit compliance, opt-out compliance.

#### 6.3.18 Reply Intelligence Agent (`reply_intelligence`)

- **Mission:** Classify lead replies, extract needs, and prepare grounded next actions without commitments.
- **Operating ceiling:** medium risk; $1.80 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `vector_search`.
- **Authority:** `analyse`, `draft_external`.
- **Approved data:** `lead_threads`, `leads`, `pricing_policy`.
- **Verification:** reviewer `sales_closer`; escalation destination `jarvis`.
- **Performance measures:** classification accuracy, commitment violations, response latency.

#### 6.3.19 Discovery and Meeting Agent (`discovery`)

- **Mission:** Prepare evidence-backed meeting briefs and turn founder notes into bounded requirements.
- **Operating ceiling:** low risk; $2.20 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `create_document`, `vector_search`.
- **Authority:** `analyse`, `draft`.
- **Approved data:** `leads`, `evidence`, `communications`, `portfolio`.
- **Verification:** reviewer `sales_closer`; escalation destination `jarvis`.
- **Performance measures:** brief completeness, unresolved-risk capture, next-action clarity.

### 6.4 Delivery

#### 6.4.1 Won Project Handoff Agent (`project_handoff`)

- **Mission:** Create a complete, least-privilege delivery packet after approved commercial acceptance.
- **Operating ceiling:** medium risk; $3.00 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `write_file`, `create_document`.
- **Authority:** `draft`, `create_delivery_packet`.
- **Approved data:** `won_leads`, `approved_proposals`, `client_requirements`.
- **Verification:** reviewer `product_manager`; escalation destination `jarvis`.
- **Performance measures:** handoff completeness, delivery clarification rate, credential exposure rate.

### 6.5 Product engineering

#### 6.5.1 Product Manager (`product_manager`)

- **Mission:** Turn validated needs into requirements, acceptance criteria, milestones, and releases.
- **Operating ceiling:** low risk; $4.00 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `search_code`, `get_project_structure`.
- **Authority:** `plan`, `define_acceptance_criteria`.
- **Approved data:** `products`, `user_evidence`, `roadmap`.
- **Verification:** reviewer `technical_architect`; escalation destination `jarvis`.
- **Performance measures:** acceptance-criteria pass rate, scope change rate.

#### 6.5.2 Technical Architect (`technical_architect`)

- **Mission:** Define secure, maintainable architecture, boundaries, data design, and rollback strategy.
- **Operating ceiling:** low risk; $5.00 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `search_code`, `get_project_structure`, `analyze_code`.
- **Authority:** `analyse_repo`, `author_adr`, `recommend`.
- **Approved data:** `repositories`, `products`, `security_policy`.
- **Verification:** reviewer `qa`; escalation destination `jarvis`.
- **Performance measures:** architecture defects, decision reversals.

#### 6.5.3 Repository Intelligence Agent (`repository_intelligence`)

- **Mission:** Select only relevant repository context and maintain symbol and dependency maps.
- **Operating ceiling:** low risk; $3.00 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `search_code`, `find_files`, `get_project_structure`, `index_repository`, `query_symbols`.
- **Authority:** `read_repo`, `index_repo`.
- **Approved data:** `repositories`.
- **Verification:** reviewer `technical_architect`; escalation destination `jarvis`.
- **Performance measures:** context precision, wrong-file rate, context token savings.

#### 6.5.4 Builder Agent (`builder`)

- **Mission:** Implement approved plans in isolated workspaces without self-certification.
- **Operating ceiling:** medium risk; $12.00 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `search_code`, `write_file`, `run_command`, `run_tests`.
- **Authority:** `read_repo`, `write_branch`, `run_safe_commands`.
- **Approved data:** `assigned_repository`, `approved_plan`.
- **Verification:** reviewer `qa`; escalation destination `jarvis`.
- **Performance measures:** first-pass QA rate, regression rate, cost per accepted task.

#### 6.5.5 Patch Engineer (`patch_engineer`)

- **Mission:** Apply exact, pre-approved transformations and report the expected post-edit state.
- **Operating ceiling:** medium risk; $5.00 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `edit_file`, `diff_files`.
- **Authority:** `read_repo`, `write_exact_patch`.
- **Approved data:** `approved_plan`, `target_files`.
- **Verification:** reviewer `qa`; escalation destination `jarvis`.
- **Performance measures:** patch application rate, wrong-file rate, format compliance.

#### 6.5.6 QA Agent (`qa`)

- **Mission:** Independently verify acceptance criteria, regressions, security, and evidence.
- **Operating ceiling:** low risk; $7.00 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `search_code`, `run_tests`, `lint_code`, `analyze_code`, `git_diff`.
- **Authority:** `read_repo`, `run_safe_commands`, `approve_or_reject`.
- **Approved data:** `repositories`, `test_evidence`, `policies`.
- **Verification:** reviewer `jarvis`; escalation destination `jarvis`.
- **Performance measures:** escaped defects, false approvals, verification coverage.

### 6.6 Growth and media

#### 6.6.1 Content Strategy Agent (`content_strategy`)

- **Mission:** Turn verified company events into focused content opportunities and editorial plans.
- **Operating ceiling:** low risk; $3.00 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `web_search`.
- **Authority:** `research`, `plan`, `draft`.
- **Approved data:** `verified_company_events`, `brand_policy`, `marketing_metrics`.
- **Verification:** reviewer `jarvis`; escalation destination `jarvis`.
- **Performance measures:** business-qualified content ideas, evidence coverage.

#### 6.6.2 Content Production Agent (`content_production`)

- **Mission:** Create platform-ready assets from verified master sources without inventing achievements.
- **Operating ceiling:** medium risk; $5.00 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `create_document`, `create_presentation`.
- **Authority:** `draft_public`.
- **Approved data:** `approved_content_brief`, `verified_evidence`, `brand_policy`.
- **Verification:** reviewer `jarvis`; escalation destination `jarvis`.
- **Performance measures:** approval rate, claim correction rate, attributed outcomes.

#### 6.6.3 Head of Marketing and Demand Generation (`marketing_head`)

- **Mission:** Turn verified Amaura work into qualified interest, authority, and commercial conversations.
- **Operating ceiling:** medium risk; $4.00 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `web_search`, `create_document`.
- **Authority:** `plan`, `draft_public`.
- **Approved data:** `verified_company_events`, `portfolio`, `brand_policy`, `marketing_metrics`.
- **Verification:** reviewer `jarvis`; escalation destination `jarvis`.
- **Performance measures:** qualified enquiries, portfolio clicks, influenced revenue.

#### 6.6.4 Trend and Content Research Employee (`content_research`)

- **Mission:** Find audience questions, demand, credible sources, content gaps, and Amaura's unique angle.
- **Operating ceiling:** low risk; $2.50 per-task cost limit; model policy `balanced`.
- **Tools:** `web_search`, `web_fetch`, `read_file`.
- **Authority:** `research`, `draft`.
- **Approved data:** `public`, `verified_company_events`, `portfolio`.
- **Verification:** reviewer `content_strategy`; escalation destination `jarvis`.
- **Performance measures:** source quality, content-gap precision, business relevance.

#### 6.6.5 Scriptwriting Employee (`scriptwriter`)

- **Mission:** Create factual long-form scripts, scene plans, claims, demonstrations, hooks, and metadata.
- **Operating ceiling:** medium risk; $3.50 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `create_document`.
- **Authority:** `draft_public`.
- **Approved data:** `approved_content_brief`, `verified_evidence`, `brand_policy`.
- **Verification:** reviewer `media_qa`; escalation destination `jarvis`.
- **Performance measures:** claim accuracy, script approval rate, repurposing yield.

#### 6.6.6 Product Demo Employee (`demo_operator`)

- **Mission:** Record reproducible product demonstrations with secrets and private data excluded.
- **Operating ceiling:** medium risk; $2.50 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `run_command`.
- **Authority:** `run_safe_commands`, `record_demo`.
- **Approved data:** `approved_demo_plan`, `assigned_product`.
- **Verification:** reviewer `media_qa`; escalation destination `jarvis`.
- **Performance measures:** demo success rate, retake rate, secret exposure rate.

#### 6.6.7 Voice Production Employee (`voice_production`)

- **Mission:** Produce consistent, licensed narration without impersonation or unauthorised voice cloning.
- **Operating ceiling:** low risk; $2.00 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `run_command`.
- **Authority:** `run_safe_commands`, `render_audio`.
- **Approved data:** `approved_script`, `pronunciation_dictionary`.
- **Verification:** reviewer `media_qa`; escalation destination `jarvis`.
- **Performance measures:** pronunciation accuracy, audio defects, licence compliance.

#### 6.6.8 Media Asset and Licence Employee (`asset_curator`)

- **Mission:** Collect only owned or licensed visuals with source, creator, terms, and retrieval evidence.
- **Operating ceiling:** low risk; $2.50 per-task cost limit; model policy `balanced`.
- **Tools:** `web_search`, `web_fetch`, `read_file`.
- **Authority:** `research`, `download_approved_assets`.
- **Approved data:** `approved_asset_sources`, `brand_policy`, `content_campaigns`.
- **Verification:** reviewer `media_qa`; escalation destination `jarvis`.
- **Performance measures:** licence completeness, asset relevance, attribution defects.

#### 6.6.9 Video Production Employee (`video_production`)

- **Mission:** Assemble approved recordings, narration, assets, captions, and templates into validated renders.
- **Operating ceiling:** medium risk; $6.00 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `run_command`.
- **Authority:** `run_safe_commands`, `render_media`.
- **Approved data:** `approved_campaign_assets`, `render_templates`.
- **Verification:** reviewer `media_qa`; escalation destination `jarvis`.
- **Performance measures:** render success, technical defect rate, production time.

#### 6.6.10 Short-form Repurposing Employee (`shorts_editor`)

- **Mission:** Select standalone, high-value moments and create permission-safe vertical variants.
- **Operating ceiling:** medium risk; $3.00 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `run_command`.
- **Authority:** `run_safe_commands`, `render_media`.
- **Approved data:** `owned_long_form`, `transcripts`, `brand_policy`.
- **Verification:** reviewer `media_qa`; escalation destination `jarvis`.
- **Performance measures:** accepted clips, context rejection rate, short retention.

#### 6.6.11 Thumbnail and Metadata Employee (`thumbnail_metadata`)

- **Mission:** Create readable, deterministic thumbnail variants, accurate titles, chapters, and descriptions.
- **Operating ceiling:** medium risk; $2.20 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `create_document`, `run_command`.
- **Authority:** `draft_public`, `render_media`.
- **Approved data:** `approved_campaign_assets`, `brand_policy`, `verified_evidence`.
- **Verification:** reviewer `media_qa`; escalation destination `jarvis`.
- **Performance measures:** mobile readability, title accuracy, click-through rate.

#### 6.6.12 Media QA and Claims Employee (`media_qa`)

- **Mission:** Independently verify facts, privacy, licences, audio/video integrity, captions, and calls to action.
- **Operating ceiling:** low risk; $3.50 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `run_command`.
- **Authority:** `run_safe_commands`, `approve_or_reject`.
- **Approved data:** `campaign_assets`, `verified_evidence`, `licence_records`, `policies`.
- **Verification:** reviewer `jarvis`; escalation destination `jarvis`.
- **Performance measures:** escaped claims, privacy escapes, technical defect escapes.

#### 6.6.13 Publishing and Scheduling Employee (`publishing`)

- **Mission:** Prepare private drafts and schedules; make nothing public without founder approval.
- **Operating ceiling:** high risk; $1.80 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`.
- **Authority:** `draft_public`, `schedule_after_approval`.
- **Approved data:** `approved_content`, `platform_policy`, `publication_calendar`.
- **Verification:** reviewer `founder`; escalation destination `jarvis`.
- **Performance measures:** unauthorised publications, metadata completeness, schedule accuracy.

#### 6.6.14 Content Analytics and Learning Employee (`content_analytics`)

- **Mission:** Measure business and audience outcomes at 24h, 72h, 7d, and 30d and preserve evidence-backed lessons.
- **Operating ceiling:** low risk; $2.00 per-task cost limit; model policy `balanced`.
- **Tools:** `read_file`, `vector_search`.
- **Authority:** `analyse`, `recommend`.
- **Approved data:** `platform_analytics`, `content_campaigns`, `revenue_attribution`.
- **Verification:** reviewer `marketing_head`; escalation destination `jarvis`.
- **Performance measures:** lesson evidence quality, qualified enquiries, influenced revenue.

### 6.7 AI research

#### 6.7.1 Research and Evaluation Agent (`research_evaluation`)

- **Mission:** Run hypothesis-led, reproducible research and independently report regressions and costs.
- **Operating ceiling:** medium risk; $15.00 per-task cost limit; model policy `balanced`.
- **Tools:** `web_search`, `web_fetch`, `read_pdf`, `read_file`, `run_command`, `run_tests`.
- **Authority:** `research`, `run_sandboxed_experiment`, `evaluate`.
- **Approved data:** `research`, `datasets`, `models`, `experiment_registry`.
- **Verification:** reviewer `qa`; escalation destination `jarvis`.
- **Performance measures:** reproducible experiments, regressions detected, cost per accepted improvement.

## 7. Workflow engine and task lifecycle

### 7.1 Work hierarchy

A programme creation call validates the objective, success metric, priority, workspace, required inputs, and workflow. JARVIS then inserts the programme, project, milestone, and all tasks. Dependencies are stored as task IDs. Each assignment is policy-validated before the programme is returned.

### 7.2 Task state machine

```text
assigned ──start──> in_progress ──submit+evidence──> awaiting_review
   ▲                    │                                  │
   │                    └── dependency incomplete ──> blocked
   │                                                       │
   └──────── reviewer rejects / changes needed ────────────┘

awaiting_review ──review approved──> completed (low/internal)
awaiting_review ──review approved──> awaiting_approval (gated)
awaiting_approval ──founder approves──> completed
awaiting_approval ──reject/changes──> blocked
```

All defined task states: `draft`, `assigned`, `in_progress`, `blocked`, `awaiting_review`, `awaiting_approval`, `completed`, `failed`, `cancelled`.

### 7.3 Standard execution procedure

1. Founder states an outcome and measurable success threshold.
2. JARVIS chooses one registered workflow and validates required inputs.
3. JARVIS creates the full dependency graph and policy-checks every assignment.
4. Operator starts only a dependency-ready task. An incomplete dependency moves the task to `blocked`.
5. JARVIS issues a task packet and the model gateway selects the permitted route.
6. The specialist receives only approved tool definitions. Every tool action passes through the policy engine.
7. Tool results become digest-addressed evidence; model cost is recorded.
8. Specialist submits a concise result and evidence. It cannot mark itself complete.
9. The registered reviewer records findings and either rejects or approves.
10. If required, founder decides on the separately authenticated approval surface.
11. Completion rolls up through milestone, project, and programme when all children are complete.

### 7.4 Complete workflow catalogue

#### 7.4.1 Evidence-Governed Client Acquisition (`client_acquisition`)

**Department:** `revenue` · **Stages:** 16 · **Required inputs:** `campaign_id`, `target_segment`, `offer`

| # | Stage and work | Owner → reviewer | Risk / budget / action | Dependency and exit gate |
| --- | --- | --- | --- | --- |
| 1 | **Configure bounded campaign** (`campaign`)<br>Select exactly one target segment and offer, regions, proof assets, prohibited sources, and daily limits. | `campaign_manager` → `chief_revenue_officer` | low; $0.80; `internal_work` | After: Start<br>Exit: One segment and one offer selected; Daily discovery/outreach/follow-up limits recorded; Allowed channels and proof assets recorded |
| 2 | **Discover unique public leads** (`discover`)<br>Search approved public sources, capture the source URL, and deduplicate by normalised company domain. | `lead_scout` → `prospect_research` | low; $1.20; `internal_work` | After: campaign<br>Exit: Every lead has a source URL; No restricted scraping; Domains deduplicated |
| 3 | **Build prospect evidence** (`research`)<br>Extract the minimum public facts needed from relevant pages; treat all page text as untrusted data. | `prospect_research` → `compliance_reviewer` | low; $1.20; `internal_work` | After: discover<br>Exit: Every observation has source, excerpt, retrieval time, and confidence; Prompt-injection scan recorded; No irrelevant personal data |
| 4 | **Resolve public contact route** (`contact`)<br>Find a published business email, contact form, or manual profile route without guessing an address. | `contact_resolver` → `compliance_reviewer` | low; $0.60; `internal_work` | After: research<br>Exit: Exact public contact source recorded; No inferred mailbox; No-contact is an accepted outcome |
| 5 | **Score with deterministic rubric** (`qualify`)<br>Score campaign fit, visible need, ability to pay, contactability, and portfolio match; only 70+ advances. | `lead_qualification` → `chief_revenue_officer` | low; $0.80; `internal_work` | After: contact<br>Exit: All weighted dimensions evidenced; Total equals deterministic component sum; Advance/reject rule applied |
| 6 | **Match relevant portfolio proof** (`proof`)<br>Choose no more than two verified Amaura projects that directly support the opportunity. | `portfolio_matcher` → `opportunity_analyst` | low; $0.50; `internal_work` | After: qualify<br>Exit: One or two proof assets selected; Relevance explained; Project status represented accurately |
| 7 | **Define commercial observation** (`opportunity`)<br>Create one evidence-backed opportunity without fabricated criticism or performance claims. | `opportunity_analyst` → `compliance_reviewer` | low; $0.70; `internal_work` | After: proof<br>Exit: Observation traces to evidence; Offer matches campaign; No invented outcome claim |
| 8 | **Draft personalised outreach** (`outreach`)<br>Prepare a concise first contact and two bounded follow-ups with one CTA and relevant proof. | `outreach_writer` → `compliance_reviewer` | medium; $1.00; `draft_external` | After: opportunity<br>Exit: 70-170 words; One evidence-backed observation; One CTA; Maximum two links; No spam language |
| 9 | **Independently review outreach** (`compliance`)<br>Check claims, contact provenance, opt-out state, duplicate contact, length, CTA count, and proof relevance. | `compliance_reviewer` → `jarvis` | low; $0.60; `internal_work` | After: outreach<br>Exit: Claim-evidence links checked; Do-not-contact checked; Idempotency key checked; Rewrite or approval recommendation recorded |
| 10 | **Approve first contact** (`approve_contact`)<br>Present the founder with the lead, score, evidence, complete draft, channel, and exact proposed action. | `approval_coordinator` → `founder` | high; $0.00; `external_outreach` | After: compliance<br>Exit: Founder decision recorded; Approval is message-specific; Stale approvals cannot execute |
| 11 | **Prepare due follow-ups** (`followup`)<br>Prepare day-4 and day-9 follow-ups only when permitted; stop after two or immediately on opt-out. | `followup` → `compliance_reviewer` | medium; $0.60; `draft_external` | After: approve_contact<br>Exit: Next action date recorded; Maximum follow-ups enforced; Opt-out checked |
| 12 | **Classify reply and recommend action** (`reply`)<br>Classify the response, update contact restrictions, and prepare a grounded next action. | `reply_intelligence` → `sales_closer` | low; $0.80; `internal_work` | After: followup<br>Exit: Reply classification recorded; Unsubscribe immediately blocks contact; Unknowns and commitments flagged |
| 13 | **Prepare discovery brief** (`discovery`)<br>Summarise evidence, requirements, questions, decision authority, budget, timeline, and risk for founder-led discovery. | `discovery` → `sales_closer` | low; $1.00; `internal_work` | After: reply<br>Exit: Evidence URLs included; Decision, budget, and timeline gaps explicit; Next action defined |
| 14 | **Draft bounded commercial proposal** (`proposal`)<br>Create a reviewable scope, exclusions, milestones, assumptions, price placeholder, payment terms, and support boundaries. | `sales_closer` → `jarvis` | medium; $1.80; `external_proposal` | After: discovery<br>Exit: Scope and exclusions explicit; Pricing remains human-controlled; Advance payment recommended; No binding promise |
| 15 | **Approve proposal and commitments** (`approve_proposal`)<br>Founder reviews price, timeline, legal terms, capacity, and the exact external document. | `jarvis` → `founder` | high; $0.00; `client_commitment` | After: proposal<br>Exit: Founder decision recorded; Exact proposal version hashed; Capacity confirmed |
| 16 | **Create won-project delivery handoff** (`handoff`)<br>After accepted terms, create intake, scope, milestones, risks, QA plan, communication cadence, and credential checklist. | `project_handoff` → `product_manager` | medium; $2.00; `repository_write` | After: approve_proposal<br>Exit: Commercial source documents linked; Delivery and QA ownership assigned; No raw credentials stored |

#### 7.4.2 Amaura Evidence-Based Content Factory (`content_factory`)

**Department:** `growth_media` · **Stages:** 12 · **Required inputs:** `campaign_id`, `audience`, `business_objective`

| # | Stage and work | Owner → reviewer | Risk / budget / action | Dependency and exit gate |
| --- | --- | --- | --- | --- |
| 1 | **Research demand and verified context** (`research`)<br>Collect real Amaura product evidence, credible sources, audience questions, content gaps, and competing formats. | `content_research` → `content_strategy` | low; $1.20; `internal_work` | After: Start<br>Exit: Source register complete; Amaura relevance explained; No competitor copying |
| 2 | **Create the content strategy** (`strategy`)<br>Choose topic, audience, format, hook, CTA, repurposing angles, business value, and demonstration plan. | `content_strategy` → `marketing_head` | low; $1.00; `internal_work` | After: research<br>Exit: Audience value and business objective explicit; Demonstrability confirmed; Repurposing plan included |
| 3 | **Create script and production package** (`script`)<br>Produce long-form script, sources, claim map, shot list, demo plan, shorts angles, titles, description, and chapters. | `scriptwriter` → `media_qa` | medium; $1.80; `public_content` | After: strategy<br>Exit: Every public claim mapped to evidence; Limitations and status preserved; Scene and demo instructions complete |
| 4 | **Record reproducible product demonstration** (`demo`)<br>Record the real product workflow from an approved plan with private data and secrets excluded. | `demo_operator` → `media_qa` | medium; $1.50; `media_capture` | After: script<br>Exit: Approved demo sequence completed; No credentials or private data visible; Recording integrity verified |
| 5 | **Render narration** (`voice`)<br>Generate scene-based narration using an approved non-cloned voice and pronunciation dictionary. | `voice_production` → `media_qa` | low; $1.00; `internal_work` | After: script<br>Exit: Voice rights recorded; Pronunciation checked; Audio normalised |
| 6 | **Collect licensed media assets** (`assets`)<br>Collect owned screenshots, diagrams, code, and approved stock with complete licence and attribution records. | `asset_curator` → `media_qa` | low; $1.20; `internal_work` | After: script<br>Exit: Every external asset has source and licence; Creator attribution recorded; Only relevant assets retained |
| 7 | **Render master video** (`render`)<br>Combine approved demo, narration, assets, music, transitions, subtitles, and brand templates into a validated master. | `video_production` → `media_qa` | medium; $3.00; `media_render` | After: demo, voice, assets<br>Exit: 1080p master rendered; Audio/video/subtitle synchronisation verified; No black frames or missing assets |
| 8 | **Independently verify master asset** (`qa`)<br>Verify facts, sources, privacy, licences, platform policy, technical integrity, disclosure, and CTA. | `media_qa` → `jarvis` | low; $1.50; `internal_work` | After: render<br>Exit: Claim audit passes; Secret/privacy scan passes; Licence inventory passes; Media integrity checks pass |
| 9 | **Create short-form and written variants** (`repurpose`)<br>Create standalone Shorts/Reels and supporting LinkedIn, X, blog, GitHub, portfolio, and proposal proof assets. | `shorts_editor` → `media_qa` | medium; $1.80; `public_content` | After: qa<br>Exit: Clips are independently understandable; Owned/approved source only; Variants trace to verified master |
| 10 | **Create thumbnails and metadata** (`metadata`)<br>Create three readable thumbnail concepts, accurate titles, chapters, descriptions, captions, and schedule recommendations. | `thumbnail_metadata` → `media_qa` | medium; $1.20; `public_content` | After: repurpose<br>Exit: Text added deterministically; Mobile readability checked; Metadata claims verified |
| 11 | **Approve and prepare publication** (`publish`)<br>Create private platform drafts and present exact previews, claims, channels, timing, and permissions for founder approval. | `publishing` → `founder` | high; $0.80; `public_publish` | After: metadata<br>Exit: Private drafts created; Founder decision recorded; Exact asset hashes included |
| 12 | **Measure and learn** (`analytics`)<br>Collect 24h, 72h, 7d, and 30d performance and revenue signals, then save evidence-backed lessons. | `content_analytics` → `marketing_head` | low; $1.00; `internal_work` | After: publish<br>Exit: Measurement windows recorded; Business metrics separated from vanity metrics; Recommendation tied to evidence |

#### 7.4.3 Lead to Revenue (`lead_to_revenue`)

**Department:** `revenue` · **Stages:** 5 · **Required inputs:** No workflow-specific inputs beyond objective and success metric

| # | Stage and work | Owner → reviewer | Risk / budget / action | Dependency and exit gate |
| --- | --- | --- | --- | --- |
| 1 | **Discover opportunity** (`discover`)<br>Capture source, budget, timeline, requirements, and evidence. | `opportunity_scout` → `lead_qualification` | low; $1.00; `internal_work` | After: Start<br>Exit: Source URL or evidence attached; Budget and timeline captured |
| 2 | **Qualify lead** (`qualify`)<br>Score fit, value, risk, founder involvement, recurrence, and win probability. | `lead_qualification` → `jarvis` | low; $1.00; `internal_work` | After: discover<br>Exit: Fit score justified; Reject/advance recommendation recorded |
| 3 | **Draft proposal** (`proposal`)<br>Produce scope, milestones, assumptions, price recommendation, and exclusions. | `proposal` → `jarvis` | medium; $2.00; `external_proposal` | After: qualify<br>Exit: Requirements traced; No unsupported commitment; Pricing policy applied |
| 4 | **Approve proposal submission** (`approve_proposal`)<br>Founder reviews external commitments before submission. | `jarvis` → `founder` | high; $0.00; `client_commitment` | After: proposal<br>Exit: Founder decision recorded |
| 5 | **Track CRM and next action** (`track`)<br>Record proposal status, expected value, probability, and follow-up date. | `crm` → `jarvis` | low; $0.50; `internal_work` | After: approve_proposal<br>Exit: CRM fields complete; Next action dated |

#### 7.4.4 Verified Software Delivery (`software_delivery`)

**Department:** `product_engineering` · **Stages:** 7 · **Required inputs:** No workflow-specific inputs beyond objective and success metric

| # | Stage and work | Owner → reviewer | Risk / budget / action | Dependency and exit gate |
| --- | --- | --- | --- | --- |
| 1 | **Define requirements** (`requirements`)<br>Write user stories, boundaries, measurable acceptance criteria, and explicit exclusions. | `product_manager` → `technical_architect` | low; $1.50; `internal_work` | After: Start<br>Exit: User outcome defined; Acceptance criteria are testable; Scope exclusions recorded |
| 2 | **Approve technical design** (`architecture`)<br>Map architecture, interfaces, data flow, security constraints, and rollback. | `technical_architect` → `qa` | low; $1.50; `internal_work` | After: requirements<br>Exit: Relevant ADR recorded; Security and rollback addressed |
| 3 | **Build repository context** (`context`)<br>Identify exact files, symbols, dependencies, tests, and recent changes needed by builders. | `repository_intelligence` → `technical_architect` | low; $1.00; `internal_work` | After: architecture<br>Exit: Relevant files justified; Dependency context attached; Irrelevant context excluded |
| 4 | **Implement approved plan** (`implementation`)<br>Implement the accepted design in an isolated branch and record commands and diffs. | `builder` → `qa` | medium; $5.00; `repository_write` | After: context<br>Exit: Implementation matches approved design; No placeholders; Change evidence attached |
| 5 | **Apply precision patch** (`patch`)<br>Apply exact remaining transformations to approved target files. | `patch_engineer` → `qa` | medium; $2.00; `repository_write` | After: implementation<br>Exit: Patch applies cleanly; Expected post-edit state demonstrated |
| 6 | **Independently verify delivery** (`verification`)<br>Run unit, integration, regression, security, and acceptance checks. | `qa` → `jarvis` | low; $3.00; `internal_work` | After: patch<br>Exit: Acceptance criteria evidenced; Tests and regressions reported; No self-certification |
| 7 | **Prepare release decision** (`release`)<br>Collect evidence, migrations, rollback plan, notes, version, and deployment request. | `jarvis` → `founder` | high; $1.00; `production_deployment` | After: verification<br>Exit: Release evidence complete; Rollback plan tested; Founder decision recorded |

#### 7.4.5 Verified Company Content (`content_campaign`)

**Department:** `growth_media` · **Stages:** 3 · **Required inputs:** No workflow-specific inputs beyond objective and success metric

| # | Stage and work | Owner → reviewer | Risk / budget / action | Dependency and exit gate |
| --- | --- | --- | --- | --- |
| 1 | **Collect content evidence** (`evidence`)<br>Identify a verified company event, audience, business objective, sources, and sensitivity. | `content_strategy` → `jarvis` | low; $1.00; `internal_work` | After: Start<br>Exit: Evidence sources attached; Audience and objective named; Sensitivity assessed |
| 2 | **Create master content asset** (`master_asset`)<br>Create one factual source asset preserving limitations and actual claims. | `content_production` → `jarvis` | medium; $2.00; `public_content` | After: evidence<br>Exit: Every public claim has evidence; Limitations preserved; Call to action defined |
| 3 | **Approve publication** (`publication`)<br>Review final variants, timing, claims, permissions, and platform policy. | `jarvis` → `founder` | high; $0.00; `public_publish` | After: master_asset<br>Exit: Founder approval recorded |

#### 7.4.6 Reproducible Research Experiment (`research_experiment`)

**Department:** `ai_research` · **Stages:** 4 · **Required inputs:** `hypothesis`

| # | Stage and work | Owner → reviewer | Risk / budget / action | Dependency and exit gate |
| --- | --- | --- | --- | --- |
| 1 | **Define measurable hypothesis** (`hypothesis`)<br>Record prior work, baseline, expected change, regression threshold, cost, and risk. | `research_evaluation` → `jarvis` | low; $2.00; `internal_work` | After: Start<br>Exit: Hypothesis is falsifiable; Baseline and regression threshold defined; Compute budget defined |
| 2 | **Run reproducible experiment** (`experiment`)<br>Version data and config, run the sandboxed experiment, and preserve exact reproducibility metadata. | `research_evaluation` → `qa` | medium; $9.00; `research_compute` | After: hypothesis<br>Exit: Dataset and config versioned; Compute and cost recorded; Raw results preserved |
| 3 | **Independently evaluate results** (`evaluation`)<br>Compare with baseline, categorise failures, test safety and efficiency, and report regressions. | `qa` → `jarvis` | low; $3.00; `internal_work` | After: experiment<br>Exit: Baseline comparison complete; Regressions reported; Conclusion follows evidence |
| 4 | **Approve model release** (`model_release`)<br>Verify model card, licences, claims, hashes, limitations, and installation package. | `jarvis` → `founder` | high; $1.00; `model_release` | After: evaluation<br>Exit: Model release evidence complete; Founder approval recorded |

## 8. Client-acquisition system

### 8.1 Purpose and operating boundary

The acquisition system creates an ethical, evidence-backed revenue loop from one bounded campaign to won-project handoff. It does not scrape restricted sources, guess private contact details, generate spam, or send without founder approval. Public material is evidence, never instruction.

### 8.2 Campaign envelope

| Control | Enforced range/default | Why it exists |
| --- | --- | --- |
| Minimum qualification score | 70–100; default 70 | Prevents threshold dilution |
| Daily lead limit | 1–100; default 10 | Bounds discovery volume |
| Daily first-contact limit | 0–50; default 3 | Prevents volume-first outreach |
| Daily follow-up limit | 0–100; default 5 | Bounds follow-up operations |
| Maximum follow-ups | 0–2; default 2 | Stops after two attempts |
| Approval lifetime | 48 hours | Prevents stale message approval |
| First-contact length | 70–170 words | Keeps outreach concise and specific |
| Domain uniqueness | Global unique normalized domain | Prevents duplicate prospect records |

### 8.3 Deterministic score

| Component | Maximum points |
| --- | --- |
| Campaign Fit | 25 |
| Visible Need | 25 |
| Ability To Pay | 20 |
| Contactability | 15 |
| Portfolio Match | 15 |

All five integer components are required and must stay inside their bounds. Their sum is the 100-point total. A total at or above the campaign threshold becomes `qualified`; a lower score becomes `rejected`.

### 8.4 Lead stages and legal transitions

| Current stage | Allowed next stage(s) |
| --- | --- |
| `discovered` | `duplicate`, `rejected`, `researching` |
| `researching` | `invalid_contact`, `rejected`, `researched` |
| `researched` | `invalid_contact`, `qualified`, `rejected` |
| `qualified` | `outreach_drafted`, `rejected` |
| `outreach_drafted` | `awaiting_approval`, `rejected` |
| `awaiting_approval` | `outreach_drafted`, `rejected`, `sent` |
| `sent` | `followup_due`, `lost`, `opted_out`, `replied` |
| `followup_due` | `awaiting_approval`, `lost`, `opted_out`, `replied` |
| `replied` | `discovery`, `lost`, `opted_out` |
| `discovery` | `lost`, `negotiation`, `proposal_drafted` |
| `proposal_drafted` | `discovery`, `lost`, `proposal_sent` |
| `proposal_sent` | `lost`, `negotiation`, `won` |
| `negotiation` | `lost`, `proposal_drafted`, `won` |
| `won` | `delivery` |
| `delivery` | `completed` |
| `completed` | `testimonial_requested` |
| `testimonial_requested` | Terminal |

Terminal stages block further transition or contact: `rejected`, `lost`, `opted_out`, `invalid_contact`, and `duplicate`. Opt-out also sets the permanent do-not-contact flag and clears the next action.

### 8.5 Evidence record

Every prospect-specific claim requires a public HTTP(S) source, an exact excerpt, confidence from 0 to 1, retrieval time, and SHA-256 content hash. The excerpt is scanned for prompt injection and sensitive data, redacted when necessary, and stored as evidence. Duplicate evidence is rejected by a database uniqueness constraint.

### 8.6 Message governance

- First contact requires a qualifying score and at least one evidence record.
- Draft identity is derived from the lead, channel, message type, subject, and body; identical staging returns the existing message.
- The founder approves or rejects the exact stored message. A changed message requires a new approval.
- After 48 hours, an undecided message becomes stale.
- An approved message is not `sent` until a provider message ID is recorded.
- Daily send caps are enforced atomically inside SQLite, including concurrent calls.
- A lead that opts out between approval and send is still blocked.

### 8.7 Revenue dashboard

The dashboard reports kill-switch state, campaign and lead counts, qualified count, active pipeline value, messages awaiting approval, provider-confirmed sends, opt-outs, and counts for every lead stage. Treat it as an operating summary, not an accounting ledger.

## 9. Amaura Content Factory

### 9.1 Purpose

The Content Factory turns verified company work into factual, licensed, quality-checked, founder-approved content and then records measured outcomes. It separates research, script, demonstration, voice, assets, rendering, QA, repurposing, metadata, publishing, and analytics so no creator self-certifies the final public asset.

### 9.2 Asset record contract

Every asset needs a campaign, asset type, URI, and valid lowercase SHA-256 digest. External HTTP(S) assets additionally require a source URL and recorded licence. Supported non-web schemes are local paths, `file`, and `artifact`. Status must be `draft`, `approved`, or `rejected`. The combination of campaign, type, and digest is unique.

### 9.3 Publication readiness

A campaign is technically ready only when these approved asset types exist: `claim_map`, `licence_inventory`, `master`, `metadata`, `qa_report`. It must also have no missing external licence/source record and no duplicate asset hashes. Even then, founder approval remains required.

### 9.4 Measurement and learning

Metrics are recorded by platform for the controlled windows `24h`, `30d`, `72h`, `7d`. Values must be non-negative numbers. Track qualified enquiries, portfolio clicks, discovery calls, proposals, influenced revenue, retention, and conversion separately from vanity metrics such as raw impressions.

### 9.5 Media-specific rules

- Demonstrations use real approved workflows and exclude credentials and private data.
- Narration uses a licensed, approved non-cloned voice unless explicit rights exist.
- Every external visual, audio, dataset, code sample, and model has a source and licence record.
- Every public number, benchmark, date, achievement, and attribution appears in the claim map.
- Media QA independently checks privacy, secrets, licences, audio/video integrity, captions, policy, disclosure, CTA, and limitations.
- Publishing starts with a private platform draft. The founder reviews the exact asset hashes, claims, channel, timing, permissions, and metadata.

## 10. Data, evidence, and storage

### 10.1 Default location and portability

The Amaura database path is `AMAURA_DATA_DIR/amaura.db`. Set `AMAURA_DATA_DIR` to a writable, backed-up location. JARVIS stores its other data under `JARVIS_DATA_DIR`. SQLite foreign keys are enabled and journal mode is WAL for safe concurrent readers and controlled writers.

### 10.2 Database catalogue

| Table | Purpose | Important controls |
| --- | --- | --- |
| `agents` | Persisted workforce definitions and enabled state | Unique agent ID; pause/resume state |
| `work_items` | Programme/project/milestone/task hierarchy | Parent FKs, budgets, state, evidence, dependencies, metadata |
| `approvals` | Founder decision requests | Task FK, status, decision actor/reason, immutable history |
| `events` | Durable company event stream | Monotonic sequence and timestamp |
| `audit_logs` | Authority and policy decisions | Actor, action, resource, outcome, details |
| `knowledge` | Versioned institutional knowledge and policy material | Namespace/key identity, evidence refs, sensitivity |
| `decisions` | Institutional decision register | Options, choice, rationale, owner, review date |
| `costs` | Task/employee cost ledger | Non-negative amount; task and owner linkage |
| `campaigns` | Acquisition campaign boundaries | Threshold and daily limit checks |
| `leads` | Prospect state and commercial fields | Unique normalized domain; score and do-not-contact constraints |
| `lead_evidence` | Source-linked prospect claims | Confidence, content hash, uniqueness |
| `messages` | Exact outbound drafts and provider confirmations | Unique idempotency key and provider message ID |
| `pipeline_events` | Acquisition audit/event ledger | Input hash, output, agent, lead and campaign linkage |
| `idempotency_records` | Duplicate-side-effect prevention | Unique operation key |
| `system_controls` | Kill switches and runtime controls | Named key, actor, update time |
| `content_campaigns` | Content objectives and configuration | Campaign identity and status |
| `content_assets` | Hash-addressed content and licence inventory | Unique campaign/type/hash and approval status |
| `content_metrics` | Platform/window performance | Unique campaign/platform/window |
| `content_lessons` | Evidence-backed learning | Campaign linkage and evidence refs |

### 10.3 Evidence quality standard

A good evidence reference is stable, reproducible, minimal, and directly supports the claim. Examples: `pytest` result digest plus report path, immutable artifact SHA-256, source URL plus exact excerpt and retrieval time, Git diff/commit reference, database query result, or provider message ID. A model saying “done” is not evidence.

### 10.4 Data handling

- Store credentials only in an environment or secrets manager, never prompts, source, artifacts, or logs.
- Mark client-confidential, secret, or restricted tasks with matching sensitivity so model routing stays device-only.
- Grant the minimum data namespace and workspace needed for the task.
- Preserve audit, event, approval, and decision history.
- Deletion of material or client data is high risk and requires founder authority.

## 11. Models, prompts, tools, and execution

### 11.1 Model routing

| Condition | Route | Fallback | Privacy behavior |
| --- | --- | --- | --- |
| Sensitivity is client-confidential, secret, or restricted | `ollama-local` | None | Device-only; failure stops the task |
| Vision required | `llama-vision` through approved NVIDIA route | `llama-3.3-70b` | Cloud-approved data only |
| Balanced agent or high/critical reasoning | `fable-5-reasoning` hybrid | `llama-3.3-70b` | Cloud-approved data only |
| Routine permitted task | `llama-3.3-70b` | `ollama-local` | Lower-cost route |

Routing estimates cost before execution and refuses a route that exceeds remaining task budget. Restricted local inference never falls back to cloud. The local model is controlled by `AMAURA_LOCAL_MODEL` and Ollama by `OLLAMA_URL`.

### 11.2 Prompt catalogue

Five founder-supplied revenue prompts are packaged, versioned, and loaded into matching roles: Revenue Workforce Orchestrator, Chief Revenue Officer, Lead Discovery and Outreach, Senior Sales Closer, and Head of Marketing and Demand Generation. All roles also receive the company doctrine. Treat prompt text as versioned configuration; deterministic policy code remains the authority boundary.

### 11.3 Tool risk classes

| Class | Meaning | Registered tools/examples |
| --- | --- | --- |
| R0 | Read-only local context | find_files, get_project_structure, query_symbols, read_file, search_code, vector_search |
| R1 | External/public retrieval | read_pdf, web_fetch, web_search |
| R2 | Workspace mutation or local execution | create_document, create_presentation, edit_file, run_command, run_tests, write_file |
| R3 | External communication/publication | create_gmail_draft, publish_content, schedule_post, send_email, send_message |
| R4 | Critical/irreversible | delete_data, payment, production_deploy, refund |

Unknown tools default to R2. R3 and R4 tools cannot run directly through an employee; they require an authenticated founder approval adapter. R4 remains manual execution.

### 11.4 Command and path safety

Company employees cannot use shell operators, substitutions, newlines, or redirection in `run_command`. Commands must match the governed prefixes below. Every path argument must resolve inside the task's assigned workspace.

```text
pytest
python -m pytest
python3 -m pytest
ruff
mypy
tsc
rg
ls
git status
git diff
git log
npm test
npm run test
npm run build
npm run lint
pnpm test
pnpm build
pnpm lint
cargo test
cargo check
go test
```

### 11.5 Prompt-injection and secret defense

Untrusted public text is scanned for instruction override language, system/developer prompt references, secret-exfiltration language, role-tag markup, and sensitive credential patterns. Store it as quoted evidence inside an explicit untrusted-data boundary. A positive scan does not become an instruction; it becomes a security finding and content hash.

# Part III — Installation and everyday use

## 12. Installation and first-time configuration

### 12.1 Prerequisites

- macOS or another supported Python environment with this repository present.
- The repository virtual environment at `.venv` and project dependencies installed.
- Ollama running with the configured local model for restricted tasks.
- FFmpeg when media rendering is required.
- Three independent random authority keys of at least 24 characters.

### 12.2 Configure the environment

Copy `.env.amaura.example` into your secret-management method. Do not commit real values. For a temporary local shell:

```bash
cd /path/to/Amaura-Company-OS
source .venv/bin/activate
export AMAURA_FOUNDER_NAME="Akshat"
export AMAURA_FOUNDER_ID="founder"
export AMAURA_DATA_DIR="$PWD/.amaura-data"
export JARVIS_DATA_DIR="$PWD/.jarvis-data"
export AMAURA_OPERATOR_KEY="replace-with-independent-random-value"
export AMAURA_APPROVAL_KEY="replace-with-a-different-random-value"
export JARVIS_API_KEY="replace-with-a-third-random-value"
export JARVIS_HOST="127.0.0.1"
export JARVIS_PORT="8000"
export OLLAMA_URL="http://127.0.0.1:11434"
export AMAURA_LOCAL_MODEL="qwen2.5-coder:1.5b"
```

> Generate secrets with an approved password manager or `python -c 'import secrets; print(secrets.token_urlsafe(32))'`. Run it separately for each key. Never paste the generated values into source, tickets, screenshots, or the handbook.

### 12.3 Environment variable reference

| Variable | Required | Purpose / safe default |
| --- | --- | --- |
| `AMAURA_FOUNDER_NAME` | Recommended | Name shown in briefing/dashboard; default `Akshat` |
| `AMAURA_FOUNDER_ID` | Recommended | Founder authority identity; default `founder` |
| `AMAURA_DATA_DIR` | Recommended | Writable Amaura SQLite location |
| `JARVIS_DATA_DIR` | Recommended | Writable general JARVIS data location |
| `AMAURA_OPERATOR_KEY` | Yes | Detailed reads and ordinary Amaura mutations; 24+ characters |
| `AMAURA_APPROVAL_KEY` | Yes | Separate founder-only decisions; 24+ characters and different |
| `JARVIS_API_KEY` | Remote mode; recommended local | General API/WebSocket authority |
| `JARVIS_HOST` | No | Keep `127.0.0.1` unless behind a trusted TLS/auth/network boundary |
| `JARVIS_PORT` | No | HTTP port; default `8000` |
| `JARVIS_CORS_ORIGINS` | No | Explicit allowed web origins; defaults to local origins |
| `OLLAMA_URL` | For restricted AI work | Local Ollama endpoint |
| `AMAURA_LOCAL_MODEL` | For restricted AI work | Device-only model ID |
| `NVIDIA_API_KEY` | For cloud model routes | Base approved model-provider credential |
| `NVIDIA_API_KEY_<AGENT_ID>` | Optional | Per-employee provider key override |
| `TELEGRAM_BOT_TOKEN` | Optional | Telegram bot adapter credential |
| `TELEGRAM_USER_ID` | Optional | Authorized Telegram founder identity; approval buttons stay disabled without it |

## 13. How to start and access the system

### 13.1 Start the local server

```bash
cd /path/to/Amaura-Company-OS
source .venv/bin/activate
python -m jarvis.server
```

Keep the terminal running. The server binds to loopback by default.

### 13.2 Access surfaces

| Surface | Address / command | Use |
| --- | --- | --- |
| JARVIS web dashboard | `http://127.0.0.1:8000/` | Primary browser interface |
| Interactive API documentation | `http://127.0.0.1:8000/docs` | Inspect schemas and execute REST calls |
| Health | `http://127.0.0.1:8000/api/health` | Basic process/provider health |
| Amaura executive dashboard | `GET /api/amaura/dashboard` | High-level company status |
| Readiness | `GET /api/amaura/readiness` | Configuration blockers and adapter truth |
| Terminal interface | `python -m jarvis` | Conversational CLI |
| JARVIS commands | `/company`, `/briefing`, `/approvals` | Executive status and decisions |

### 13.3 Authentication headers

| Header | Use | Never use for |
| --- | --- | --- |
| `X-Amaura-Operator-Key` | Detailed reads, programme/task operations, campaigns, leads, evidence, metrics and send confirmation | Founder approval decisions |
| `X-Amaura-Approval-Key` | Company approvals, exact message decisions, acquisition kill switch | Routine operator calls |
| `X-JARVIS-API-Key` | General JARVIS mutations/remote-mode access where required | Replacing the two Amaura authority keys |

Unconfigured authority returns HTTP 503. An invalid key returns HTTP 403. Do not weaken this behavior for convenience.

### 13.4 Basic access test

```bash
curl -s http://127.0.0.1:8000/api/health
curl -s -H "X-Amaura-Operator-Key: $AMAURA_OPERATOR_KEY" \
  http://127.0.0.1:8000/api/amaura/readiness
curl -s -H "X-Amaura-Operator-Key: $AMAURA_OPERATOR_KEY" \
  http://127.0.0.1:8000/api/amaura/agents
```

## 14. First-day acceptance procedure

Perform this procedure before using real client, prospect, production, or public data.

1. Verify the three keys are configured, 24+ characters, and all different.
2. Confirm `JARVIS_HOST` is loopback and CORS contains only trusted local origins.
3. Call readiness and require `ready: true` for authenticated local operation.
4. Confirm the registry reports 57 unique governed roles and the workflow catalogue includes all 21 workflows.
5. Run `pytest -q` and the focused Ruff/mypy commands in Section 21.
6. Run `python scripts/stress_amaura.py` in a disposable data directory.
7. Create a test programme in a disposable workspace and run its first ready task.
8. Verify a task owner cannot review its own submission.
9. Verify a founder-gated action creates an approval and the operator key cannot decide it.
10. Verify a backup can be restored and passes the integrity check.
11. Keep external adapters in draft/private mode until their provider confirmation tests pass.
12. Record the acceptance decision in the institutional decision register.

## 15. Daily founder and operator routine

### 15.1 Start of day — 10 to 15 minutes

1. Start the server and check `/api/health` and `/api/amaura/readiness`.
2. Read `/briefing` or `GET /api/amaura/briefing`.
3. Review top founder decisions, blocked tasks, stalled tasks, overdue deadlines, budget alerts, critical risks, acquisition opt-outs, and content ready for publication.
4. Resolve only decisions with complete evidence. Use changes requested when the packet is incomplete.
5. Select the next dependency-ready task in each active programme; do not start downstream tasks early.

### 15.2 Midday operating check — 5 to 10 minutes

- Check acquisition daily caps, approval backlog, replies requiring classification, and next-action dates.
- Check content render/QA failures and missing publication asset types.
- Check tasks above 80% of budget and any employee with repeated review rejection.
- Pause an employee or use the acquisition kill switch immediately when unsafe behavior is suspected.

### 15.3 End of day — 10 minutes

- Record real provider IDs for approved sends that actually occurred.
- Confirm opt-outs and failed contacts have terminal state and no next action.
- Capture content metrics only for due measurement windows.
- Record institutional decisions and unresolved risks.
- Create a consistent database backup; inspect the latest audit and event entries.
- Stop or leave the local server according to device security policy.

## 16. Running a client-acquisition campaign

### 16.1 Recommended first campaign

Start with one narrow offer and one segment. The recommended 14-day campaign is small branding, SEO, marketing, and design agencies needing white-label websites, SaaS MVPs, web applications, or AI product development.

### 16.2 Create the governed programme

```bash
curl -s -X POST http://127.0.0.1:8000/api/amaura/programmes \
  -H "Content-Type: application/json" \
  -H "X-Amaura-Operator-Key: $AMAURA_OPERATOR_KEY" \
  -d '{
    "objective": "Create qualified agency-partner opportunities for Amaura Labs",
    "success_metric": "At least 3 qualified replies in 14 days with zero policy violations",
    "workflow_key": "client_acquisition",
    "title": "14-day agency partnership campaign",
    "priority": 2,
    "inputs": {
      "campaign_id": "agency_partner_14d",
      "campaign_name": "14-day agency partnership campaign",
      "target_segment": "Small branding, SEO, marketing and design agencies",
      "offer": "White-label websites, SaaS MVPs, web applications and AI product development",
      "minimum_score": 70,
      "daily_lead_limit": 10,
      "daily_outreach_limit": 3,
      "daily_followup_limit": 5,
      "maximum_followups": 2,
      "proof_assets": ["VEXO", "Cognition OS", "Solar Dynamics", "LeadGenPro"],
      "regions": ["approved regions only"],
      "workspace": "/path/to/Amaura-Company-OS"
    }
  }'
```

Save the returned programme and task IDs. Run only the first dependency-ready task. Each stage's acceptance criteria and reviewer are listed in Section 7.4.

### 16.3 Operator procedure for each prospect

1. Discover a unique public company domain with a public source URL.
2. Research the minimum necessary public pages; record exact claim evidence.
3. Resolve only a verifiable public business contact route. Never infer private addresses.
4. Apply the five-component deterministic score.
5. For a qualified lead, select at most two genuinely relevant proof assets.
6. Write one precise opportunity observation and a 70–170 word first-contact draft.
7. Compliance reviewer checks claims, relevance, duplication, opt-out, tone, and channel policy.
8. Founder approves or rejects the exact message within 48 hours.
9. Approved adapter creates a draft or sends according to the approved rollout stage.
10. Record `sent` only after the provider returns its message ID.
11. Stop immediately on rejection or opt-out; use no more than two follow-ups.
12. On a positive reply, classify need, prepare discovery, propose bounded paid milestones, obtain commercial approval, and create a least-privilege handoff.

### 16.4 Minimum founder approval card

The approval view should show the company, domain, public contact source, campaign, score and components, exact evidence excerpts and URLs, selected proof, exact subject/body, message type, prior thread, opt-out status, daily-cap position, and compliance findings. Reject incomplete cards.

## 17. Running a content campaign

### 17.1 Create the programme

```bash
curl -s -X POST http://127.0.0.1:8000/api/amaura/programmes \
  -H "Content-Type: application/json" \
  -H "X-Amaura-Operator-Key: $AMAURA_OPERATOR_KEY" \
  -d '{
    "objective": "Publish an evidence-backed demonstration of the Amaura AI Workforce",
    "success_metric": "One approved master, three standalone clips, and measured qualified interest",
    "workflow_key": "content_factory",
    "title": "Amaura Workforce demonstration",
    "inputs": {
      "campaign_id": "amaura_workforce_demo_01",
      "audience": "Founders and small agencies needing governed AI delivery",
      "business_objective": "Generate qualified discovery conversations",
      "workspace": "/path/to/Amaura-Company-OS"
    }
  }'
```

### 17.2 Production procedure

1. Research real audience questions and credible sources.
2. Select one business-relevant angle that the real product can demonstrate.
3. Write script, sources, claim map, shot list, demo plan, shorts angles, titles, description, chapters, disclosure, and CTA.
4. Record the approved real workflow with synthetic/test data and no visible secrets.
5. Produce licensed narration and record pronunciation/rights.
6. Register owned/licensed assets with source, creator, terms, and SHA-256.
7. Render the master and verify resolution, synchronization, subtitles, black frames, missing assets, and audio quality.
8. Independent media QA verifies claims, privacy, licensing, policy, integrity, limitations, disclosure, and CTA.
9. Repurpose only understandable, permission-safe moments from the approved master.
10. Create readable thumbnail variants and accurate metadata.
11. Register and approve the required asset set; require readiness `true`.
12. Create private platform drafts and present exact hashes/claims/timing to the founder.
13. After founder approval and real provider publication, record metrics at 24h, 72h, 7d, and 30d.
14. Save evidence-backed lessons and update future briefs; do not rewrite history around vanity metrics.

### 17.3 Asset registration example

```bash
curl -s -X POST \
  http://127.0.0.1:8000/api/amaura/content/campaigns/amaura_workforce_demo_01/assets \
  -H "Content-Type: application/json" \
  -H "X-Amaura-Operator-Key: $AMAURA_OPERATOR_KEY" \
  -d '{
    "asset_type": "master",
    "uri": "artifact://amaura/demo/master-v1.mp4",
    "sha256": "replace-with-64-lowercase-hex-digest",
    "creator": "Amaura Labs",
    "licence": "Owned",
    "status": "approved",
    "metadata": {"resolution": "1920x1080", "version": 1}
  }'
```

# Part IV — Operations, API, testing, and recovery

## 18. Approvals, pauses, kill switches, and incidents

### 18.1 Decide a company approval

```bash
curl -s -X POST \
  http://127.0.0.1:8000/api/amaura/approvals/APPROVAL_ID \
  -H "Content-Type: application/json" \
  -H "X-Amaura-Approval-Key: $AMAURA_APPROVAL_KEY" \
  -d '{"decision": "approved", "reason": "Evidence and exact action reviewed"}'
```

Use `changes_requested` when evidence, scope, claims, permissions, rollback, or cost is incomplete. Never approve merely to unblock the queue.

### 18.2 Pause and resume an employee

JARVIS or the founder can pause any employee except JARVIS. In-progress tasks owned by that employee become blocked and retain evidence/audit history. Only the founder can resume an employee, and a reason is mandatory. JARVIS itself is stopped only through the founder's manual process shutdown.

### 18.3 Acquisition kill switch

```bash
curl -s -X POST http://127.0.0.1:8000/api/amaura/revenue/kill-switch \
  -H "Content-Type: application/json" \
  -H "X-Amaura-Approval-Key: $AMAURA_APPROVAL_KEY" \
  -d '{"enabled": true, "reason": "Unexpected outbound behavior under investigation"}'
```

The kill switch immediately blocks lead discovery and send confirmation. It does not delete records. Turn it off only after cause, impact, and corrective evidence are reviewed.

### 18.4 Incident response

1. **Contain:** stop the server or affected adapter; enable kill switch; pause involved employees; revoke external tokens if exposure is possible.
2. **Preserve:** copy logs and create a consistent database backup. Do not edit audit records.
3. **Scope:** identify affected tasks, tools, workspaces, leads, messages, assets, providers, and time window.
4. **Protect:** rotate exposed keys, remove provider access, preserve opt-outs, and notify the founder immediately for client data or credentials.
5. **Correct:** patch deterministic controls, add a regression test, and verify with adversarial/stress testing.
6. **Recover:** restore only from verified state, resume one component at a time, and keep external adapters in draft mode.
7. **Learn:** record the decision, root cause, evidence, impact, correction, and review date.

## 19. Monitoring, costs, backup, and recovery

### 19.1 What to monitor

| Signal | Healthy behavior | Escalate when |
| --- | --- | --- |
| Readiness | `ready: true`, core operational, no unexpected blocker | Any key, binding, database, registry, prompt, or workflow check fails |
| Task age | Dependency-ready work advances within the operating window | Stalled ≥24 hours without recorded reason |
| Budget | Spend stays below task limit | 80% alert, repeated underestimation, or denied overrun |
| Review | Independent findings and evidence | Self-review attempt, repeated rejection, unsupported completion |
| Acquisition | Caps respected, exact approvals, provider-confirmed sends, opt-outs terminal | Duplicate/unsourced contact, cap pressure, stale approvals, opt-out attempt |
| Content | All required approved assets, valid licences, exact hashes | Missing claim map/licence/QA, duplicate hash, public action without approval |
| Security | No secrets in payloads/logs; injection findings isolated | Secret scan, path escape, unsafe command, suspicious external content |
| Database | Integrity `ok`, no FK violations, WAL | Any integrity failure or unexpected journal mode |

### 19.2 Cost behavior

Every cost names the task, assigned employee, category, amount, units, and metadata. A cost cannot be negative, belong to another employee, or push task spend over budget. The daily briefing flags active tasks at or above 80% of budget. Financial transfers remain manual founder actions.

### 19.3 Consistent backup

```bash
python - <<'PY'
from datetime import datetime, timezone
from pathlib import Path
from jarvis.amaura.store import CompanyStore
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
store = CompanyStore()
target = Path('backups') / f'amaura-{stamp}.db'
print(store.backup(target))
print(store.integrity_check())
store.close()
PY
```

Store backups outside the active data directory, encrypt them, restrict access, retain according to policy, and test restoration on a schedule.

### 19.4 Restore test

1. Stop writers or restore into a separate test path.
2. Copy the chosen backup to a new location; never overwrite the only live copy during a test.
3. Start `AmauraControlPlane(db_path=...)` against the restored file.
4. Require database integrity `ok`, no foreign-key violations, correct agent count, and expected programme/message/asset records.
5. Run read-only dashboard, briefing, audit, and event checks.
6. Record the restore test result and destroy test copies according to retention policy.

## 20. REST API and command reference

### 20.1 Amaura REST endpoints

| Method | Path | Authority | Purpose |
| --- | --- | --- | --- |
| GET | /api/amaura/dashboard | None | Executive dashboard |
| GET | /api/amaura/agents | Operator | Complete employee registry and enabled state |
| GET | /api/amaura/tasks | Operator | Tasks; optional `state`, `owner_id` |
| GET | /api/amaura/tasks/{task_id} | Operator | Task and issued packet |
| POST | /api/amaura/programmes | Operator | Create governed workflow hierarchy |
| POST | /api/amaura/tasks/{task_id}/run | Operator | Run ready specialist task |
| POST | /api/amaura/tasks/{task_id}/review | Operator | Record registered independent review |
| GET | /api/amaura/approvals | Operator | List approvals by status |
| POST | /api/amaura/approvals/{approval_id} | Founder | Decide company approval |
| GET | /api/amaura/events | Operator | Durable events; optional type/limit |
| GET | /api/amaura/audit | Operator | Policy/authority audit entries |
| GET | /api/amaura/briefing | Operator | Daily founder briefing |
| GET | /api/amaura/readiness | Operator | Core blockers and optional adapters |
| GET | /api/amaura/revenue | Operator | Acquisition dashboard |
| POST | /api/amaura/revenue/campaigns | Operator | Create/update bounded campaign |
| GET | /api/amaura/revenue/leads | Operator | Leads; optional campaign/stage |
| POST | /api/amaura/revenue/leads | Operator | Discover unique public lead |
| POST | /api/amaura/revenue/leads/{lead_id}/evidence | Operator | Record source-linked evidence |
| POST | /api/amaura/revenue/leads/{lead_id}/score | Operator | Apply 100-point rubric |
| POST | /api/amaura/revenue/leads/{lead_id}/transition | Operator | Legal state transition with reason |
| POST | /api/amaura/revenue/leads/{lead_id}/messages | Operator | Stage exact idempotent message |
| POST | /api/amaura/revenue/messages/{message_id}/decision | Founder | Approve/reject exact message |
| POST | /api/amaura/revenue/messages/{message_id}/sent | Operator | Record provider-confirmed send |
| POST | /api/amaura/revenue/kill-switch | Founder | Enable/disable acquisition stop |
| POST | /api/amaura/content/campaigns | Operator | Create content campaign |
| POST | /api/amaura/content/campaigns/{campaign_id}/assets | Operator | Register hash/licence asset |
| GET | /api/amaura/content/campaigns/{campaign_id}/readiness | Operator | Publication asset readiness |
| POST | /api/amaura/content/campaigns/{campaign_id}/metrics | Operator | Record platform/window metrics |

### 20.2 Programme request fields

| Field | Required | Rule |
| --- | --- | --- |
| `objective` | Yes | Concrete non-empty company outcome |
| `success_metric` | Yes | Measurable non-empty proof of success |
| `workflow_key` | Yes | One of the nine registered keys |
| `title` | No | Defaults to objective prefix |
| `priority` | No | 1 highest through 5 lowest; default 3 |
| `deadline` | No | ISO-8601 recommended |
| `inputs` | Depends | Workflow inputs plus valid workspace/repository path and optional sensitivity |

### 20.3 Run, review, and approval payloads

```json
POST /api/amaura/tasks/{id}/run
{"max_iterations": 12}

POST /api/amaura/tasks/{id}/review
{"reviewer_id": "qa", "approve": true, "findings": "Criteria and evidence verified"}

POST /api/amaura/approvals/{id}
{"decision": "approved", "reason": "Exact action and evidence reviewed"}
```

### 20.4 JARVIS company tools

| Tool | Use |
| --- | --- |
| `amaura_company_status` | Read executive dashboard |
| `amaura_list_agents` | Inspect employee envelopes |
| `amaura_create_program` | Create full workflow hierarchy |
| `amaura_revenue_dashboard` | Inspect acquisition pipeline |
| `amaura_create_campaign` | Configure bounded campaign |
| `amaura_discover_lead` | Register unique sourced lead |
| `amaura_score_lead` | Apply deterministic score |
| `amaura_list_tasks` | Filter task queue |
| `amaura_task_packet` | Inspect exact task contract |
| `amaura_run_task` | Dispatch specialist |
| `amaura_review_task` | Record independent findings |
| `amaura_pending_approvals` | List founder decisions |
| `amaura_pause_agent` | Pause employee and block active work |
| `amaura_record_decision` | Write institutional decision |
| `amaura_daily_briefing` | Generate daily operating summary |

## 21. Testing, stress testing, and release readiness

### 21.1 Standard verification

```bash
pytest -q
ruff check jarvis/amaura jarvis/paths.py tests/test_amaura_os.py tests/test_amaura_growth.py
mypy --follow-imports=skip --ignore-missing-imports \
  jarvis/amaura/models.py jarvis/amaura/store.py jarvis/amaura/pipeline.py \
  jarvis/amaura/content_factory.py jarvis/amaura/security.py jarvis/amaura/readiness.py \
  jarvis/amaura/registry.py jarvis/amaura/workflows.py
python scripts/stress_amaura.py
python -m build --wheel --no-isolation
```

### 21.2 Stress test coverage

The supplied stress test exercises concurrent lead ingestion, evidence handling, prompt-injection detection, daily outbound caps, duplicate races, provider-confirmed send semantics, and final database integrity. A separate regression test starts 40 simultaneous discoveries against a five-lead daily limit and requires exactly five records.

### 21.3 Release gate

Do not call a release production-ready unless all required tests and analysis pass, the wheel builds, authenticated smoke tests pass, readiness is true for the target environment, database backup/restore is tested, rollback exists, and optional adapter claims match actual installed/configured state. External provider actions require their own sandbox or draft-mode tests and provider evidence.

### 21.4 Known warnings

The verified full suite emitted four upstream/deprecation warnings from HTTPX, MLX, and SpeechRecognition. They were not failures of the Amaura kernel. Track them during dependency upgrades; do not suppress new warnings without understanding them.

## 22. External integrations and rollout stages

### 22.1 Optional integration inventory

| Integration | Probe | Required for core | Operational use |
| --- | --- | --- | --- |
| PydanticAI | `pydantic_ai` | No | Optional typed-agent adapter |
| LangGraph | `langgraph` | No | Optional graph orchestration |
| DBOS | `dbos` | No | Optional durable execution |
| LiteLLM | `litellm` | No | Optional model-provider gateway |
| OpenTelemetry | `opentelemetry` | No | Optional traces/metrics |
| FFmpeg | `ffmpeg` | No | Media rendering and validation |
| Ollama | `ollama` | No | Device-only restricted-data inference |
| OBS | `obs` | No | Product demo recording |
| Promptfoo | `promptfoo` | No | Prompt evaluation/regression |
| Docker/OpenSandbox host | `docker` | No | External isolation host |

At the verified snapshot, FFmpeg and Ollama were available. PydanticAI, LangGraph, DBOS, LiteLLM, OpenTelemetry, OBS, Promptfoo, and Docker/OpenSandbox were not installed. The readiness endpoint must be treated as the current truth because machine state can change.

### 22.2 Safe adapter rollout

| Stage | External behavior | Promotion evidence |
| --- | --- | --- |
| 0 — Offline | Kernel only; no external side effect | Core tests, readiness, audit, backup |
| 1 — Draft | Create Gmail/platform/private draft only | Exact payload, provider draft ID, least privilege, no public/send action |
| 2 — Founder-triggered | Founder clicks/executes exact approved action | Identity check, exact hash/message, provider ID, audit |
| 3 — Bounded automation | Low-volume approved adapter under caps | Sandbox history, idempotency, opt-out, rollback, alerting, error injection |
| 4 — Expanded | Higher controlled volume or more channels | Measured safety/quality, legal/platform review, incident drills, founder approval |

### 22.3 Provider adapter contract

A production adapter must accept the exact approved resource, verify approval freshness and identity, enforce idempotency and daily caps, perform one least-privilege provider action, capture provider response/ID/time, map errors without claiming success, write audit/event records, support dry-run/draft mode, and expose a kill switch. Never store OAuth tokens in the Amaura message body or prompt.

## 23. Troubleshooting and maintenance

| Symptom | Likely cause | Resolution |
| --- | --- | --- |
| HTTP 503 on protected route | Authority key not configured | Set the correct 24+ character environment key and restart |
| HTTP 403 | Wrong header or mismatched key | Use operator vs approval header correctly; compare environment; do not log values |
| Readiness false | One or more blockers | Read the `blockers` array; correct key separation, binding, database, registry, prompt, or workflow check |
| Task becomes blocked at start | Dependency incomplete or employee paused | Complete/review/approve upstream dependency or resolve pause |
| Task cannot run | Wrong state, missing model/provider, exhausted budget | Inspect task packet, state, route, budget, and provider health |
| Restricted task fails | Ollama/model unavailable | Start Ollama and install/configure `AMAURA_LOCAL_MODEL`; no cloud fallback is allowed |
| Tool denied | Not approved, wrong owner/state, unsafe command, path escape, secret, or R3/R4 | Narrow the action; use task workspace and allowed command; remove secret; use approval adapter |
| Review denied | Actor is not registered reviewer, self-review, wrong state, or no findings | Use exact reviewer and provide concrete findings |
| Lead rejected as duplicate | Normalized domain already exists | Use existing record; do not create another identity |
| Lead score rejected | Missing/extra component or out-of-range/non-integer value | Supply exactly the five bounded integers |
| Message staging rejected | No evidence, low score, opt-out/terminal state, wrong length, follow-up maximum | Correct the underlying governance failure; do not bypass |
| Message marked stale | Approval older than 48 hours | Create/review a fresh exact draft |
| Send confirmation rejected | Not approved, no provider ID, cap exceeded, opt-out, kill switch | Do not claim send; resolve valid cause or wait for cap window |
| Content readiness false | Missing approved type, licence issue, or duplicate hash | Register/approve unique required assets with complete source/licence |
| Database integrity fails | Storage corruption or invalid external modification | Stop writes, preserve evidence, restore verified backup, investigate root cause |

### 23.1 Change-management procedure

1. State the behavior change and risk.
2. Update registry/workflow/policy/API/schema source deliberately; do not edit persisted records as a substitute.
3. Add unit, negative, concurrency, security, and migration tests appropriate to the change.
4. Run the full release gate and regenerate this handbook when interfaces change.
5. Record compatibility, migration, rollback, and provider impact.
6. Deploy locally/draft-first; observe; then request founder promotion.

### 23.2 Handbook regeneration

```bash
PYTHONPATH=/path/to/Amaura-Company-OS \
  .venv/bin/python \
  scripts/build_amaura_handbook.py
```

The generator reads the live employee registry, workflow catalogue, policies, score limits, transitions, integrations, and tool classes. Re-render and visually verify the DOCX after regeneration.

## 24. Operational checklists and glossary

### 24.1 Before any external outreach

- [ ] Campaign is narrow, active, within daily limits, and threshold is at least 70.
- [ ] Domain is unique and public source is recorded.
- [ ] Evidence includes exact excerpt, URL, confidence, hash, and safe scan handling.
- [ ] Score uses all five components and meets threshold.
- [ ] Contact route is verifiable and public; no guessed private address.
- [ ] Proof is real, relevant, and no more than two assets.
- [ ] First contact is 70–170 words, specific, truthful, and has a reasonable stop/opt-out path.
- [ ] Independent compliance review passed.
- [ ] Founder approved the exact message within 48 hours.
- [ ] Provider returned a real identifier before the system recorded `sent`.

### 24.2 Before public content

- [ ] Master, claim map, licence inventory, QA report, and metadata are approved and hash-addressed.
- [ ] External assets have source and licence; creator/attribution is recorded.
- [ ] Privacy/secret scan, claim audit, platform policy, disclosure, limitations, captions, and technical QA passed.
- [ ] Readiness reports no missing asset type, licence issue, or duplicate hash.
- [ ] Founder reviewed exact files/hashes, claims, timing, channel, permissions, and CTA.
- [ ] Platform starts as private/draft; provider confirmation is recorded after actual publication.

### 24.3 Before software/model release

- [ ] Requirements and acceptance criteria are testable.
- [ ] Architecture, security, data flow, migration, and rollback are documented.
- [ ] Implementation is isolated and evidence-bearing.
- [ ] Independent unit, integration, regression, security, and acceptance verification passed.
- [ ] Licence inventory and model card exist when applicable.
- [ ] Full release gate, backup, readiness, and rollback test passed.
- [ ] Founder approved; production execution remains a controlled human action.

### 24.4 Glossary

| Term | Operational definition |
| --- | --- |
| Acceptance criteria | Testable conditions that must be evidenced before review can approve. |
| Approval adapter | Authenticated component that performs one exact founder-approved external action. |
| Audit log | Durable record of actor, action, resource, outcome, details, and time. |
| Claim map | Public statement-to-evidence mapping for content verification. |
| Daily cap | Atomic campaign limit on discovery, first contact, or follow-up operations. |
| Doctrine | Company-wide immutable operating instructions shared by all employees. |
| Evidence snapshot | Exact evidence IDs/hashes attached to a staged message or task result. |
| Founder gate | Separately authenticated decision required before consequential completion. |
| Least privilege | Minimum tool, data, credential, and duration needed for one task. |
| Provider confirmation | External service identifier proving an action actually occurred. |
| Reviewer | Registered independent role that verifies the task owner’s submission. |
| Sensitivity | Data handling label controlling model route and exposure. |
| Task packet | Complete bounded work contract issued only by JARVIS. |
| Terminal state | Pipeline state from which further outreach or transition is blocked. |
| WAL | SQLite write-ahead logging mode used for durable concurrent operation. |

## Final operating rule

> Use the system to increase speed, coverage, and consistency—not to dilute truth or authority. If an action changes money, law, reputation, client commitment, public state, production state, or irreversible data, stop at the founder boundary and require complete evidence.

---

Handbook version 1.0. Generated from the implemented Amaura source snapshot dated 2026-07-27.
