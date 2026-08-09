"""Budget-, privacy-, and mode-aware model routing for company employees."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass

from jarvis.amaura.models import GovernanceError, RiskLevel
from jarvis.amaura.registry import get_agent


@dataclass(frozen=True, slots=True)
class ModelRoute:
    model_key: str
    provider: str
    privacy: str
    estimated_cost_cents: int
    fallback_model_key: str | None
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


class ModelGateway:
    """Select an explicit configured model without broadening data authority."""

    def route(
        self,
        agent_id: str,
        *,
        risk: str = "low",
        sensitivity: str = "internal",
        estimated_tokens: int = 4000,
        remaining_budget_cents: int,
        needs_vision: bool = False,
    ) -> ModelRoute:
        agent = get_agent(agent_id)
        estimated_tokens = max(1, int(estimated_tokens))
        mode = os.environ.get("AMAURA_MODEL_MODE", "local").strip().lower()
        if mode not in {"local", "balanced", "cloud"}:
            raise GovernanceError("AMAURA_MODEL_MODE must be local, balanced, or cloud")

        local_model = os.environ.get("AMAURA_LOCAL_MODEL", "nova:3b").strip()
        cloud_model = os.environ.get("AMAURA_CLOUD_WORKER_MODEL", "").strip()
        vision_model = os.environ.get("AMAURA_CLOUD_VISION_MODEL", "").strip() or cloud_model
        restricted = sensitivity in {"client_confidential", "secret", "restricted"}

        if restricted or mode == "local":
            if not local_model:
                raise GovernanceError("AMAURA_LOCAL_MODEL is required for local or restricted work")
            route = ModelRoute(
                model_key=local_model,
                provider="local",
                privacy="device_only",
                estimated_cost_cents=0,
                fallback_model_key=None,
                reason=(
                    "Restricted data is routed to the configured device-only model with no cloud fallback."
                    if restricted
                    else "Local mode routes all work to the configured device-only model."
                ),
            )
        else:
            selected = vision_model if needs_vision else cloud_model
            if not selected:
                variable = "AMAURA_CLOUD_VISION_MODEL or AMAURA_CLOUD_WORKER_MODEL" if needs_vision else "AMAURA_CLOUD_WORKER_MODEL"
                raise GovernanceError(f"{variable} is required for cloud-routed work")
            complexity_multiplier = 2 if (
                needs_vision
                or agent.model_policy == "balanced"
                or RiskLevel(risk) in {RiskLevel.HIGH, RiskLevel.CRITICAL}
            ) else 1
            route = ModelRoute(
                model_key=selected,
                provider="nvidia",
                privacy="cloud_approved",
                estimated_cost_cents=max(1, complexity_multiplier * estimated_tokens // 4000),
                fallback_model_key=local_model if mode == "balanced" and local_model else None,
                reason=(
                    "Vision work uses the explicitly configured cloud vision model."
                    if needs_vision
                    else "Cloud-approved work uses the explicitly configured worker model."
                ),
            )

        if route.estimated_cost_cents > remaining_budget_cents:
            raise GovernanceError(
                f"Estimated model cost {route.estimated_cost_cents}c exceeds remaining task budget {remaining_budget_cents}c"
            )
        return route
