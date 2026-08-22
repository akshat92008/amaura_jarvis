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

    # Reconstruct the current mission from durable CompanyStore metadata before
    # every founder turn. In-memory bindings are caches only.
    from jarvis.durable_session import install_durable_session_guard

    install_durable_session_guard()

    # Literal Company OS ids are database primary keys, not natural-language
    # hints. Keep this guard outermost so explicit goal_/task_/proj_/mile_
    # status queries can never fall through to fuzzy/model reference handling.
    from jarvis.exact_reference import install_exact_reference_guard

    install_exact_reference_guard()

    from jarvis.cli import main as legacy_main

    return legacy_main()


if __name__ == "__main__":
    main()
