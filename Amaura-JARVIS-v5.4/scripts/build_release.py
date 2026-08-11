#!/usr/bin/env python3
"""Build deterministic Amaura source and wheel release artifacts.

The builder stages an allowlisted source tree, rejects runtime state and secret
material, creates deterministic archives, installs the wheel in isolation, and
emits external SHA-256 sums, an SPDX 2.3 SBOM, SLSA-shaped provenance, and an
optional detached Minisign signature over the checksum ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import tomllib
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _project_version() -> str:
    payload = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(payload["project"]["version"])


VERSION = _project_version()
QUALIFICATION_REPORTS = (
    "TEST_REPORT.json",
    "QUALIFICATION_REPORT.json",
    "QUALIFICATION_EVIDENCE.json",
    "RELEASE_VERIFICATION.json",
    "EVIDENCE_SHA256SUMS",
)
FIXED_ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)
SOURCE_DATE_EPOCH = "1767225600"

EXCLUDED_DIRS = {
    ".git", ".github-cache", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".tox", ".venv", "__pycache__", "build", "dist", "evidence",
    "node_modules", "release", ".amaura-data", ".jarvis-data", "runtime",
}
EXCLUDED_SUFFIXES = {
    ".db", ".db-shm", ".db-wal", ".sqlite", ".sqlite3", ".pyc", ".pyo",
    ".pem", ".key", ".p12", ".pfx", ".log", ".minisig",
}
EXCLUDED_NAMES = {".env", ".env.amaura", ".DS_Store", "Thumbs.db"}
ALLOWED_ROOTS = {
    ".github", "aimodel", "desktop-app", "docker", "docs", "jarvis", "jarvis_app",
    "scripts", "tests",
}
ALLOWED_ROOT_FILES = {
    ".env.amaura.example", ".gitignore", "AMAURA_HARDENING_CHANGELOG.md",
    "AMAURA_V3_5_COMPLETION_REPORT.md", "AMAURA_V3_5_1_REMEDIATION_REPORT.md", "AMAURA_V3_5_2_SECURITY_RELEASE.md",
    "AMAURA_V3_5_2_QUALIFICATION.md", "AMAURA_V3_5_3_NETWORK_SECURITY.md",
    "AMAURA_V3_6_0_FREE_FIRST_INTEGRATIONS.md", "AMAURA_OSS_CAPABILITIES.md", "AMAURA_LAUNCH.md",
    "Install_Amaura.command", "Install_Amaura_Autopilot.command", "Install_Amaura_Desktop.command",
    "LICENSE", "Launch_Amaura.command", "Launch_Amaura_Desktop.command", "README.md",
    "Setup_Amaura_Runtime.command", "Setup_Amaura_Antigravity.command", "Setup_Amaura_OmniRoute.command",
    "Uninstall_Amaura_Autopilot.command", "jarvis.sh",
    "pyproject.toml", "requirements-dev.lock", "requirements.lock", "requirements.txt",
    "uv.lock",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def forbidden(relative: Path) -> str | None:
    if any(part in EXCLUDED_DIRS for part in relative.parts):
        return "excluded directory"
    if relative.name in EXCLUDED_NAMES or (
        relative.name.startswith(".env.") and relative.name != ".env.amaura.example"
    ):
        return "secret environment file"
    if any(str(relative).endswith(suffix) for suffix in EXCLUDED_SUFFIXES):
        return "runtime/generated file"
    return None


def stage_source(destination: Path, qualification_dir: Path) -> list[str]:
    copied: list[str] = []
    for child in sorted(ROOT.iterdir(), key=lambda item: item.name):
        if child.name in ALLOWED_ROOTS and child.is_dir():
            for source in sorted(child.rglob("*")):
                if not source.is_file():
                    continue
                relative = source.relative_to(ROOT)
                if forbidden(relative):
                    continue
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                copied.append(relative.as_posix())
        elif child.name in ALLOWED_ROOT_FILES and child.is_file():
            target = destination / child.name
            shutil.copy2(child, target)
            copied.append(child.name)
    for name in QUALIFICATION_REPORTS:
        source = qualification_dir / name
        target = destination / name
        shutil.copy2(source, target)
        copied.append(name)
    return copied


def validate_qualification(directory: Path) -> dict[str, Any]:
    directory = directory.expanduser().resolve()
    missing = [name for name in QUALIFICATION_REPORTS if not (directory / name).is_file()]
    if missing:
        raise RuntimeError(f"Qualification evidence is incomplete: {missing}")
    parsed: dict[str, Any] = {}
    for name in QUALIFICATION_REPORTS:
        if name.endswith(".json"):
            parsed[name] = json.loads((directory / name).read_text(encoding="utf-8"))
    versions = {str(payload.get("version", "")) for payload in parsed.values()}
    if versions != {VERSION}:
        raise RuntimeError(f"Qualification version mismatch: expected {VERSION}, found {sorted(versions)}")
    test_report = parsed["TEST_REPORT.json"]
    qualification = parsed["QUALIFICATION_REPORT.json"]
    verification = parsed["RELEASE_VERIFICATION.json"]
    collected = int(test_report.get("collected_tests", -1))
    verified = int(test_report.get("verified_tests", -1))
    if collected <= 0 or verified != collected:
        raise RuntimeError(f"Qualification test count mismatch: collected={collected}, verified={verified}")
    if int(qualification.get("tests", {}).get("verified", -1)) != verified:
        raise RuntimeError("QUALIFICATION_REPORT test total does not match TEST_REPORT")
    if int(verification.get("automated_tests", -1)) != verified:
        raise RuntimeError("RELEASE_VERIFICATION test total does not match TEST_REPORT")
    if not all([
        bool(test_report.get("passed")),
        bool(qualification.get("source_certified")),
        bool(verification.get("source_certified")),
        bool(verification.get("all_tests_passed")),
    ]):
        raise RuntimeError("Qualification evidence does not certify the source")
    git = qualification.get("git", {})
    if not git.get("available") or git.get("dirty") or git.get("commit") in {None, "", "unknown"}:
        raise RuntimeError("Qualification evidence must reference a clean, known Git commit")
    expected_lines = {
        line.split("  ", 1)[1]: line.split("  ", 1)[0]
        for line in (directory / "EVIDENCE_SHA256SUMS").read_text(encoding="utf-8").splitlines()
        if "  " in line
    }
    for name in QUALIFICATION_REPORTS:
        if not name.endswith(".json"):
            continue
        if expected_lines.get(name) != sha256(directory / name):
            raise RuntimeError(f"Qualification evidence digest mismatch: {name}")
    return {
        "directory": str(directory),
        "version": VERSION,
        "tests": verified,
        "git_commit": str(git["commit"]),
        "source_certified": True,
    }


def validate_tree(root: Path) -> None:
    violations: list[str] = []
    for path in root.rglob("*"):
        if path.is_file():
            reason = forbidden(path.relative_to(root))
            if reason:
                violations.append(f"{path.relative_to(root)}: {reason}")
    if violations:
        raise RuntimeError("Forbidden release files:\n" + "\n".join(violations))


def deterministic_zip(source: Path, target: Path, prefix: str) -> None:
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            relative = Path(prefix) / path.relative_to(source)
            info = zipfile.ZipInfo(relative.as_posix(), FIXED_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if os.access(path, os.X_OK) else 0o644) << 16
            info.create_system = 3
            archive.writestr(info, path.read_bytes())


def validate_archive(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        violations: list[str] = []
        for name in archive.namelist():
            parts = Path(name).parts[1:]
            if not parts:
                continue
            reason = forbidden(Path(*parts))
            if reason:
                violations.append(f"{name}: {reason}")
        if violations:
            raise RuntimeError("Forbidden archive members:\n" + "\n".join(violations))


def canonicalize_wheel(path: Path) -> None:
    """Rewrite a wheel with deterministic entry order, timestamps, and modes."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(
        temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as target:
        for name in sorted(source.namelist()):
            original = source.getinfo(name)
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = (original.external_attr >> 16) & 0o777
            info.external_attr = (mode or 0o644) << 16
            info.create_system = 3
            target.writestr(info, source.read(name))
    os.replace(temporary, path)


