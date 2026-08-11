# Amaura Company OS v3.5.3 — Network Security Remediation

This release closes the v3.5.2 bind/authentication mismatch and removes the
secondary unauthenticated web application.

## Security changes

- The CLI now passes the configured `JARVIS_HOST` to Uvicorn exactly.
- Non-loopback binds fail closed unless `JARVIS_API_KEY` is at least 24 characters.
- Runtime middleware derives remote exposure from the effective bind and concrete socket addresses.
- General API routes require the configured local key when `JARVIS_REQUIRE_LOCAL_AUTH=1`.
- WebSocket chat always requires the API key and supports a browser-safe subprotocol transport.
- `jarvis.web` is now a compatibility alias to the governed `jarvis.server` application.
- macOS `launchctl` and `osascript` calls have bounded timeouts.
- The release scanner rejects hard-coded wildcard Uvicorn binds.

Production activation still requires the target-machine doctor, real model and
provider evaluation, pinned Docker digest, independent storage, release-owner
signature, and multi-day soak evidence. Source remediation does not fabricate
those external proofs.
