"""Content-addressed evidence and signed independent-review attestations."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jarvis.amaura.models import GovernanceError


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    sha256: str
    reference: str
    media_type: str
    byte_length: int
    source: str
    created_at: str
    provenance_sha256: str = ""
    signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EvidenceVault:
    """Write-once evidence vault with signed, provenance-bound manifests.

    Blobs remain content addressed, while the public evidence reference points to
    a manifest that binds the bytes to their source, capture time, media type,
    worker/task identity, and retrieval metadata. Legacy sha256 references remain
    readable for backward compatibility but are not provenance authenticated.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _valid_digest(digest: str) -> bool:
        return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)

    def _path(self, digest: str) -> Path:
        if not self._valid_digest(digest):
            raise GovernanceError("Invalid evidence digest")
        return self.root / "sha256" / digest[:2] / digest[2:]

    def _manifest_path(self, digest: str) -> Path:
        if not self._valid_digest(digest):
            raise GovernanceError("Invalid evidence manifest digest")
        return self.root / "manifests" / "sha256" / digest[:2] / f"{digest[2:]}.json"

    @staticmethod
    def _evidence_key() -> bytes:
        return os.environ.get("AMAURA_EVIDENCE_HMAC_KEY", "").encode("utf-8")

    @classmethod
    def _sign_manifest(cls, payload: dict[str, Any]) -> str:
        key = cls._evidence_key()
        if len(key) < 32:
            return ""
        return hmac.new(key, _canonical_bytes(payload), hashlib.sha256).hexdigest()

    @staticmethod
    def _atomic_write(target: Path, payload: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".evidence-", delete=False) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        try:
            temporary_path.replace(target)
        finally:
            temporary_path.unlink(missing_ok=True)

    def put_text(
        self,
        text: str,
        *,
        source: str,
        media_type: str = "text/plain; charset=utf-8",
        worker_id: str = "",
        task_id: str = "",
        retrieval_metadata: dict[str, Any] | None = None,
        captured_at: str | None = None,
    ) -> EvidenceRecord:
        return self.put_bytes(
            text.encode("utf-8", errors="replace"), source=source, media_type=media_type,
            worker_id=worker_id, task_id=task_id, retrieval_metadata=retrieval_metadata,
            captured_at=captured_at,
        )

    def put_json(
        self,
        value: Any,
        *,
        source: str,
        worker_id: str = "",
        task_id: str = "",
        retrieval_metadata: dict[str, Any] | None = None,
        captured_at: str | None = None,
    ) -> EvidenceRecord:
        return self.put_bytes(
            _canonical_bytes(value), source=source, media_type="application/json",
            worker_id=worker_id, task_id=task_id, retrieval_metadata=retrieval_metadata,
            captured_at=captured_at,
        )

    @staticmethod
    def _parse_reference(reference: str) -> tuple[str, str]:
        if reference.startswith("evidence://manifest/"):
            return "manifest", reference.removeprefix("evidence://manifest/")
        for prefix in ("evidence://sha256/", "ev:"):
            if reference.startswith(prefix):
                return "blob", reference[len(prefix):]
        return "blob", reference

    def _load_manifest(self, digest: str) -> dict[str, Any]:
        target = self._manifest_path(digest)
        if not target.is_file():
            raise GovernanceError(f"Evidence manifest not found: {digest}")
        try:
            value = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GovernanceError("Evidence manifest is invalid") from exc
        if not isinstance(value, dict):
            raise GovernanceError("Evidence manifest must be an object")
        return value

    def get_bytes(self, reference: str) -> bytes:
        kind, digest = self._parse_reference(reference)
        if kind == "manifest":
            manifest = self._load_manifest(digest)
            digest = str(manifest.get("payload_sha256", ""))
        target = self._path(digest)
        if not target.exists():
            raise GovernanceError(f"Evidence reference not found: {reference}")
        return target.read_bytes()

    def get_text(self, reference: str) -> str:
        return self.get_bytes(reference).decode("utf-8", errors="replace")

    def put_bytes(
        self,
        payload: bytes,
        *,
        source: str,
        media_type: str,
        worker_id: str = "",
        task_id: str = "",
        retrieval_metadata: dict[str, Any] | None = None,
        captured_at: str | None = None,
    ) -> EvidenceRecord:
        source = str(source).strip()
        if not source:
            raise GovernanceError("Evidence source is required")
        digest = hashlib.sha256(payload).hexdigest()
        target = self._path(digest)
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise GovernanceError("Evidence vault collision or tampering detected")
        else:
            self._atomic_write(target, payload)
        created_at = captured_at or datetime.now(UTC).isoformat()
        unsigned_manifest = {
            "version": 1,
            "payload_sha256": digest,
            "byte_length": len(payload),
            "media_type": str(media_type),
            "source": source,
            "captured_at": created_at,
            "worker_id": str(worker_id),
            "task_id": str(task_id),
            "retrieval_metadata": dict(retrieval_metadata or {}),
        }
        signature = self._sign_manifest(unsigned_manifest)
        manifest = {**unsigned_manifest, "algorithm": "hmac-sha256" if signature else "none", "signature": signature}
        manifest_bytes = _canonical_bytes(manifest)
        manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
        manifest_target = self._manifest_path(manifest_digest)
        if manifest_target.exists():
            if hashlib.sha256(manifest_target.read_bytes()).hexdigest() != manifest_digest:
                raise GovernanceError("Evidence manifest collision or tampering detected")
        else:
            self._atomic_write(manifest_target, manifest_bytes)
        return EvidenceRecord(
            sha256=digest,
            reference=f"evidence://manifest/{manifest_digest}",
            media_type=str(media_type),
            byte_length=len(payload),
            source=source,
            created_at=created_at,
            provenance_sha256=manifest_digest,
            signature=signature,
        )

    def verify(self, reference: str, *, expected_sha256: str = "") -> dict[str, Any]:
        kind, digest = self._parse_reference(reference)
        if not self._valid_digest(digest):
            return {"ok": False, "reference": reference, "reason": "invalid_digest"}
        manifest: dict[str, Any] | None = None
        if kind == "manifest":
            target = self._manifest_path(digest)
            if not target.is_file():
                return {"ok": False, "reference": reference, "reason": "missing_manifest"}
            raw_manifest = target.read_bytes()
            if not hmac.compare_digest(hashlib.sha256(raw_manifest).hexdigest(), digest):
                return {"ok": False, "reference": reference, "reason": "manifest_tampered"}
            try:
                manifest = json.loads(raw_manifest)
            except json.JSONDecodeError:
                return {"ok": False, "reference": reference, "reason": "manifest_invalid"}
            unsigned = {key: manifest[key] for key in (
                "version", "payload_sha256", "byte_length", "media_type", "source",
                "captured_at", "worker_id", "task_id", "retrieval_metadata"
            ) if key in manifest}
            signature = str(manifest.get("signature", ""))
            key = self._evidence_key()
            if signature:
                if len(key) < 32 or not hmac.compare_digest(signature, self._sign_manifest(unsigned)):
                    return {"ok": False, "reference": reference, "reason": "provenance_signature_invalid"}
            elif os.environ.get("AMAURA_STRICT_EVIDENCE_SIGNATURES", "0") == "1":
                return {"ok": False, "reference": reference, "reason": "provenance_unsigned"}
            digest = str(manifest.get("payload_sha256", ""))
            if not self._valid_digest(digest):
                return {"ok": False, "reference": reference, "reason": "manifest_payload_invalid"}
        blob = self._path(digest)
        if not blob.is_file():
            return {"ok": False, "reference": reference, "reason": "missing"}
        actual = hashlib.sha256(blob.read_bytes()).hexdigest()
        if expected_sha256 and not hmac.compare_digest(actual, expected_sha256):
            return {"ok": False, "reference": reference, "reason": "declared_digest_mismatch", "sha256": actual}
        ok = hmac.compare_digest(actual, digest)
        return {
            "ok": ok,
            "reference": reference,
            "sha256": actual,
            "byte_length": blob.stat().st_size,
            "reason": "" if ok else "tampered",
            "provenance": manifest or {},
            "provenance_authenticated": bool(manifest and manifest.get("signature")),
        }


