# Amaura Company OS v3.4.0 — Independent Build Verification

## Verdict

Version 3.4.0 closes the reproduced P0 trust-boundary defects from the v3.1.0 audit. It is source-certified for a founder-supervised internal pilot. Live production readiness intentionally remains false until the target Mac has its real keys, models, Docker sandbox, provider credentials, and live soak certification.

## Remediated defects

- Cross-process audit appends are serialized with database write transactions.
- Audit entries are HMAC-authenticated and can be checked against an external signed head checkpoint.
- Offline SHA-256 history recomputation is detected.
- Evidence references bind bytes to signed provenance manifests: source, capture time, media type, worker, task, and retrieval metadata.
- Outbound HTTP(S) connects to the validated public IP and preserves TLS hostname verification, preventing DNS rebinding.
- Model text is HTML-escaped before Markdown rendering; the HUD has a restrictive Content Security Policy.
- All Amaura API reads require the operator key; founder mutations require the separate approval key.
- Ventures sprint admission is database-atomic.
- The wheel contains the HUD and all employee prompt profiles.
- SQLite connections have deterministic runtime cleanup and the server has a lifespan shutdown path.

## Verification performed

- 207 automated tests passed with Python warnings treated as errors.
  - Group A: 129 passed.
  - Group B: 78 passed.
- 28 targeted trust, production, and Ventures tests passed.
- Complete Python compilation passed.
- Repository secret scan: zero findings.
- Static source certification passed.
- Backup and restore probe passed.
- Installed-wheel HUD smoke test passed.
- Wheel contains `index.html`, `app.js`, `styles.css`, and 59 prompt profiles.

### Acquisition stress

- 32 concurrent workers.
- 1,000 lead records.
- 100 adversarial inputs detected.
- 60 provider-confirmed sends.
- 20 excess sends blocked.
- 500 duplicate attempts produced one record.
- SQLite integrity and foreign keys passed.

### Trust-foundation stress

- 32 independent audit processes.
- 640 signed audit entries with one valid chain and checkpoint.
- Offline history rewrite detected.
- 32 simultaneous Ventures contenders: one started, 31 blocked.
- Same bytes from different sources produced distinct provenance references.
- Provenance-manifest tampering was rejected.

## Operating boundary

The release manifest correctly reports:

```json
{
  "source_certified": true,
  "production_ready": false
}
```

Before enabling unattended external actions on the MacBook, `amaura doctor` must pass with separate operator, founder, reviewer, evidence, audit, and provider keys; a working Docker sandbox; distinct worker and reviewer models; strict evidence/review/Git modes; post-merge validation; official provider credentials; and live Mac sleep/reboot/network-loss testing.
