"""Keep regression tests isolated from an operator's production .env.amaura."""

from __future__ import annotations

import os

# The installer intentionally creates .env.amaura before operators may rerun
# tests.  Unit tests must use their explicit patches/fixtures rather than
# inheriting live secrets, strict-mode switches, provider credentials, or paths.
os.environ["AMAURA_SKIP_ENV_FILE"] = "1"