def strict_evidence_enabled(task: dict[str, Any]) -> bool:
    metadata = dict(task.get("metadata") or {})
    return metadata.get("strict_evidence") is True or os.environ.get("AMAURA_STRICT_EVIDENCE", "0") == "1"


def strict_review_enabled(task: dict[str, Any]) -> bool:
    metadata = dict(task.get("metadata") or {})
    return metadata.get("strict_review") is True or os.environ.get("AMAURA_STRICT_REVIEW", "0") == "1"


def validate_criterion_review(
    task: dict[str, Any],
    decision: dict[str, Any],
    vault: EvidenceVault,
) -> dict[str, Any]:
    """Validate reviewer criterion coverage against the immutable task evidence set."""
    criteria = [str(item) for item in (task.get("acceptance_criteria") or [])]
    raw_results = decision.get("criteria")
    findings: list[str] = []
    normalized: list[dict[str, Any]] = []
    successful_refs = {
        str(item.get("reference", ""))
        for item in (task.get("evidence") or [])
        if item.get("success") is not False and str(item.get("reference", ""))
    }
    strict = strict_review_enabled(task)
    if not isinstance(raw_results, list):
        raw_results = []
    if strict and criteria and len(raw_results) != len(criteria):
        findings.append(
            f"Reviewer covered {len(raw_results)} of {len(criteria)} acceptance criteria"
        )

    covered: set[int] = set()
    for position, raw in enumerate(raw_results, start=1):
        if not isinstance(raw, dict):
            findings.append(f"Criterion review {position} is not an object")
            continue
        raw_index = raw.get("criterion_index")
        index: int | None = None
        if isinstance(raw_index, int):
            candidate = raw_index - 1 if raw_index >= 1 else raw_index
            if 0 <= candidate < len(criteria):
                index = candidate
        if index is None:
            criterion_text = str(raw.get("criterion", "")).strip()
            matches = [i for i, criterion in enumerate(criteria) if criterion == criterion_text]
            if len(matches) == 1:
                index = matches[0]
        if index is None:
            findings.append(f"Criterion review {position} does not identify a real acceptance criterion")
            continue
        if index in covered:
            findings.append(f"Acceptance criterion {index + 1} is reviewed more than once")
            continue
        covered.add(index)
        passed = raw.get("passed")
        if not isinstance(passed, bool):
            findings.append(f"Acceptance criterion {index + 1} has no boolean passed result")
            passed = False
        refs = raw.get("evidence_refs", raw.get("evidence", []))
        if isinstance(refs, str):
            refs = [refs]
        if not isinstance(refs, list):
            refs = []
        refs = [str(ref).strip() for ref in refs if str(ref).strip()]
        invalid_refs = [ref for ref in refs if ref not in successful_refs]
        if invalid_refs:
            findings.append(
                f"Acceptance criterion {index + 1} cites evidence outside the approved submission"
            )
        if strict and not refs:
            findings.append(f"Acceptance criterion {index + 1} has no evidence reference")
        if strict:
            for ref in refs:
                verification = vault.verify(ref)
                if not verification["ok"]:
                    findings.append(
                        f"Acceptance criterion {index + 1} cites unverifiable evidence: {verification['reason']}"
                    )
        normalized.append(
            {
                "criterion_index": index + 1,
                "criterion": criteria[index],
                "passed": bool(passed),
                "evidence_refs": refs,
                "notes": str(raw.get("notes", "")).strip(),
            }
        )

    if strict:
        missing = [index + 1 for index in range(len(criteria)) if index not in covered]
        if missing:
            findings.append(f"Acceptance criteria missing reviewer coverage: {missing}")
        if decision.get("approve") is True:
            failed = [item["criterion_index"] for item in normalized if not item["passed"]]
            if failed:
                findings.append(f"Reviewer approved while criteria failed: {failed}")
    return {
        "ok": not findings,
        "strict": strict,
        "findings": findings,
        "criteria": normalized,
        "criteria_count": len(criteria),
        "covered_count": len(covered),
    }


