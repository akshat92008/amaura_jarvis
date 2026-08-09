# Amaura Company OS v3.0 — Autonomous Company Runtime

Amaura Company OS is a founder-controlled operating system for running an early-stage AI research and product company with a governed AI workforce.

## What v3.0 operates continuously

The runtime maintains 12 persistent founder objectives and 18 governed workflows across research, product, engineering, content, distribution, community, customer success, revenue, finance, operations, security and open-source delivery.

Every company cycle performs the following bounded loop:

1. Create and verify the daily SQLite backup.
2. Reconcile completed programmes into measurable founder objectives.
3. Detect internal signals from failed work, security alerts, content analytics and cost pressure.
4. Convert eligible signals into exactly-once response programmes.
5. Schedule due daily, weekly and monthly objective programmes.
6. Enqueue only founder-approved publications whose schedule has arrived.
7. Execute a bounded number of governed tasks.
8. Independently review evidence with a distinct local or NVIDIA reviewer model.
9. Pause departments automatically after repeated failures.
10. Produce the founder portfolio, briefing, approval queue and run ledger.

## Autonomy boundary

Agents may autonomously research, analyse, draft, code in isolated workspaces, run tests, prepare content packages, manage internal records and recommend decisions.

The following remain founder-controlled:

- public publishing;
- outbound communication;
- production deployment and merging high-risk changes;
- spending and payments;
- legal commitments;
- strategy changes;
- credential grants;
- destructive production operations.

This is intentional. Removing those gates would make the system less reliable, not more agentic.

## Free-first model strategy

`AMAURA_MODEL_MODE=balanced` uses NVIDIA for approved cloud work and local Ollama for restricted data or fallback. Review can use either:

- `AMAURA_REVIEW_MODE=local` with a distinct local reviewer model; or
- `AMAURA_REVIEW_MODE=cloud` with `AMAURA_CLOUD_REVIEW_MODEL` and an NVIDIA key.

Cloud review reads the worker model execution receipt and rejects correlated review when the same model performed the work.

## Continuous macOS operation

Interactive launch:

```bash
./Launch_Amaura.command
```

Install the login/crash-restarting LaunchAgent:

```bash
./Install_Amaura_Autopilot.command
```

Remove it:

```bash
./Uninstall_Amaura_Autopilot.command
```

The generated LaunchAgent contains no credentials. The runtime loads the private mode-0600 `.env.amaura` file itself.

## Kill switches

Pause all autonomous planning and execution:

```bash
.venv/bin/amaura company autopilot pause --reason "Founder pause"
```

Re-enable it:

```bash
.venv/bin/amaura company autopilot enable --reason "Founder restart"
```

Pause a single department:

```bash
.venv/bin/amaura company department growth_media pause --reason "Quality review"
```

## Daily verified backups

Autopilot creates one transactionally consistent database backup per UTC day, validates SQLite integrity and foreign keys, atomically installs the final file and removes backups older than the configured retention period.

```dotenv
AMAURA_AUTOMATIC_BACKUPS=1
AMAURA_BACKUP_RETENTION_DAYS=14
```

## MacBook M3 8GB profile

The Mac runs the control plane, database, evidence vault, task queue, dashboard and bounded local tools. Heavy model inference is routed to NVIDIA when approved. Local models are used sequentially for restricted or fallback work. Docker limits the sandbox to the configured memory and CPU values.

Do not run local video generation or multiple large models alongside the company runtime on an 8GB machine. Flow, official APIs or external media workers remain optional accelerators.
