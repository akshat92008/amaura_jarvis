#!/usr/bin/env python3
"""Assemble a macOS Amaura desktop application without npm dependencies.

The builder consumes a caller-supplied, checksum-pinned official Electron zip
and the self-contained Amaura backend sidecar.  It never resolves floating npm
packages.  Signing, notarisation, and DMG creation are optional explicit steps.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import plistlib
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop-app"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_input(path: Path, expected: str) -> None:
    normalized = expected.strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError("--electron-sha256 must be a 64-character lowercase SHA-256 digest")
    actual = sha256(path)
    if actual != normalized:
        raise RuntimeError(f"Electron archive digest mismatch: expected {normalized}, got {actual}")


def copy_application_source(resources: Path) -> None:
    target = resources / "app"
    target.mkdir(parents=True, exist_ok=True)
    for name in ("main.js", "preload.js", "package.json"):
        shutil.copy2(DESKTOP / name, target / name)
    for name in ("renderer", "assets"):
        shutil.copytree(DESKTOP / name, target / name)


def update_info_plist(app_bundle: Path, version: str) -> None:
    plist_path = app_bundle / "Contents" / "Info.plist"
    with plist_path.open("rb") as handle:
        payload = plistlib.load(handle)
    payload.update(
        {
            "CFBundleDisplayName": "Amaura Company OS",
            "CFBundleIdentifier": "ai.amaura.companyos",
            "CFBundleName": "Amaura Company OS",
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version,
            "LSApplicationCategoryType": "public.app-category.productivity",
            "NSHighResolutionCapable": True,
        }
    )
    with plist_path.open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=True)


def sign_app(app_bundle: Path, identity: str) -> None:
    command = [
        "codesign",
        "--force",
        "--deep",
        "--timestamp",
        "--options",
        "runtime",
        "--entitlements",
        str(DESKTOP / "entitlements.plist"),
        "--sign",
        identity,
        str(app_bundle),
    ]
    subprocess.run(command, check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app_bundle)], check=True)


def create_dmg(app_bundle: Path, target: Path) -> None:
    staging = target.parent / ".dmg-staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    shutil.copytree(app_bundle, staging / app_bundle.name, symlinks=True)
    subprocess.run(
        [
            "hdiutil",
            "create",
            "-volname",
            "Amaura Company OS",
            "-srcfolder",
            str(staging),
            "-ov",
            "-format",
            "UDZO",
            str(target),
        ],
        check=True,
    )
    shutil.rmtree(staging)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--electron-zip", type=Path, required=True)
    parser.add_argument("--electron-sha256", required=True)
    parser.add_argument("--backend", type=Path, default=DESKTOP / "runtime" / "amaura-backend")
    parser.add_argument("--output", type=Path, default=ROOT / "release-desktop")
    parser.add_argument("--version", default="3.6.1")
    parser.add_argument("--sign-identity", default=os.environ.get("AMAURA_CODESIGN_IDENTITY", ""))
    parser.add_argument("--dmg", action="store_true")
    args = parser.parse_args()

    electron_zip = args.electron_zip.expanduser().resolve()
    backend = args.backend.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not electron_zip.is_file():
        raise FileNotFoundError(electron_zip)
    if not backend.is_file():
        raise FileNotFoundError(f"Backend sidecar is missing: {backend}")
    verify_input(electron_zip, args.electron_sha256)

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    app_bundle = output / "Amaura Company OS.app"

    with tempfile.TemporaryDirectory(prefix="amaura-electron-") as tmp:
        extracted = Path(tmp)
        with zipfile.ZipFile(electron_zip) as archive:
            archive.extractall(extracted)
        templates = list(extracted.rglob("Electron.app"))
        if len(templates) != 1:
            raise RuntimeError(f"Expected one Electron.app in archive, found {len(templates)}")
        shutil.copytree(templates[0], app_bundle, symlinks=True)

    resources = app_bundle / "Contents" / "Resources"
    copy_application_source(resources)
    backend_target = resources / "backend" / "amaura-backend"
    backend_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backend, backend_target)
    backend_target.chmod(0o755)
    update_info_plist(app_bundle, args.version)

    if args.sign_identity:
        sign_app(app_bundle, args.sign_identity)
    if args.dmg:
        create_dmg(app_bundle, output / f"Amaura-Company-OS-{args.version}.dmg")

    report = output / "DESKTOP_BUILD.sha256"
    report.write_text(
        f"electron_zip {sha256(electron_zip)}\nbackend {sha256(backend_target)}\n",
        encoding="utf-8",
    )
    print(app_bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
