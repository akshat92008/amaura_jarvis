"""Domain-Command Bus definitions for the Amaura kernel."""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field


class Command(BaseModel):
    """Base class for all Amaura commands."""
    
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- Control Plane Commands ---

class CreateProgramCommand(Command):
    domain: ClassVar[Literal["control_plane"]] = "control_plane"
    handler: ClassVar[str] = "create_program"
    
    objective: str
    success_metric: str
    workflow_key: str
    title: str | None = None
    priority: int = 3
    deadline: str | None = None
    inputs: dict[str, Any] | None = None
    actor: str = "jarvis"


class StartTaskCommand(Command):
    domain: ClassVar[Literal["control_plane"]] = "control_plane"
    handler: ClassVar[str] = "start_task"
    
    task_id: str
    actor: str = "jarvis"


class SubmitTaskCommand(Command):
    domain: ClassVar[Literal["control_plane"]] = "control_plane"
    handler: ClassVar[str] = "submit_task"
    
    task_id: str
    actor: str
    summary: str
    evidence: list[dict[str, Any]]


class ReviewTaskCommand(Command):
    domain: ClassVar[Literal["control_plane"]] = "control_plane"
    handler: ClassVar[str] = "review_task"
    
    task_id: str
    actor: str
    approve: bool
    findings: str
    attestation: dict[str, Any] | None = None


class DecideApprovalCommand(Command):
    domain: ClassVar[Literal["control_plane"]] = "control_plane"
    handler: ClassVar[str] = "decide_approval"
    
    approval_id: str
    actor: str
    decision: Literal["approved", "rejected", "changes_requested"]
    reason: str


class RecordCostCommand(Command):
    domain: ClassVar[Literal["control_plane"]] = "control_plane"
    handler: ClassVar[str] = "record_cost"
    
    task_id: str
    agent_id: str
    amount_cents: int
    category: str
    units: float = 0
    unit_name: str = ""
    metadata: dict[str, Any] | None = None


class PauseAgentCommand(Command):
    domain: ClassVar[Literal["control_plane"]] = "control_plane"
    handler: ClassVar[str] = "pause_agent"
    
    agent_id: str
    reason: str
    actor: str = "jarvis"


class ResumeAgentCommand(Command):
    domain: ClassVar[Literal["control_plane"]] = "control_plane"
    handler: ClassVar[str] = "resume_agent"
    
    agent_id: str
    reason: str
    actor: str


class RecordDecisionCommand(Command):
    domain: ClassVar[Literal["control_plane"]] = "control_plane"
    handler: ClassVar[str] = "record_decision"
    
    decision: str
    context: str
    options: list[str]
    chosen_option: str
    reason: str
    actor: str
    review_date: str | None = None


# --- Acquisition Pipeline Commands ---

class CreateCampaignCommand(Command):
    domain: ClassVar[Literal["acquisition"]] = "acquisition"
    handler: ClassVar[str] = "create_campaign"
    
    campaign_id: str
    name: str
    target_segment: str
    offer: str
    minimum_score: int
    daily_lead_limit: int
    daily_outreach_limit: int
    daily_followup_limit: int
    maximum_followups: int
    config: dict[str, Any]


class DiscoverLeadCommand(Command):
    domain: ClassVar[Literal["acquisition"]] = "acquisition"
    handler: ClassVar[str] = "discover_lead"
    
    campaign_id: str
    company_name: str
    domain_name: str = Field(alias="domain")
    source_url: str
    country: str = ""
    industry: str = ""
    metadata: dict[str, Any] | None = None


class AddEvidenceCommand(Command):
    domain: ClassVar[Literal["acquisition"]] = "acquisition"
    handler: ClassVar[str] = "add_evidence"
    
    lead_id: str
    claim_type: str
    claim: str
    source_url: str
    source_excerpt: str
    confidence: float
    actor: str = "prospect_research"


class ScoreLeadCommand(Command):
    domain: ClassVar[Literal["acquisition"]] = "acquisition"
    handler: ClassVar[str] = "score_lead"
    
    lead_id: str
    components: dict[str, int]
    actor: str = "qualification_bot"


class TransitionLeadCommand(Command):
    domain: ClassVar[Literal["acquisition"]] = "acquisition"
    handler: ClassVar[str] = "transition"
    
    lead_id: str
    to_stage: str
    actor: str
    reason: str


class StageMessageCommand(Command):
    domain: ClassVar[Literal["acquisition"]] = "acquisition"
    handler: ClassVar[str] = "stage_message"
    
    lead_id: str
    recipient: str
    channel: str
    message_type: str
    subject: str
    body: str
    actor: str = "outreach_writer"


class DecideMessageCommand(Command):
    domain: ClassVar[Literal["acquisition"]] = "acquisition"
    handler: ClassVar[str] = "decide_message"
    
    message_id: str
    actor: str
    approve: bool
    reason: str


class ConfirmExternalSendCommand(Command):
    domain: ClassVar[Literal["acquisition"]] = "acquisition"
    handler: ClassVar[str] = "confirm_external_send"
    
    message_id: str
    provider_receipt: dict[str, Any]
    thread_id: str | None = None
    external_message_id: str | None = None
    actor: str


class DeliverApprovedMessageCommand(Command):
    domain: ClassVar[Literal["acquisition"]] = "acquisition"
    handler: ClassVar[str] = "deliver_approved_message"
    
    message_id: str
    recipient: str
    actor: str
    adapter: Any | None = Field(default=None, exclude=True)


class UpdateCRMCommand(Command):
    domain: ClassVar[Literal["acquisition"]] = "acquisition"
    handler: ClassVar[str] = "update_crm"

    lead_id: str
    fields: dict[str, Any]
    actor: str = "jarvis"


class SetKillSwitchCommand(Command):
    domain: ClassVar[Literal["acquisition"]] = "acquisition"
    handler: ClassVar[str] = "set_kill_switch"
    
    enabled: bool
    actor: str
    reason: str


# --- Content Factory Commands ---

class ContentCreateCampaignCommand(Command):
    domain: ClassVar[Literal["content_factory"]] = "content_factory"
    handler: ClassVar[str] = "create_campaign"
    
    campaign_id: str
    title: str
    audience: str
    business_objective: str
    config: dict[str, Any]


class RegisterAssetCommand(Command):
    domain: ClassVar[Literal["content_factory"]] = "content_factory"
    handler: ClassVar[str] = "register_asset"
    
    campaign_id: str
    asset_type: str
    uri: str
    content: bytes | None = Field(default=None, exclude=True)
    sha256: str = ""
    source_url: str = ""
    creator: str = ""
    licence: str = ""
    status: str = "draft"
    metadata: dict[str, Any] | None = None


class RecordMetricsCommand(Command):
    domain: ClassVar[Literal["content_factory"]] = "content_factory"
    handler: ClassVar[str] = "record_metrics"
    
    campaign_id: str
    platform: str
    window: str
    metrics: dict[str, Any]
    captured_at: str | None = None
