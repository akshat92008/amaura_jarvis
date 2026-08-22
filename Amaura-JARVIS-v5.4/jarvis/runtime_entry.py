"""Production entrypoint that installs JARVIS reliability guards before boot."""

from __future__ import annotations

from typing import Any


def main() -> Any:
    from jarvis.amaura.runtime_guards import install_runtime_guards
    from jarvis.reliable_cli import main as reliable_main

    install_runtime_guards()
    return reliable_main()


if __name__ == "__main__":
    main()
