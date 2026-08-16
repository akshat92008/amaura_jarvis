"""Objective-driven mission control for Amaura Labs.

Mission control turns founder-approved long-term objectives into bounded, recurring
company programmes. It never broadens authority: generated programmes still pass
through the governed control plane and external actions remain approval-gated.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.models import GovernanceError
from jarvis.amaura.workflows import get_workflow

OBJECTIVE_STATUSES = {"active", "paused", "completed", "cancelled"}
OBJECTIVE_CADENCES = {"daily", "weekly", "monthly", "manual"}
_TERMINAL_PROGRAMME_STATES = {"completed", "cancelled", "failed"}


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _cadence_key(cadence: str, now: datetime) -> str:
    if cadence == "daily":
        return now.date().isoformat()
    if cadence == "weekly":
        year, week, _ = now.isocalendar()
        return f"{year}-W{week:02d}"
    if cadence == "monthly":
        return now.strftime("%Y-%m")
    return "manual"


def _render(value: Any, variables: dict[str, str]) -> Any:
    if isinstance(value, str):
        try:
            return value.format_map(variables)
        except KeyError as exc:
            raise GovernanceError(f"Unknown objective template variable: {exc.args[0]}") from exc
    if isinstance(value, list):
        return [_render(item, variables) for item in value]
    if isinstance(value, dict):
        return {str(key): _render(item, variables) for key, item in value.items()}
    return value


class MissionControl:
    """Persistent founder objectives, cadence planning, and progress accounting."""

    def __init__(self, control: AmauraControlPlane):
        self.control = control

    def create_objective(
        self,
        *,
        title: str,
        objective: str,
        success_metric: str,
        workflow_key: str,
        cadence: str = "weekly",
        inputs: dict[str, Any] | None = None,
        priority: int = 3,
        target_value: float | None = None,
        current_value: float = 0.0,
        unit: str = "",
        max_active_programmes: int = 1,
        budget_cents: int = 0,
        deadline: str | None = None,
        actor: str | None = None,
    ) -> dict[str, Any]:
        actor = actor or self.control.founder_id
        if actor != self.control.founder_id:
            raise GovernanceError("Only the founder may create company objectives")
        if not title.strip() or not objective.strip() or not success_metric.strip():
            raise GovernanceError("Objective title, description, and success metric are required")
        if cadence not in OBJECTIVE_CADENCES:
            raise GovernanceError(f"Cadence must be one of: {', '.join(sorted(OBJECTIVE_CADENCES))}")
        if not 1 <= int(priority) <= 5:
            raise GovernanceError("Objective priority must be between 1 and 5")
        if not 1 <= int(max_active_programmes) <= 20:
            raise GovernanceError("max_active_programmes must be between 1 and 20")
        if int(budget_cents) < 0:
            raise GovernanceError("Objective budget cannot be negative")
        if target_value is not None and float(target_value) <= 0:
            raise GovernanceError("Objective target value must be positive")
        if float(current_value) < 0:
            raise GovernanceError("Objective current value cannot be negative")

        workflow = get_workflow(workflow_key)
        supplied = dict(inputs or {})
        preview = _render(
            supplied,
            {
                "objective_id": "preview",
                "cadence_key": "preview",
                "date": "2099-01-01",
                "week": "2099-W01",
                "month": "2099-01",
            },
        )
        missing = [key for key in workflow.required_inputs if not preview.get(key)]
        if missing:
            raise GovernanceError(f"Objective workflow requires input(s): {', '.join(missing)}")
        workflow_budget = sum(step.budget_cents for step in workflow.steps)
        if budget_cents and workflow_budget > budget_cents:
            raise GovernanceError(f"Objective budget {budget_cents}c is below workflow maximum {workflow_budget}c")

        objective_id = _id("obj")
        created = self.control.store.create_objective(
            {
                "id": objective_id,
                "title": title.strip(),
                "objective": objective.strip(),
                "department": workflow.department,
                "workflow_key": workflow.key,
                "status": "active",
                "priority": int(priority),
                "success_metric": success_metric.strip(),
                "target_value": None if target_value is None else float(target_value),
                "current_value": float(current_value),
                "unit": unit.strip(),
                "cadence": cadence,
                "inputs": supplied,
                "max_active_programmes": int(max_active_programmes),
                "budget_cents": int(budget_cents),
                "deadline": deadline,
                "created_by": actor,
            }
        )
        self.control.store.publish_event(
            "company.objective.created",
            objective_id,
            {"workflow": workflow.key, "cadence": cadence, "priority": priority},
        )
        self.control.store.audit(
            actor,
            "create_objective",
            "company_objective",
            objective_id,
            "allowed",
            {"workflow": workflow.key, "cadence": cadence},
        )
        return created

    def set_status(
        self,
        objective_id: str,
        status: str,
        *,
        reason: str,
        actor: str | None = None,
    ) -> dict[str, Any]:
        actor = actor or self.control.founder_id
        if actor != self.control.founder_id:
            raise GovernanceError("Only the founder may change objective status")
        if status not in OBJECTIVE_STATUSES:
            raise GovernanceError(f"Invalid objective status: {status}")
        if not reason.strip():
            raise GovernanceError("A reason is required when changing objective status")
        objective = self.control.store.update_objective(objective_id, status=status)
        self.control.store.publish_event(
            "company.objective.status_changed",
            objective_id,
            {"status": status, "reason": reason.strip()},
        )
        self.control.store.audit(
            actor,
            "set_objective_status",
            "company_objective",
            objective_id,
            "allowed",
            {"status": status, "reason": reason.strip()},
        )
        return objective

    def record_progress(
        self,
        objective_id: str,
        *,
        value: float | None = None,
        delta: float | None = None,
        note: str,
        evidence_refs: list[dict[str, Any]],
        actor: str = "jarvis",
    ) -> dict[str, Any]:
        if actor not in {"jarvis", self.control.founder_id}:
            raise GovernanceError("Only JARVIS or the founder may update objective progress")
        if (value is None) == (delta is None):
            raise GovernanceError("Provide exactly one of value or delta")
        if not note.strip():
            raise GovernanceError("Objective progress requires a note")
        if not evidence_refs:
            raise GovernanceError("Objective progress requires at least one evidence reference")
        objective = self.control.store.get_objective(objective_id)
        previous = float(objective["current_value"])
        new_value = float(value) if value is not None else previous + float(delta or 0)
        if new_value < 0:
            raise GovernanceError("Objective progress cannot be negative")

        status = objective["status"]
        target = objective.get("target_value")
        if target is not None and new_value >= float(target):
            status = "completed"
        with self.control.store.atomic_block():
            updated = self.control.store.update_objective(
                objective_id,
                current_value=new_value,
                status=status,
            )
            update = self.control.store.record_objective_update(
                update_id=_id("objupd"),
                objective_id=objective_id,
                previous_value=previous,
                new_value=new_value,
                note=note.strip(),
                evidence_refs=evidence_refs,
                actor=actor,
            )
            self.control.store.publish_event(
                "company.objective.progress",
                objective_id,
                {"previous": previous, "current": new_value, "status": status},
            )
            self.control.store.audit(
                actor,
                "record_objective_progress",
                "company_objective",
                objective_id,
                "allowed",
                {"previous": previous, "current": new_value, "status": status},
            )
        return {"objective": updated, "update": update}

    def _programmes_for_objective(self, objective_id: str) -> list[dict[str, Any]]:
        programmes = self.control.store.list_work_items(item_type="programme", limit=1000)
        return [
            item
            for item in programmes
            if (item.get("metadata") or {}).get("inputs", {}).get("objective_id") == objective_id
        ]

    def plan_due_work(
        self,
        *,
        now: datetime | None = None,
        max_new_programmes: int | None = None,
    ) -> list[dict[str, Any]]:
        """Create due programmes exactly once across threads and processes.

        Cadence reservation, durable daily-budget accounting, programme creation,
        and objective bookkeeping share one SQLite ``BEGIN IMMEDIATE`` transaction.
        This prevents duplicate work even when multiple autopilot workers tick at
        the same time.
        """
        if self.control.store.get_control("autopilot_enabled", "1") != "1":
            return []
        now = now or datetime.now(UTC)
        limit = max_new_programmes
        if limit is None:
            limit = int(os.environ.get("AMAURA_MAX_NEW_PROGRAMMES_PER_CYCLE", "3"))
        limit = max(0, min(int(limit), 20))
        if limit == 0:
            return []
        daily_budget_cap = max(
            0,
            int(os.environ.get("AMAURA_AUTOPILOT_DAILY_BUDGET_CENTS", "5000")),
        )
        created: list[dict[str, Any]] = []

        for snapshot in self.control.store.list_objectives(status="active", limit=1000):
            if len(created) >= limit:
                break
            if snapshot["cadence"] == "manual":
                continue
            if snapshot.get("deadline"):
                deadline = datetime.fromisoformat(str(snapshot["deadline"]))
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=UTC)
                if now > deadline:
                    continue

            key = _cadence_key(snapshot["cadence"], now)
            workflow = get_workflow(snapshot["workflow_key"])
            if self.control.store.get_control(f"autonomy.department.{workflow.department}", "enabled") != "enabled":
                continue
            workflow_budget = sum(step.budget_cents for step in workflow.steps)
            objective_cap = int(snapshot["budget_cents"] or workflow_budget)
            if workflow_budget > objective_cap:
                continue

            programme: dict[str, Any] | None = None
            with self.control.store.atomic_block():
                # Re-read under the write lock because another worker may have
                # changed status, capacity, or cadence since the outer snapshot.
                objective = self.control.store.get_objective(snapshot["id"])
                if objective["status"] != "active" or objective["cadence"] == "manual":
                    continue
                if objective.get("last_planned_key") == key:
                    continue
                if self.control.store.get_objective_cadence_run(objective["id"], key):
                    self.control.store.update_objective(
                        objective["id"], last_planned_key=key, last_planned_at=now.isoformat()
                    )
                    continue

                programmes = self._programmes_for_objective(objective["id"])
                if any((item.get("metadata") or {}).get("inputs", {}).get("cadence_key") == key for item in programmes):
                    self.control.store.update_objective(
                        objective["id"], last_planned_key=key, last_planned_at=now.isoformat()
                    )
                    continue
                active_count = sum(item["state"] not in _TERMINAL_PROGRAMME_STATES for item in programmes)
                if active_count >= int(objective["max_active_programmes"]):
                    continue

                already_reserved = self.control.store.objective_cadence_budget_for_date(now.date().isoformat())
                if daily_budget_cap and already_reserved + workflow_budget > daily_budget_cap:
                    continue
                claimed = self.control.store.claim_objective_cadence(
                    objective["id"],
                    key,
                    budget_cents=workflow_budget,
                    created_at=now.isoformat(),
                )
                if not claimed:
                    continue

                variables = {
                    "objective_id": objective["id"],
                    "cadence_key": key,
                    "date": now.date().isoformat(),
                    "week": _cadence_key("weekly", now),
                    "month": _cadence_key("monthly", now),
                }
                inputs = _render(dict(objective.get("inputs") or {}), variables)
                inputs.update({"objective_id": objective["id"], "cadence_key": key})
                programme = self.control.create_program(
                    objective=_render(objective["objective"], variables),
                    success_metric=objective["success_metric"],
                    workflow_key=objective["workflow_key"],
                    title=f"{objective['title']} — {key}",
                    priority=int(objective["priority"]),
                    deadline=objective.get("deadline"),
                    inputs=inputs,
                )
                programme_id = programme["programme"]["id"]
                self.control.store.complete_objective_cadence(objective["id"], key, programme_id=programme_id)
                self.control.store.update_objective(
                    objective["id"], last_planned_key=key, last_planned_at=now.isoformat()
                )
                self.control.store.publish_event(
                    "company.objective.programme_created",
                    objective["id"],
                    {"programme_id": programme_id, "cadence_key": key},
                )
                self.control.store.audit(
                    "jarvis",
                    "plan_objective_programme",
                    "company_objective",
                    objective["id"],
                    "allowed",
                    {"programme_id": programme_id, "cadence_key": key},
                )
            if programme is not None:
                created.append(programme)
        return created

    def sync_completed_programmes(self, *, max_updates: int = 100) -> list[dict[str, Any]]:
        """Credit completed recurring programmes back to their founder objectives.

        A content-addressed completion receipt plus all submitted task evidence is
        stored with the objective update. The cadence row transitions from
        ``created`` to ``credited`` in the same transaction as the metric update,
        making reconciliation restart-safe and exactly-once.
        """
        updates: list[dict[str, Any]] = []
        limit = max(1, min(int(max_updates), 1000))
        for run in self.control.store.list_objective_cadence_runs(status="created", limit=limit):
            programme_id = str(run.get("programme_id") or "")
            if not programme_id:
                continue
            try:
                programme = self.control.store.get_work_item(programme_id)
            except KeyError:
                continue
            if programme["state"] != "completed":
                continue

            objective_id = str(run["objective_id"])
            cadence_key = str(run["cadence_key"])
            related = [
                item
                for item in self.control.store.list_work_items(limit=5000)
                if (item.get("metadata") or {}).get("inputs", {}).get("objective_id") == objective_id
                and (item.get("metadata") or {}).get("inputs", {}).get("cadence_key") == cadence_key
            ]
            task_evidence = [
                {
                    **evidence,
                    "task_id": item["id"],
                }
                for item in related
                if item.get("item_type") == "task"
                for evidence in (item.get("evidence") or [])
                if evidence.get("reference")
            ]
            completion_record = self.control.evidence.put_json(
                {
                    "objective_id": objective_id,
                    "cadence_key": cadence_key,
                    "programme_id": programme_id,
                    "programme_state": programme["state"],
                    "completed_tasks": [
                        item["id"]
                        for item in related
                        if item.get("item_type") == "task" and item.get("state") == "completed"
                    ],
                    "task_evidence_refs": [item.get("reference") for item in task_evidence],
                },
                source=f"objective:{objective_id}:cadence:{cadence_key}:completion",
            )
            evidence_refs = [
                {
                    "type": "programme_completion_receipt",
                    "reference": completion_record.reference,
                    "sha256": completion_record.sha256,
                    "byte_length": completion_record.byte_length,
                    "programme_id": programme_id,
                },
                *task_evidence[:200],
            ]

            result: dict[str, Any] | None = None
            with self.control.store.atomic_block():
                current_run = self.control.store.get_objective_cadence_run(objective_id, cadence_key)
                if not current_run or current_run["status"] != "created":
                    continue
                objective = self.control.store.get_objective(objective_id)
                previous = float(objective["current_value"])
                new_value = previous + 1.0
                target = objective.get("target_value")
                status = objective["status"]
                if target is not None and new_value >= float(target) and status != "cancelled":
                    new_value = max(new_value, float(target))
                    status = "completed"
                if not self.control.store.credit_objective_cadence(objective_id, cadence_key):
                    continue
                updated = self.control.store.update_objective(
                    objective_id,
                    current_value=new_value,
                    status=status,
                )
                update = self.control.store.record_objective_update(
                    update_id=_id("objupd"),
                    objective_id=objective_id,
                    previous_value=previous,
                    new_value=new_value,
                    note=f"Completed programme {programme_id} for {cadence_key}",
                    evidence_refs=evidence_refs,
                    actor="jarvis",
                )
                self.control.store.publish_event(
                    "company.objective.programme_credited",
                    objective_id,
                    {
                        "programme_id": programme_id,
                        "cadence_key": cadence_key,
                        "current_value": new_value,
                        "status": status,
                    },
                )
                self.control.store.audit(
                    "jarvis",
                    "credit_objective_programme",
                    "company_objective",
                    objective_id,
                    "allowed",
                    {
                        "programme_id": programme_id,
                        "cadence_key": cadence_key,
                        "previous": previous,
                        "current": new_value,
                    },
                )
                result = {"objective": updated, "update": update, "run": current_run}
            if result is not None:
                updates.append(result)
        return updates

    def portfolio(self) -> dict[str, Any]:
        objectives = self.control.store.list_objectives(limit=1000)
        rows: list[dict[str, Any]] = []
        for objective in objectives:
            target = objective.get("target_value")
            current = float(objective["current_value"])
            progress = None
            if target is not None and float(target) > 0:
                progress = min(100.0, round(current / float(target) * 100, 2))
            programmes = self._programmes_for_objective(objective["id"])
            rows.append(
                {
                    **objective,
                    "progress_percent": progress,
                    "programme_count": len(programmes),
                    "active_programmes": sum(item["state"] not in _TERMINAL_PROGRAMME_STATES for item in programmes),
                }
            )
        return {
            "autopilot_enabled": self.control.store.get_control("autopilot_enabled", "1") == "1",
            "objectives": rows,
            "counts": {status: sum(item["status"] == status for item in rows) for status in sorted(OBJECTIVE_STATUSES)},
        }

    def set_autopilot(self, enabled: bool, *, reason: str, actor: str | None = None) -> dict[str, Any]:
        actor = actor or self.control.founder_id
        if actor != self.control.founder_id:
            raise GovernanceError("Only the founder may enable or pause company autopilot")
        if not reason.strip():
            raise GovernanceError("Autopilot state changes require a reason")
        self.control.store.set_control("autopilot_enabled", "1" if enabled else "0", actor)
        self.control.store.publish_event(
            "company.autopilot.changed", "jarvis", {"enabled": enabled, "reason": reason.strip()}
        )
        self.control.store.audit(
            actor,
            "set_autopilot",
            "company_control",
            "autopilot_enabled",
            "allowed",
            {"enabled": enabled, "reason": reason.strip()},
        )
        return {"enabled": enabled, "reason": reason.strip()}

    def bootstrap_distribution_first(
        self,
        *,
        repository_path: str | None = None,
        actor: str | None = None,
    ) -> list[dict[str, Any]]:
        actor = actor or self.control.founder_id
        existing_titles = {item["title"] for item in self.control.store.list_objectives(limit=1000)}
        definitions: list[dict[str, Any]] = [
            {
                "title": "Build Amaura's owned audience",
                "objective": "Produce the Amaura build-in-public content package for {cadence_key}",
                "success_metric": "One evidence-backed long-form asset and reusable short-form package reaches founder approval",
                "workflow_key": "content_factory",
                "cadence": "weekly",
                "inputs": {
                    "campaign_id": "amaura-owned-distribution",
                    "audience": "AI builders, students, developers, researchers and founders",
                    "business_objective": "Grow an owned audience for Amaura Labs and its products",
                    "content_theme": "Build Amaura Labs in public — {cadence_key}",
                },
                "priority": 1,
                "target_value": 52,
                "unit": "approved weekly content packages",
                "max_active_programmes": 1,
            },
            {
                "title": "Validate high-leverage AI product opportunities",
                "objective": "Evaluate one high-leverage affordable-AI opportunity for {month}",
                "success_metric": "Produce an evidence-backed build, test, or kill decision",
                "workflow_key": "product_discovery",
                "cadence": "monthly",
                "inputs": {
                    "problem_space": "Affordable AI, developer productivity and AI-native workflows",
                    "target_user": "Indian developers, students, researchers and resource-constrained teams",
                },
                "priority": 2,
                "target_value": 12,
                "unit": "validated opportunity decisions",
                "max_active_programmes": 1,
            },
        ]
        if repository_path:
            definitions.append(
                {
                    "title": "Ship verified Amaura product improvements",
                    "objective": "Ship one bounded, verified Amaura or Nexus improvement for {cadence_key}",
                    "success_metric": "Acceptance tests pass and the founder receives an auditable release decision",
                    "workflow_key": "software_delivery",
                    "cadence": "weekly",
                    "inputs": {"repository_path": repository_path},
                    "priority": 2,
                    "target_value": 52,
                    "unit": "verified product improvements",
                    "max_active_programmes": 1,
                }
            )
        created: list[dict[str, Any]] = []
        for definition in definitions:
            if definition["title"] in existing_titles:
                continue
            created.append(self.create_objective(actor=actor, **definition))
        return created


__all__ = ["MissionControl", "OBJECTIVE_CADENCES", "OBJECTIVE_STATUSES"]
