# Amaura Company OS v3.5.1 — Implementation and Operations

## Delivered scope

Amaura Company OS is a founder-directed, AI-native, evidence-governed and free-first internal workforce. It is designed to run company cadence, research, product discovery, software delivery, content production, distribution, revenue operations, customer success, community, finance and security without granting uncontrolled external authority.

### Workforce and departments

The registry contains 57 governed role contracts. Each employee has a mission, tool envelope, data boundary, task budget, risk limit, reviewer and measurable output contract. Department leads coordinate narrow specialists rather than relying on one unrestricted general agent.

### Workflows

Twenty-one durable workflows are registered. The added company-level workflows are:

1. `company_operating_review` — evidence, finance, distribution, product and priority review.
2. `product_discovery` — problem evidence, market assessment, product specification and decision memo.
3. `incident_response` — contain, investigate, repair, independently review and reactivate.

Existing acquisition, content and governed delivery workflows remain available.

## Safe autonomy

`AutonomousCompanyRuntime` performs a bounded company tick:

1. Ensures exactly one weekly operating-review programme using an ISO-week idempotency key.
2. Lets the governed supervisor advance one eligible unit of work.
3. Performs independent review when configured.
4. Returns a founder briefing and supervisor status.

It cannot independently publish, message external people, deploy to production, spend above policy, make payments, accept legal commitments, delete production data, grant credentials or change company strategy.

## Free-first capability routing

The router ranks resources in this order:

1. Amaura built-ins and SQLite.
2. Open-source/local tools such as Git, FFmpeg, Whisper, Ollama and Docker.
3. Configured free APIs such as NVIDIA.
4. Existing subscriptions through approved handoffs.
5. Paid APIs only when explicitly allowed.

Optional services such as n8n, Qdrant, Twenty CRM and PostHog are adapters, not mandatory runtime dependencies. This prevents the 8GB Mac from running every service simultaneously.

## Antigravity and Google Flow

`amaura handoff antigravity` creates an immutable engineering packet containing the repository, allowed paths, ordered plan, acceptance criteria, test evidence requirements, risk summary and rollback requirements.

`amaura handoff flow` creates a scene-by-scene production packet containing prompts, duration, camera direction, continuity, negative prompts, aspect ratio, licensing restrictions and QA criteria.

These handoffs never store or automate consumer credentials. An official API or CLI adapter can later replace a manual handoff without changing company workflows.

## MacBook M3 8GB operating profile

Keep the control plane, SQLite, dashboard and lightweight queue active. Start browser workers, Docker, Whisper, Ollama or media rendering only when required, then stop them. Recommended concurrent agent executions: two. Heavy reasoning and generation should use configured cloud providers.

## Security defaults

- Legacy direct tool mode defaults to disabled; any explicitly enabled read-only tools share governed workspace and network boundaries.
- `/api/tool` is disabled unless `JARVIS_ENABLE_LEGACY_DIRECT_TOOLS=1`.
- Direct WebSocket tool execution is disabled.
- WebSocket origins are allowlisted.
- Fable API routes and dashboards are disabled unless explicitly enabled.
- Workspace writes are contained and commands use an allowlist without `shell=True`.
- Remote sensitive HTTP APIs require authentication.
- Sensitive external actions remain founder-approved and receipt-backed.

## Core commands

```bash
amaura company-blueprint
amaura resources
amaura init
amaura doctor
amaura autopilot --once
amaura worker --once
```

Create a managed engineering handoff:

```bash
amaura handoff antigravity \
  --objective "Implement the bounded feature" \
  --repository /path/to/repository \
  --plan-json '["Inspect the repository", "Implement the bounded change", "Run verification"]' \
  --criteria-json '["All tests pass", "Risk and rollback notes are returned"]'
```

Create a Flow production handoff:

```bash
amaura handoff flow \
  --objective "Produce approved scenes" \
  --scenes-json '[{"prompt":"Approved scene prompt","duration_seconds":8}]' \
  --criteria-json '["Clip matches the approved storyboard", "No unlicensed assets"]' \
  --aspect-ratio 16:9
```

## Verification

Run:

```bash
bash scripts/verify_amaura.sh
PYTHONPATH=. python3 scripts/stress_amaura.py
```

At the packaging checkpoint:

- 233 tests pass in isolated process shards.
- Full repository Python compilation passes.
- The corrected adversarial stress run passes with 1,000 leads and 32 workers.
- Static source certification passes.
- Production remains fail-closed until environment secrets, provider receipt keys, distinct reviewer routing, strict local model configuration and the Docker sandbox are validated on the target machine.

## Honest limitation

This is an operational company kernel, not a magical independent corporation. External credentials, platform access, human judgment, product-market feedback and real-world partnerships are still required. Autonomy should be expanded only after measured task success, low correction rates, stable costs and zero policy violations.
