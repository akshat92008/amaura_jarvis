"""Typed action facade used only by explicitly enabled experimental graphs."""

from __future__ import annotations

from typing import Any

from jarvis.amaura.bus import CommandBus
from jarvis.amaura.commands import (
    AddEvidenceCommand,
    DecideMessageCommand,
    DeliverApprovedMessageCommand,
    DiscoverLeadCommand,
    ScoreLeadCommand,
    StageMessageCommand,
    TransitionLeadCommand,
    UpdateCRMCommand,
)
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.models import GovernanceError


class AmauraActions:
    """Map graph nodes to typed, atomic Amaura command-bus operations."""

    def __init__(self, control: AmauraControlPlane, worker_id: str = "langgraph-worker"):
        self.control = control
        self.worker_id = worker_id
        self.bus = CommandBus(control)

    def discover_lead(
        self,
        campaign_id: str,
        company_name: str,
        domain_name: str,
        source_url: str,
    ) -> str:
        result = self.bus.execute(
            DiscoverLeadCommand(
                campaign_id=campaign_id,
                company_name=company_name,
                domain=domain_name,
                source_url=source_url,
            )
        )
        return str(result["id"])

    def add_evidence(
        self,
        lead_id: str,
        claim_type: str,
        claim: str,
        source_url: str,
        source_excerpt: str,
        confidence: float,
    ) -> dict[str, Any]:
        return self.bus.execute(
            AddEvidenceCommand(
                lead_id=lead_id,
                claim_type=claim_type,
                claim=claim,
                source_url=source_url,
                source_excerpt=source_excerpt,
                confidence=confidence,
                actor=self.worker_id,
            )
        )

    def score_lead(self, lead_id: str, components: dict[str, int]) -> dict[str, Any]:
        return self.bus.execute(
            ScoreLeadCommand(
                lead_id=lead_id,
                components=components,
                actor=self.worker_id,
            )
        )

    def transition_lead(self, lead_id: str, to_stage: str, reason: str) -> dict[str, Any]:
        return self.bus.execute(
            TransitionLeadCommand(
                lead_id=lead_id,
                to_stage=to_stage,
                actor=self.worker_id,
                reason=reason,
            )
        )

    def stage_message(
        self,
        lead_id: str,
        recipient: str,
        channel: str,
        message_type: str,
        subject: str,
        body: str,
    ) -> str:
        result = self.bus.execute(
            StageMessageCommand(
                lead_id=lead_id,
                recipient=recipient,
                channel=channel,
                message_type=message_type,
                subject=subject,
                body=body,
                actor=self.worker_id,
            )
        )
        return str(result["id"])

    def decide_message(self, message_id: str, approve: bool, reason: str) -> dict[str, Any]:
        if self.worker_id != self.control.founder_id:
            raise GovernanceError("Experimental graph workers cannot exercise founder approval authority")
        return self.bus.execute(
            DecideMessageCommand(
                message_id=message_id,
                actor=self.worker_id,
                approve=approve,
                reason=reason,
            )
        )

    def send_message(self, message_id: str, recipient: str) -> dict[str, Any]:
        return self.bus.execute(
            DeliverApprovedMessageCommand(
                message_id=message_id,
                recipient=recipient,
                actor=self.worker_id,
            )
        )

    def update_crm(self, lead_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        return self.bus.execute(
            UpdateCRMCommand(lead_id=lead_id, fields=fields, actor=self.worker_id)
        )
