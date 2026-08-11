> **Historical v4.0 artifact.** Current release documentation is `README.md`, `AMAURA_JARVIS_V4_1.md`, `V4_1_CHANGELOG.md`, and `V4_1_VALIDATION.json`.

# Amaura JARVIS v4

Amaura v4 adds a general founder-facing intelligence and execution layer **above** the existing governed Company OS. Existing workflows, employees, approvals, evidence, audit, resource controls, integrations and supervisor behaviour remain available.

## What changed

- Natural-language missions compile into bounded dynamic task DAGs.
- Persistent personal/project memory feeds planning.
- Failed dynamic tasks can be re-queued with recorded failure context and a different-strategy instruction.
- Noryx is a first-class governed engineering backend with a strict task/result contract and secret-minimizing environment allowlist.
- The old Nexus adapter/event names remain compatible.
- Antigravity remains founder-controlled: Amaura creates a complete immutable handoff packet and never falsely reports that the external UI executed it.
- Desktop Mission Control exposes missions, chat, memory, company state, approvals and status from one app.

## Execution model

`Founder intent -> GoalCompiler -> validated task DAG -> existing AmauraSupervisor -> worker/Noryx -> evidence -> independent review -> approval boundary -> completion/replan`

Dynamic plans are deliberately restricted to low/medium-risk internal work. External communications, payments, production deployment, destructive changes and similar consequences continue through the existing explicit governed workflows and approval policies.

## Run

1. Copy `.env.amaura.example` to `.env` and configure the existing Amaura keys/providers you intend to use.
2. Install Python dependencies (`pip install -e .`).
3. On macOS, run `./Install_Amaura_Desktop.command` once and then `./Launch_Amaura_Desktop.command`.
4. Cross-platform development: `cd desktop-app && npm install && npm start`.
5. Or start the backend directly with `.venv/bin/python -m jarvis.server`.

The Electron app starts the local backend itself when launched normally.

## Noryx contract

Configure `AMAURA_NORYX_COMMAND` and optionally `AMAURA_NORYX_ARGUMENTS`. Noryx receives `amaura.noryx-task.v1` JSON and must return a structured result file. A zero process exit without a structured result is a failure, not success.

## Antigravity

Antigravity is not exposed as fake unattended automation. Selecting the Antigravity backend generates an immutable founder handoff packet containing the objective, repository, plan, constraints and acceptance criteria.
