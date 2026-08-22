"""Shared, fail-closed routing rules for independent model review."""

from __future__ import annotations

import os
from collections.abc import Mapping

_DYNAMIC_SELECTOR_PREFIXES = ("auto/", "best/", "default/")
_DYNAMIC_SELECTOR_NAMES = {"auto", "best", "default", "router"}


def _value(name: str, environment: Mapping[str, str] | None = None) -> str:
    source = os.environ if environment is None else environment
    return str(source.get(name, "")).strip()


def effective_review_mode(environment: Mapping[str, str] | None = None) -> str:
    """Resolve review mode exactly as governed review execution does."""
    mode = _value("AMAURA_REVIEW_MODE", environment).lower() or "auto"
    if mode == "auto":
        return "omniroute" if _value("AMAURA_MODEL_PROVIDER", environment).lower() == "omniroute" else "local"
    return mode


def is_dynamic_model_selector(model: str) -> bool:
    normalized = model.strip().lower()
    return normalized in _DYNAMIC_SELECTOR_NAMES or normalized.startswith(_DYNAMIC_SELECTOR_PREFIXES)


def omniroute_review_route(environment: Mapping[str, str] | None = None) -> dict[str, object]:
    """Describe the static safety of the explicit OmniRoute review route.

    Model aliases are deliberately not treated as independent: a gateway can
    resolve them to the worker model at runtime, where the existing provenance
    check remains the final fail-closed guard.
    """
    worker_primary = _value("AMAURA_OMNIROUTE_MODEL", environment) or _value("OMNIROUTE_MODEL", environment)
    worker_fallback = _value("AMAURA_OMNIROUTE_FALLBACK_MODEL", environment)
    reviewer_model = _value("AMAURA_OMNIROUTE_REVIEW_MODEL", environment)
    reviewer_fallback = _value("AMAURA_OMNIROUTE_REVIEW_FALLBACK_MODEL", environment)
    worker_models = {model for model in (worker_primary, worker_fallback) if model}
    blockers: list[str] = []
    if not reviewer_model:
        blockers.append("reviewer_model_missing")
    elif is_dynamic_model_selector(reviewer_model):
        blockers.append("reviewer_model_dynamic")
    elif reviewer_model in worker_models:
        blockers.append("reviewer_model_matches_worker")
    if reviewer_fallback:
        if is_dynamic_model_selector(reviewer_fallback):
            blockers.append("reviewer_fallback_dynamic")
        elif reviewer_fallback in worker_models:
            blockers.append("reviewer_fallback_matches_worker")
    return {
        "mode": "omniroute",
        "model": reviewer_model,
        "fallback_model": reviewer_fallback,
        "worker_models": sorted(worker_models),
        "independent": not blockers,
        "blockers": blockers,
    }