def build_wheel(stage: Path, output: Path) -> Path:
    wheel_dir = output / "wheel"
    wheel_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation",
        "--wheel-dir", str(wheel_dir),
    ]
    build_env = {**os.environ, "SOURCE_DATE_EPOCH": SOURCE_DATE_EPOCH, "PYTHONHASHSEED": "0"}
    subprocess.run(command, cwd=stage, env=build_env, check=True, timeout=180)
    wheels = sorted(wheel_dir.glob("jarvis-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"Expected one wheel, found {len(wheels)}")
    final = output / wheels[0].name
    shutil.copy2(wheels[0], final)
    canonicalize_wheel(final)
    shutil.rmtree(wheel_dir)
    return final


def smoke_wheel(wheel: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="amaura-wheel-smoke-") as tmp:
        target = Path(tmp) / "site"
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(target), str(wheel)],
            check=True, timeout=120, capture_output=True, text=True,
        )
        code = f"""
import json
from pathlib import Path
import jarvis
from jarvis.server import STATIC_DIR
from jarvis.amaura.prompts import load_prompt_catalogue
assert jarvis.__version__ == {VERSION!r}
for name in ('index.html', 'app.js', 'styles.css'):
    assert (Path(STATIC_DIR) / name).is_file(), name
profiles = load_prompt_catalogue()
assert len(profiles) >= 57
print(json.dumps({{'version': jarvis.__version__, 'profiles': len(profiles)}}))
"""
        env = {**os.environ, "PYTHONPATH": str(target), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
        result = subprocess.run(
            [sys.executable, "-c", code], cwd="/tmp", env=env, check=True,
            timeout=60, capture_output=True, text=True,
        )
        return json.loads(result.stdout.strip().splitlines()[-1])



def load_locked_components(lockfile: Path) -> list[dict[str, Any]]:
    """Return the exact Python component inventory from uv.lock."""
    payload = tomllib.loads(lockfile.read_text(encoding="utf-8"))
    components: list[dict[str, Any]] = []
    for package in payload.get("package", []):
        name = str(package.get("name", "")).strip()
        version = str(package.get("version", "")).strip()
        if not name or not version or name == "jarvis":
            continue
        source = package.get("source", {}) if isinstance(package.get("source"), dict) else {}
        registry = str(source.get("registry", "")).strip()
        hashes: list[str] = []
        sdist = package.get("sdist") if isinstance(package.get("sdist"), dict) else {}
        if isinstance(sdist.get("hash"), str) and sdist["hash"].startswith("sha256:"):
            hashes.append(sdist["hash"].split(":", 1)[1])
        for wheel in package.get("wheels", []) if isinstance(package.get("wheels"), list) else []:
            if isinstance(wheel, dict) and isinstance(wheel.get("hash"), str) and wheel["hash"].startswith("sha256:"):
                hashes.append(wheel["hash"].split(":", 1)[1])
        components.append({
            "name": name,
            "version": version,
            "registry": registry,
            "sha256": sorted(set(hashes)),
        })
    return sorted(components, key=lambda item: (item["name"], item["version"]))

def _spdx_id(relative: str) -> str:
    suffix = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:20]
    return f"SPDXRef-File-{suffix}"



