# Launch Amaura Company OS v3.6.0

1. Copy `.env.amaura.example` to `.env.amaura` and replace every placeholder with an independently generated secret.
2. Install two distinct local models, or configure a separate cloud reviewer key/model.
3. Build `amaura-sandbox:3.6.0`, record its immutable `sha256:` image ID in `AMAURA_SANDBOX_IMAGE_DIGEST`, and run the doctor.
4. Create a private 20+ case evaluation pack outside the repository and sign it with `scripts/sign_evaluation_pack.py`.
5. Put `AMAURA_AUDIT_CHECKPOINT_PATH` and `AMAURA_BACKUP_DIR` on a separate encrypted or cloud-synced volume.
6. Keep Gmail, iMessage, CRM/n8n, publication, deployment, and spending disabled during shadow validation.
7. Run the full isolated suite, static gate, both stress scripts, and clean release builder.
8. Enable providers one at a time and verify token refresh, signed receipt contracts, idempotency, timeout ambiguity, and reconciliation.
9. Run a supervised soak on the target Mac before enabling continuous autopilot.

`production_ready` is an environment verdict, not a source-code label. A source release cannot certify credentials, macOS permissions, network providers, Docker, installed models, or long-duration host behaviour on another machine.