def deterministic_evidence_review(
    task: dict[str, Any],
    vault: EvidenceVault,
) -> dict[str, Any]:
    """Reject missing, failed, or tampered completion evidence before model review."""

    evidence = task.get("evidence") or []
    findings: list[str] = []
    verified: list[dict[str, Any]] = []
    strict = strict_evidence_enabled(task)
    if not str(task.get("summary", "")).strip():
        findings.append("Submission has no completion summary")
    if not evidence:
        findings.append("Submission has no evidence")
    for index, item in enumerate(evidence):
        if item.get("success") is False:
            findings.append(f"Evidence {index + 1} records a failed operation")
        reference = str(item.get("reference", ""))
        if reference.startswith("evidence://"):
            result = vault.verify(
                reference,
                expected_sha256=str(item.get("sha256", "")),
            )
            verified.append(result)
            if not result["ok"]:
                findings.append(
                    f"Evidence {index + 1} failed integrity verification: "
                    f"{result['reason']}"
                )
            else:
                # Inspect structured verification receipt fields
                try:
                    raw_text = vault.get_text(reference)
                    receipt_data = json.loads(raw_text)
                    if isinstance(receipt_data, dict):
                        # Write verification
                        if receipt_data.get("tool_name") == "write_file" or receipt_data.get("action") == "write":
                            if receipt_data.get("verification_passed") is False:
                                findings.append(f"Evidence {index + 1} write verification failed")
                            if receipt_data.get("content_match") is False:
                                findings.append(f"Evidence {index + 1} write content mismatch")
                            exp_size = int(receipt_data.get("expected_size", 0) or 0)
                            act_size = int(receipt_data.get("actual_size", receipt_data.get("size_bytes", receipt_data.get("bytes", 0))) or 0)
                            if exp_size > 0 and act_size == 0:
                                findings.append(f"Evidence {index + 1} produced 0-byte file for non-empty write request ({exp_size} chars expected)")
                        # Workflow verification
                        elif receipt_data.get("tool_name") == "multi_step_workflow" or receipt_data.get("execution_type") == "workflow":
                            if receipt_data.get("verification_passed") is False:
                                findings.append(f"Evidence {index + 1} workflow verification failed")
                        # Browser compound verification
                        elif "browser" in str(receipt_data.get("tool_name", "")).lower() or receipt_data.get("execution_type") == "browser":
                            if receipt_data.get("verification_passed") is False or receipt_data.get("status") in {"partial_failure", "total_failure"}:
                                findings.append(f"Evidence {index + 1} browser extraction failed required fields")
                except Exception:
                    pass
        elif strict or item.get("type") == "tool_result":
            findings.append(
                f"Evidence {index + 1} is not stored in the content-addressed evidence vault"
            )
    criteria = task.get("acceptance_criteria") or []
    if criteria and not evidence:
        findings.append("Acceptance criteria have no supporting evidence")
    return {
        "approve": not findings,
        "findings": findings,
        "verified_evidence": verified,
        "criteria_count": len(criteria),
        "evidence_count": len(evidence),
        "strict": strict,
        "submission_sha256": hashlib.sha256(
            _canonical_bytes(
                {
                    "task_id": task.get("id"),
                    "summary": task.get("summary"),
                    "evidence": evidence,
                    "acceptance_criteria": criteria,
                }
            )
        ).hexdigest(),
    }