def write_spdx_sbom(
    output: Path,
    *,
    manifest: dict[str, str],
    dependencies: list[str],
    locked_components: list[dict[str, Any]],
    artifacts: list[Path],
) -> Path:
    """Write an SPDX document containing source files and exact locked components."""
    namespace_seed = "|".join(f"{path.name}:{sha256(path)}" for path in artifacts)
    namespace = f"https://amaura.ai/spdx/{uuid.uuid5(uuid.NAMESPACE_URL, namespace_seed)}"
    files = [
        {
            "SPDXID": _spdx_id(name),
            "fileName": f"./{name}",
            "checksums": [{"algorithm": "SHA256", "checksumValue": digest}],
            "licenseConcluded": "NOASSERTION",
            "copyrightText": "NOASSERTION",
        }
        for name, digest in sorted(manifest.items())
    ]
    root_package = {
        "name": "jarvis",
        "SPDXID": "SPDXRef-Package-Amaura",
        "versionInfo": VERSION,
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": True,
        "licenseConcluded": "MIT",
        "licenseDeclared": "MIT",
        "copyrightText": "NOASSERTION",
        "externalRefs": [{
            "referenceCategory": "PACKAGE-MANAGER",
            "referenceType": "purl",
            "referenceLocator": f"pkg:pypi/jarvis@{VERSION}",
        }],
        "annotations": [{
            "annotationDate": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "annotationType": "OTHER",
            "annotator": "Tool: Amaura deterministic release builder",
            "comment": "Declared direct runtime dependencies: " + ", ".join(dependencies),
        }],
    }
    component_packages: list[dict[str, Any]] = []
    component_ids: list[str] = []
    for component in locked_components:
        identity = f"{component['name']}@{component['version']}"
        component_id = "SPDXRef-Package-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        component_ids.append(component_id)
        package: dict[str, Any] = {
            "name": component["name"],
            "SPDXID": component_id,
            "versionInfo": component["version"],
            "downloadLocation": component["registry"] or "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "NOASSERTION",
            "copyrightText": "NOASSERTION",
            "externalRefs": [{
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": f"pkg:pypi/{component['name']}@{component['version']}",
            }],
        }
        if component.get("sha256"):
            package["checksums"] = [
                {"algorithm": "SHA256", "checksumValue": digest}
                for digest in component["sha256"]
            ]
        component_packages.append(package)
    relationships: list[dict[str, str]] = [{
        "spdxElementId": "SPDXRef-DOCUMENT",
        "relationshipType": "DESCRIBES",
        "relatedSpdxElement": "SPDXRef-Package-Amaura",
    }]
    relationships.extend({
        "spdxElementId": "SPDXRef-Package-Amaura",
        "relationshipType": "CONTAINS",
        "relatedSpdxElement": item["SPDXID"],
    } for item in files)
    relationships.extend({
        "spdxElementId": "SPDXRef-Package-Amaura",
        "relationshipType": "DEPENDS_ON",
        "relatedSpdxElement": component_id,
    } for component_id in component_ids)
    payload: dict[str, Any] = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"Amaura-Company-OS-{VERSION}",
        "documentNamespace": namespace,
        "creationInfo": {
            "created": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "creators": ["Tool: Amaura deterministic release builder"],
        },
        "packages": [root_package, *component_packages],
        "files": files,
        "relationships": relationships,
    }
    target = output / f"Amaura-Company-OS-v{VERSION}.spdx.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target



