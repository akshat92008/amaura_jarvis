"""Versioned company policies loaded before relevant agent work."""

from __future__ import annotations

from typing import Any

POLICIES: dict[str, dict[str, Any]] = {
    "core_authority": {
        "version": "1.0",
        "applies_to": ["*"],
        "rules": [
            "The founder owns strategy, truth, financial/legal commitments, reputation, and production risk.",
            "JARVIS is the only company orchestrator and may pause any employee or workflow.",
            "No employee may certify its own work; completion requires evidence and the registered reviewer.",
            "Critical actions require explicit manual execution, not autonomous tool use.",
        ],
    },
    "external_communication": {
        "version": "1.0", "applies_to": ["external_proposal", "client_commitment", "draft_external"],
        "rules": ["Drafts must distinguish facts, assumptions, and recommendations.", "No price, deadline, scope, partnership, or outcome may be promised without founder approval.", "Client communication must use only the approved client record."],
    },
    "pricing_and_discounts": {
        "version": "1.0", "applies_to": ["external_proposal", "client_commitment", "payment", "refund"],
        "rules": ["Pricing must include delivery effort, model/API cost, support burden, risk premium, and margin.", "Discounts and refunds require founder approval and a recorded rationale."],
    },
    "client_data": {
        "version": "1.0", "applies_to": ["client_commitment", "repository_write", "draft_external"],
        "rules": ["Confidential client data stays on approved local models and stores.", "Grant least-privilege access for the shortest required duration.", "Never place credentials, personal data, or confidential code in prompts or logs."],
    },
    "licensing": {
        "version": "1.0", "applies_to": ["repository_write", "research_compute", "model_release", "public_content"],
        "rules": ["Record source and licence for code, datasets, models, and media.", "Reject incompatible or unknown licences.", "Model releases require a licence inventory."],
    },
    "public_claims": {
        "version": "1.0", "applies_to": ["public_content", "public_publish", "model_release"],
        "rules": ["Every number, achievement, benchmark, date, and attribution must link to evidence.", "Preserve limitations and negative results.", "Client material requires documented permission."],
    },
    "model_evaluation": {
        "version": "1.0", "applies_to": ["research_compute", "model_release"],
        "rules": ["No experiment runs without a falsifiable hypothesis, baseline, regression threshold, and budget.", "Accept models only on recorded evaluation suites, never subjective impressions.", "Training and evaluation data must be checked for contamination."],
    },
    "production_deployment": {
        "version": "1.0", "applies_to": ["production_deployment"],
        "rules": ["Production requires test evidence, migration check, health thresholds, and a tested rollback plan.", "Founder approval is mandatory.", "Roll back automatically when approved health thresholds fail."],
    },
    "security_incidents": {
        "version": "1.0", "applies_to": ["incident_response"],
        "rules": ["Contain harm before diagnosis or public communication.", "Preserve logs and an incident timeline.", "Escalate suspected client-data or credential exposure immediately."],
    },
    "credentials": {
        "version": "1.0", "applies_to": ["*"],
        "rules": ["Secrets belong in the configured secrets manager or environment, never source, prompts, artefacts, or logs.", "Rotate exposed credentials and record the incident."],
    },
    "data_retention": {
        "version": "1.0", "applies_to": ["*"],
        "rules": ["Retain only data required for a documented company purpose.", "Deletion of material or client data is high risk and needs founder approval.", "Audit and decision records are immutable."],
    },
    "financial_spending": {
        "version": "1.0", "applies_to": ["research_compute", "payment", "refund", "repository_write"],
        "rules": ["Every cost must name a task, employee, category, amount, and units.", "Stop before the task or employee budget is exceeded.", "Money transfer requires explicit manual founder execution."],
    },
    "content_publication": {
        "version": "1.0", "applies_to": ["public_content", "public_publish"],
        "rules": ["Publishing requires verified sources, sensitivity review, platform policy check, and founder approval.", "Founder Voice content must not imply personal authorship or experience that did not occur."],
    },
    "conflicts_of_interest": {
        "version": "1.0", "applies_to": ["external_proposal", "client_commitment", "public_publish"],
        "rules": ["Disclose material affiliations, incentives, and client conflicts before recommendation or publication."],
    },
    "agent_shutdown": {
        "version": "1.0", "applies_to": ["*"],
        "rules": ["JARVIS may pause an employee on repeated failure, budget breach, policy violation, or unsafe behaviour.", "Shutdown preserves evidence, state, and audit history.", "Only the founder may restore an employee disabled for a critical violation."],
    },
}


def policies_for(action_type: str) -> dict[str, dict[str, Any]]:
    """Return only policies relevant to an action plus universal policy."""
    return {
        key: policy
        for key, policy in POLICIES.items()
        if "*" in policy["applies_to"] or action_type in policy["applies_to"]
    }
