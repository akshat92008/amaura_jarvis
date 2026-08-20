"""Bounded reviewer-model diversity for governed Amaura task review.

Automatic hosted review must never silently certify work with the same actual
model that produced the worker evidence. Hosted aliases can legitimately resolve
to the same model, so requested-model inequality is insufficient. This module
decorates the stable review runner with a small fail-closed routing loop for
hosted automatic review while preserving deterministic and explicitly local
review paths implemented by the stable core.

Explicit founder/operator review configuration is never overridden. A concrete
pinned reviewer model remains authoritative. The special OmniRoute automatic
alias ``auto/best-reasoning`` is not a concrete model pin, however; when that
alias collides with worker provenance, ARCH may try other distinct OmniRoute
reviewer models while preserving the operator's chosen provider. Local models
are never introduced as a fallback by this decorator.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from jarvis.amaura import executor_core as _core
from jarvis.amaura.models import GovernanceError, TaskState

_BASE_REVIEW_RUNNER = _core.GovernedReviewRunner
_INSTALLED = False

_DEFAULT_OMNIROUTE_MODELS = (
    "z-ai/glm-5.2",
    "moonshotai/kimi-k2.6",
    "deepseek-ai/deepseek-v4-pro",
    "auto/best-reasoning",
)
_DEFAULT_CLOUD_MODELS = (
    "z-ai/glm-5.2",
    "moonshotai/kimi-k2.6",
    "meta/llama-3.3-70b-instruct",
)
_AUTOMATIC_OMNIROUTE_ALIASES = {"", "auto", "auto/best-reasoning"}
_RETRYABLE_REVIEW_MARKERS = (
    "Actual reviewer model must differ from every worker model used for the task",
    "Independent reviewer model must differ from every worker model used for the task",
    "OmniRoute worker execution failed",
    "OmniRoute returned no completion choices",
    "OmniRoute returned an empty worker completion",
    "Reviewer returned no JSON decision",
    "Reviewer returned malformed JSON",
    "Reviewer decision is missing approve/findings",
    "The configured NVIDIA provider failed and provider fallback is disabled",
)
_HOSTED_WORKER_PROVIDERS = {
    "omniroute",
    "nvidia",
    "openrouter",
    "openai",
    "anthropic",
    "groq",
}


def _bounded_float(name: str, *, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def _attempt_timeout_seconds() -> float:
    """Bound one hosted reviewer attempt without making cold providers unusable."""
    return _bounded_float(
        "AMAURA_REVIEW_DIVERSITY_ATTEMPT_TIMEOUT_SECONDS",
        default=45.0,
        minimum=10.0,
        maximum=90.0,
    )


def _total_budget_seconds() -> float:
    """Bound the complete automatic reviewer-diversity loop."""
    return _bounded_float(
        "AMAURA_REVIEW_DIVERSITY_TOTAL_BUDGET_SECONDS",
        default=120.0,
        minimum=30.0,
        maximum=240.0,
    )


def _split_models(value: str | None) -> list[str]:
    result: list[str] = []
    for raw in str(value or "").replace("\n", ",").split(","):
        model = raw.strip()
        if model and model not in result:
            result.append(model)
    return result


def _max_attempts() -> int:
    raw = os.environ.get("AMAURA_REVIEW_DIVERSITY_MAX_ATTEMPTS", "4").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 4
    return max(1, min(value, 6))


def _omniroute_configured() -> bool:
    base = os.environ.get("AMAURA_OMNIROUTE_BASE_URL", "").strip() or os.environ.get(
        "OMNIROUTE_BASE_URL", ""
    ).strip()
    key = os.environ.get("AMAURA_OMNIROUTE_API_KEY", "").strip() or os.environ.get(
        "OMNIROUTE_API_KEY", ""
    ).strip()
    return bool(base and key)


def _nvidia_review_configured() -> bool:
    return bool(
        os.environ.get("NVIDIA_REVIEW_API_KEY", "").strip()
        or os.environ.get("NVIDIA_API_KEY", "").strip()
    )


def _dedupe_distinct(models: list[str], worker_models: set[str]) -> list[str]:
    result: list[str] = []
    for model in models:
        value = model.strip()
        if not value or value in result or value in worker_models:
            continue
        result.append(value)
    return result


def _provider_candidates(provider: str, worker_models: set[str]) -> list[str]:
    if provider == "omniroute":
        configured = _split_models(os.environ.get("AMAURA_OMNIROUTE_REVIEW_MODEL_CANDIDATES"))
        single = os.environ.get("AMAURA_OMNIROUTE_REVIEW_MODEL", "").strip()
        models = ([single] if single else []) + configured + list(_DEFAULT_OMNIROUTE_MODELS)
        return _dedupe_distinct(models, worker_models)
    if provider == "cloud":
        configured = _split_models(os.environ.get("AMAURA_CLOUD_REVIEW_MODEL_CANDIDATES"))
        single = os.environ.get("AMAURA_CLOUD_REVIEW_MODEL", "").strip()
        models = ([single] if single else []) + configured + list(_DEFAULT_CLOUD_MODELS)
        return _dedupe_distinct(models, worker_models)
    return []


def _review_attempts(worker_models: set[str], *, provider_scope: str = "auto") -> list[tuple[str, str]]:
    """Build a bounded hosted-only automatic review route list.

    ``provider_scope='omniroute'`` is used when the operator explicitly selected
    OmniRoute but left its reviewer model on an automatic alias. In that case
    ARCH may diversify models inside OmniRoute, but it may not cross providers.
    """
    omni = (
        _provider_candidates("omniroute", worker_models)
        if provider_scope in {"auto", "omniroute"} and _omniroute_configured()
        else []
    )
    cloud = (
        _provider_candidates("cloud", worker_models)
        if provider_scope == "auto" and _nvidia_review_configured()
        else []
    )
    attempts: list[tuple[str, str]] = []

    if omni:
        attempts.append(("omniroute", omni.pop(0)))
    if omni:
        attempts.append(("omniroute", omni.pop(0)))
    if cloud:
        attempts.append(("cloud", cloud.pop(0)))

    while omni or cloud:
        if omni:
            attempts.append(("omniroute", omni.pop(0)))
        if cloud:
            attempts.append(("cloud", cloud.pop(0)))

    return attempts[: _max_attempts()]


def _uses_core_deterministic_review(task: dict[str, Any], raw_mode: str) -> bool:
    """Mirror the stable core's deterministic-review eligibility exactly.

    Reviewer diversity must sit *after* this policy boundary. Repository work
    already proven by independent Antigravity evidence, and direct-action proof
    paths, are verified deterministically and must not be forced through a
    hosted model merely because model provenance exists in their receipts.
    """
    metadata = dict(task.get("metadata") or {})
    return bool(
        task.get("action_type") == "direct_action"
        or (metadata.get("goal_plan") or {}).get("domain") == "direct_action"
        or (
            task.get("action_type") == "repository_write"
            and metadata.get("coding_backend_used") == "antigravity"
            and raw_mode in {"", "auto", "deterministic"}
        )
    )


def _automatic_hosted_review_requested() -> bool:
    """Return True only when the worker/runtime policy is actually hosted.

    Availability of an unrelated cloud credential is not enough to change the
    semantics of an explicitly local Company OS. This keeps legacy/local auto
    review behavior stable while enabling diversity for real hosted workers.
    """
    provider = (
        os.environ.get("AMAURA_MODEL_PROVIDER", "").strip().lower()
        or os.environ.get("AMAURA_JARVIS_PROVIDER", "").strip().lower()
    )
    mode = os.environ.get("AMAURA_MODEL_MODE", "local").strip().lower()
    return provider in _HOSTED_WORKER_PROVIDERS or mode in {"cloud", "omniroute"}


def _review_scope(raw_mode: str) -> str | None:
    """Resolve whether model diversity is automatic and its provider boundary.

    Empty/``auto`` review mode may use any configured hosted reviewer provider.
    Explicit ``omniroute`` remains provider-pinned, but an automatic model alias
    is still eligible for *within-provider* diversity. Concrete model pins and
    every other explicit mode are left completely untouched.
    """
    if raw_mode in {"", "auto"}:
        return "auto"
    if raw_mode == "omniroute":
        model = os.environ.get("AMAURA_OMNIROUTE_REVIEW_MODEL", "").strip().lower()
        if model in _AUTOMATIC_OMNIROUTE_ALIASES:
            return "omniroute"
    return None


@contextmanager
def _temporary_review_route(provider: str, model: str, *, timeout_seconds: float) -> Iterator[None]:
    names = (
        "AMAURA_REVIEW_MODE",
        "AMAURA_OMNIROUTE_REVIEW_MODEL",
        "AMAURA_CLOUD_REVIEW_MODEL",
        "AMAURA_OMNIROUTE_FALLBACK_MODEL",
        "AMAURA_OMNIROUTE_WORKER_TIMEOUT_SECONDS",
        "AMAURA_NVIDIA_TIMEOUT",
        "AMAURA_NVIDIA_CONNECT_TIMEOUT",
    )
    previous = {name: os.environ.get(name) for name in names}
    try:
        if provider == "omniroute":
            os.environ["AMAURA_REVIEW_MODE"] = "omniroute"
            os.environ["AMAURA_OMNIROUTE_REVIEW_MODEL"] = model
            os.environ["AMAURA_OMNIROUTE_FALLBACK_MODEL"] = ""
            os.environ["AMAURA_OMNIROUTE_WORKER_TIMEOUT_SECONDS"] = str(timeout_seconds)
        elif provider == "cloud":
            os.environ["AMAURA_REVIEW_MODE"] = "cloud"
            os.environ["AMAURA_CLOUD_REVIEW_MODEL"] = model
            os.environ["AMAURA_NVIDIA_TIMEOUT"] = str(timeout_seconds)
            os.environ["AMAURA_NVIDIA_CONNECT_TIMEOUT"] = str(min(10.0, max(3.0, timeout_seconds / 3.0)))
        else:
            raise GovernanceError(f"Unsupported automatic review provider: {provider}")
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _retryable_review_error(exc: Exception) -> bool:
    text = str(exc)
    return any(marker in text for marker in _RETRYABLE_REVIEW_MARKERS)


def _failure_summary(failures: list[dict[str, str]]) -> str:
    if not failures:
        return "no eligible hosted reviewer route was available"
    return "; ".join(f"{item['provider']}:{item['model']}:{item['error_type']}" for item in failures)


class DiverseGovernedReviewRunner(_BASE_REVIEW_RUNNER):
    """Stable reviewer plus bounded actual-model diversity recovery in auto mode."""

    _arch_review_diversity_installed = True

    def run(self, task_id: str) -> dict[str, Any]:
        raw_mode = os.environ.get("AMAURA_REVIEW_MODE", "").strip().lower()
        provider_scope = _review_scope(raw_mode)

        # Explicit concrete operator choices remain authoritative. The one
        # exception is an explicit OmniRoute provider paired with its automatic
        # model alias; that is provider-pinned, not actual-model-pinned.
        if provider_scope is None:
            return super().run(task_id)

        task = self.control.store.get_work_item(task_id)
        if _uses_core_deterministic_review(task, raw_mode):
            return super().run(task_id)
        if not _automatic_hosted_review_requested():
            return super().run(task_id)

        worker_models = set(self._worker_models_from_evidence(task))
        if not worker_models:
            return super().run(task_id)

        attempts = _review_attempts(worker_models, provider_scope=provider_scope)
        if not attempts:
            raise GovernanceError(
                "Automatic independent review has hosted worker model provenance but no distinct hosted reviewer route. "
                "Configure OmniRoute or NVIDIA review credentials/models; local fallback is not permitted."
            )

        failures: list[dict[str, str]] = []
        started = time.monotonic()
        total_budget = _total_budget_seconds()
        for provider, model in attempts:
            remaining = total_budget - (time.monotonic() - started)
            if remaining < 5.0:
                failures.append(
                    {
                        "provider": provider,
                        "model": model,
                        "error_type": "ReviewDiversityBudgetExhausted",
                    }
                )
                break
            timeout_seconds = min(_attempt_timeout_seconds(), remaining)
            with _temporary_review_route(provider, model, timeout_seconds=timeout_seconds):
                try:
                    return super().run(task_id)
                except Exception as exc:  # noqa: BLE001 - only a narrow allowlist is retryable
                    current = self.control.store.get_work_item(task_id)
                    if current.get("state") != TaskState.AWAITING_REVIEW.value:
                        raise
                    if not _retryable_review_error(exc):
                        raise
                    failures.append(
                        {
                            "provider": provider,
                            "model": model,
                            "error_type": type(exc).__name__,
                        }
                    )

        raise GovernanceError(
            "Automatic independent review exhausted distinct hosted reviewer routes without weakening the "
            f"worker/reviewer separation invariant: {_failure_summary(failures)}"
        )


def install_review_diversity() -> type[Any]:
    """Install the reviewer decorator exactly once and return the active class."""
    global _INSTALLED
    current = _core.GovernedReviewRunner
    if getattr(current, "_arch_review_diversity_installed", False):
        _INSTALLED = True
        return current
    _core.GovernedReviewRunner = DiverseGovernedReviewRunner  # type: ignore[misc]
    _INSTALLED = True
    return DiverseGovernedReviewRunner


__all__ = [
    "DiverseGovernedReviewRunner",
    "install_review_diversity",
]
