"""Amaura Labs company blueprint and operating cadence."""

from __future__ import annotations

from collections import Counter
from typing import Any

from jarvis.amaura.registry import ALL_AGENTS
from jarvis.amaura.resources import CapabilityRouter
from jarvis.amaura.workflows import WORKFLOWS


DEPARTMENT_MISSIONS = {
    "control_plane": "Translate founder direction into governed programmes, approvals and operating reviews.",
    "strategy": "Choose high-leverage company priorities and measure progress against the mission.",
    "ai_research": "Run reproducible AI research and convert findings into defensible advantages.",
    "product": "Validate painful problems and turn evidence into focused product specifications.",
    "product_engineering": "Build, test, secure and release reliable products.",
    "growth_media": "Create and distribute evidence-backed content that compounds trust and demand.",
    "revenue": "Convert qualified product demand and partnerships into sustainable revenue ethically.",
    "ventures": "Operate a time-boxed startup studio that funds Amaura Labs through focused products without becoming an agency.",
    "customer_success": "Onboard users, close feedback loops and protect retention.",
    "community": "Grow a useful developer and researcher community around Amaura's mission.",
    "operations": "Maintain cadence, documentation, capacity, risk and execution hygiene.",
    "finance": "Track burn, budgets, unit economics and runway without moving funds.",
    "security_legal": "Protect systems, data, licences, claims and company integrity.",
    "delivery": "Handoff accepted commitments into bounded, least-privilege delivery programmes.",
}

OPERATING_CADENCE = {
    "daily": [
        "Generate founder briefing: outcomes, blockers, approvals, costs and today's top three priorities.",
        "Review open security alerts and failed/retried executions.",
        "Advance ready workflow steps and stop work that lacks evidence or authority.",
    ],
    "weekly": [
        "Run company operating review across research, product, engineering, distribution, users and finance.",
        "Select one distribution thesis and one product/research milestone for the next week.",
        "Review agent scorecards and reduce permissions after repeated low-quality or unsafe work.",
    ],
    "monthly": [
        "Review strategy, runway, subscriptions, infrastructure cost and product portfolio.",
        "Archive or kill projects without evidence of strategic or user value.",
        "Update company knowledge, policies and capability-provider decisions.",
    ],
}


def company_blueprint() -> dict[str, Any]:
    counts = Counter(agent.department for agent in ALL_AGENTS)
    router = CapabilityRouter()
    departments = []
    for key, count in sorted(counts.items()):
        departments.append(
            {
                "key": key,
                "mission": DEPARTMENT_MISSIONS.get(key, "Execute governed company work."),
                "employee_count": count,
                "employees": [
                    {"id": agent.agent_id, "name": agent.name, "reviewer": agent.reviewer_id}
                    for agent in ALL_AGENTS
                    if agent.department == key
                ],
            }
        )
    return {
        "company": "Amaura Labs",
        "operating_model": "founder-directed, AI-native, evidence-governed, free-first",
        "employee_count": len(ALL_AGENTS),
        "workflow_count": len(WORKFLOWS),
        "departments": departments,
        "workflows": [
            {"key": workflow.key, "name": workflow.name, "department": workflow.department, "steps": len(workflow.steps)}
            for workflow in WORKFLOWS.values()
        ],
        "cadence": OPERATING_CADENCE,
        "resource_profile": router.mac_8gb_profile(),
        "autonomy_boundary": {
            "autonomous": ["research", "planning", "drafting", "sandbox testing", "internal reporting"],
            "approval_required": ["publishing", "external messaging", "production deployment", "paid usage above policy"],
            "founder_only": ["payments", "legal commitments", "production deletion", "credential grants", "strategy changes"],
        },
    }


__all__ = ["DEPARTMENT_MISSIONS", "OPERATING_CADENCE", "company_blueprint"]
