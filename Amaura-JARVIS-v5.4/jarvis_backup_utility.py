"""
jarvis_backup_utility.py
------------------------
Real-world backup utility providing cryptographic integrity verification
for file collections via SHA-256 manifests.

Author : J.A.R.V.I.S. — Amaura JARVIS v5.4
"""

from __future__ import annotations

import hashlib


class BackupManager:
    """Manages cryptographic integrity verification for backup sets.

    All operations are stateless and side-effect-free; the class is
    intentionally designed to be instantiated once and reused across
    many backup cycles without any internal mutable state.
    """

    # ------------------------------------------------------------------
    # Core cryptographic primitive
    # ------------------------------------------------------------------

    @staticmethod
    def compute_sha256(data: bytes) -> str:
        """Return the SHA-256 hex digest of *data*.

        Args:
            data: Raw bytes to hash.

        Returns:
            Lowercase hexadecimal string (64 characters) representing
            the SHA-256 digest of *data*.

        Example:
            >>> BackupManager.compute_sha256(b'ironman')
            '4f278cdddf52263fe21c64c94932f2b2ec316acecd39a7adcc01eb2e6592a678'
        """
        return hashlib.sha256(data).hexdigest()

    # ------------------------------------------------------------------
    # Manifest creation
    # ------------------------------------------------------------------

    def create_manifest(self, file_paths: list[str]) -> dict[str, str]:
        """Build a SHA-256 manifest by reading each file on disk.

        For every path in *file_paths* the file is opened in binary mode,
        its contents are hashed with :meth:`compute_sha256`, and the
        result is stored in the returned mapping.

        Args:
            file_paths: Ordered list of absolute or relative file paths
                        to include in the manifest.

        Returns:
            ``{path: sha256_hex_digest}`` for every path supplied.

        Raises:
            FileNotFoundError: If any path does not exist on disk.
            PermissionError:   If any path cannot be read.
        """
        manifest: dict[str, str] = {}
        for path in file_paths:
            with open(path, "rb") as fh:
                manifest[path] = self.compute_sha256(fh.read())
        return manifest

    # ------------------------------------------------------------------
    # Manifest verification
    # ------------------------------------------------------------------

    def verify_manifest(
        self,
        manifest: dict[str, str],
        file_contents: dict[str, bytes],
    ) -> bool:
        """Verify that every entry in *manifest* matches *file_contents*.

        The check is intentionally strict:

        * Every key present in *manifest* **must** appear in
          *file_contents* — a missing entry is treated as a failure.
        * The SHA-256 digest of the supplied bytes must equal the
          recorded digest exactly (constant-time comparison via
          :func:`hmac.compare_digest` is not required here because the
          digests are not secret tokens, but correctness is paramount).

        Args:
            manifest:      ``{path: expected_sha256_hex}`` as produced by
                           :meth:`create_manifest`.
            file_contents: ``{path: raw_bytes}`` representing the current
                           on-disk (or in-memory) state of each file.

        Returns:
            ``True`` if every path in *manifest* is present in
            *file_contents* **and** its digest matches; ``False``
            otherwise.
        """
        for path, expected_digest in manifest.items():
            raw = file_contents.get(path)
            if raw is None:
                return False
            if self.compute_sha256(raw) != expected_digest:
                return False
        return True
