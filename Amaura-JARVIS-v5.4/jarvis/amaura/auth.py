"""Credential parsing and identity binding for Amaura authorities."""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass

from jarvis.amaura.models import GovernanceError


@dataclass(frozen=True, slots=True)
class ReviewerCredential:
    reviewer_id: str
    key: str


def reviewer_credentials(raw: str | None = None) -> tuple[ReviewerCredential, ...]:
    value = os.environ.get("AMAURA_REVIEWER_KEYS", "") if raw is None else raw
    credentials: list[ReviewerCredential] = []
    identities: set[str] = set()
    keys: set[str] = set()
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise GovernanceError("AMAURA_REVIEWER_KEYS entries must use reviewer_id:key")
        reviewer_id, key = (part.strip() for part in item.split(":", 1))
        if not reviewer_id or not key:
            raise GovernanceError("Reviewer identity and key may not be empty")
        if len(key.encode()) < 24:
            raise GovernanceError("Reviewer keys must contain at least 24 bytes")
        if reviewer_id in identities or key in keys:
            raise GovernanceError("Reviewer identities and keys must be unique")
        identities.add(reviewer_id)
        keys.add(key)
        credentials.append(ReviewerCredential(reviewer_id, key))
    return tuple(credentials)


def resolve_reviewer_identity(supplied_key: str) -> str | None:
    if not supplied_key:
        return None
    for credential in reviewer_credentials():
        if hmac.compare_digest(supplied_key, credential.key):
            return credential.reviewer_id
    return None


__all__ = ["ReviewerCredential", "reviewer_credentials", "resolve_reviewer_identity"]
