"""Production entrypoint that installs JARVIS reliability guards before boot."""

from __future__ import annotations

from typing import Any


def main() -> Any:
    from jarvis.amaura.runtime_guards import install_runtime_guards
    from jarvis.reliable_cli import install_reliability_boundary

    install_runtime_guards()
    install_reliability_boundary()

    # Import only after the reliable boundary is installed so this guard wraps
    # the hardened founder-facing executor rather than the legacy agent method.
    from jarvis.session_control import install_session_control_guard

    install_session_control_guard()

    from jarvis.cli import main as legacy_main

    return legacy_main()


if __name__ == "__main__":
    main()