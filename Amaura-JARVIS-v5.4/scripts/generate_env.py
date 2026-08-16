#!/usr/bin/env python3
"""Generate a secure Amaura environment file from the packaged template.

Paths are explicit or repository-relative; no developer-machine paths are
embedded. Existing values may be imported from a legacy env file, while
placeholder secrets are generated with cryptographically secure randomness.
"""

from __future__ import annotations

import argparse
import os
import secrets
import stat
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET_PLACEHOLDER = "replace-with-independent-random-value"


def generate_key() -> str:
    return secrets.token_urlsafe(48)


def load_env(filepath: Path | None) -> dict[str, str]:
    env_vars: dict[str, str] = {}
    if filepath is None or not filepath.is_file():
        return env_vars
    for raw_line in filepath.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env_vars[key.strip()] = value.strip()
    return env_vars


def build_env(template: Path, inherited: dict[str, str]) -> list[str]:
    lines: list[str] = []
    for raw_line in template.read_text(encoding="utf-8").splitlines(keepends=True):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            lines.append(raw_line)
            continue
        key, example = (part.strip() for part in stripped.split("=", 1))
        if inherited.get(key):
            value = inherited[key]
        elif example == SECRET_PLACEHOLDER:
            value = generate_key()
        else:
            value = example
        lines.append(f"{key}={value}\n")
    return lines


def atomic_private_write(path: Path, lines: list[str], *, force: bool) -> None:
    path = path.expanduser().resolve()
    if path.exists() and not force:
        raise FileExistsError(f"Refusing to overwrite existing environment file: {path}; pass --force explicitly")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.writelines(lines)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, default=ROOT / ".env.amaura.example")
    parser.add_argument(
        "--import-env", type=Path, default=None, help="Optional legacy env file whose values take precedence"
    )
    parser.add_argument("--output", type=Path, default=ROOT / ".env.amaura")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    template = args.template.expanduser().resolve()
    if not template.is_file():
        raise FileNotFoundError(f"Environment template does not exist: {template}")
    inherited = load_env(args.import_env.expanduser().resolve() if args.import_env else None)
    atomic_private_write(args.output, build_env(template, inherited), force=args.force)
    print(f"Created {args.output.expanduser().resolve()} with owner-only permissions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
