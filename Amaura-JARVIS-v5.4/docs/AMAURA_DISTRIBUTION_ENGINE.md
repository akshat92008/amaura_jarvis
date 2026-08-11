# Amaura Distribution Control Plane v2.2.0

Amaura v2.2 converts approved content assets into immutable, scheduled publication packages. It does not store social-media passwords or automate consumer subscriptions. Public actions use an official provider API or a founder-controlled self-hosted bridge such as n8n.

## Safety model

1. A content campaign must pass publication readiness.
2. Every selected asset must be approved and SHA-256 bound.
3. JARVIS stages the exact title, body, platform, schedule, account reference and asset set.
4. The founder approves the immutable package.
5. Autopilot enqueues the package only when approval is complete and its schedule is due.
6. The provider must echo the idempotency key and payload digest.
7. A signed provider receipt confirms the exact external action.
8. Timeouts and ambiguous outcomes are quarantined for founder reconciliation; they are never blindly replayed.
9. Performance windows generate evidence-backed lessons for the next controlled experiment.

## Commands

```bash
amaura distribution list

amaura distribution stage \
  --campaign-id build-log-001 \
  --platform youtube \
  --title "Building Amaura Company OS" \
  --body "Verified build log and limitations." \
  --asset-ids-json '["asset_..."]' \
  --visibility public \
  --scheduled-at '2026-08-06T18:00:00+05:30'

amaura distribution decide approval_... \
  --decision approved \
  --reason "Claims, licences, assets and timing verified."

# Manual enqueue, or let autopilot enqueue the approved due package.
amaura distribution dispatch pub_...
amaura autopilot --once --max-work-units 4 --max-new-programmes 2

amaura distribution metrics pub_... \
  --window 24h \
  --metrics-json '{"impressions":1000,"clicks":40,"views":300,"watch_time_seconds":18000}'

amaura distribution lessons pub_...
```

## Provider bridge contract

Set these only after an official provider integration or a secure self-hosted bridge exists:

```bash
AMAURA_ENABLE_PUBLICATION=1
AMAURA_ENABLE_PUBLIC_PUBLISH=1
AMAURA_PUBLIC_PUBLISH_ENDPOINT=https://your-controlled-endpoint.example/publish
AMAURA_PUBLIC_PUBLISH_ACCESS_TOKEN=...
```

The endpoint must return JSON containing:

```json
{
  "id": "platform-post-id",
  "provider": "youtube",
  "visibility": "published",
  "idempotency_key": "publication:<sha256>",
  "payload_sha256": "<exact request payload digest>"
}
```

The endpoint must implement provider-side idempotency. An HTTP success without the matching identifiers is rejected.
