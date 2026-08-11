"""Keep regression tests isolated from an operator's production .env.amaura."""

from __future__ import annotations

import os

# The installer intentionally creates .env.amaura before operators may rerun
# tests.  Unit tests must use their explicit patches/fixtures rather than
# inheriting live secrets, strict-mode switches, provider credentials, or paths.
os.environ["AMAURA_SKIP_ENV_FILE"] = "1"

# Unit fixtures may run tiny verifier commands on the test host. Production defaults remain fail-closed/isolation-required.
os.environ["AMAURA_VERIFIER_MODE"] = "host"
os.environ["AMAURA_ALLOW_HOST_VERIFICATION"] = "1"
os.environ["AMAURA_ANTIGRAVITY_ALLOW_GLOBAL_EXECUTABLE_CUSTOMIZATIONS"] = "1"
os.environ["AMAURA_RAM_PRESSURE_LIMIT_MB"] = "100000"
os.environ["AMAURA_IGNORE_RAM_PRESSURE"] = "1"
