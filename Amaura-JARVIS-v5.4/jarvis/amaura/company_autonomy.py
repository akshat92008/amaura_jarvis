"""Company-wide autonomy for Amaura Labs.

This module turns the governed kernel into a practical company operating loop. It
bootstraps recurring objectives for every core department, accepts durable signals
from product/content/engineering systems, converts those signals into bounded
workflows, and applies company-level budget and circuit-breaker controls.

It deliberately does not grant agents new authority. External messages,
publishing, releases, payments, legal commitments, strategy changes and product
investment remain approval-gated by the control plane.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.mission_control import MissionControl
from jarvis.amaura.models import GovernanceError
from jarvis.amaura.workflows import WORKFLOWS, get_workflow

SIGNAL_SEVERITIES = {"low", "medium", "high", "critical"}
SIGNAL_TYPES = {
    "security_incident",
    "build_failure",
    "customer_feedback",
    "content_underperformance",
    "runway_risk",
    "research_opportunity",
    "community_request",
    "release_ready",
    "revenue_signal",
    "venture_opportunity",
}


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _week_key(now: datetime) -> str:
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


class CompanyAutonomyEngine:
    """Founder-controlled company bootstrap, signals, budgets and safety circuits."""

    def __init__(
        self,
        control: AmauraControlPlane,
        *,
        worker_id: str = "amaura-company-autonomy",
    ):
        self.control = control
        self.worker_id = worker_id
        self.mission = MissionControl(control)

    @staticmethod
    def objective_definitions(
        *,
        repository_path: str,
        product_name: str = "Amaura Labs",
        audience: str = "AI builders, students, developers, researchers and founders",
        target_user: str = "Indian developers, students, researchers and resource-constrained teams",
    ) -> list[dict[str, Any]]:
        repository = str(Path(repository_path).expanduser().resolve())
        return [
            {
                "title": "Amaura research intelligence",
                "objective": "Map the most important affordable-AI and agentic-system developments for {cadence_key}",
                "success_metric": "Founder receives an evidence-backed research direction decision",
                "workflow_key": "research_intelligence_cycle",
                "cadence": "weekly",
                "inputs": {
                    "research_theme": "Affordable AI, efficient models, autonomous agents and India-first AI infrastructure"
                },
                "priority": 2,
                "target_value": 52,
                "unit": "research direction decisions",
                "max_active_programmes": 1,
            },
            {
                "title": "Amaura product opportunity validation",
                "objective": "Validate one high-leverage AI product problem for {month}",
                "success_metric": "An evidence-backed build, test or kill decision is ready",
                "workflow_key": "product_discovery",
                "cadence": "monthly",
                "inputs": {
                    "problem_space": "Affordable AI, developer productivity and AI-native company workflows",
                    "target_user": target_user,
                },
                "priority": 2,
                "target_value": 12,
                "unit": "validated product decisions",
                "max_active_programmes": 1,
            },
            {
                "title": "Amaura engineering reliability",
                "objective": "Complete one bounded reliability improvement for {cadence_key}",
                "success_metric": "Independent verification passes and a release decision is ready",
                "workflow_key": "engineering_reliability_cycle",
                "cadence": "weekly",
                "inputs": {"repository_path": repository},
                "priority": 1,
                "target_value": 52,
                "unit": "verified reliability improvements",
                "max_active_programmes": 1,
            },
            {
                "title": "Amaura owned content engine",
                "objective": "Produce the Amaura build-in-public content package for {cadence_key}",
                "success_metric": "One evidence-backed long-form asset and reusable short-form package reaches founder approval",
                "workflow_key": "content_factory",
                "cadence": "weekly",
                "inputs": {
                    "campaign_id": "amaura-owned-distribution",
                    "audience": audience,
                    "business_objective": "Grow an owned audience for Amaura Labs and its products",
                    "content_theme": "Build Amaura Labs in public — {cadence_key}",
                },
                "priority": 1,
                "target_value": 52,
                "unit": "approved content packages",
                "max_active_programmes": 1,
            },
            {
                "title": "Amaura distribution learning",
                "objective": "Run one measured distribution experiment for {cadence_key}",
                "success_metric": "A channel bottleneck is diagnosed and one exact experiment reaches founder approval",
                "workflow_key": "distribution_optimization_cycle",
                "cadence": "weekly",
                "inputs": {"channel": "YouTube, Shorts, GitHub, X and LinkedIn", "audience": audience},
                "priority": 1,
                "target_value": 52,
                "unit": "measured distribution experiments",
                "max_active_programmes": 1,
            },
            {
                "title": "Amaura customer learning",
                "objective": "Convert user feedback into one measured product response for {cadence_key}",
                "success_metric": "A sourced user-problem cluster and bounded response decision is ready",
                "workflow_key": "customer_feedback_cycle",
                "cadence": "weekly",
                "inputs": {"product_name": product_name},
                "priority": 2,
                "target_value": 52,
                "unit": "customer learning cycles",
                "max_active_programmes": 1,
            },
            {
                "title": "Amaura community flywheel",
                "objective": "Deliver one useful community intervention for {cadence_key}",
                "success_metric": "One sourced community need is converted into an approved response or contributor package",
                "workflow_key": "community_growth_cycle",
                "cadence": "weekly",
                "inputs": {"community_name": "Amaura AI Community", "audience": audience},
                "priority": 3,
                "target_value": 52,
                "unit": "community value interventions",
                "max_active_programmes": 1,
            },
            {
                "title": "Amaura product-led revenue",
                "objective": "Run one evidence-led monetisation review for {month}",
                "success_metric": "One bounded pricing, packaging or activation decision is ready",
                "workflow_key": "product_revenue_cycle",
                "cadence": "monthly",
                "inputs": {"product_name": product_name, "target_user": target_user},
                "priority": 3,
                "target_value": 12,
                "unit": "monetisation decisions",
                "max_active_programmes": 1,
            },
            {
                "title": "Amaura Ventures opportunity pipeline",
                "objective": "Find and score one focused revenue-product opportunity for {cadence_key}",
                "success_metric": "One evidence-backed opportunity is rejected or reaches founder validation approval",
                "workflow_key": "venture_opportunity_cycle",
                "cadence": "weekly",
                "inputs": {
                    "venture_theme": "Small products that can fund Amaura Labs without becoming client services",
                    "founder_time_budget_minutes": "20",
                },
                "priority": 2,
                "target_value": 52,
                "unit": "venture opportunity decisions",
                "max_active_programmes": 1,
            },
            {
                "title": "Amaura Ventures cash-flow engine",
                "objective": "Reconcile, rank and advance the highest-leverage low-capital revenue stream for {cadence_key}",
                "success_metric": "One source-backed cash-flow action reaches completion or an exact founder approval decision",
                "workflow_key": "venture_cashflow_cycle",
                "cadence": "weekly",
                "inputs": {"review_window": "{cadence_key}"},
                "priority": 1,
                "target_value": 52,
                "unit": "cash-flow portfolio cycles",
                "max_active_programmes": 1,
            },
            {
                "title": "Amaura Ventures portfolio discipline",
                "objective": "Review every active venture and enforce kill, iterate or double-down discipline for {month}",
                "success_metric": "Every active venture has sourced metrics, a current recommendation and a founder decision where required",
                "workflow_key": "venture_portfolio_review",
                "cadence": "monthly",
                "inputs": {"review_window": "{month}"},
                "priority": 2,
                "target_value": 12,
                "unit": "venture portfolio reviews",
                "max_active_programmes": 1,
            },
            {
                "title": "Amaura finance and runway control",
                "objective": "Reconcile cost, runway and free-first resource allocation for {month}",
                "success_metric": "Founder receives a reconciled runway and resource-allocation decision",
                "workflow_key": "financial_control_cycle",
                "cadence": "monthly",
                "inputs": {"review_window": "{month}"},
                "priority": 2,
                "target_value": 12,
                "unit": "financial control reviews",
                "max_active_programmes": 1,
            },
            {
                "title": "Amaura security and compliance watch",
                "objective": "Review security, licences, privacy and public claims for {cadence_key}",
                "success_metric": "All critical risks are classified and owned remediation is recorded",
                "workflow_key": "security_watch_cycle",
                "cadence": "weekly",
                "inputs": {"review_window": "{cadence_key}"},
                "priority": 1,
                "target_value": 52,
                "unit": "security reviews",
                "max_active_programmes": 1,
            },
            {
                "title": "Amaura open-source release readiness",
                "objective": "Prepare one verified open-source release decision for {month}",
                "success_metric": "A clean release candidate with exact artefact hashes reaches founder approval",
                "workflow_key": "open_source_release_cycle",
                "cadence": "monthly",
                "inputs": {"repository_path": repository, "project_name": product_name},
                "priority": 3,
                "target_value": 12,
                "unit": "verified open-source release decisions",
                "max_active_programmes": 1,
            },
            {
                "title": "Amaura operating review",
                "objective": "Run the Amaura company operating review for {week}",
                "success_metric": "Founder receives evidenced priorities, stop decisions, risks and budget implications",
                "workflow_key": "company_operating_review",
                "cadence": "weekly",
                "inputs": {"review_window": "{week}"},
                "priority": 1,
                "target_value": 52,
                "unit": "company operating reviews",
                "max_active_programmes": 1,
            },
        ]

    def bootstrap_company(
        self,
        *,
        repository_path: str,
        product_name: str = "Amaura Labs",
        audience: str = "AI builders, students, developers, researchers and founders",
        target_user: str = "Indian developers, students, researchers and resource-constrained teams",
        actor: str | None = None,
    ) -> dict[str, Any]:
        actor = actor or self.control.founder_id
        if actor != self.control.founder_id:
            raise GovernanceError("Only the founder may bootstrap the company objective portfolio")
        repository = Path(repository_path).expanduser().resolve()
        if not repository.exists() or not repository.is_dir():
            raise GovernanceError("Company repository path must be an existing directory")
        existing_titles = {item["title"]: item for item in self.control.store.list_objectives(limit=2000)}
        created: list[dict[str, Any]] = []
        existing: list[dict[str, Any]] = []
        for definition in self.objective_definitions(
            repository_path=str(repository),
            product_name=product_name,
            audience=audience,
            target_user=target_user,
        ):
            if definition["title"] in existing_titles:
                existing.append(existing_titles[definition["title"]])
                continue
            created.append(self.mission.create_objective(actor=actor, **definition))
        self.control.store.set_control("company_autonomy_bootstrapped", "1", actor)
        self.control.store.set_control("company_repository_path", str(repository), actor)
        self.control.store.publish_event(
            "company.autonomy.bootstrapped",
            "amaura",
            {"created": len(created), "existing": len(existing), "repository": str(repository)},
        )
        self.control.store.audit(
            actor,
            "bootstrap_company_autonomy",
            "company",
            "amaura",
            "allowed",
            {"created": len(created), "existing": len(existing)},
        )
        return {
            "created": created,
            "existing": existing,
            "portfolio": self.mission.portfolio(),
        }

    def ingest_signal(
        self,
        *,
        signal_type: str,
        source: str,
        severity: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
        actor: str = "jarvis",
    ) -> dict[str, Any]:
        if actor not in {"jarvis", self.control.founder_id}:
            raise GovernanceError("Only JARVIS or the founder may ingest company signals")
        if signal_type not in SIGNAL_TYPES:
            raise GovernanceError(f"Unsupported company signal: {signal_type}")
        if severity not in SIGNAL_SEVERITIES:
            raise GovernanceError(f"Signal severity must be one of: {', '.join(sorted(SIGNAL_SEVERITIES))}")
        if not source.strip():
            raise GovernanceError("Company signals require a source")
        if not payload:
            raise GovernanceError("Company signals require a non-empty payload")
        stable = {"signal_type": signal_type, "source": source, "payload": payload}
        key = idempotency_key or f"signal:{_canonical_hash(stable)}"
        signal = self.control.store.create_company_signal(
            {
                "id": _id("sig"),
                "idempotency_key": key,
                "signal_type": signal_type,
                "source": source.strip(),
                "severity": severity,
                "department": self._signal_department(signal_type),
                "payload": payload,
            }
        )
        self.control.store.publish_event(
            "company.signal.received",
            signal["id"],
            {"signal_type": signal_type, "severity": severity, "source": source},
        )
        self.control.store.audit(
            actor,
            "ingest_company_signal",
            "company_signal",
            signal["id"],
            "allowed",
            {"signal_type": signal_type, "severity": severity, "source": source},
        )
        return signal

    def detect_signals(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        """Turn internal telemetry into durable, idempotent company signals."""
        now = now or datetime.now(UTC)
        detected: list[dict[str, Any]] = []
        existing_keys = {
            str(signal["idempotency_key"]) for signal in self.control.store.list_company_signals(limit=5000)
        }

        def create_once(
            *,
            key: str,
            signal_type: str,
            source: str,
            severity: str,
            payload: dict[str, Any],
        ) -> None:
            if key in existing_keys:
                return
            signal = self.ingest_signal(
                signal_type=signal_type,
                source=source,
                severity=severity,
                payload=payload,
                idempotency_key=key,
                actor="jarvis",
            )
            existing_keys.add(key)
            detected.append(signal)

        for alert in self.control.store.list_alerts(status="open", limit=500):
            severity = "critical" if alert["severity"] == "critical" else "high"
            create_once(
                key=f"auto:alert:{alert['id']}",
                signal_type="security_incident",
                source="operational_alerts",
                severity=severity,
                payload={
                    "summary": alert["message"],
                    "alert_id": alert["id"],
                    "code": alert["code"],
                    "resource_id": alert.get("resource_id", ""),
                    "details": alert.get("details") or {},
                },
            )

        today = now.date().isoformat()
        for task in self.control.store.list_work_items(item_type="task", state="failed", limit=1000):
            if not str(task.get("updated_at") or "").startswith(today):
                continue
            workspace = (task.get("metadata") or {}).get("workspace")
            create_once(
                key=f"auto:failed-task:{task['id']}:{task.get('updated_at')}",
                signal_type="build_failure",
                source="workforce_supervisor",
                severity="high" if task.get("risk") in {"high", "critical"} else "medium",
                payload={
                    "summary": task.get("summary") or task.get("title") or "Task failed",
                    "task_id": task["id"],
                    "workflow_id": task.get("workflow_id"),
                    "repository_path": workspace or self.control.store.get_control("company_repository_path", ""),
                    "evidence": task.get("evidence") or [],
                },
            )

        min_ctr = float(os.environ.get("AMAURA_CONTENT_MIN_CTR_PERCENT", "2.0"))
        min_retention = float(os.environ.get("AMAURA_CONTENT_MIN_RETENTION_PERCENT", "25.0"))
        for entry in self.control.store.list_content_metrics(limit=2000):
            metrics = {str(key).lower(): value for key, value in (entry.get("metrics") or {}).items()}
            ctr = metrics.get("ctr", metrics.get("click_through_rate"))
            retention = metrics.get("retention", metrics.get("average_percentage_viewed"))
            normalised_ctr = None if ctr is None else float(ctr) * (100.0 if float(ctr) <= 1.0 else 1.0)
            normalised_retention = (
                None if retention is None else float(retention) * (100.0 if float(retention) <= 1.0 else 1.0)
            )
            weak_reasons: list[str] = []
            if normalised_ctr is not None and normalised_ctr < min_ctr:
                weak_reasons.append(f"CTR {normalised_ctr:.2f}% below {min_ctr:.2f}%")
            if normalised_retention is not None and normalised_retention < min_retention:
                weak_reasons.append(f"Retention {normalised_retention:.2f}% below {min_retention:.2f}%")
            if not weak_reasons:
                continue
            create_once(
                key=(
                    f"auto:content:{entry['campaign_id']}:{entry['platform']}:{entry['window']}:{entry['captured_at']}"
                ),
                signal_type="content_underperformance",
                source="content_analytics",
                severity="medium",
                payload={
                    "campaign_id": entry["campaign_id"],
                    "channel": entry["platform"],
                    "audience": "Amaura audience",
                    "window": entry["window"],
                    "captured_at": entry["captured_at"],
                    "metrics": entry.get("metrics") or {},
                    "summary": "; ".join(weak_reasons),
                },
            )

        monthly_cost_cap = max(0, int(os.environ.get("AMAURA_MONTHLY_COST_ALERT_CENTS", "0")))
        if monthly_cost_cap:
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            total = self.control.store.cost_total_since(month_start.isoformat())
            if total >= monthly_cost_cap:
                create_once(
                    key=f"auto:runway:{now.strftime('%Y-%m')}:{monthly_cost_cap}",
                    signal_type="runway_risk",
                    source="finance_ledger",
                    severity="high",
                    payload={
                        "summary": "Monthly operating cost crossed the configured alert threshold",
                        "month": now.strftime("%Y-%m"),
                        "cost_cents": total,
                        "threshold_cents": monthly_cost_cap,
                    },
                )

        return detected

    @staticmethod
    def _signal_department(signal_type: str) -> str:
        return {
            "security_incident": "security_legal",
            "build_failure": "product_engineering",
            "customer_feedback": "customer_success",
            "content_underperformance": "growth_media",
            "runway_risk": "finance",
            "research_opportunity": "product",
            "community_request": "community",
            "release_ready": "product_engineering",
            "revenue_signal": "revenue",
            "venture_opportunity": "ventures",
        }[signal_type]

    def _signal_programme(self, signal: dict[str, Any], now: datetime) -> dict[str, Any] | None:
        payload = dict(signal.get("payload") or {})
        signal_type = signal["signal_type"]
        repository = str(
            payload.get("repository_path")
            or self.control.store.get_control("company_repository_path", "")
            or os.getcwd()
        )
        mapping: dict[str, tuple[str, str, str, dict[str, Any]]] = {
            "security_incident": (
                "incident_response",
                "Respond to detected security or reliability incident",
                "Incident is contained, repaired, independently verified and ready for restoration decision",
                {
                    "incident_summary": str(
                        payload.get("summary") or payload.get("incident_summary") or "Automated security signal"
                    )
                },
            ),
            "build_failure": (
                "engineering_reliability_cycle",
                "Repair a verified build or test failure",
                "Build failure is reproduced, repaired and independently verified",
                {"repository_path": repository, "failure": payload},
            ),
            "customer_feedback": (
                "customer_feedback_cycle",
                "Convert customer feedback into product learning",
                "Feedback is clustered and a bounded product response reaches founder decision",
                {"product_name": str(payload.get("product_name") or "Amaura product"), "feedback_signal": payload},
            ),
            "content_underperformance": (
                "distribution_optimization_cycle",
                "Diagnose and improve an underperforming distribution asset",
                "One measured distribution experiment reaches founder approval",
                {
                    "channel": str(payload.get("channel") or "owned channels"),
                    "audience": str(payload.get("audience") or "Amaura audience"),
                    "performance_signal": payload,
                },
            ),
            "runway_risk": (
                "financial_control_cycle",
                "Review a detected runway or cost risk",
                "Founder receives reconciled runway scenarios and exact resource recommendations",
                {"review_window": now.strftime("%Y-%m"), "runway_signal": payload},
            ),
            "research_opportunity": (
                "product_discovery",
                "Validate a research-derived product opportunity",
                "Evidence supports a build, test or kill decision",
                {
                    "problem_space": str(payload.get("problem_space") or payload.get("summary") or "AI opportunity"),
                    "target_user": str(payload.get("target_user") or "resource-constrained AI users"),
                },
            ),
            "community_request": (
                "community_growth_cycle",
                "Respond to a recurring community need",
                "One useful community response reaches founder approval",
                {
                    "community_name": str(payload.get("community_name") or "Amaura AI Community"),
                    "audience": str(payload.get("audience") or "Amaura community"),
                    "request_signal": payload,
                },
            ),
            "release_ready": (
                "open_source_release_cycle",
                "Verify and prepare a candidate open-source release",
                "Exact release artefacts pass verification and reach founder approval",
                {
                    "repository_path": repository,
                    "project_name": str(payload.get("project_name") or "Amaura project"),
                    "release_signal": payload,
                },
            ),
            "revenue_signal": (
                "product_revenue_cycle",
                "Evaluate a product-led revenue signal",
                "A bounded monetisation decision reaches founder approval",
                {
                    "product_name": str(payload.get("product_name") or "Amaura product"),
                    "target_user": str(payload.get("target_user") or "Amaura users"),
                    "revenue_signal": payload,
                },
            ),
            "venture_opportunity": (
                "venture_opportunity_cycle",
                "Evaluate a possible Amaura Ventures product opportunity",
                "One evidence-backed opportunity is rejected or reaches founder validation approval",
                {
                    "venture_theme": str(
                        payload.get("venture_theme") or payload.get("summary") or "Focused revenue product"
                    ),
                    "founder_time_budget_minutes": str(payload.get("founder_time_budget_minutes") or "20"),
                    "opportunity_signal": payload,
                },
            ),
        }
        workflow_key, objective, metric, inputs = mapping[signal_type]
        if self.department_paused(get_workflow(workflow_key).department):
            return None
        return self.control.create_program(
            objective=objective,
            success_metric=metric,
            workflow_key=workflow_key,
            title=f"Signal response: {signal_type} — {signal['id']}",
            priority=1 if signal["severity"] in {"critical", "high"} else 2,
            inputs={**inputs, "signal_id": signal["id"], "signal_source": signal["source"]},
        )

    def _signal_budget_used_today(self, now: datetime) -> int:
        used = 0
        date_prefix = now.date().isoformat()
        for signal in self.control.store.list_company_signals(status="resolved", limit=5000):
            if not str(signal.get("resolved_at") or "").startswith(date_prefix):
                continue
            programme_id = str(signal.get("programme_id") or "")
            if not programme_id:
                continue
            try:
                programme = self.control.store.get_work_item(programme_id)
            except KeyError:
                continue
            workflow = WORKFLOWS.get(str(programme.get("workflow_id") or ""))
            if workflow:
                used += sum(step.budget_cents for step in workflow.steps)
        return used

    def process_signals(
        self,
        *,
        now: datetime | None = None,
        max_signals: int = 3,
    ) -> list[dict[str, Any]]:
        if self.control.store.get_control("autopilot_enabled", "1") != "1":
            return []
        now = now or datetime.now(UTC)
        daily_cap = max(0, int(os.environ.get("AMAURA_SIGNAL_DAILY_BUDGET_CENTS", "5000")))
        budget_used = self._signal_budget_used_today(now)
        results: list[dict[str, Any]] = []
        claimed = self.control.store.claim_company_signals(
            worker_id=self.worker_id,
            limit=max(1, min(int(max_signals), 20)),
            lease_seconds=int(os.environ.get("AMAURA_SIGNAL_LEASE_SECONDS", "300")),
        )
        for signal in claimed:
            workflow_key = {
                "security_incident": "incident_response",
                "build_failure": "engineering_reliability_cycle",
                "customer_feedback": "customer_feedback_cycle",
                "content_underperformance": "distribution_optimization_cycle",
                "runway_risk": "financial_control_cycle",
                "research_opportunity": "product_discovery",
                "community_request": "community_growth_cycle",
                "release_ready": "open_source_release_cycle",
                "revenue_signal": "product_revenue_cycle",
                "venture_opportunity": "venture_opportunity_cycle",
            }[signal["signal_type"]]
            workflow_budget = sum(step.budget_cents for step in get_workflow(workflow_key).steps)
            if daily_cap and budget_used + workflow_budget > daily_cap:
                self.control.store.release_company_signal(signal["id"], error="company signal daily budget exhausted")
                break
            try:
                programme = self._signal_programme(signal, now)
                if programme is None:
                    self.control.store.release_company_signal(
                        signal["id"], error="department circuit breaker is paused"
                    )
                    continue
                completed = self.control.store.complete_company_signal(
                    signal["id"], programme_id=programme["programme"]["id"]
                )
                budget_used += workflow_budget
                results.append({"signal": completed, "programme": programme})
                self.control.store.publish_event(
                    "company.signal.programme_created",
                    signal["id"],
                    {"programme_id": programme["programme"]["id"], "workflow": workflow_key},
                )
            except Exception as exc:
                self.control.store.release_company_signal(signal["id"], error=str(exc)[:1000])
        return results

    def department_paused(self, department: str) -> bool:
        return self.control.store.get_control(f"autonomy.department.{department}", "enabled") != "enabled"

    def set_department(
        self,
        department: str,
        *,
        enabled: bool,
        reason: str,
        actor: str | None = None,
    ) -> dict[str, Any]:
        actor = actor or self.control.founder_id
        if actor != self.control.founder_id:
            raise GovernanceError("Only the founder may resume or manually pause a department")
        if not reason.strip():
            raise GovernanceError("Department state changes require a reason")
        known = {workflow.department for workflow in WORKFLOWS.values()}
        if department not in known:
            raise GovernanceError(f"Unknown company department: {department}")
        value = "enabled" if enabled else "paused"
        self.control.store.set_control(f"autonomy.department.{department}", value, actor)
        self.control.store.publish_event(
            "company.department.changed",
            department,
            {"enabled": enabled, "reason": reason.strip()},
        )
        self.control.store.audit(
            actor,
            "set_department_autonomy",
            "department",
            department,
            "allowed",
            {"enabled": enabled, "reason": reason.strip()},
        )
        return {"department": department, "enabled": enabled, "reason": reason.strip()}

    def evaluate_circuit_breakers(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or datetime.now(UTC)
        threshold = max(1, int(os.environ.get("AMAURA_DEPARTMENT_FAILURE_THRESHOLD", "3")))
        today = now.date().isoformat()
        failed_by_department: dict[str, int] = {}
        for task in self.control.store.list_work_items(item_type="task", state="failed", limit=1000):
            if not str(task.get("updated_at") or "").startswith(today):
                continue
            workflow = WORKFLOWS.get(str(task.get("workflow_id") or ""))
            if workflow:
                failed_by_department[workflow.department] = failed_by_department.get(workflow.department, 0) + 1
        tripped: list[dict[str, Any]] = []
        for department, failures in failed_by_department.items():
            if failures < threshold or self.department_paused(department):
                continue
            self.control.store.set_control(f"autonomy.department.{department}", "paused", "jarvis")
            alert = self.control.store.create_alert(
                {
                    "id": _id("alert"),
                    "severity": "critical",
                    "code": "department_circuit_breaker",
                    "message": f"Paused {department} after {failures} failed tasks today",
                    "resource_id": department,
                    "details": {"department": department, "failures": failures, "threshold": threshold},
                }
            )
            self.control.store.publish_event(
                "company.department.circuit_tripped",
                department,
                {"failures": failures, "threshold": threshold, "alert_id": alert["id"]},
            )
            tripped.append(alert)
        return tripped

    def status(self) -> dict[str, Any]:
        departments = sorted({workflow.department for workflow in WORKFLOWS.values()})
        return {
            "bootstrapped": self.control.store.get_control("company_autonomy_bootstrapped", "0") == "1",
            "autopilot_enabled": self.control.store.get_control("autopilot_enabled", "1") == "1",
            "repository_path": self.control.store.get_control("company_repository_path", ""),
            "department_autonomy": {
                department: "paused" if self.department_paused(department) else "enabled" for department in departments
            },
            "signals": {
                status: len(self.control.store.list_company_signals(status=status, limit=5000))
                for status in ("pending", "claimed", "resolved", "failed", "ignored")
            },
            "recent_runs": self.control.store.list_autonomy_runs(limit=20),
            "portfolio": self.mission.portfolio(),
            "dashboard": self.control.dashboard(),
        }


__all__ = [
    "CompanyAutonomyEngine",
    "SIGNAL_SEVERITIES",
    "SIGNAL_TYPES",
]
