"""
test_jarvis_backup_utility.py
-----------------------------
Verification suite for BackupManager.

Covers:
  1. compute_sha256 golden-vector test  (b'ironman')
  2. create_manifest over two in-memory temp files
  3. verify_manifest — positive (all hashes match)
  4. verify_manifest — negative (tampered content)
  5. verify_manifest — negative (missing file entry)

Exits with a non-zero status code on any assertion failure so that CI
pipelines catch regressions automatically.
"""

from __future__ import annotations

import os
import tempfile

from jarvis_backup_utility import BackupManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_temp(content: bytes) -> str:
    """Write *content* to a named temporary file and return its path."""
    fd, path = tempfile.mkstemp()
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
    except Exception:
        os.close(fd)
        raise
    return path


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def test_compute_sha256_golden_vector() -> None:
    """SHA-256 of b'ironman' must match the known digest."""
    bm = BackupManager()
    expected = "4f278cdddf52263fe21c64c94932f2b2ec316acecd39a7adcc01eb2e6592a678"
    result = bm.compute_sha256(b"ironman")
    assert result == expected, (
        f"compute_sha256 golden-vector FAILED\n"
        f"  expected : {expected}\n"
        f"  got      : {result}"
    )


def test_compute_sha256_empty() -> None:
    """SHA-256 of empty bytes is a well-known constant."""
    bm = BackupManager()
    expected = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert bm.compute_sha256(b"") == expected


def test_manifest_generation_and_verification() -> None:
    """create_manifest + verify_manifest round-trip over two sample files."""
    bm = BackupManager()

    # --- sample payloads ---------------------------------------------------
    payload_a = b"Amaura JARVIS backup payload alpha"
    payload_b = b"Amaura JARVIS backup payload beta"

    path_a = _write_temp(payload_a)
    path_b = _write_temp(payload_b)

    try:
        # --- manifest creation ---------------------------------------------
        manifest = bm.create_manifest([path_a, path_b])

        assert path_a in manifest, "path_a missing from manifest"
        assert path_b in manifest, "path_b missing from manifest"
        assert manifest[path_a] == bm.compute_sha256(payload_a), (
            "Manifest digest for path_a is incorrect"
        )
        assert manifest[path_b] == bm.compute_sha256(payload_b), (
            "Manifest digest for path_b is incorrect"
        )

        # --- positive verification -----------------------------------------
        file_contents: dict[str, bytes] = {
            path_a: payload_a,
            path_b: payload_b,
        }
        assert bm.verify_manifest(manifest, file_contents) is True, (
            "verify_manifest returned False for a valid, unmodified backup set"
        )

        # --- negative verification: tampered content ----------------------
        tampered: dict[str, bytes] = {
            path_a: b"TAMPERED DATA - this should not match",
            path_b: payload_b,
        }
        assert bm.verify_manifest(manifest, tampered) is False, (
            "verify_manifest returned True for tampered content (should be False)"
        )

        # --- negative verification: missing file entry --------------------
        incomplete: dict[str, bytes] = {path_a: payload_a}
        assert bm.verify_manifest(manifest, incomplete) is False, (
            "verify_manifest returned True when a file entry is missing (should be False)"
        )

    finally:
        os.unlink(path_a)
        os.unlink(path_b)


def test_static_method_callable_without_instance() -> None:
    """compute_sha256 is a static method and must be callable on the class."""
    digest = BackupManager.compute_sha256(b"ironman")
    assert len(digest) == 64, "SHA-256 hex digest must be 64 characters"
    assert all(c in "0123456789abcdef" for c in digest), (
        "SHA-256 hex digest must contain only lowercase hex characters"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_compute_sha256_golden_vector()
    test_compute_sha256_empty()
    test_manifest_generation_and_verification()
    test_static_method_callable_without_instance()

    print("BACKUP_UTILITY_VERIFIED")
