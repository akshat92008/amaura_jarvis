"""Trust provenance for company signals and external observations.

Trust metadata is data-plane provenance, not authorization.  It follows a signal
into downstream workflow inputs so model-facing text can distinguish founder
instructions from system observations and untrusted external evidence.
"""

from __future__ import annotations

from enum import StrEnum
from html import escape
from typing import Any

SIGNAL_TRUST_KEY = "trust_provenance"


class TrustLevel(StrEnum):
    """Origin trust level for durable company-signal data."""

    EXTERNAL_UNTRUSTED = "external_untrusted"
    SYSTEM_OBSERVED = "system_observed"
    FOUNDER = "founder"


def make_signal_trust(
    level: TrustLevel,
    *,
    source: str,
    untrusted_fields: tuple[str, ...] | list[str] = (),
) -> dict[str, Any]:
    """Build normalized, JSON-safe provenance metadata."""
    fields = list(dict.fromkeys(str(field).strip() for field in untrusted_fields if str(field).strip()))
    return {
        "level": level.value,
        "source": source.strip(),
        "instruction_authority": level is TrustLevel.FOUNDER,
        "untrusted_fields": fields,
    }


def trust_from_payload(payload: dict[str, Any], *, default_source: str = "internal") -> dict[str, Any]:
    """Return validated provenance, defaulting legacy/internal data safely."""
    raw = payload.get(SIGNAL_TRUST_KEY)
    if isinstance(raw, dict):
        try:
            level = TrustLevel(str(raw.get("level") or ""))
        except ValueError:
            level = TrustLevel.SYSTEM_OBSERVED
        source = str(raw.get("source") or default_source).strip() or default_source
        fields_raw = raw.get("untrusted_fields")
        fields = fields_raw if isinstance(fields_raw, list) else []
        return make_signal_trust(level, source=source, untrusted_fields=[str(field) for field in fields])
    return make_signal_trust(TrustLevel.SYSTEM_OBSERVED, source=default_source)


def render_untrusted_external_text(value: str, *, field: str) -> str:
    """Render external natural language as evidence, never as instruction text."""
    return (
        f'<untrusted_external_data field="{escape(field, quote=True)}" instruction_authority="false">'
        f"{escape(value, quote=False)}"
        "</untrusted_external_data>"
    )


def protect_signal_payload(
    payload: dict[str, Any],
    *,
    default_source: str = "internal",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Carry trust metadata forward and fence declared untrusted text fields."""
    protected = dict(payload)
    trust = trust_from_payload(protected, default_source=default_source)
    if trust["level"] == TrustLevel.EXTERNAL_UNTRUSTED.value:
        for field in trust["untrusted_fields"]:
            value = protected.get(field)
            if isinstance(value, str):
                protected[field] = render_untrusted_external_text(value, field=field)
    protected[SIGNAL_TRUST_KEY] = trust
    return protected, trust


__all__ = [
    "SIGNAL_TRUST_KEY",
    "TrustLevel",
    "make_signal_trust",
    "protect_signal_payload",
    "render_untrusted_external_text",
    "trust_from_payload",
]