def create_review_attestation(
    *,
    task_id: str,
    reviewer_id: str,
    reviewer_model: str,
    decision: dict[str, Any],
    deterministic_review: dict[str, Any],
    reviewer_provider: str = "",
    requested_reviewer_model: str = "",
    key: str | None = None,
) -> dict[str, Any]:
    secret = (key if key is not None else os.environ.get(
        "AMAURA_REVIEW_ATTESTATION_KEY", ""
    )).encode()
    if len(secret) < 32:
        raise GovernanceError(
            "AMAURA_REVIEW_ATTESTATION_KEY must contain at least 32 bytes"
        )
    payload = {
        "task_id": task_id,
        "reviewer_id": reviewer_id,
        "reviewer_model": reviewer_model,
        "reviewer_provider": reviewer_provider,
        "requested_reviewer_model": requested_reviewer_model or reviewer_model,
        "decision": decision,
        "deterministic_review": deterministic_review,
        "created_at": datetime.now(UTC).isoformat(),
    }
    signature = hmac.new(secret, _canonical_bytes(payload), hashlib.sha256).hexdigest()
    return {
        **payload,
        "algorithm": "hmac-sha256",
        "signature": signature,
    }


def verify_review_attestation(
    attestation: dict[str, Any],
    *,
    key: str | None = None,
) -> bool:
    secret = (key if key is not None else os.environ.get(
        "AMAURA_REVIEW_ATTESTATION_KEY", ""
    )).encode()
    if len(secret) < 32:
        return False
    payload = {
        name: attestation[name]
        for name in (
            "task_id",
            "reviewer_id",
            "reviewer_model",
            "reviewer_provider",
            "requested_reviewer_model",
            "decision",
            "deterministic_review",
            "created_at",
        )
        if name in attestation
    }
    expected = hmac.new(secret, _canonical_bytes(payload), hashlib.sha256).hexdigest()
    return hmac.compare_digest(str(attestation.get("signature", "")), expected)


__all__ = [
    "EvidenceRecord",
    "EvidenceVault",
    "create_review_attestation",
    "deterministic_evidence_review",
    "strict_evidence_enabled",
    "strict_review_enabled",
    "validate_criterion_review",
    "verify_review_attestation",
]
