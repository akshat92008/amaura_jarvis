"""Process entry point for the canonical Amaura v7 company runtime."""

from __future__ import annotations

import argparse
import json
import signal
import sys
from typing import NoReturn

from jarvis.amaura.autopilot import AutonomousCompanyRuntime
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.runtime import load_amaura_env


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the governed Amaura company runtime")
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--max-work-units", type=int, default=1)
    parser.add_argument("--max-new-programmes", type=int, default=None)
    parser.add_argument("--max-signals", type=int, default=3)
    parser.add_argument("--max-dynamic-goals", type=int, default=3)
    parser.add_argument("--env-file", default=None)
    return parser


def _shutdown(signum: int, _frame) -> NoReturn:
    raise SystemExit(128 + int(signum))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # Service startup uses the same strict parser as the operator CLI and never
    # executes shell text from the env file. POSIX deployments require private
    # permissions because this file contains independent authority secrets.
    load_amaura_env(args.env_file, require_private_permissions=True)

    # Heavy execution is intentionally conservative on the target small-Mac
    # deployment. The scheduler can manage many missions, but only one heavy
    # execution slot is enabled by default and this daemon caps explicit values
    # at two until resource-aware worker pooling is separately qualified.
    max_work_units = max(1, min(int(args.max_work_units), 2))
    poll_seconds = max(5.0, min(float(args.poll_seconds), 3600.0))

    try:
        with AmauraControlPlane() as control:
            runtime = AutonomousCompanyRuntime(control)
            print(
                json.dumps(
                    {
                        "event": "amaura_company_runtime_started",
                        "poll_seconds": poll_seconds,
                        "max_work_units": max_work_units,
                        "max_signals": max(1, min(int(args.max_signals), 20)),
                        "max_dynamic_goals": max(1, min(int(args.max_dynamic_goals), 20)),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            runtime.run_forever(
                poll_seconds=poll_seconds,
                max_work_units=max_work_units,
                max_new_programmes=args.max_new_programmes,
                max_signals=max(1, min(int(args.max_signals), 20)),
                max_dynamic_goals=max(1, min(int(args.max_dynamic_goals), 20)),
            )
    except SystemExit as exc:
        code = int(exc.code or 0)
        print(json.dumps({"event": "amaura_company_runtime_stopped", "code": code}, sort_keys=True), flush=True)
        return code
    except Exception as exc:
        # Integrity failures intentionally reach this boundary rather than being
        # swallowed by the service loop. launchd may restart the process, but the
        # same fail-closed check will block again until the underlying state is
        # repaired by the founder/operator.
        print(
            json.dumps(
                {
                    "event": "amaura_company_runtime_failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:2000],
                },
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
