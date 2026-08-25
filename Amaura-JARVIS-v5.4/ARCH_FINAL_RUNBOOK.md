# ARCH Final Production Runbook

This is the authoritative operator path for the current Amaura JARVIS runtime.
Historical launch scripts and older Company OS documents remain for compatibility
and development, but they are not the production deployment sequence.

## Runtime architecture

- **ARCH** is the single persistent founder-facing runtime.
- **OmniRoute** is the production cognition gateway for executive chat, Company OS workers, and independent model review.
- **Antigravity (`agy`)** is the primary governed repository-engineering backend.
- **Nova/Ollama are not production fallbacks.**
- macOS persistence is owned by the single LaunchAgent `com.amaura.arch`.
- consequential actions remain subject to Company OS approval boundaries.

## Fresh install / recovery

From `Amaura-JARVIS-v5.4`:

```bash
./Install_Amaura.command
./Setup_Amaura_OmniRoute.command
./Setup_Amaura_Antigravity.command
./Setup_Amaura_Runtime.command
```

`Setup_Amaura_OmniRoute.command` requires a fresh private OmniRoute credential and
an explicit reviewer model different from every worker route. Do not reuse a
credential that has ever appeared in source-control history.

## Final target-Mac certification

Run:

```bash
.venv/bin/python -m jarvis.amaura.deployment_gate
```

The only successful final verdict is:

```text
READY_FOR_COMPANY_DEPLOYMENT
```

The gate performs authoritative runtime certification, installs/restarts the
canonical ARCH LaunchAgent, black-box tests the deployed service, runs a live
Antigravity repair, runs a live semantic company task with independent review,
audits live CompanyStore health, and completes the two-hour exact-SHA resource
soak.

Do not weaken or skip a failing stage. Fix the reported blocker and rerun.

## Daily use after the gate passes

ARCH is already persistent under `com.amaura.arch`; do not start parallel
`jarvis.server`, `amaura-company`, or other background runtimes.

For the visual founder interface, install the desktop shell once if needed:

```bash
./Install_Amaura_Desktop.command
```

Then launch it with:

```bash
./Launch_Amaura_Desktop.command
```

The desktop app authenticates and attaches to the existing background ARCH
service. Normal operating mode is `execute_until_approval`, with Antigravity as
the coding backend.

## Useful verification commands

```bash
.venv/bin/python -m jarvis.amaura.ready_cli --check-only
.venv/bin/python -m jarvis.amaura.cli status
launchctl print gui/$(id -u)/com.amaura.arch
curl -fsS http://127.0.0.1:8000/api/health
```

The health endpoint is intentionally subject to ARCH authentication semantics in
some runtime modes; the deployment gate is the authoritative proof.
