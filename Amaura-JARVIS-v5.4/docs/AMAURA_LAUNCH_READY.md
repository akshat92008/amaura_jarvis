# Amaura Labs Internal Workforce — Launch Guide

This repository is configured for **private, founder-controlled local operation**. It fails closed when model separation, Docker isolation, signing keys, evidence rules, Git controls, or founder binding are missing.

## 1. Local prerequisites

Install on the Mac that will run Amaura:

- Python 3.11 or 3.12
- Docker Desktop, with the daemon running
- Ollama
- Git

The default local model configuration is:

```text
worker:   nova:3b
reviewer: qwen2.5-coder:3b
```

The worker and reviewer must be **different installed models**. Change the names in `.env.amaura` when your local Ollama tags differ.

## 2. One-time installation

From Finder, double-click:

```text
Install_Amaura.command
```

Or run:

```bash
./Install_Amaura.command
```

The installer:

1. Creates `.venv`.
2. Installs the package and development verification tools.
3. Generates five independent local signing/API keys.
4. Writes `.env.amaura` with permission mode `0600`.
5. Creates private data, evidence, and backup directories.
6. Runs the full source regression suite.
7. Runs static source certification.

It does **not** enable email or public publishing.

After installation, configure and certify the target Mac:

```bash
./Setup_Amaura_Runtime.command
```

This checks or starts Ollama and Docker Desktop, verifies the distinct worker
and reviewer models, builds the governed sandbox, and runs the live release
gate. It fails closed when any local prerequisite is missing.

## 3. Required founder configuration

Open `.env.amaura` and verify these fields:

```bash
AMAURA_LOCAL_MODEL=nova:3b
AMAURA_LOCAL_REVIEW_MODEL=qwen2.5-coder:3b
```

Telegram control is optional. When enabled, set both values together so approvals are bound to the founder:

```bash
TELEGRAM_BOT_TOKEN=<bot token>
TELEGRAM_USER_ID=<Akshat's numeric Telegram user ID>
```

Keep these safety settings unchanged for the first launch:

```bash
AMAURA_STRICT_EVIDENCE=1
AMAURA_STRICT_REVIEW=1
AMAURA_STRICT_GIT=1
AMAURA_ENABLE_EXPERIMENTAL_LANGGRAPH=0
AMAURA_ENABLE_GMAIL=0
AMAURA_ENABLE_PUBLICATION=0
```

Pull or verify the models:

```bash
ollama list
ollama pull qwen2.5-coder:3b
```

Use the exact tag shown by `ollama list` in `.env.amaura`.

## 4. Production readiness gate

Run:

```bash
.venv/bin/amaura doctor
```

Launch is allowed only when the report contains:

```json
{
  "production_ready": true
}
```

The gate checks source contracts, repository security, SQLite integrity, backup restoration, Docker health, Ollama reachability, both model installations, model quality evaluation, key separation, strict review/evidence/Git modes, conditional founder Telegram binding, and provider configuration.

Static source-only certification is:

```bash
.venv/bin/amaura doctor --static
```

## 5. First controlled run

Start with one supervisor tick:

```bash
.venv/bin/amaura worker --once
```

Inspect state:

```bash
.venv/bin/amaura status
```

Drain a bounded amount of ready work:

```bash
.venv/bin/amaura worker --drain --max-ticks 25
```

After a successful shadow run, start the continuous supervisor:

```bash
./Launch_Amaura.command
```

This launches the API/HUD and the supervisor as one local stack. Open `http://127.0.0.1:8000`; server logs are stored in `.amaura-data/logs/server.log`. Stop both processes with `Ctrl+C`.

## 6. Create a governed company programme

Example:

```bash
.venv/bin/amaura create-program \
  --workflow client_acquisition \
  --title "India website lead pipeline" \
  --objective "Find and qualify recent Indian businesses that need a website" \
  --success-metric "Ten evidence-backed qualified opportunities" \
  --inputs-json '{"country":"India","payment_currency":"INR","maximum_lead_age_days":7}'
```

Available workflow keys are defined in `jarvis/amaura/workflows.py`.

## 7. Safe engineering delivery

Repository-writing tasks now use this sequence:

1. Confirm a clean named base branch.
2. Record the exact base commit.
3. Create an isolated Git worktree and task branch.
4. Commit all task changes with an immutable diff.
5. Attach content-addressed evidence.
6. Require independent criterion-level review.
7. Bind founder approval to the exact reviewed Git snapshot.
8. Acquire an exclusive repository merge lock.
9. Reject branch drift, target drift, dirty workspaces, or changed reviewed commits.
10. Merge and run the allowlisted post-merge validation command.
11. Roll back automatically when validation or durable completion fails.
12. Clean the task worktree after successful durable completion.

For a repository whose test command differs, set task metadata `post_merge_validation` or update:

```bash
AMAURA_POST_MERGE_COMMAND=python -m pytest -q
```

Only allowlisted validation command families are accepted.

## 8. Ambiguous external delivery

Email is never blindly replayed after a timeout or worker crash. An uncertain send enters:

```text
reconciliation_required
```

List uncertain operations:

```bash
.venv/bin/amaura reconcile list
```

After checking the provider manually, resolve one event:

```bash
.venv/bin/amaura reconcile resolve <event-id> \
  --resolution completed \
  --receipt-json /path/to/provider-receipt.json \
  --reason "Verified in Gmail Sent folder"
```

Other resolutions are `failed` and `requeue`. Do not requeue email unless non-delivery is confirmed.

A `completed` resolution is accepted only when the signed receipt matches the exact approved recipient, subject, body, operation, and idempotency key. A mismatched or forged receipt leaves the event quarantined.

## 9. Backups and verification

Create a timestamped consistent backup:

```bash
.venv/bin/amaura backup
```

Create one at a chosen path:

```bash
.venv/bin/amaura backup /Volumes/Backup/Amaura/amaura.db
```

Run the complete source regression and static gate:

```bash
./scripts/verify_amaura.sh
```

## 10. Recommended first-week operating policy

Keep Amaura in **shadow mode**:

- External email disabled
- Public publishing disabled
- Founder approval required for client commitments and repository merges
- One programme at a time
- Daily backup
- Review every blocked task and every reconciliation event
- Do not enable experimental LangGraph orchestration

Enable one external provider only after its delivery, receipt verification, timeout, and reconciliation paths have been tested with a private test account.

## 11. What “ready” means

The repository is a launch candidate only when:

- The full automated test suite passes locally.
- `amaura doctor` reports `production_ready: true` on the actual Mac.
- A real worker task and a real independent review complete.
- A test repository change survives merge validation and rollback testing.
- Backup restoration succeeds.
- Telegram control is bound to the founder when the Telegram bot is enabled.
- External providers remain disabled or are individually certified.

No source archive can truthfully guarantee perfect autonomous operation. This gate converts readiness into explicit, measurable checks rather than a marketing score.