def _git_metadata() -> dict[str, Any]:
    if not (ROOT / ".git").exists():
        return {"available": False, "commit": "unknown", "dirty": None}
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True, timeout=10
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, check=True, capture_output=True, text=True, timeout=10
        ).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return {"available": False, "commit": "unknown", "dirty": None}
    return {"available": True, "commit": commit, "dirty": bool(status.strip())}


def write_provenance(output: Path, artifacts: list[Path], *, source_files: int) -> Path:
    now = datetime.now(UTC).isoformat()
    payload = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [
            {"name": path.name, "digest": {"sha256": sha256(path)}} for path in artifacts
        ],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": "https://amaura.ai/build-types/deterministic-python-release/v1",
                "externalParameters": {
                    "version": VERSION,
                    "sourceFiles": source_files,
                    "sourceDateEpoch": SOURCE_DATE_EPOCH,
                },
                "internalParameters": {
                    "python": sys.version,
                    "platform": platform.platform(),
                },
                "resolvedDependencies": [
                    {
                        "uri": "file:uv.lock",
                        "digest": {"sha256": sha256(ROOT / "uv.lock")},
                    },
                    {
                        "uri": "file:desktop-app/package-lock.json",
                        "digest": {"sha256": sha256(ROOT / "desktop-app" / "package-lock.json")},
                    },
                ],
            },
            "runDetails": {
                "builder": {"id": "https://amaura.ai/builders/release-builder/v1"},
                "metadata": {
                    "invocationId": str(uuid.uuid4()),
                    "startedOn": now,
                    "finishedOn": now,
                    "git": _git_metadata(),
                },
            },
        },
    }
    target = output / "PROVENANCE.intoto.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def write_checksums(output: Path, artifacts: list[Path]) -> Path:
    target = output / "SHA256SUMS"
    target.write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in sorted(artifacts, key=lambda item: item.name)),
        encoding="utf-8",
    )
    return target


