"""Amaura Ventures: a founder-controlled startup studio that funds the lab.

The studio is deliberately separate from client services. It discovers product
opportunities, scores them deterministically, runs evidence-first 14-day
validation sprints, and recommends kill / iterate / double-down decisions.
Irreversible actions and product investment remain founder-approved.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from jarvis.amaura.network import fetch_public_bytes
from jarvis.amaura.security import scan_untrusted_text

from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.models import GovernanceError

PRODUCT_TYPES = {"mobile_app", "micro_saas", "web_app", "browser_extension", "developer_tool", "template", "game", "ai_utility", "kdp_book", "digital_download", "template_pack", "content_asset", "affiliate_content", "newsletter"}
OPPORTUNITY_STATUSES = {"discovered", "review_required", "qualified", "rejected", "selected", "experimenting", "archived"}
EXPERIMENT_STAGES = {"planned", "validating", "building", "launching", "measuring", "paused", "killed", "scaling", "completed"}
DECISIONS = {"kill", "iterate", "double_down", "pause"}
SCORE_WEIGHTS = {
    "pain": 25,
    "evidence": 20,
    "distribution_fit": 20,
    "speed": 15,
    "monetization": 10,
    "strategic_fit": 10,
}


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:14]}"


class VentureStudio:
    """Governed startup-factory layer for Amaura Labs."""

    def __init__(self, control: AmauraControlPlane):
        self.control = control

    @staticmethod
    def score(score_components: dict[str, float | int]) -> int:
        missing = set(SCORE_WEIGHTS) - set(score_components)
        extra = set(score_components) - set(SCORE_WEIGHTS)
        if missing or extra:
            raise GovernanceError(
                "Venture score requires exactly: " + ", ".join(SCORE_WEIGHTS)
            )
        total = 0.0
        for key, weight in SCORE_WEIGHTS.items():
            value = float(score_components[key])
            if not 0 <= value <= 100:
                raise GovernanceError(f"Venture score component {key} must be 0-100")
            total += value * weight / 100.0
        return int(round(total))

    def _verified_market_evidence(self, evidence: list[dict[str, Any]], *, actor: str) -> tuple[list[dict[str, Any]], set[str]]:
        if not evidence:
            raise GovernanceError("Venture opportunities require source-backed evidence before scoring")
        normalized: list[dict[str, Any]] = []
        domains: set[str] = set()
        for index, item in enumerate(evidence, start=1):
            if not isinstance(item, dict):
                raise GovernanceError(f"Venture evidence {index} must be an object")
            source_url = str(item.get("source", "")).strip()
            claim = str(item.get("claim", "")).strip()
            excerpt = str(item.get("excerpt", claim)).strip()
            if not source_url or not claim or not excerpt:
                raise GovernanceError("Each venture evidence item requires source, claim, and excerpt")
            parsed = urlsplit(source_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise GovernanceError("Venture evidence sources must be public HTTP(S) URLs")
            claim_scan = scan_untrusted_text(f"{claim}\n{excerpt}")
            if not claim_scan.safe:
                raise GovernanceError("Venture evidence contains prompt-injection or sensitive-data patterns")
            reference = str(item.get("reference", "")).strip()
            if reference:
                verification = self.control.evidence.verify(reference)
                if not verification.get("ok"):
                    raise GovernanceError(f"Venture evidence reference failed verification: {verification.get('reason')}")
                provenance = verification.get("provenance") or {}
                if str(provenance.get("source", "")).rstrip("/") != source_url.rstrip("/"):
                    raise GovernanceError("Venture evidence source does not match its signed provenance manifest")
                fetched_text = self.control.evidence.get_text(reference)
                retrieval = dict(provenance.get("retrieval_metadata") or {})
                payload_sha256 = str(verification.get("sha256", ""))
                captured_at = str(provenance.get("captured_at", ""))
            else:
                raw, retrieval = fetch_public_bytes(source_url, max_length=200_000)
                fetched_text = raw.decode("utf-8", errors="replace")
                source_scan = scan_untrusted_text(fetched_text)
                if not source_scan.safe:
                    raise GovernanceError("Venture evidence source was quarantined by the prompt-injection scanner")
                if excerpt.casefold() not in fetched_text.casefold():
                    raise GovernanceError("Venture evidence excerpt was not found in the retrieved source")
                record = self.control.evidence.put_bytes(
                    raw,
                    source=source_url,
                    media_type=str(retrieval.get("headers", {}).get("content-type", "text/plain; charset=utf-8")),
                    worker_id=actor,
                    task_id="venture-opportunity-intake",
                    retrieval_metadata=retrieval,
                )
                reference = record.reference
                payload_sha256 = record.sha256
                captured_at = record.created_at
            domains.add(parsed.hostname.lower().removeprefix("www."))
            normalized.append({
                "source": source_url,
                "claim": claim,
                "excerpt": excerpt,
                "reference": reference,
                "sha256": payload_sha256,
                "captured_at": captured_at,
                "confidence": max(0.0, min(float(item.get("confidence", 0.75)), 1.0)),
                "retrieval": retrieval,
            })
        return normalized, domains

    @staticmethod
    def _computed_score(*, evidence: list[dict[str, Any]], domains: set[str], estimated_build_days: int, monetization: str, distribution_channel: str, strategic_fit: str) -> dict[str, float]:
        confidence = sum(float(item.get("confidence", 0.0)) for item in evidence) / max(1, len(evidence))
        components = {
            "pain": min(100.0, 45.0 + 12.0 * len(evidence) + 15.0 * confidence),
            "evidence": min(100.0, 20.0 * len(evidence) + 20.0 * len(domains) + 20.0 * confidence),
            "distribution_fit": 80.0 if distribution_channel.strip() else 0.0,
            "speed": max(0.0, 100.0 - max(0, int(estimated_build_days) - 1) * 6.0),
            "monetization": 75.0 if monetization.strip() else 0.0,
            "strategic_fit": 85.0 if strategic_fit.strip() else 40.0,
        }
        return components

    def create_opportunity(
        self,
        *,
        title: str,
        problem: str,
        target_user: str,
        product_type: str,
        source: str,
        evidence: list[dict[str, Any]],
        score_components: dict[str, float | int],
        estimated_build_days: int,
        monetization: str,
        distribution_channel: str,
        strategic_fit: str,
        actor: str = "jarvis",
    ) -> dict[str, Any]:
        if actor not in {"jarvis", self.control.founder_id}:
            raise GovernanceError("Only JARVIS or the founder may register venture opportunities")
        if product_type not in PRODUCT_TYPES:
            raise GovernanceError(f"Unsupported venture product type: {product_type}")
        if not all(value.strip() for value in (title, problem, target_user, source, monetization, distribution_channel)):
            raise GovernanceError("Venture opportunities require a title, problem, user, source, monetization and channel")
        if not 1 <= int(estimated_build_days) <= 14:
            raise GovernanceError("Venture products must be testable within 14 days")
        verified_evidence, evidence_domains = self._verified_market_evidence(evidence, actor=actor)
        computed_components = self._computed_score(
            evidence=verified_evidence, domains=evidence_domains, estimated_build_days=int(estimated_build_days),
            monetization=monetization, distribution_channel=distribution_channel, strategic_fit=strategic_fit,
        )
        total = self.score(computed_components)
        min_sources = max(2, int(os.environ.get("AMAURA_VENTURE_MIN_INDEPENDENT_SOURCES", "2")))
        status = "review_required" if total >= int(os.environ.get("AMAURA_VENTURE_MIN_SCORE", "70")) and len(evidence_domains) >= min_sources else "rejected"
        opportunity = self.control.store.create_venture_opportunity(
            {
                "id": _id("vopp"),
                "title": title.strip(),
                "problem": problem.strip(),
                "target_user": target_user.strip(),
                "product_type": product_type,
                "source": source.strip(),
                "evidence": verified_evidence,
                "score_components": computed_components,
                "total_score": total,
                "estimated_build_days": int(estimated_build_days),
                "monetization": monetization.strip(),
                "distribution_channel": distribution_channel.strip(),
                "status": status,
                "strategic_fit": strategic_fit.strip(),
            }
        )
        self.control.store.publish_event(
            "ventures.opportunity.scored",
            opportunity["id"],
            {"score": total, "status": status, "product_type": product_type, "caller_score_ignored": bool(score_components)},
        )
        self.control.store.audit(
            actor,
            "create_venture_opportunity",
            "venture_opportunity",
            opportunity["id"],
            "allowed",
            {"score": total, "status": status},
        )
        return opportunity

    def start_validation(
        self,
        *,
        opportunity_id: str,
        product_name: str,
        hypothesis: str,
        primary_metric: str,
        target_value: float,
        kill_threshold: float,
        budget_cents: int = 0,
        timebox_days: int = 14,
        actor: str | None = None,
    ) -> dict[str, Any]:
        actor = actor or self.control.founder_id
        if actor != self.control.founder_id:
            raise GovernanceError("Only the founder may start a venture validation sprint")
        opportunity = self.control.store.get_venture_opportunity(opportunity_id)
        if opportunity["status"] not in {"review_required", "qualified", "selected"}:
            raise GovernanceError("Only evidence-qualified venture opportunities may enter validation")
        if not 1 <= int(timebox_days) <= 14:
            raise GovernanceError("A venture validation sprint may not exceed 14 days")
        max_budget = int(os.environ.get("AMAURA_VENTURE_MAX_SPRINT_BUDGET_CENTS", "5000"))
        if not 0 <= int(budget_cents) <= max_budget:
            raise GovernanceError(f"Venture sprint budget exceeds the configured cap of {max_budget} cents")
        if float(target_value) <= float(kill_threshold):
            raise GovernanceError("Target value must be greater than the kill threshold")
        if not all(value.strip() for value in (product_name, hypothesis, primary_metric)):
            raise GovernanceError("Venture validation requires product name, hypothesis and primary metric")
        max_active = max(1, int(os.environ.get("AMAURA_VENTURE_MAX_ACTIVE_SPRINTS", "1")))
        started = datetime.now(UTC)
        if opportunity["status"] == "review_required":
            opportunity = self.control.store.update_venture_opportunity(opportunity_id, status="selected")
        try:
            experiment = self.control.store.create_venture_experiment_with_slot(
            {
                "id": _id("vexp"),
                "opportunity_id": opportunity_id,
                "product_name": product_name.strip(),
                "hypothesis": hypothesis.strip(),
                "stage": "validating",
                "timebox_days": int(timebox_days),
                "budget_cents": int(budget_cents),
                "primary_metric": primary_metric.strip(),
                "target_value": float(target_value),
                "kill_threshold": float(kill_threshold),
                "started_at": started.isoformat(),
                "deadline": (started + timedelta(days=int(timebox_days))).isoformat(),
                "metadata": {
                    "founder_attention_minutes": min(20, int(os.environ.get("AMAURA_VENTURE_FOUNDER_REVIEW_MINUTES", "20"))),
                    "one_problem": opportunity["problem"],
                    "one_user": opportunity["target_user"],
                    "one_channel": opportunity["distribution_channel"],
                },
            },
            max_active=max_active,
        )
        except RuntimeError as exc:
            raise GovernanceError(str(exc) + "; finish, kill or pause the current sprint first") from exc
        programme = self.control.create_program(
            objective=f"Validate {product_name} as a focused revenue product within {timebox_days} days",
            success_metric=f"Measure {primary_metric}; kill at or below {kill_threshold}, double down at or above {target_value}",
            workflow_key="venture_validation_sprint",
            title=f"Amaura Ventures validation: {product_name}",
            priority=2,
            deadline=experiment["deadline"],
            inputs={
                "opportunity_id": opportunity_id,
                "experiment_id": experiment["id"],
                "product_name": product_name.strip(),
                "target_user": opportunity["target_user"],
                "repository_path": self.control.store.get_control("company_repository_path", "."),
            },
        )
        experiment = self.control.store.update_venture_experiment(
            experiment["id"], programme_id=programme["programme"]["id"]
        )
        self.control.store.update_venture_opportunity(opportunity_id, status="experimenting")
        self.control.store.publish_event(
            "ventures.validation.started",
            experiment["id"],
            {"opportunity_id": opportunity_id, "deadline": experiment["deadline"]},
        )
        self.control.store.audit(
            actor,
            "start_venture_validation",
            "venture_experiment",
            experiment["id"],
            "allowed",
            {"timebox_days": timebox_days, "budget_cents": budget_cents},
        )
        return {"experiment": experiment, "programme": programme}

    def set_stage(
        self,
        experiment_id: str,
        *,
        stage: str,
        reason: str,
        actor: str | None = None,
    ) -> dict[str, Any]:
        actor = actor or self.control.founder_id
        if actor not in {"jarvis", self.control.founder_id}:
            raise GovernanceError("Only JARVIS or the founder may update venture stages")
        if stage not in EXPERIMENT_STAGES:
            raise GovernanceError(f"Invalid venture stage: {stage}")
        if stage in {"building", "launching", "scaling"} and actor != self.control.founder_id:
            raise GovernanceError("Founder approval is required to build, launch or scale a venture")
        if stage in {"building", "launching"}:
            conflicts = [
                item for item in self.control.store.list_venture_experiments(limit=1000)
                if item["id"] != experiment_id and item["stage"] in {"building", "launching"}
            ]
            if conflicts:
                raise GovernanceError("Amaura Ventures permits only one active build or launch at a time")
        if not reason.strip():
            raise GovernanceError("Venture stage changes require a reason")
        updated = self.control.store.update_venture_experiment(experiment_id, stage=stage)
        self.control.store.publish_event("ventures.experiment.stage", experiment_id, {"stage": stage, "reason": reason})
        self.control.store.audit(actor, "set_venture_stage", "venture_experiment", experiment_id, "allowed", {"stage": stage, "reason": reason})
        return updated

    def record_metric(
        self,
        experiment_id: str,
        *,
        metric_name: str,
        value: float,
        source: str,
        evidence: list[dict[str, Any]],
        captured_at: str | None = None,
        actor: str = "jarvis",
    ) -> dict[str, Any]:
        if actor not in {"jarvis", self.control.founder_id}:
            raise GovernanceError("Only JARVIS or the founder may record venture metrics")
        experiment = self.control.store.get_venture_experiment(experiment_id)
        if metric_name != experiment["primary_metric"]:
            raise GovernanceError("Metric must match the experiment's primary metric")
        if not source.strip() or not evidence:
            raise GovernanceError("Venture metrics require a source and evidence")
        event = self.control.store.record_venture_metric(
            {
                "id": _id("vmet"),
                "experiment_id": experiment_id,
                "metric_name": metric_name,
                "value": float(value),
                "source": source.strip(),
                "evidence": evidence,
                "captured_at": captured_at or datetime.now(UTC).isoformat(),
            }
        )
        updated = self.control.store.update_venture_experiment(experiment_id, current_value=float(value))
        recommendation = self.recommend(experiment_id)
        self.control.store.publish_event(
            "ventures.metric.recorded",
            experiment_id,
            {"metric": metric_name, "value": value, "recommendation": recommendation["recommendation"]},
        )
        return {"metric": event, "experiment": updated, "recommendation": recommendation}

    def recommend(self, experiment_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        experiment = self.control.store.get_venture_experiment(experiment_id)
        now = now or datetime.now(UTC)
        current = float(experiment["current_value"])
        target = float(experiment["target_value"])
        kill = float(experiment["kill_threshold"])
        deadline = datetime.fromisoformat(experiment["deadline"]) if experiment.get("deadline") else now
        metrics = self.control.store.list_venture_metrics(experiment_id)
        if current >= target:
            recommendation = "double_down"
            reason = f"Primary metric {current:g} reached target {target:g}"
        elif now >= deadline and current <= kill:
            recommendation = "kill"
            reason = f"Timebox ended with {current:g}, at or below kill threshold {kill:g}"
        elif now >= deadline:
            recommendation = "iterate"
            reason = f"Timebox ended between kill threshold {kill:g} and target {target:g}"
        else:
            recommendation = "continue"
            reason = f"Validation remains inside the timebox with {len(metrics)} evidenced metric event(s)"
        updated = self.control.store.update_venture_experiment(
            experiment_id, recommendation=recommendation, metadata={**(experiment.get("metadata") or {}), "recommendation_reason": reason}
        )
        return {"recommendation": recommendation, "reason": reason, "experiment": updated}

    def decide(
        self,
        experiment_id: str,
        *,
        decision: str,
        reason: str,
        actor: str | None = None,
    ) -> dict[str, Any]:
        actor = actor or self.control.founder_id
        if actor != self.control.founder_id:
            raise GovernanceError("Only the founder may make a venture portfolio decision")
        if decision not in DECISIONS:
            raise GovernanceError(f"Decision must be one of: {', '.join(sorted(DECISIONS))}")
        if not reason.strip():
            raise GovernanceError("Venture decisions require a reason")
        stage = {"kill": "killed", "iterate": "validating", "double_down": "scaling", "pause": "paused"}[decision]
        updated = self.control.store.update_venture_experiment(
            experiment_id, decision=decision, decision_reason=reason.strip(), stage=stage
        )
        opportunity_id = updated["opportunity_id"]
        if decision == "kill":
            self.control.store.update_venture_opportunity(opportunity_id, status="archived")
        self.control.store.publish_event("ventures.experiment.decided", experiment_id, {"decision": decision, "stage": stage})
        self.control.store.audit(actor, "decide_venture_experiment", "venture_experiment", experiment_id, "allowed", {"decision": decision, "reason": reason})
        return updated

    def dashboard(self) -> dict[str, Any]:
        opportunities = self.control.store.list_venture_opportunities(limit=1000)
        experiments = self.control.store.list_venture_experiments(limit=1000)
        from jarvis.amaura.ventures_cashflow import CashflowEngine
        cashflow = CashflowEngine(self.control)
        return {
            "branch": "Amaura Ventures",
            "mission": "Fund Amaura Labs through focused products and low-capital cash-flow experiments without turning the lab into an agency",
            "cashflow": cashflow.portfolio(),
            "rules": {
                "max_validation_days": 14,
                "max_active_builds": 1,
                "minimum_opportunity_score": int(os.environ.get("AMAURA_VENTURE_MIN_SCORE", "70")),
                "founder_review_minutes_per_decision": int(os.environ.get("AMAURA_VENTURE_FOUNDER_REVIEW_MINUTES", "20")),
                "external_actions_require_approval": True,
            },
            "opportunity_counts": {status: sum(1 for item in opportunities if item["status"] == status) for status in OPPORTUNITY_STATUSES},
            "experiment_counts": {stage: sum(1 for item in experiments if item["stage"] == stage) for stage in EXPERIMENT_STAGES},
            "top_opportunities": opportunities[:10],
            "active_experiments": [item for item in experiments if item["stage"] not in {"killed", "completed"}],
        }


__all__ = [
    "VentureStudio", "PRODUCT_TYPES", "OPPORTUNITY_STATUSES", "EXPERIMENT_STAGES",
    "DECISIONS", "SCORE_WEIGHTS",
]
