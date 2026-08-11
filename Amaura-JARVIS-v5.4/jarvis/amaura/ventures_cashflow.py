"""Cash-flow portfolio layer for Amaura Ventures.

This module extends the original venture studio into a low-capital, founder-time-
aware portfolio engine.  It does not promise income and it never bypasses the
Company OS approval boundary.  Its job is to find evidence-backed opportunities,
rank them for time-to-cash and automation, maintain a small portfolio of revenue
streams, reconcile source-backed revenue/cost events, and propose the next safest
high-leverage action.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.models import GovernanceError, TaskState

CashflowLane = Literal[
    "kdp_book",
    "digital_download",
    "template_pack",
    "content_asset",
    "affiliate_content",
    "newsletter",
    "micro_saas",
    "web_app",
    "browser_extension",
    "developer_tool",
    "ai_utility",
    "mobile_app",
]

LANE_PROFILES: dict[str, dict[str, Any]] = {
    "kdp_book": {"product_type": "kdp_book", "time_to_cash": 58, "automation": 68, "capital": 96, "margin": 72},
    "digital_download": {"product_type": "digital_download", "time_to_cash": 88, "automation": 92, "capital": 98, "margin": 94},
    "template_pack": {"product_type": "template_pack", "time_to_cash": 90, "automation": 94, "capital": 99, "margin": 96},
    "content_asset": {"product_type": "content_asset", "time_to_cash": 62, "automation": 82, "capital": 98, "margin": 86},
    "affiliate_content": {"product_type": "affiliate_content", "time_to_cash": 48, "automation": 76, "capital": 99, "margin": 82},
    "newsletter": {"product_type": "newsletter", "time_to_cash": 42, "automation": 77, "capital": 96, "margin": 90},
    "micro_saas": {"product_type": "micro_saas", "time_to_cash": 64, "automation": 88, "capital": 88, "margin": 92},
    "web_app": {"product_type": "web_app", "time_to_cash": 60, "automation": 86, "capital": 88, "margin": 90},
    "browser_extension": {"product_type": "browser_extension", "time_to_cash": 68, "automation": 91, "capital": 92, "margin": 92},
    "developer_tool": {"product_type": "developer_tool", "time_to_cash": 66, "automation": 92, "capital": 94, "margin": 94},
    "ai_utility": {"product_type": "ai_utility", "time_to_cash": 63, "automation": 90, "capital": 84, "margin": 88},
    "mobile_app": {"product_type": "mobile_app", "time_to_cash": 52, "automation": 82, "capital": 78, "margin": 84},
}

STREAM_STATUSES = {"draft", "validation", "ready", "live", "paused", "retired"}
FINANCIAL_EVENT_TYPES = {"revenue", "refund", "fee", "cost", "cogs", "marketing", "tax", "payout"}
PROVIDER_FINANCIAL_SUCCESS_STATUSES = {"confirmed", "success", "succeeded", "completed", "paid", "captured", "settled", "posted", "refunded"}
ACTION_STATUSES = {"proposed", "approved", "running", "completed", "blocked", "cancelled", "failed"}
STREAM_TRANSITIONS = {
    "draft": {"validation", "retired"},
    "validation": {"ready", "paused", "retired"},
    "ready": {"live", "paused", "retired"},
    "live": {"paused", "retired"},
    "paused": {"validation", "ready", "live", "retired"},
    "retired": set(),
}
ACTION_TYPES = {
    "research_demand", "improve_offer", "create_asset", "listing_optimization", "seo_content",
    "distribution_draft", "pricing_review", "conversion_review", "retention_review", "portfolio_review",
}

PROHIBITED_PATTERNS = (
    "fake review", "fake reviews", "plagiar", "copyright infringement", "scrape private",
    "spam dm", "mass dm", "evade ban", "bypass platform", "impersonate", "guaranteed income",
)
PROHIBITED_CONCEPTS = (
    ({"review", "rating", "testimonial"}, {"fake", "buy", "fabricate", "manufacture", "astroturf"}),
    ({"message", "dm", "outreach", "email"}, {"mass", "bulk", "unsolicited", "blast", "spam"}),
    ({"content", "book", "template", "product"}, {"copy", "clone", "steal", "plagiarize", "pirate"}),
    ({"platform", "ban", "restriction", "moderation"}, {"evade", "bypass", "circumvent", "avoid"}),
    ({"identity", "founder", "person"}, {"impersonate", "pretend", "spoof"}),
    ({"income", "revenue", "return", "profit"}, {"guaranteed", "certain", "riskless", "assured"}),
)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:14]}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


class CashflowEngine:
    """Portfolio manager for low-capital owned revenue streams."""

    def __init__(self, control: AmauraControlPlane):
        self.control = control

    @staticmethod
    def lane_profile(lane: str) -> dict[str, Any]:
        try:
            return {"lane": lane, **LANE_PROFILES[lane]}
        except KeyError as exc:
            raise GovernanceError(f"Unsupported cash-flow lane: {lane}") from exc

    @staticmethod
    def _validate_offer_text(*parts: str) -> None:
        text = " ".join(parts).casefold()
        if any(pattern in text for pattern in PROHIBITED_PATTERNS):
            raise GovernanceError("Cash-flow stream conflicts with Amaura anti-spam/originality/platform-safety policy")
        tokens = {token.strip(".,:;!?()[]{}\"'") for token in text.replace("-", " ").split()}
        for subject_terms, abuse_terms in PROHIBITED_CONCEPTS:
            if tokens & subject_terms and tokens & abuse_terms:
                raise GovernanceError("Cash-flow stream semantically conflicts with Amaura integrity/platform-safety policy")

    @classmethod
    def rank_opportunity(cls, opportunity: dict[str, Any], *, founder_minutes_per_week: int = 60) -> dict[str, Any]:
        lane = str(opportunity.get("product_type") or "")
        if lane not in LANE_PROFILES:
            # Original product types remain compatible and map to their closest cash-flow lane.
            lane = {
                "template": "template_pack", "game": "mobile_app",
            }.get(lane, lane)
        profile = LANE_PROFILES.get(lane, {"time_to_cash": 55, "automation": 70, "capital": 80, "margin": 78})
        base = float(opportunity.get("total_score") or 0)
        build_days = max(1, int(opportunity.get("estimated_build_days") or 14))
        speed_adjusted = max(0.0, 100.0 - (build_days - 1) * 5.5)
        time_budget = max(15, int(founder_minutes_per_week))
        attention_fit = min(100.0, 60.0 + max(0.0, (120 - time_budget) / 3.0))
        score = round(
            base * 0.32
            + float(profile["time_to_cash"]) * 0.20
            + float(profile["automation"]) * 0.15
            + float(profile["capital"]) * 0.12
            + float(profile["margin"]) * 0.11
            + speed_adjusted * 0.06
            + attention_fit * 0.04,
            1,
        )
        return {
            "opportunity_id": opportunity.get("id"),
            "title": opportunity.get("title"),
            "lane": lane,
            "cashflow_score": min(100.0, score),
            "venture_score": base,
            "estimated_build_days": build_days,
            "profile": profile,
            "why": "Rank combines evidence quality, time-to-cash, automation, capital efficiency, margin and founder-time fit.",
        }

    def _lane_learning(self, lane: str) -> dict[str, Any]:
        """Derive bounded empirical adjustments from Amaura's own completed/live streams."""
        samples: list[dict[str, Any]] = []
        for stream in self.control.store.list_venture_cashflow_streams(limit=5000):
            if str(stream.get("lane")) != lane:
                continue
            econ = self.stream_economics(str(stream["id"]))
            if econ["trusted_event_count"] == 0:
                continue
            events = self.control.store.list_venture_financial_events(str(stream["id"]), limit=5000)
            revenue_events = [e for e in events if e.get("event_type") == "revenue" and e.get("trust_level") in {"provider_verified", "founder_manual"}]
            hours_to_cash = None
            if revenue_events:
                try:
                    created = datetime.fromisoformat(str(stream["created_at"]).replace("Z", "+00:00"))
                    first = min(datetime.fromisoformat(str(e["occurred_at"]).replace("Z", "+00:00")) for e in revenue_events)
                    hours_to_cash = max(0.0, (first - created).total_seconds() / 3600.0)
                except (KeyError, ValueError):
                    hours_to_cash = None
            samples.append({"net": int(econ["net_cashflow_cents"]), "margin": float(econ["net_margin_pct"]), "hours_to_cash": hours_to_cash, "founder_minutes": int(stream.get("founder_minutes_per_week") or 0)})
        if not samples:
            return {"sample_count": 0, "weight": 0.0, "outcome_score": 50.0}
        profitable = sum(1 for row in samples if row["net"] > 0) / len(samples)
        margins = [max(-100.0, min(100.0, row["margin"])) for row in samples]
        avg_margin = sum(margins) / len(margins)
        cash_times = [row["hours_to_cash"] for row in samples if row["hours_to_cash"] is not None]
        cash_score = 50.0 if not cash_times else max(0.0, 100.0 - min(100.0, (sum(cash_times) / len(cash_times)) / 7.2))
        avg_minutes = sum(row["founder_minutes"] for row in samples) / len(samples)
        attention_score = max(0.0, 100.0 - min(100.0, avg_minutes / 1.8))
        outcome = max(0.0, min(100.0, profitable * 45.0 + ((avg_margin + 100.0) / 2.0) * 0.25 + cash_score * 0.20 + attention_score * 0.10))
        return {"sample_count": len(samples), "weight": min(0.35, len(samples) * 0.08), "outcome_score": round(outcome, 1), "profitable_rate": round(profitable, 3), "avg_margin_pct": round(avg_margin, 1), "avg_hours_to_first_cash": round(sum(cash_times)/len(cash_times), 1) if cash_times else None}

    def ranked_opportunities(self, *, limit: int = 20, founder_minutes_per_week: int | None = None) -> list[dict[str, Any]]:
        minutes = founder_minutes_per_week or int(os.environ.get("AMAURA_VENTURE_FOUNDER_WEEKLY_MINUTES", "60"))
        candidates = [
            item for item in self.control.store.list_venture_opportunities(limit=1000)
            if item.get("status") in {"review_required", "qualified", "selected", "experimenting"}
        ]
        ranked = [self.rank_opportunity(item, founder_minutes_per_week=minutes) for item in candidates]
        for row in ranked:
            learning = self._lane_learning(str(row["lane"]))
            weight = float(learning.get("weight") or 0.0)
            row["prior_cashflow_score"] = row["cashflow_score"]
            row["cashflow_score"] = round(float(row["cashflow_score"]) * (1.0 - weight) + float(learning["outcome_score"]) * weight, 1)
            row["learning"] = learning
        ranked.sort(key=lambda row: (float(row["cashflow_score"]), float(row["venture_score"])), reverse=True)
        return ranked[: max(1, min(int(limit), 200))]

    def create_stream(
        self,
        *,
        opportunity_id: str,
        name: str,
        lane: str,
        platform: str,
        offer: str,
        target_user: str,
        distribution_channel: str,
        price_cents: int,
        unit_cost_cents: int = 0,
        currency: str = "INR",
        founder_minutes_per_week: int = 60,
        automation_level: int = 80,
        experiment_id: str = "",
        actor: str | None = None,
    ) -> dict[str, Any]:
        actor = actor or self.control.founder_id
        if actor != self.control.founder_id:
            raise GovernanceError("Only the founder may activate a new cash-flow stream")
        opportunity = self.control.store.get_venture_opportunity(opportunity_id)
        if opportunity.get("status") not in {"review_required", "qualified", "selected", "experimenting"}:
            raise GovernanceError("Cash-flow streams require an evidence-qualified opportunity")
        self.lane_profile(lane)
        self._validate_offer_text(name, platform, offer, distribution_channel)
        if not all(str(value).strip() for value in (name, platform, offer, target_user, distribution_channel, currency)):
            raise GovernanceError("Cash-flow stream requires name, platform, offer, user, channel and currency")
        if int(price_cents) < 0 or int(unit_cost_cents) < 0:
            raise GovernanceError("Price and unit cost cannot be negative")
        if int(unit_cost_cents) > int(price_cents) and int(price_cents) > 0:
            raise GovernanceError("Unit cost exceeds selling price; revise the stream economics")
        if not 0 <= int(automation_level) <= 100:
            raise GovernanceError("automation_level must be 0-100")
        max_minutes = int(os.environ.get("AMAURA_VENTURE_MAX_FOUNDER_MINUTES_WEEKLY", "180"))
        if not 0 <= int(founder_minutes_per_week) <= max_minutes:
            raise GovernanceError(f"Founder attention exceeds configured weekly cap of {max_minutes} minutes")
        stream_payload = {
            "id": _id("vcf"),
            "opportunity_id": opportunity_id,
            "experiment_id": experiment_id.strip(),
            "name": name.strip(),
            "lane": lane,
            "platform": platform.strip(),
            "status": "validation",
            "offer": offer.strip(),
            "target_user": target_user.strip(),
            "distribution_channel": distribution_channel.strip(),
            "currency": currency.strip().upper(),
            "price_cents": int(price_cents),
            "unit_cost_cents": int(unit_cost_cents),
            "founder_minutes_per_week": int(founder_minutes_per_week),
            "automation_level": int(automation_level),
            "metadata": {"created_by": actor, "approval_required_for_publish": True, "approval_required_for_spend": True},
        }
        try:
            stream = self.control.store.create_venture_cashflow_stream_guarded(
                stream_payload, max_founder_minutes=max_minutes
            )
        except ValueError as exc:
            raise GovernanceError(str(exc)) from exc
        self.control.store.publish_event("ventures.cashflow.stream.created", stream["id"], {"lane": lane, "platform": platform})
        self.control.store.audit(actor, "create_venture_cashflow_stream", "venture_cashflow_stream", stream["id"], "allowed", {"lane": lane})
        return stream

    def set_stream_status(self, stream_id: str, *, status: str, reason: str, actor: str | None = None) -> dict[str, Any]:
        actor = actor or self.control.founder_id
        if actor != self.control.founder_id:
            raise GovernanceError("Only the founder may change cash-flow stream lifecycle state")
        if status not in STREAM_STATUSES:
            raise GovernanceError(f"Invalid cash-flow stream status: {status}")
        if not reason.strip():
            raise GovernanceError("Cash-flow lifecycle changes require a reason")
        current = self.control.store.get_venture_cashflow_stream(stream_id)
        if status == current.get("status"):
            return current
        allowed = STREAM_TRANSITIONS.get(str(current.get("status")), set())
        if status not in allowed:
            raise GovernanceError(f"Invalid cash-flow stream transition: {current.get('status')} -> {status}")
        max_live = max(1, int(os.environ.get("AMAURA_VENTURE_MAX_LIVE_STREAMS", "4")))
        max_minutes = int(os.environ.get("AMAURA_VENTURE_MAX_FOUNDER_MINUTES_WEEKLY", "180"))
        try:
            updated = self.control.store.transition_venture_cashflow_stream_guarded(
                stream_id, status=status, max_live=max_live, max_founder_minutes=max_minutes
            )
        except ValueError as exc:
            raise GovernanceError(str(exc)) from exc
        self.control.store.publish_event("ventures.cashflow.stream.status", stream_id, {"status": status, "reason": reason})
        self.control.store.audit(actor, "set_venture_cashflow_status", "venture_cashflow_stream", stream_id, "allowed", {"status": status, "reason": reason})
        return updated

    def record_financial_event(
        self,
        stream_id: str,
        *,
        event_type: str,
        amount_cents: int,
        source: str,
        evidence: list[dict[str, Any]],
        currency: str = "",
        occurred_at: str | None = None,
        metadata: dict[str, Any] | None = None,
        actor: str = "jarvis",
    ) -> dict[str, Any]:
        if actor not in {"jarvis", self.control.founder_id}:
            raise GovernanceError("Only JARVIS or the founder may record venture financial evidence")
        if event_type not in FINANCIAL_EVENT_TYPES:
            raise GovernanceError(f"Unsupported financial event type: {event_type}")
        stream = self.control.store.get_venture_cashflow_stream(stream_id)
        if int(amount_cents) <= 0:
            raise GovernanceError("Financial event amount must be greater than zero")
        if not source.strip() or not evidence:
            raise GovernanceError("Financial events require a source and evidence")
        normalized_evidence: list[dict[str, Any]] = []
        provider = ""
        external_event_id = ""
        provider_verified = False
        founder_manual = False
        for item in evidence:
            if not isinstance(item, dict):
                raise GovernanceError("Each financial evidence item must be an object")
            normalized = dict(item)
            provider_receipt = item.get("provider_receipt")
            if isinstance(provider_receipt, dict):
                from jarvis.amaura.integrations import ProviderReceipt
                receipt = ProviderReceipt.from_dict(provider_receipt)
                if not receipt.verify():
                    raise GovernanceError("Financial provider receipt signature is invalid")
                if receipt.status.strip().lower() not in PROVIDER_FINANCIAL_SUCCESS_STATUSES:
                    raise GovernanceError(f"Financial provider receipt is not a successful/confirmed outcome: {receipt.status}")
                provider_payload = item.get("provider_payload")
                if not isinstance(provider_payload, dict):
                    raise GovernanceError("Financial provider receipt requires the exact provider_payload it authenticates")
                payload_sha256 = hashlib.sha256(json.dumps(
                    provider_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
                ).encode()).hexdigest()
                if payload_sha256 != receipt.payload_sha256:
                    raise GovernanceError("Financial provider receipt does not authenticate the supplied provider payload")
                if int(provider_payload.get("amount_cents") or 0) != int(amount_cents):
                    raise GovernanceError("Provider financial amount does not match the ledger event")
                if str(provider_payload.get("event_type") or "") != event_type:
                    raise GovernanceError("Provider financial event type does not match the ledger event")
                declared_currency = str(provider_payload.get("currency") or currency or stream.get("currency") or "INR").upper()
                if declared_currency != str(currency or stream.get("currency") or "INR").upper():
                    raise GovernanceError("Provider financial currency does not match the ledger event")
                provider_verified = True
                provider = receipt.provider
                external_event_id = receipt.external_id
                normalized["provider_receipt"] = receipt.to_dict()
                normalized["provider_payload"] = provider_payload
                normalized["trust"] = "provider_verified"
            reference = str(item.get("reference") or "").strip()
            if reference:
                # EvidenceVault authenticates that Amaura stored these exact bytes and
                # provenance metadata.  It does *not* authenticate a payment/revenue
                # provider: any ordinary internal caller can create evidence with an
                # arbitrary source label.  Therefore a vault reference may support a
                # financial event, but it can never elevate that event to
                # provider_verified on its own.  That trust class requires the separate
                # ProviderReceipt credential above.
                verification = self.control.evidence.verify(reference)
                if not verification.get("ok"):
                    raise GovernanceError("Financial evidence reference failed EvidenceVault verification")
                normalized["evidence_vault_verified"] = True
            if actor == self.control.founder_id and item.get("founder_attestation") is True:
                founder_manual = True
                normalized["trust"] = "founder_manual"
            normalized_evidence.append(normalized)

        if provider_verified:
            if not provider.strip() or not external_event_id.strip():
                raise GovernanceError("Provider-verified financial evidence requires provider and external event identity")
            trust_level = "provider_verified"
        elif actor == self.control.founder_id and founder_manual:
            trust_level = "founder_manual"
        else:
            raise GovernanceError(
                "Automated financial events require an authenticated provider receipt or signed provider evidence; "
                "manual transactions must be explicitly founder-certified"
            )

        event_currency = (currency or stream.get("currency") or "INR").upper()
        if event_currency != str(stream.get("currency") or "INR").upper():
            raise GovernanceError("A cash-flow stream may not mix currencies without an explicit conversion stream")
        manual_event_id = ""
        if trust_level == "founder_manual":
            for item in normalized_evidence:
                if item.get("founder_attestation") is True and str(item.get("manual_event_id") or "").strip():
                    manual_event_id = str(item["manual_event_id"]).strip()
                    break
            if not manual_event_id:
                raise GovernanceError("Founder-certified financial events require a stable manual_event_id (for example a bank/order/statement reference)")
        if trust_level == "provider_verified" and external_event_id:
            idem_payload = {
                "stream_id": stream_id, "event_type": event_type, "provider": provider,
                "external_event_id": external_event_id,
            }
        elif trust_level == "founder_manual":
            idem_payload = {
                "stream_id": stream_id, "event_type": event_type, "manual_event_id": manual_event_id,
            }
        else:
            idem_payload = {
                "stream_id": stream_id, "event_type": event_type, "amount_cents": int(amount_cents),
                "currency": event_currency, "source": source.strip(), "evidence": normalized_evidence,
                "trust_level": trust_level,
            }
        idempotency_key = hashlib.sha256(json.dumps(idem_payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        row = self.control.store.record_venture_financial_event({
            "id": _id("vfin"),
            "stream_id": stream_id,
            "event_type": event_type,
            "amount_cents": int(amount_cents),
            "currency": event_currency,
            "source": source.strip(),
            "evidence": normalized_evidence,
            "trust_level": trust_level,
            "provider": provider,
            "external_event_id": external_event_id,
            "idempotency_key": idempotency_key,
            "occurred_at": occurred_at or _now(),
            "metadata": metadata or {},
        })
        if trust_level in {"provider_verified", "founder_manual"}:
            if int(row["amount_cents"]) != int(amount_cents) or str(row["currency"]) != event_currency or str(row["event_type"]) != event_type:
                label = "Provider" if trust_level == "provider_verified" else "Founder-manual"
                raise GovernanceError(f"{label} event was already recorded with conflicting financial values")
        self.control.store.publish_event("ventures.cashflow.financial", stream_id, {"event_type": event_type, "amount_cents": amount_cents})
        return {"event": row, "stream": stream, "economics": self.stream_economics(stream_id)}

    def stream_economics(self, stream_id: str) -> dict[str, Any]:
        stream = self.control.store.get_venture_cashflow_stream(stream_id)
        events = self.control.store.list_venture_financial_events(stream_id, limit=5000)
        trusted = [row for row in events if row.get("trust_level") in {"provider_verified", "founder_manual"}]
        provider_events = [row for row in trusted if row.get("trust_level") == "provider_verified"]
        manual_events = [row for row in trusted if row.get("trust_level") == "founder_manual"]
        def total(rows: list[dict[str, Any]], event_type: str) -> int:
            return sum(int(row["amount_cents"]) for row in rows if row["event_type"] == event_type)
        def units(row: dict[str, Any]) -> int:
            if row.get("trust_level") == "provider_verified":
                for evidence in row.get("evidence") or []:
                    payload = evidence.get("provider_payload") if isinstance(evidence, dict) else None
                    if isinstance(payload, dict) and payload.get("units") is not None:
                        try:
                            return max(0, int(payload["units"]))
                        except (TypeError, ValueError):
                            return 0
            if row.get("trust_level") == "founder_manual":
                try:
                    return max(0, int((row.get("metadata") or {}).get("units") or 0))
                except (TypeError, ValueError):
                    return 0
            return 0
        revenue = total(trusted, "revenue")
        provider_revenue = total(provider_events, "revenue")
        manual_revenue = total(manual_events, "revenue")
        refunds = total(trusted, "refund")
        fees = total(trusted, "fee")
        cogs = total(trusted, "cogs")
        marketing = total(trusted, "marketing")
        taxes = total(trusted, "tax")
        operating_costs = total(trusted, "cost")
        payouts = total(trusted, "payout")
        units_sold = sum(units(row) for row in trusted if row.get("event_type") == "revenue")
        units_refunded = sum(units(row) for row in trusted if row.get("event_type") == "refund")
        gross_profit = revenue - refunds - cogs
        contribution_profit = gross_profit - fees - marketing
        net = contribution_profit - taxes - operating_costs
        price = int(stream.get("price_cents") or 0)
        unit_cost = int(stream.get("unit_cost_cents") or 0)
        estimated_units = units_sold or (revenue // price if price > 0 else 0)
        return {
            "stream_id": stream_id, "name": stream["name"], "currency": stream["currency"],
            "gross_revenue_cents": revenue, "provider_verified_revenue_cents": provider_revenue,
            "founder_certified_revenue_cents": manual_revenue, "refunds_cents": refunds,
            "cogs_cents": cogs, "gross_profit_cents": gross_profit, "fees_cents": fees,
            "marketing_cents": marketing, "contribution_profit_cents": contribution_profit,
            "taxes_cents": taxes, "costs_cents": operating_costs, "net_cashflow_cents": net,
            "payouts_cents": payouts, "units_sold": units_sold, "units_refunded": units_refunded,
            "estimated_units_sold": estimated_units,
            "customer_acquisition_cost_cents": round(marketing / estimated_units) if marketing and estimated_units else 0,
            "event_count": len(events), "trusted_event_count": len(trusted), "unverified_event_count": len(events) - len(trusted),
            "gross_margin_pct": round((gross_profit / revenue) * 100.0, 1) if revenue else 0.0,
            "contribution_margin_pct": round((contribution_profit / revenue) * 100.0, 1) if revenue else 0.0,
            "net_margin_pct": round((net / revenue) * 100.0, 1) if revenue else 0.0,
            "estimated_unit_margin_cents": max(0, price - unit_cost),
            "estimated_unit_margin_pct": round(((price - unit_cost) / price) * 100.0, 1) if price else 0.0,
        }

    def portfolio(self) -> dict[str, Any]:
        streams = self.control.store.list_venture_cashflow_streams(limit=1000)
        economics = [self.stream_economics(row["id"]) for row in streams]
        currency_groups: dict[str, dict[str, int]] = {}
        for row in economics:
            cur = row["currency"]
            bucket = currency_groups.setdefault(cur, {
                "gross_revenue_cents": 0, "provider_verified_revenue_cents": 0,
                "founder_certified_revenue_cents": 0, "net_cashflow_cents": 0, "costs_cents": 0,
                "cogs_cents": 0, "marketing_cents": 0, "taxes_cents": 0, "fees_cents": 0, "refunds_cents": 0
            })
            for key in bucket:
                bucket[key] += int(row[key])
        return {
            "streams": streams,
            "economics": economics,
            "totals_by_currency": currency_groups,
            "live_streams": sum(1 for row in streams if row["status"] == "live"),
            "founder_minutes_per_week": sum(int(row.get("founder_minutes_per_week") or 0) for row in streams if row["status"] in {"validation", "ready", "live"}),
            "ranked_opportunities": self.ranked_opportunities(limit=10),
        }

    def propose_actions(self, *, limit: int = 12, actor: str = "jarvis") -> list[dict[str, Any]]:
        if actor not in {"jarvis", self.control.founder_id}:
            raise GovernanceError("Only JARVIS or the founder may propose venture actions")
        existing = [
            row for row in self.control.store.list_venture_cashflow_actions(limit=1000)
            if row.get("status") in {"proposed", "approved", "running", "blocked"}
        ]
        existing_keys = {(row.get("stream_id"), row.get("action_type")) for row in existing}
        streams = self.control.store.list_venture_cashflow_streams(limit=1000)
        proposals: list[dict[str, Any]] = []
        for stream in streams:
            if stream["status"] not in {"validation", "ready", "live"}:
                continue
            econ = self.stream_economics(stream["id"])
            sequence: list[tuple[str, str, bool]]
            if stream["status"] == "validation":
                sequence = [
                    ("research_demand", "Refresh demand and competitor evidence", False),
                    ("create_asset", "Prepare the smallest saleable asset or prototype", False),
                    ("distribution_draft", "Prepare one honest distribution/listing package", True),
                ]
            elif econ["gross_revenue_cents"] <= 0:
                sequence = [
                    ("conversion_review", "Diagnose why the live stream has not produced evidenced revenue", False),
                    ("listing_optimization", "Prepare one evidence-backed offer/listing improvement", True),
                ]
            else:
                sequence = [
                    ("retention_review", "Reconcile repeat use/refunds/support and identify the strongest retention lever", False),
                    ("pricing_review", "Prepare a pricing/packaging recommendation from actual economics", True),
                    ("seo_content", "Prepare one durable organic distribution asset", True),
                ]
            for action_type, title, approval in sequence:
                key = (stream["id"], action_type)
                if key in existing_keys:
                    continue
                try:
                    action = self.control.store.create_venture_cashflow_action({
                        "id": _id("vact"),
                        "stream_id": stream["id"],
                        "action_type": action_type,
                        "title": title,
                        "status": "proposed",
                        "priority": 2 if action_type in {"conversion_review", "research_demand"} else 3,
                        "requires_founder_approval": bool(approval),
                        "payload": {"lane": stream["lane"], "platform": stream["platform"], "offer": stream["offer"], "distribution_channel": stream["distribution_channel"]},
                        "payload_hash": "",
                        "result": {},
                        "due_at": "",
                    })
                except sqlite3.IntegrityError:
                    # A concurrent MissionRunner/tick won the active-action slot.
                    existing_keys.add(key)
                    continue
                proposals.append(action)
                existing_keys.add(key)
                if len(proposals) >= limit:
                    return proposals
        return proposals


    @staticmethod
    def _action_approval_payload(action: dict[str, Any], stream: dict[str, Any]) -> dict[str, Any]:
        return {
            "action_id": action["id"], "stream_id": action.get("stream_id", ""),
            "action_type": action["action_type"], "title": action["title"],
            "payload": dict(action.get("payload") or {}),
            "stream": {"name": stream.get("name"), "lane": stream.get("lane"), "platform": stream.get("platform")},
        }

    def _ensure_action_approval(self, action: dict[str, Any]) -> dict[str, Any]:
        if not action.get("requires_founder_approval"):
            return action
        stream = self.control.store.get_venture_cashflow_stream(str(action["stream_id"]))
        canonical = self._action_approval_payload(action, stream)
        payload_hash = self.control.store.canonical_hash(canonical)
        existing_hash = str(action.get("payload_hash") or "")
        if existing_hash and existing_hash != payload_hash:
            raise GovernanceError("Venture action payload changed after approval was requested; create a fresh action")
        approval_id = str(action.get("approval_id") or "")
        if approval_id:
            self.control.store.get_approval(approval_id)
            return self.control.store.update_venture_cashflow_action(action["id"], payload_hash=payload_hash)
        task_id = _id("vactgate")
        gate = self.control.store.insert_work_item({
            "id": task_id, "item_type": "task", "title": f"Approve Ventures action: {action['title']}",
            "description": "Canonical founder authority gate for one Amaura Ventures cash-flow action.",
            "owner_id": "venture_director", "reviewer_id": "jarvis",
            "state": TaskState.AWAITING_APPROVAL.value, "priority": int(action.get("priority") or 3),
            "risk": "high", "action_type": "venture_cashflow_action",
            "success_metric": "Founder decision is bound to the immutable action payload",
            "acceptance_criteria": ["Approval payload hash matches exact Ventures action"],
            "evidence": [], "summary": json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str),
            "metadata": {"cashflow_action_id": action["id"], "cashflow_payload_hash": payload_hash},
        })
        approval = self.control._request_approval(gate, requested_by="jarvis")
        return self.control.store.update_venture_cashflow_action(
            action["id"], payload_hash=payload_hash, approval_id=approval["id"], approval_task_id=task_id
        )

    def _sync_canonical_approval(self, action: dict[str, Any]) -> dict[str, Any]:
        """Mirror the authoritative Company OS approval state into the Ventures action."""
        if not action.get("requires_founder_approval"):
            return action
        action = self._ensure_action_approval(action)
        approval = self.control.store.get_approval(str(action["approval_id"]))
        approval_status = str(approval.get("status") or "pending")
        current = str(action.get("status") or "proposed")
        if approval_status == "approved" and current == "proposed":
            action = self.control.store.update_venture_cashflow_action(
                action["id"], status="approved", result={**dict(action.get("result") or {}), "canonical_approval_synced_at": _now()}
            )
        elif approval_status in {"rejected", "changes_requested", "expired"} and current in {"proposed", "approved"}:
            target = "cancelled" if approval_status == "rejected" else "blocked"
            action = self.control.store.update_venture_cashflow_action(
                action["id"], status=target, result={**dict(action.get("result") or {}), "canonical_approval_status": approval_status, "canonical_approval_synced_at": _now()}
            )
        return action

    def _approval_is_valid(self, action: dict[str, Any]) -> bool:
        if not action.get("requires_founder_approval"):
            return True
        action = self._ensure_action_approval(action)
        stream = self.control.store.get_venture_cashflow_stream(str(action["stream_id"]))
        expected = self.control.store.canonical_hash(self._action_approval_payload(action, stream))
        if expected != str(action.get("payload_hash") or ""):
            return False
        approval = self.control.store.get_approval(str(action["approval_id"]))
        return approval.get("status") == "approved"

    def _launch_action_mission(self, action: dict[str, Any]) -> dict[str, Any]:
        action = self.control.store.get_venture_cashflow_action(str(action["id"]))
        if action.get("mission_id"):
            return action
        if action.get("requires_founder_approval") and not self._approval_is_valid(action):
            return action
        from jarvis.amaura.brain import GoalRequest, JarvisBrain
        stream = self.control.store.get_venture_cashflow_stream(str(action["stream_id"]))
        objective = (
            f"Amaura Ventures action for '{stream['name']}': {action['title']}. "
            f"Action type: {action['action_type']}. Execute the exact reversible/internal work represented by this action payload. "
            "Produce evidence and a founder-ready result. Do not publish externally, spend money, create or modify accounts, "
            "contact people, deploy, or change live pricing unless a separate governed Company OS approval explicitly authorizes that consequence."
        )
        request = GoalRequest(
            objective=objective,
            success_criteria=[
                "The requested Ventures action is completed with durable evidence",
                "No authority beyond the action payload or Company OS policy is exercised",
                "The result contains a concrete next recommendation for the stream",
            ],
            autonomy="execute", priority=int(action.get("priority") or 3), max_replans=2,
            title=f"Ventures — {action['title']}", metadata={"cashflow_action_id": action["id"], "cashflow_stream_id": stream["id"]},
        )
        submitted = JarvisBrain(self.control).submit(
            request, external_context=json.dumps({"cashflow_action": action, "cashflow_stream": stream}, default=str)
        )
        goal_id = str(submitted["goal"]["id"])
        result = dict(action.get("result") or {})
        result.update({"mission_id": goal_id, "mission_state": submitted.get("state", "queued"), "mission_linked_at": _now()})
        updated = self.control.store.update_venture_cashflow_action(action["id"], status="running", mission_id=goal_id, result=result)
        self.control.store.publish_event("ventures.cashflow.action.mission_linked", action["id"], {"mission_id": goal_id})
        return updated

    def sync_action_missions(self) -> list[dict[str, Any]]:
        from jarvis.amaura.brain import JarvisBrain
        brain = JarvisBrain(self.control)
        changed: list[dict[str, Any]] = []
        for action in self.control.store.list_venture_cashflow_actions(limit=2000):
            mission_id = str(action.get("mission_id") or "")
            if not mission_id or action.get("status") in {"completed", "cancelled"}:
                continue
            try:
                status = brain.status(mission_id)
            except KeyError:
                result = dict(action.get("result") or {})
                result.update({"mission_state": "missing", "mission_error": "linked mission not found"})
                changed.append(self.control.store.update_venture_cashflow_action(action["id"], status="failed", result=result))
                continue
            state = str(status.get("state") or "")
            result = dict(action.get("result") or {})
            result["mission_state"] = state
            result["mission_checked_at"] = _now()
            if state == "completed":
                task_results = [
                    {"task_id": t["id"], "summary": t.get("summary", ""), "evidence": t.get("evidence", [])}
                    for t in status.get("tasks", []) if t.get("state") == TaskState.COMPLETED.value
                ]
                result["mission_results"] = task_results
                changed.append(self.control.store.update_venture_cashflow_action(action["id"], status="completed", result=result))
                self.control.store.publish_event("ventures.cashflow.action.completed", action["id"], {"mission_id": mission_id})
            elif state in {"failed", "cancelled"}:
                result["mission_error"] = f"Mission ended in {state}"
                changed.append(self.control.store.update_venture_cashflow_action(action["id"], status="failed", result=result))
            else:
                changed.append(self.control.store.update_venture_cashflow_action(action["id"], status="running", result=result))
        return changed

    def set_action_status(
        self, action_id: str, *, status: str, reason: str, result: dict[str, Any] | None = None, actor: str = "jarvis"
    ) -> dict[str, Any]:
        if status not in ACTION_STATUSES:
            raise GovernanceError(f"Invalid cash-flow action status: {status}")
        if not reason.strip():
            raise GovernanceError("Cash-flow action changes require a reason")
        action = self.control.store.get_venture_cashflow_action(action_id)
        current_status = str(action.get("status") or "proposed")
        if current_status in {"completed", "cancelled"}:
            raise GovernanceError(f"Cash-flow action is terminal: {current_status}")
        if actor not in {"jarvis", self.control.founder_id}:
            raise GovernanceError("Only JARVIS or the founder may update cash-flow actions")

        if status == "approved":
            if actor != self.control.founder_id:
                raise GovernanceError("Founder authority is required to approve a cash-flow action")
            action = self._ensure_action_approval(action)
            if not action.get("requires_founder_approval"):
                raise GovernanceError("This cash-flow action does not require founder approval")
            stream = self.control.store.get_venture_cashflow_stream(str(action["stream_id"]))
            if self.control.store.canonical_hash(self._action_approval_payload(action, stream)) != str(action.get("payload_hash") or ""):
                raise GovernanceError("Cash-flow action payload changed after approval was requested")
            approval = self.control.store.get_approval(str(action["approval_id"]))
            if approval.get("status") == "pending":
                self.control.decide_approval(str(action["approval_id"]), self.control.founder_id, "approved", reason.strip())
            elif approval.get("status") != "approved":
                raise GovernanceError(f"Canonical approval is already {approval.get('status')}")
            approved_action = self.control.store.update_venture_cashflow_action(
                action_id, status="approved",
                result={**dict(action.get("result") or {}), "status_reason": reason.strip(), "status_actor": actor, "status_at": _now()},
            )
            # Founder approval immediately closes the action→mission gap: the
            # durable mission is queued now rather than waiting for another UI click.
            return self._launch_action_mission(approved_action)

        if status == "cancelled":
            if actor != self.control.founder_id:
                raise GovernanceError("Founder authority is required to cancel a cash-flow action")
            if action.get("requires_founder_approval"):
                action = self._ensure_action_approval(action)
                approval = self.control.store.get_approval(str(action["approval_id"]))
                if approval.get("status") == "pending":
                    self.control.decide_approval(str(action["approval_id"]), self.control.founder_id, "rejected", reason.strip())
            mission_id = str(action.get("mission_id") or "")
            if mission_id:
                from jarvis.amaura.brain import JarvisBrain
                JarvisBrain(self.control).cancel(mission_id, actor=self.control.founder_id, reason=reason.strip())
            return self.control.store.update_venture_cashflow_action(action_id, status="cancelled", result={**dict(action.get("result") or {}), "status_reason": reason.strip(), "status_actor": actor, "status_at": _now()})

        if current_status == "failed" and status == "proposed":
            # A failed mission is immutable history.  Retrying the Ventures action
            # must create a *new* durable mission; otherwise the old mission_id
            # causes _launch_action_mission() to no-op forever.  Keep the old
            # mission trace in result for auditability and bound retries so a
            # poison action cannot churn indefinitely.
            previous = dict(action.get("result") or {})
            retry_count = int(previous.get("retry_count") or 0)
            max_retries = max(0, min(int(os.environ.get("AMAURA_VENTURE_ACTION_MAX_RETRIES", "2")), 10))
            if retry_count >= max_retries:
                raise GovernanceError(f"Cash-flow action retry limit reached ({max_retries})")
            mission_id = str(action.get("mission_id") or "")
            history = list(previous.get("mission_history") or [])
            if mission_id:
                history.append({
                    "mission_id": mission_id,
                    "state": str(previous.get("mission_state") or "failed"),
                    "archived_at": _now(),
                })
            previous.update({
                "mission_history": history,
                "retry_count": retry_count + 1,
                "retry_reason": reason.strip(),
                "retry_requested_at": _now(),
            })
            previous.pop("mission_id", None)
            previous.pop("mission_state", None)
            previous.pop("mission_error", None)
            return self.control.store.update_venture_cashflow_action(
                action_id, status="proposed", mission_id="", result=previous
            )

        allowed_transitions = {
            "proposed": {"running"}, "approved": {"running"},
            "running": {"completed", "blocked", "failed"},
            "blocked": {"running", "failed"},
        }
        if status not in allowed_transitions.get(current_status, set()):
            raise GovernanceError(f"Invalid cash-flow action transition: {current_status} -> {status}")
        if status == "running":
            if action.get("requires_founder_approval") and not self._approval_is_valid(action):
                raise GovernanceError("Canonical founder approval is required before this cash-flow action can execute")
            return self._launch_action_mission(action)
        if status == "completed" and action.get("mission_id"):
            from jarvis.amaura.brain import JarvisBrain
            if JarvisBrain(self.control).status(str(action["mission_id"])).get("state") != "completed":
                raise GovernanceError("A mission-linked cash-flow action cannot complete before its JARVIS mission")
        payload = dict(action.get("result") or {})
        if result:
            payload.update(result)
        payload.update({"status_reason": reason.strip(), "status_actor": actor, "status_at": _now()})
        return self.control.store.update_venture_cashflow_action(action_id, status=status, result=payload)

    def tick(self, *, actor: str = "jarvis", proposal_limit: int = 8, auto_execute: bool = True) -> dict[str, Any]:
        if actor not in {"jarvis", self.control.founder_id}:
            raise GovernanceError("Only JARVIS or the founder may run a cash-flow portfolio tick")
        synchronized = self.sync_action_missions()
        proposals = self.propose_actions(limit=proposal_limit, actor=actor)
        approval_requests: list[dict[str, Any]] = []
        launched: list[dict[str, Any]] = []
        seen_actions: set[str] = set()
        for action in [*proposals, *self.control.store.list_venture_cashflow_actions(limit=1000)]:
            action_id = str(action.get("id") or "")
            if not action_id or action_id in seen_actions:
                continue
            seen_actions.add(action_id)
            try:
                if action.get("requires_founder_approval"):
                    prepared = self._sync_canonical_approval(action)
                    if prepared.get("status") in {"proposed", "blocked"}:
                        approval_requests.append({"action_id": prepared["id"], "approval_id": prepared.get("approval_id"), "payload_hash": prepared.get("payload_hash")})
                        continue
                    action = prepared
                if action.get("status") not in {"proposed", "approved"}:
                    continue
                if auto_execute:
                    launched.append(self._launch_action_mission(action))
            except GovernanceError as exc:
                current = self.control.store.get_venture_cashflow_action(str(action["id"]))
                failure = {**dict(current.get("result") or {}), "dispatch_error": str(exc), "dispatch_error_at": _now()}
                self.control.store.update_venture_cashflow_action(str(action["id"]), result=failure)
        return {
            "generated_at": _now(), "proposals_created": proposals, "missions_synchronized": synchronized,
            "approval_requests": approval_requests, "missions_launched": launched,
            "portfolio": self.portfolio(), "action_queue": self.next_actions(limit=30),
        }

    def next_actions(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.control.store.list_venture_cashflow_actions(limit=1000)
        order = {"approved": 0, "proposed": 1, "running": 2, "blocked": 3, "failed": 4, "completed": 5, "cancelled": 6}
        rows.sort(key=lambda r: (order.get(r["status"], 9), int(r.get("priority") or 5), str(r.get("created_at") or "")))
        return rows[: max(1, min(int(limit), 200))]

    def dashboard(self) -> dict[str, Any]:
        portfolio = self.portfolio()
        return {
            "branch": "Amaura Ventures Cashflow",
            "mission": "Build a small evidence-backed portfolio of owned, low-capital revenue streams while protecting founder study time.",
            "lanes": [self.lane_profile(key) for key in LANE_PROFILES],
            "rules": {
                "income_not_guaranteed": True,
                "founder_approval_for_publish_spend_accounts_pricing": True,
                "original_work_only": True,
                "no_fake_reviews_or_spam": True,
                "max_live_streams": int(os.environ.get("AMAURA_VENTURE_MAX_LIVE_STREAMS", "4")),
                "max_founder_minutes_weekly": int(os.environ.get("AMAURA_VENTURE_MAX_FOUNDER_MINUTES_WEEKLY", "180")),
            },
            "portfolio": portfolio,
            "action_queue": self.next_actions(limit=20),
        }


__all__ = [
    "CashflowEngine", "CashflowLane", "LANE_PROFILES", "STREAM_STATUSES",
    "FINANCIAL_EVENT_TYPES", "ACTION_STATUSES", "ACTION_TYPES",
]