def sign_checksums(checksums: Path, secret_key: Path | None, *, require_signature: bool) -> dict[str, Any]:
    if secret_key is None:
        if require_signature:
            raise RuntimeError("A detached release signature is required, but --minisign-secret-key was not provided")
        return {"status": "not_requested", "signature": None}
    key = secret_key.expanduser().resolve()
    if not key.is_file():
        raise FileNotFoundError(f"Minisign secret key does not exist: {key}")
    executable = shutil.which("minisign")
    if not executable:
        raise RuntimeError("minisign executable is required when a signing key is provided")
    signature = checksums.with_suffix(checksums.suffix + ".minisig")
    subprocess.run(
        [executable, "-Sm", str(checksums), "-s", str(key), "-x", str(signature)],
        check=True,
        timeout=60,
    )
    return {"status": "signed", "signature": signature.name, "sha256": sha256(signature)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "release")
    parser.add_argument("--qualification-dir", type=Path, required=True)
    parser.add_argument(
        "--minisign-secret-key",
        type=Path,
        default=Path(os.environ["AMAURA_MINISIGN_SECRET_KEY"]) if os.environ.get("AMAURA_MINISIGN_SECRET_KEY") else None,
    )
    parser.add_argument("--require-signature", action="store_true")
    args = parser.parse_args()
    qualification_dir = args.qualification_dir.expanduser().resolve()
    qualification_summary = validate_qualification(qualification_dir)
    output = args.output.expanduser().resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    with tempfile.TemporaryDirectory(prefix="amaura-release-stage-") as tmp:
        stage = Path(tmp) / f"Amaura-Company-OS-v{VERSION}"
        stage.mkdir()
        copied = stage_source(stage, qualification_dir)
        validate_tree(stage)
        project = tomllib.loads((stage / "pyproject.toml").read_text(encoding="utf-8"))
        dependencies = list(project.get("project", {}).get("dependencies", []))
        locked_components = load_locked_components(stage / "uv.lock")

        manifest = {
            path.relative_to(stage).as_posix(): sha256(path)
            for path in sorted(stage.rglob("*")) if path.is_file()
        }
        (stage / "RELEASE_MANIFEST.sha256.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        source_zip = output / f"Amaura-Company-OS-v{VERSION}-Hardened.zip"
        deterministic_zip(stage, source_zip, stage.name)
        validate_archive(source_zip)
        wheel = build_wheel(stage, output)
        smoke = smoke_wheel(wheel)

    qualification_artifacts: list[Path] = []
    for name in QUALIFICATION_REPORTS:
        target = output / name
        shutil.copy2(qualification_dir / name, target)
        qualification_artifacts.append(target)

    sbom = write_spdx_sbom(
        output,
        manifest=manifest,
        dependencies=dependencies,
        locked_components=locked_components,
        artifacts=[source_zip, wheel],
    )
    provenance = write_provenance(output, [source_zip, wheel, sbom], source_files=len(copied))
    checksums = write_checksums(output, [source_zip, wheel, sbom, provenance, *qualification_artifacts])
    signing = sign_checksums(checksums, args.minisign_secret_key, require_signature=args.require_signature)

    report = {
        "version": VERSION,
        "built_at": datetime.now(UTC).isoformat(),
        "source_files": len(copied),
        "source_zip": {"name": source_zip.name, "sha256": sha256(source_zip), "bytes": source_zip.stat().st_size},
        "wheel": {"name": wheel.name, "sha256": sha256(wheel), "bytes": wheel.stat().st_size},
        "sbom": {"name": sbom.name, "sha256": sha256(sbom), "locked_components": len(locked_components)},
        "provenance": {"name": provenance.name, "sha256": sha256(provenance)},
        "checksums": {"name": checksums.name, "sha256": sha256(checksums)},
        "signature": signing,
        "wheel_smoke": smoke,
        "qualification": qualification_summary,
        "bundle_name": f"Amaura-Company-OS-v{VERSION}-Source-Qualified-Release-Bundle.zip",
        "forbidden_runtime_state": "absent",
        "production_ready": False,
        "status": "built",
    }
    build_report = output / "BUILD_REPORT.json"
    build_report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    with tempfile.TemporaryDirectory(prefix="amaura-release-bundle-") as tmp:
        bundle_stage = Path(tmp) / f"Amaura-Company-OS-v{VERSION}-Source-Qualified-Release-Bundle"
        bundle_stage.mkdir()
        bundle_members = [
            source_zip, wheel, sbom, provenance, checksums, build_report,
            *qualification_artifacts,
        ]
        signature_name = signing.get("signature")
        if signature_name:
            bundle_members.append(output / str(signature_name))
        for artifact in bundle_members:
            shutil.copy2(artifact, bundle_stage / artifact.name)
        (bundle_stage / "START_HERE.md").write_text(
            f"# Amaura Company OS v{VERSION}\n\n"
            "Use the canonical wheel filename in this bundle. The included source was qualified "
            "from the clean Git commit recorded in QUALIFICATION_REPORT.json. Production readiness "
            "remains closed until target credentials, provider health checks, deployment signing, "
            "and live-environment gates pass.\n",
            encoding="utf-8",
        )
        bundle = output / report["bundle_name"]
        deterministic_zip(bundle_stage, bundle, bundle_stage.name)
        validate_archive(bundle)
    bundle_ledger = output / "BUNDLE_SHA256SUMS"
    bundle_ledger.write_text(f"{sha256(bundle)}  {bundle.name}\n", encoding="utf-8")
    report_for_console = {
        **report,
        "bundle": {"name": bundle.name, "sha256": sha256(bundle), "bytes": bundle.stat().st_size},
        "bundle_checksums": {"name": bundle_ledger.name, "sha256": sha256(bundle_ledger)},
    }
    print(json.dumps(report_for_console, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
