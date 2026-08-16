"""JARVIS: the master orchestrator and authority boundary for all Amaura agents."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jarvis.amaura.content_factory import ContentFactory
from jarvis.amaura.distribution import DistributionEngine
from jarvis.amaura.evidence import EvidenceVault
from jarvis.amaura.gitops import (
    cleanup_task_worktree,
    is_software_task,
    merge_approved_task,
    rollback_approved_merge,
)
from jarvis.amaura.integrations import ProviderReceipt, verify_provider_receipt
from jarvis.amaura.model_gateway import ModelGateway
from jarvis.amaura.models import (
    ApprovalStatus,
    CanonicalTaskPacket,
    GovernanceError,
    RepositoryContext,
    RiskLevel,
    TaskBudget,
    TaskDependency,
    TaskState,
)
from jarvis.amaura.pipeline import AcquisitionPipeline
from jarvis.amaura.policies import POLICIES
from jarvis.amaura.policy import PolicyEngine
from jarvis.amaura.registry import AGENTS_BY_ID, ALL_AGENTS, get_agent
from jarvis.amaura.runtime import load_amaura_env
from jarvis.amaura.store import CompanyStore
from jarvis.amaura.telemetry import OperationalTelemetry
from jarvis.amaura.workflows import WORKFLOWS, get_workflow


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class AmauraControlPlane:
    """The only service allowed to create, delegate, review, or approve company work."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        founder_id: str | None = None,
        *,
        audit_checkpoint_path: str | Path | None = None,
    ):
        load_amaura_env()
        self.store = CompanyStore(db_path, audit_checkpoint_path=audit_checkpoint_path)
        self.founder_id = founder_id or os.environ.get("AMAURA_FOUNDER_ID", "founder")
        self.founder_name = os.environ.get("AMAURA_FOUNDER_NAME", "Akshat")
        self.policy = PolicyEngine()
        self.models = ModelGateway()
        evidence_dir = Path(
            os.environ.get(
                "AMAURA_EVIDENCE_DIR",
                str(self.store.db_path.parent / "evidence"),
            )
        )
        self.evidence = EvidenceVault(evidence_dir)
        self.telemetry = OperationalTelemetry(self.store)
        self.acquisition = AcquisitionPipeline(self.store, self.founder_id)
        self.content_factory = ContentFactory(self.store, self.founder_id)
        self.distribution = DistributionEngine(self)
        self.bootstrap()

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> AmauraControlPlane:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def bootstrap(self) -> dict[str, Any]:
        for agent in ALL_AGENTS:
            self.store.upsert_agent(agent.to_dict())
        for policy_name, policy in POLICIES.items():
            self.store.upsert_knowledge("company_policies", policy_name, policy, [], "internal", "jarvis")
        self.store.publish_event(
            "company.control_plane.ready",
            "jarvis",
            {"agents": len(ALL_AGENTS), "founder": self.founder_name, "workflows": list(WORKFLOWS)},
        )
        return {"master": "jarvis", "agents": len(ALL_AGENTS), "workflows": list(WORKFLOWS)}

    def create_program(
        self,
        *,
        objective: str,
        success_metric: str,
        workflow_key: str,
        title: str | None = None,
        priority: int = 3,
        deadline: str | None = None,
        inputs: dict[str, Any] | None = None,
        actor: str = "jarvis",
    ) -> dict[str, Any]:
        if actor != "jarvis":
            raise GovernanceError("Only JARVIS may translate objectives into company programmes")
        if not objective.strip() or not success_metric.strip():
            raise GovernanceError("Every programme requires an objective and measurable success metric")
        if not 1 <= priority <= 5:
            raise GovernanceError("Priority must be between 1 (highest) and 5 (lowest)")
        workflow = get_workflow(workflow_key)
        supplied = inputs or {}
        workspace = (
            Path(supplied.get("repository_path") or supplied.get("workspace") or os.getcwd()).expanduser().resolve()
        )
        if not workspace.exists() or not workspace.is_dir():
            raise GovernanceError(f"Assigned workspace does not exist or is not a directory: {workspace}")
        supplied = {**supplied, "workspace": str(workspace)}
        missing = [key for key in workflow.required_inputs if not supplied.get(key)]
        if missing:
            raise GovernanceError(f"Workflow requires input(s): {', '.join(missing)}")
        if workflow.key == "client_acquisition":
            try:
                self.store.get_campaign(str(supplied["campaign_id"]))
            except KeyError:
                self.acquisition.create_campaign(
                    campaign_id=str(supplied["campaign_id"]),
                    name=str(supplied.get("campaign_name") or supplied["campaign_id"]),
                    target_segment=str(supplied["target_segment"]),
                    offer=str(supplied["offer"]),
                    minimum_score=int(supplied.get("minimum_score", 70)),
                    daily_lead_limit=int(supplied.get("daily_lead_limit", 10)),
                    daily_outreach_limit=int(supplied.get("daily_outreach_limit", 3)),
                    daily_followup_limit=int(supplied.get("daily_followup_limit", 5)),
                    maximum_followups=int(supplied.get("maximum_followups", 2)),
                    config={"proof_assets": supplied.get("proof_assets", []), "regions": supplied.get("regions", [])},
                )
        elif workflow.key == "content_factory":
            try:
                self.store.get_content_campaign(str(supplied["campaign_id"]))
            except KeyError:
                self.content_factory.create_campaign(
                    campaign_id=str(supplied["campaign_id"]),
                    title=title or objective[:100],
                    audience=str(supplied["audience"]),
                    business_objective=str(supplied["business_objective"]),
                    config=supplied,
                )

        programme_id, project_id, milestone_id = _id("prog"), _id("proj"), _id("mile")
        programme_title = title or objective.strip()[:100]
        base = {
            "workflow_id": workflow.key,
            "owner_id": "jarvis",
            "state": TaskState.ASSIGNED.value,
            "priority": priority,
            "deadline": deadline,
            "success_metric": success_metric,
            "metadata": {"inputs": supplied},
        }
        step_ids = {step.key: _id("task") for step in workflow.steps}
        tasks: list[dict[str, Any]] = []

        # Priority-1: all inserts are one atomic transaction — any policy failure rolls
        # back the whole programme rather than leaving orphaned partial rows.
        with self.store.atomic_block():
            self.store.insert_work_item(
                {
                    **base,
                    "id": programme_id,
                    "parent_id": None,
                    "item_type": "programme",
                    "title": programme_title,
                    "description": objective,
                }
            )
            self.store.insert_work_item(
                {
                    **base,
                    "id": project_id,
                    "parent_id": programme_id,
                    "item_type": "project",
                    "title": workflow.name,
                    "description": f"Execute the {workflow.name} workflow for: {objective}",
                }
            )
            self.store.insert_work_item(
                {
                    **base,
                    "id": milestone_id,
                    "parent_id": project_id,
                    "item_type": "milestone",
                    "title": f"Complete {workflow.name}",
                    "description": success_metric,
                }
            )

            for step in workflow.steps:
                task = self.store.insert_work_item(
                    {
                        "id": step_ids[step.key],
                        "parent_id": milestone_id,
                        "item_type": "task",
                        "workflow_id": workflow.key,
                        "title": step.title,
                        "description": step.description,
                        "owner_id": step.owner_id,
                        "reviewer_id": step.reviewer_id,
                        "state": TaskState.ASSIGNED.value,
                        "priority": priority,
                        "deadline": deadline,
                        "budget_cents": step.budget_cents,
                        "risk": step.risk.value,
                        "action_type": step.action_type,
                        "success_metric": success_metric,
                        "acceptance_criteria": list(step.acceptance_criteria),
                        "dependencies": [step_ids[key] for key in step.depends_on],
                        "metadata": {
                            "step_key": step.key,
                            "programme_id": programme_id,
                            "inputs": supplied,
                            "workspace": str(workspace),
                            "sensitivity": supplied.get("sensitivity", "internal"),
                            "prompt_profile": step.prompt_profile,
                        },
                    }
                )
                decision = self.policy.validate_assignment(task)
                if not decision.allowed:
                    self.store.audit(actor, "assign", "task", task["id"], "denied", decision.to_dict())
                    raise GovernanceError("; ".join(decision.reasons))
                self.store.audit(actor, "assign", "task", task["id"], "allowed", {"owner": step.owner_id})
                tasks.append(task)

        self.store.publish_event(
            "project.created",
            programme_id,
            {"objective": objective, "workflow": workflow.key, "tasks": len(tasks), "success_metric": success_metric},
        )
        self.store.audit(actor, "create_program", "programme", programme_id, "allowed", {"workflow": workflow.key})
        return {
            "programme": self.store.get_work_item(programme_id),
            "project_id": project_id,
            "milestone_id": milestone_id,
            "tasks": tasks,
        }

    def task_packet(self, task_id: str, actor: str = "jarvis") -> dict[str, Any]:
        if actor != "jarvis":
            raise GovernanceError("Only JARVIS may assemble and issue task context")
        task = self._task(task_id)
        self._ensure_agent_enabled(task["owner_id"])
        agent = get_agent(task["owner_id"])
        dependency_cards = [self.store.get_work_item(dep) for dep in task["dependencies"]]
        remaining = task["budget_cents"] - task["spent_cents"]
        route = self.models.route(
            agent.agent_id,
            risk=task["risk"],
            sensitivity=task["metadata"].get("sensitivity", "internal"),
            estimated_tokens=task["metadata"].get("estimated_tokens", 4000),
            remaining_budget_cents=max(0, remaining),
        )
        execution_objective = str(task["description"])
        retry_context = str(task.get("summary") or "").strip()
        replan_instruction = str((task.get("metadata") or {}).get("replan_instruction") or "").strip()
        if retry_context or replan_instruction:
            execution_objective += "\n\nJARVIS RETRY/REPLAN CONTEXT:\n"
            if replan_instruction:
                execution_objective += replan_instruction + "\n"
            if retry_context:
                execution_objective += "Previous execution/review context:\n" + retry_context[-6000:]

        packet_model = CanonicalTaskPacket(
            packet_id=_id("pkt"),
            issued_by="jarvis",
            owner=agent.agent_id,
            reviewer=task["reviewer_id"],
            objective=execution_objective,
            success_metric=task["success_metric"],
            acceptance_criteria=task["acceptance_criteria"],
            budget=TaskBudget(limit_cents=task["budget_cents"], spent_cents=task["spent_cents"], remaining=remaining),
            tools_authorized=list(agent.tools),
            data_authorized=list(agent.data_access),
            dependencies=[
                TaskDependency(
                    id=dep["id"],
                    title=dep["title"],
                    state=dep["state"],
                    summary=dep.get("summary", ""),
                    evidence=dep["evidence"],
                )
                for dep in dependency_cards
            ],
            risk_class=task["risk"],
            action_type=task["action_type"],
            repository_context=RepositoryContext(workspace_dir=task["metadata"].get("workspace")),
            doctrine=[
                "Do not exceed this task packet.",
                "Attach evidence for every completion claim.",
                "Do not certify your own work.",
                "Stop and escalate any unapproved tool, data, cost, or external action.",
            ],
        )
        self.store.audit(actor, "issue_task_packet", "task", task_id, "allowed", {"owner": agent.agent_id})
        packet_dict = packet_model.model_dump(mode="json")
        # Preserve original fields that executor relies on internally (executor expects to use these, but they won't be shown to the agent in the packet)
        packet_dict["_model_route"] = route.to_dict()
        packet_dict["_workspace"] = task["metadata"].get("workspace")
        packet_dict["_approved_tools"] = list(agent.tools)
        return packet_dict

    def start_task(self, task_id: str, actor: str = "jarvis") -> dict[str, Any]:
        if actor != "jarvis":
            raise GovernanceError("Only JARVIS may dispatch company tasks")
        task = self._task(task_id)
        self._ensure_agent_enabled(task["owner_id"])
        if task["state"] not in {TaskState.ASSIGNED.value, TaskState.BLOCKED.value}:
            raise GovernanceError(f"Task cannot start from state '{task['state']}'")
        incomplete = [
            dep for dep in task["dependencies"] if self.store.get_work_item(dep)["state"] != TaskState.COMPLETED.value
        ]
        if incomplete:
            updated = self.store.update_work_item(task_id, state=TaskState.BLOCKED.value)
            self.store.publish_event("task.blocked", task_id, {"dependencies": incomplete})
            self.store.audit(actor, "start", "task", task_id, "denied", {"incomplete_dependencies": incomplete})
            return updated
        updated = self.store.update_work_item(task_id, state=TaskState.IN_PROGRESS.value)
        self.store.publish_event("task.started", task_id, {"owner": task["owner_id"]})
        self.store.audit(actor, "start", "task", task_id, "allowed", {"owner": task["owner_id"]})
        return updated

    def authorize_tool(self, task_id: str, agent_id: str, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        task = self._task(task_id)
        decision = self.policy.validate_tool_action(task, agent_id, tool_name, args)
        outcome = "allowed" if decision.allowed else "denied"
        self.store.audit(agent_id, f"tool:{tool_name}", "task", task_id, outcome, decision.to_dict())
        if not decision.allowed:
            raise GovernanceError("; ".join(decision.reasons))
        return decision.to_dict()

    def submit_task(self, task_id: str, actor: str, summary: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
        task = self._task(task_id)
        if actor != task["owner_id"]:
            raise GovernanceError("Only the assigned employee may submit this task")
        if task["state"] != TaskState.IN_PROGRESS.value:
            raise GovernanceError("Only in-progress tasks may be submitted")
        if not summary.strip() or not evidence:
            raise GovernanceError("Submission requires a result summary and verifiable evidence")
        for item in evidence:
            if not item.get("type") or not item.get("reference"):
                raise GovernanceError("Each evidence item requires 'type' and 'reference'")
        next_state = TaskState.AWAITING_APPROVAL if task["reviewer_id"] == "founder" else TaskState.AWAITING_REVIEW
        updated = self.store.update_work_item(
            task_id, state=next_state.value, summary=summary.strip(), evidence=evidence
        )
        self.store.publish_event(
            "qa.ready", task_id, {"reviewer": task["reviewer_id"], "evidence_count": len(evidence)}
        )
        self.store.audit(actor, "submit", "task", task_id, "allowed", {"evidence_count": len(evidence)})
        if task["reviewer_id"] == "founder":
            self._request_approval(updated, requested_by="jarvis")
        return self._task(task_id)

    def review_task(
        self, task_id: str, actor: str, approve: bool, findings: str, attestation: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        task = self._task(task_id)
        if actor != task["reviewer_id"]:
            self.store.audit(actor, "review", "task", task_id, "denied", {"expected": task["reviewer_id"]})
            raise GovernanceError(f"Independent review must be performed by '{task['reviewer_id']}'")
        if actor == task["owner_id"]:
            raise GovernanceError("No agent may certify its own work")
        if actor != self.founder_id:
            from jarvis.amaura.evidence import (
                deterministic_evidence_review,
                strict_review_enabled,
                validate_criterion_review,
                verify_review_attestation,
            )

            if not attestation:
                raise GovernanceError("Review attestation is required for non-founder reviewers")
            if not verify_review_attestation(attestation):
                raise GovernanceError("Invalid review attestation signature")
            if attestation.get("reviewer_id") != actor or attestation.get("task_id") != task_id:
                raise GovernanceError("Attestation does not match task and reviewer")
            attestation_decision = self._attestation_approves(attestation)
            if attestation_decision != approve:
                raise GovernanceError("Attestation decision does not match review approval")
            if strict_review_enabled(task):
                current_deterministic = deterministic_evidence_review(task, self.evidence)
                signed_deterministic = attestation.get("deterministic_review")
                if not isinstance(signed_deterministic, dict):
                    raise GovernanceError("Review attestation is missing deterministic evidence verification")
                if signed_deterministic.get("submission_sha256") != current_deterministic["submission_sha256"]:
                    raise GovernanceError("Review attestation was signed for a different task submission")
                if bool(signed_deterministic.get("approve")) != bool(current_deterministic["approve"]):
                    raise GovernanceError("Review attestation deterministic result is stale or inconsistent")
                criterion_review = validate_criterion_review(
                    task,
                    dict(attestation.get("decision") or {}),
                    self.evidence,
                )
                if approve and not criterion_review["ok"]:
                    raise GovernanceError(
                        "Review attestation does not prove every acceptance criterion: "
                        + "; ".join(criterion_review["findings"])
                    )
        if task["state"] != TaskState.AWAITING_REVIEW.value:
            raise GovernanceError("Task is not awaiting independent review")
        if not findings.strip():
            raise GovernanceError("Review findings are required")
        if not approve:
            updated = self.store.update_work_item(
                task_id,
                state=TaskState.ASSIGNED.value,
                summary=f"REVIEW REJECTED: {findings.strip()}\n\nPrevious submission: {task['summary']}",
            )
            self.store.publish_event("qa.rejected", task_id, {"reviewer": actor, "findings": findings})
            self.store.audit(actor, "review", "task", task_id, "rejected", {"findings": findings})
            if is_software_task(task) and task.get("metadata", {}).get("git_worktree_path"):
                cleanup_task_worktree(task, require_clean=False)
            return updated

        gate = self.policy.completion_gate(task)
        self.policy.require_allowed(gate)
        self.store.publish_event("qa.approved", task_id, {"reviewer": actor, "findings": findings})
        self.store.audit(actor, "review", "task", task_id, "approved", {"findings": findings})
        if gate.requires_approval:
            updated = self.store.update_work_item(task_id, state=TaskState.AWAITING_APPROVAL.value)
            self._request_approval(updated, requested_by="jarvis")
            return self._task(task_id)
        return self._complete_task(task_id)

    @staticmethod
    def _attestation_approves(attestation: dict[str, Any]) -> bool:
        decision = attestation.get("decision")
        if not isinstance(decision, dict) or not isinstance(decision.get("approve"), bool):
            raise GovernanceError("Review attestation decision must include boolean 'approve'")
        return decision["approve"]

    def _request_approval(self, task: dict[str, Any], requested_by: str) -> dict[str, Any]:
        self.store.expire_stale_approvals()
        existing = [a for a in self.store.list_approvals("pending") if a["task_id"] == task["id"]]
        if existing:
            return existing[0]
        payload = self._approval_payload(task)
        approval = self.store.create_approval(
            {
                "id": _id("approval"),
                "task_id": task["id"],
                "action_type": task["action_type"],
                "risk": task["risk"],
                "requested_by": requested_by,
                "payload": payload,
            }
        )
        self.store.publish_event("approval.requested", approval["id"], {"task_id": task["id"], "risk": task["risk"]})
        return approval

    @staticmethod
    def _approval_payload(task: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(task.get("metadata") or {})
        git_snapshot = {
            key: metadata.get(key)
            for key in (
                "git_repository_root",
                "git_branch",
                "git_base_branch",
                "git_base_commit",
                "git_commit",
                "git_changed_files",
                "post_merge_validation",
            )
            if metadata.get(key) not in (None, "", [])
        }
        return {
            "title": task["title"],
            "summary": task["summary"],
            "evidence": task["evidence"],
            "budget_cents": task["budget_cents"],
            "spent_cents": task["spent_cents"],
            "action_type": task["action_type"],
            "risk": task["risk"],
            "git_snapshot": git_snapshot,
        }

    def decide_approval(self, approval_id: str, actor: str, decision: str, reason: str) -> dict[str, Any]:
        if actor != self.founder_id:
            raise GovernanceError("Only the founder may decide company approval requests")
        try:
            status = ApprovalStatus(decision)
        except ValueError as exc:
            raise GovernanceError(f"Invalid approval decision: {decision}") from exc
        if status in {ApprovalStatus.PENDING, ApprovalStatus.EXPIRED}:
            raise GovernanceError("A founder decision must approve, reject, request changes, or postpone")
        if not reason.strip():
            raise GovernanceError("Founder decision reason is required")
        approval_snapshot = self.store.get_approval(approval_id)
        task_before_decision = self._task(approval_snapshot["task_id"])
        if task_before_decision["state"] != TaskState.AWAITING_APPROVAL.value:
            raise GovernanceError("The approved task is no longer awaiting founder authority")
        current_payload = self._approval_payload(task_before_decision)
        if self.store.canonical_hash(current_payload) != approval_snapshot["payload_hash"]:
            self.store.audit(
                actor,
                "decide_approval",
                "approval",
                approval_id,
                "denied",
                {"reason": "approval_payload_changed"},
            )
            raise GovernanceError("Approval payload changed after it was requested; request a fresh founder approval")

        task_id = approval_snapshot["task_id"]
        if status is ApprovalStatus.APPROVED:
            task = self._complete_task(
                task_id,
                approval_resolution=(approval_id, status.value, actor, reason.strip()),
            )
            approval = self.store.get_approval(approval_id)
            return {"approval": approval, "task": task}

        # Cleanup is an external side effect. Perform it before the atomic
        # database transition so a failure leaves the approval pending.
        if (
            status is ApprovalStatus.REJECTED
            and is_software_task(task_before_decision)
            and task_before_decision.get("metadata", {}).get("git_worktree_path")
        ):
            cleanup_task_worktree(task_before_decision, require_clean=False)

        with self.store.atomic_block():
            approval = self.store.resolve_approval(
                approval_id,
                status.value,
                actor,
                reason.strip(),
            )
            if status is ApprovalStatus.REJECTED:
                task = self.store.update_work_item(
                    task_id,
                    state=TaskState.BLOCKED.value,
                    summary=(
                        f"FOUNDER REJECTED: {reason.strip()}\n\nPrevious submission: {task_before_decision['summary']}"
                    ),
                )
            elif status is ApprovalStatus.CHANGES_REQUESTED:
                task = self.store.update_work_item(
                    task_id,
                    state=TaskState.ASSIGNED.value,
                    summary=(
                        f"CHANGES REQUESTED: {reason.strip()}\n\nPrevious submission: {task_before_decision['summary']}"
                    ),
                )
            else:
                task = self.store.update_work_item(
                    task_id,
                    state=TaskState.AWAITING_APPROVAL.value,
                )
            self.store.publish_event(
                f"approval.{status.value}",
                approval_id,
                {"task_id": task_id, "reason": reason, "actor": actor},
            )
            self.store.audit(
                actor,
                "decide_approval",
                "approval",
                approval_id,
                status.value,
                {"reason": reason},
            )
        return {"approval": approval, "task": task}

    def record_cost(
        self,
        task_id: str,
        agent_id: str,
        amount_cents: int,
        category: str,
        units: float = 0,
        unit_name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task = self._task(task_id)
        if agent_id != task["owner_id"]:
            raise GovernanceError("Cost owner must match the assigned employee")
        if amount_cents < 0 or task["spent_cents"] + amount_cents > task["budget_cents"]:
            self.store.audit(agent_id, "record_cost", "task", task_id, "denied", {"amount_cents": amount_cents})
            raise GovernanceError("Cost would exceed the task budget")
        self.store.record_cost(
            {
                "id": _id("cost"),
                "task_id": task_id,
                "agent_id": agent_id,
                "category": category,
                "amount_cents": amount_cents,
                "units": units,
                "unit_name": unit_name,
                "metadata": metadata or {},
            }
        )
        self.store.publish_event(
            "cost.recorded", task_id, {"agent_id": agent_id, "amount_cents": amount_cents, "category": category}
        )
        return self._task(task_id)

    def pause_agent(self, agent_id: str, reason: str, actor: str = "jarvis") -> dict[str, Any]:
        """Immediately stop an employee and block any work currently in progress."""
        if actor not in {"jarvis", self.founder_id}:
            raise GovernanceError("Only JARVIS or the founder may pause an employee")
        if agent_id == "jarvis":
            raise GovernanceError("JARVIS can only be stopped through the founder's manual shutdown procedure")
        if agent_id not in AGENTS_BY_ID:
            raise GovernanceError(f"Unknown Amaura agent: {agent_id}")
        if not reason.strip():
            raise GovernanceError("A pause reason is required")
        agent = self.store.set_agent_enabled(agent_id, False)
        for task in self.list_tasks(owner_id=agent_id):
            if task["state"] == TaskState.IN_PROGRESS.value:
                self.store.update_work_item(
                    task["id"],
                    state=TaskState.BLOCKED.value,
                    summary=f"PAUSED BY {actor.upper()}: {reason.strip()}\n\n{task['summary']}",
                )
                self.store.publish_event(
                    "task.blocked", task["id"], {"reason": "employee_paused", "agent_id": agent_id}
                )
        self.store.publish_event("agent.paused", agent_id, {"reason": reason, "actor": actor})
        self.store.audit(actor, "pause_agent", "agent", agent_id, "allowed", {"reason": reason})
        return agent

    def resume_agent(self, agent_id: str, reason: str, actor: str) -> dict[str, Any]:
        """Restore a paused employee using founder authority."""
        if actor != self.founder_id:
            raise GovernanceError("Only the founder may resume a paused employee")
        if not reason.strip():
            raise GovernanceError("A resume reason is required")
        agent = self.store.set_agent_enabled(agent_id, True)
        self.store.publish_event("agent.resumed", agent_id, {"reason": reason, "actor": actor})
        self.store.audit(actor, "resume_agent", "agent", agent_id, "allowed", {"reason": reason})
        return agent

    def record_decision(
        self,
        *,
        decision: str,
        context: str,
        options: list[str],
        chosen_option: str,
        reason: str,
        actor: str,
        review_date: str | None = None,
    ) -> str:
        if actor not in {"jarvis", self.founder_id}:
            raise GovernanceError("Only JARVIS or the founder may record institutional decisions")
        if chosen_option not in options:
            raise GovernanceError("Chosen option must appear in the options considered")
        decision_id = _id("decision")
        self.store.record_decision(
            {
                "id": decision_id,
                "decision": decision,
                "context": context,
                "options": options,
                "chosen_option": chosen_option,
                "reason": reason,
                "owner": actor,
                "review_date": review_date,
            }
        )
        self.store.publish_event("decision.recorded", decision_id, {"decision": decision, "owner": actor})
        self.store.audit(actor, "record_decision", "decision", decision_id, "allowed")
        return decision_id

    def reconcile_outbox_event(
        self,
        event_id: str,
        *,
        resolution: str,
        reason: str,
        provider_receipt: ProviderReceipt | dict[str, Any] | None = None,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Resolve an ambiguous provider call through an explicit founder decision.

        An uncertain email is never silently retried. A successful resolution needs
        a signed provider receipt bound to the exact approved payload and idempotency
        key; failed and requeue decisions remain fully audited.
        """
        actor = actor or self.founder_id
        if actor != self.founder_id:
            raise GovernanceError("Only the founder may reconcile external provider attempts")
        if resolution not in {"completed", "failed", "requeue"}:
            raise GovernanceError("Resolution must be completed, failed, or requeue")
        if not reason.strip():
            raise GovernanceError("A reconciliation reason is required")

        event = self.store.get_outbox_event(event_id)
        if event["status"] != "reconciliation_required":
            raise GovernanceError("Outbox event is not awaiting reconciliation")

        receipt: ProviderReceipt | None = None
        if resolution == "completed":
            if provider_receipt is None:
                raise GovernanceError("A signed provider receipt is required to mark an ambiguous action completed")
            raw_receipt = (
                provider_receipt
                if isinstance(provider_receipt, ProviderReceipt)
                else ProviderReceipt.from_dict(provider_receipt)
            )
            if event["operation"] == "send_email":
                expected_payload = {
                    "recipient": event["payload"].get("recipient", ""),
                    "subject": event["payload"].get("subject", ""),
                    "body": event["payload"].get("body", ""),
                }
                allowed_providers = {"gmail", "n8n"}
                allowed_statuses = {"sent"}
            elif event["operation"] == "send_imessage":
                expected_payload = {
                    "recipient": event["payload"].get("recipient", ""),
                    "body": event["payload"].get("body", ""),
                }
                allowed_providers = {"imessage"}
                allowed_statuses = {"sent"}
            elif event["operation"] == "sync_crm":
                expected_payload = {
                    "lead_id": event["payload"].get("lead_id", ""),
                    "data": event["payload"].get("data", {}),
                }
                allowed_providers = {"n8n"}
                allowed_statuses = {"synced"}
            elif event["operation"] == "create_private_draft":
                expected_payload = event["payload"]
                allowed_providers = {"private-publication"}
                allowed_statuses = {"private", "draft"}
            elif event["operation"] == "publish_content":
                expected_payload = event["payload"]
                allowed_providers = {
                    "approved-publication",
                    "youtube",
                    "instagram",
                    "linkedin",
                    "x",
                    "github",
                    "blog",
                }
                allowed_statuses = {"public", "published"}
            else:
                raise GovernanceError(f"No reconciliation contract exists for operation: {event['operation']}")
            if raw_receipt.provider not in allowed_providers:
                raise GovernanceError("Provider receipt is not allowed for this operation")
            receipt = verify_provider_receipt(
                raw_receipt,
                expected_operation=event["operation"],
                expected_idempotency_key=event["idempotency_key"],
                expected_payload=expected_payload,
            )
            if receipt.status not in allowed_statuses:
                raise GovernanceError("Provider receipt does not prove the requested completion state")

        message_id = str(event["payload"].get("message_id", "")).strip()
        publication_id = str(event["payload"].get("publication_id", "")).strip()
        details = {
            "resolution": resolution,
            "reason": reason.strip(),
            "operation": event["operation"],
            "provider": receipt.provider if receipt else event["provider"],
            "message_id": message_id,
            "publication_id": publication_id,
        }
        with self.store.atomic_block():
            if resolution == "completed" and message_id:
                assert receipt is not None
                self.acquisition.confirm_external_send(
                    message_id,
                    actor=actor,
                    provider_receipt=receipt,
                )
            if resolution == "completed" and publication_id:
                assert receipt is not None
                self.distribution.confirm_publication(
                    publication_id,
                    actor=actor,
                    provider_receipt=receipt,
                )

            resolved = self.store.resolve_outbox_reconciliation(
                event_id,
                resolution=resolution,
                receipt=receipt.to_dict() if receipt else None,
                reason=reason.strip(),
            )
            if message_id and resolution in {"failed", "requeue"}:
                self.store.resolve_message_reconciliation(
                    message_id,
                    resolution=resolution,
                )
            if publication_id and resolution == "failed":
                self.store.update_distribution_publication(publication_id, status="failed", error=reason.strip())
            elif publication_id and resolution == "requeue":
                self.store.update_distribution_publication(publication_id, status="enqueued", error=reason.strip())
            self.store.publish_event("outbox.reconciled", event_id, details)
            self.store.audit(actor, "reconcile_outbox", "outbox_event", event_id, "allowed", details)
        return resolved

    def dashboard(self) -> dict[str, Any]:
        dashboard = self.store.dashboard()
        dashboard["acquisition"] = self.acquisition.dashboard()
        dashboard["distribution"] = self.distribution.dashboard()
        dashboard["founder"] = self.founder_name
        dashboard["telemetry"] = {
            "metrics": len(self.store.list_metrics()),
            "open_alerts": len(self.store.list_alerts(status="open")),
        }
        dashboard["doctrine"] = {
            "master": "JARVIS",
            "independent_review": True,
            "evidence_required": True,
            "external_commitments_require_approval": True,
        }
        return dashboard

    def production_readiness(self) -> dict[str, Any]:
        from jarvis.amaura.readiness import production_readiness

        return production_readiness(self)

    def daily_briefing(self) -> dict[str, Any]:
        tasks = self.store.list_work_items(item_type="task", limit=500)
        pending = self.store.list_approvals(ApprovalStatus.PENDING.value)
        now = datetime.now(UTC)
        terminal = {TaskState.COMPLETED.value, TaskState.CANCELLED.value, TaskState.FAILED.value}
        blocked = [task for task in tasks if task["state"] == TaskState.BLOCKED.value]
        completed = [task for task in tasks if task["state"] == TaskState.COMPLETED.value]
        failed = [task for task in tasks if task["state"] == TaskState.FAILED.value]
        stalled = []
        overdue = []
        for task in tasks:
            if task["state"] in terminal:
                continue
            try:
                updated = datetime.fromisoformat(task["updated_at"])
                if (now - updated).total_seconds() >= 86_400:
                    stalled.append(task)
            except (TypeError, ValueError):
                pass
            if task.get("deadline"):
                try:
                    deadline = datetime.fromisoformat(task["deadline"])
                    if deadline.tzinfo is None:
                        deadline = deadline.replace(tzinfo=UTC)
                    if deadline < now:
                        overdue.append(task)
                except (TypeError, ValueError):
                    pass
        budget_alerts = [
            task
            for task in tasks
            if task["budget_cents"]
            and task["spent_cents"] / task["budget_cents"] >= 0.8
            and task["state"] not in terminal
        ]
        costs = sum(task["spent_cents"] for task in tasks)
        founder_decisions = [
            {
                "approval_id": item["id"],
                "task_id": item["task_id"],
                "title": item["payload"].get("title", "Decision required"),
                "risk": item["risk"],
                "action_type": item["action_type"],
            }
            for item in pending[:3]
        ]
        active_objectives = self.store.list_objectives(status="active", limit=100)
        objective_summaries = []
        for objective in active_objectives[:5]:
            target = objective.get("target_value")
            current = float(objective.get("current_value", 0))
            progress = None
            if target is not None and float(target) > 0:
                progress = min(100.0, round(current / float(target) * 100, 2))
            objective_summaries.append(
                {
                    "id": objective["id"],
                    "title": objective["title"],
                    "department": objective["department"],
                    "cadence": objective["cadence"],
                    "current_value": current,
                    "target_value": target,
                    "unit": objective.get("unit", ""),
                    "progress_percent": progress,
                }
            )
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "company_status": self.dashboard(),
            "revenue_opportunities": len(
                [
                    task
                    for task in tasks
                    if task["owner_id"] == "opportunity_scout" and task["state"] != TaskState.CANCELLED.value
                ]
            ),
            "client_actions_requiring_approval": len(
                [
                    item
                    for item in pending
                    if item["action_type"] in {"external_proposal", "client_commitment", "contract_acceptance"}
                ]
            ),
            "projects_completed": len(completed),
            "projects_blocked": len(blocked),
            "stalled_tasks": [
                {"id": task["id"], "title": task["title"], "owner_id": task["owner_id"]} for task in stalled
            ],
            "overdue_tasks": [
                {"id": task["id"], "title": task["title"], "deadline": task["deadline"]} for task in overdue
            ],
            "budget_alerts": [
                {
                    "id": task["id"],
                    "title": task["title"],
                    "spent_cents": task["spent_cents"],
                    "budget_cents": task["budget_cents"],
                }
                for task in budget_alerts
            ],
            "engineering_failures": len(
                [t for t in failed if get_agent(t["owner_id"]).department == "product_engineering"]
            ),
            "research_results": len([t for t in completed if get_agent(t["owner_id"]).department == "ai_research"]),
            "content_ready": len(
                [
                    t
                    for t in tasks
                    if t["action_type"] == "public_publish" and t["state"] == TaskState.AWAITING_APPROVAL.value
                ]
            ),
            "costs_incurred_cents": costs,
            "critical_risks": len(
                [
                    t
                    for t in tasks
                    if t["risk"] == RiskLevel.CRITICAL.value
                    and t["state"] not in {TaskState.COMPLETED.value, TaskState.CANCELLED.value}
                ]
            ),
            "top_founder_decisions": founder_decisions,
            "active_objectives": objective_summaries,
            "autopilot_enabled": self.store.get_control("autopilot_enabled", "1") == "1",
        }

    def list_tasks(self, state: str | None = None, owner_id: str | None = None) -> list[dict[str, Any]]:
        return self.store.list_work_items(item_type="task", state=state, owner_id=owner_id)

    def _task(self, task_id: str) -> dict[str, Any]:
        task = self.store.get_work_item(task_id)
        if task["item_type"] != "task":
            raise GovernanceError(f"Work item '{task_id}' is not a task")
        return task

    def _ensure_agent_enabled(self, agent_id: str) -> None:
        if not self.store.get_agent(agent_id)["enabled"]:
            raise GovernanceError(f"Employee '{agent_id}' is paused and may not receive or execute work")

    def _complete_task(
        self,
        task_id: str,
        *,
        approval_resolution: tuple[str, str, str, str] | None = None,
    ) -> dict[str, Any]:
        # repository_write merges are delegated to gitops, which checks every subprocess returncode.
        task = self.store.get_work_item(task_id)
        merge = None
        if is_software_task(task) and task.get("metadata", {}).get("git_commit"):
            merge = merge_approved_task(task, cleanup=False)
        elif is_software_task(task) and os.environ.get("AMAURA_STRICT_GIT", "0") == "1":
            raise GovernanceError("Strict launch mode blocks repository task completion without an approved Git commit")

        try:
            with self.store.atomic_block():
                if merge is not None:
                    merge_record = self.evidence.put_json(
                        merge.to_dict(),
                        source=f"task:{task_id}:merge_receipt",
                    )
                    merge_evidence = {
                        "type": "git_merge_receipt",
                        "reference": merge_record.reference,
                        "sha256": merge_record.sha256,
                        "byte_length": merge_record.byte_length,
                        "success": True,
                        "excerpt": (f"merged_head={merge.merged_head[:12]} branch={merge.branch}"),
                    }
                    task = self.store.update_work_item(
                        task_id,
                        evidence=[*task["evidence"], merge_evidence],
                        metadata={
                            **dict(task.get("metadata") or {}),
                            "git_merged_head": merge.merged_head,
                            "git_previous_head": merge.previous_head,
                        },
                    )
                    self.store.publish_event(
                        "repository.merged",
                        task_id,
                        {
                            "branch": merge.branch,
                            "previous_head": merge.previous_head,
                            "merged_head": merge.merged_head,
                        },
                    )

                task = self.store.update_work_item(
                    task_id,
                    state=TaskState.COMPLETED.value,
                )
                if approval_resolution is not None:
                    approval_id, decision, actor, reason = approval_resolution
                    self.store.resolve_approval(
                        approval_id,
                        decision,
                        actor,
                        reason,
                    )
                    self.store.publish_event(
                        f"approval.{decision}",
                        approval_id,
                        {"task_id": task_id, "reason": reason, "actor": actor},
                    )
                    self.store.audit(
                        actor,
                        "decide_approval",
                        "approval",
                        approval_id,
                        decision,
                        {"reason": reason},
                    )
                event = (
                    "release.ready"
                    if task["action_type"] in {"production_deployment", "model_release"}
                    else "task.completed"
                )
                self.store.publish_event(
                    event,
                    task_id,
                    {"owner": task["owner_id"], "evidence": len(task["evidence"])},
                )
                self._roll_up(task["parent_id"])
        except Exception:
            if merge is not None:
                rollback_approved_merge(task, merge)
            raise

        if merge is not None:
            try:
                cleanup_task_worktree(task, require_clean=False)
            except Exception as exc:  # cleanup is recoverable; do not undo completed work
                self.store.publish_event(
                    "repository.cleanup_required",
                    task_id,
                    {"branch": merge.branch, "error": str(exc)},
                )
                self.store.audit(
                    "jarvis",
                    "cleanup_task_worktree",
                    "task",
                    task_id,
                    "warning",
                    {"branch": merge.branch, "error": str(exc)},
                )
        return self.store.get_work_item(task_id)

    def _roll_up(self, parent_id: str | None) -> None:
        while parent_id:
            parent = self.store.get_work_item(parent_id)
            children = self.store.list_work_items(parent_id=parent_id, limit=500)
            if children and all(child["state"] == TaskState.COMPLETED.value for child in children):
                self.store.update_work_item(parent_id, state=TaskState.COMPLETED.value)
                self.store.publish_event(f"{parent['item_type']}.completed", parent_id, {"children": len(children)})
                parent_id = parent["parent_id"]
            else:
                break
