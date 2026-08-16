"""JARVIS tools for operating Amaura Studio's governed AI workforce."""

from __future__ import annotations

import atexit
import json
import threading
from typing import Any

from jarvis.amaura import commands as cmd
from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.executor import GovernedTaskRunner
from jarvis.amaura.supervisor import AmauraSupervisor
from jarvis.amaura.workflows import WORKFLOWS

_CONTROL: AmauraControlPlane | None = None
_LOCK = threading.Lock()


def get_amaura_bus():
    from jarvis.amaura.bus import CommandBus

    return CommandBus(get_control_plane())


def get_control_plane() -> AmauraControlPlane:
    global _CONTROL
    if _CONTROL is None:
        with _LOCK:
            if _CONTROL is None:
                _CONTROL = AmauraControlPlane()
    return _CONTROL


def reset_control_plane() -> None:
    """Close and clear the process-global control plane safely."""
    global _CONTROL
    with _LOCK:
        control = _CONTROL
        _CONTROL = None
    if control is not None:
        control.close()


atexit.register(reset_control_plane)


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, default=str)


AMAURA_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "amaura_company_blueprint",
            "description": "Read the complete Amaura department, workflow, cadence, autonomy, and Mac 8GB operating blueprint.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_resource_inventory",
            "description": "Read the free-first capability catalogue and current local/API/subscription availability.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_company_status",
            "description": "Read the Amaura executive dashboard. JARVIS is the master control plane for all listed employees.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_list_agents",
            "description": "List the governed Amaura v1 workforce with department, authority, tools, cost limit, risk ceiling, and reviewer.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_create_program",
            "description": "As JARVIS, turn a founder objective into a programme, project, milestone, and dependency-ordered employee tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "objective": {"type": "string", "description": "Concrete company outcome to achieve."},
                    "success_metric": {
                        "type": "string",
                        "description": "Measurable threshold proving the programme succeeded.",
                    },
                    "workflow_key": {"type": "string", "enum": sorted(WORKFLOWS)},
                    "title": {"type": "string"},
                    "priority": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
                    "deadline": {"type": "string", "description": "Optional ISO-8601 deadline."},
                    "inputs": {"type": "object", "description": "Workflow inputs, including hypothesis for research."},
                },
                "required": ["objective", "success_metric", "workflow_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_revenue_dashboard",
            "description": "Read the ethical client-acquisition pipeline, campaign, lead, approval, and revenue dashboard.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_create_campaign",
            "description": "Create or update one bounded acquisition campaign with strict daily limits.",
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_id": {"type": "string"},
                    "name": {"type": "string"},
                    "target_segment": {"type": "string"},
                    "offer": {"type": "string"},
                    "minimum_score": {"type": "integer", "minimum": 70, "maximum": 100, "default": 70},
                    "daily_lead_limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
                    "daily_outreach_limit": {"type": "integer", "minimum": 0, "maximum": 50, "default": 3},
                },
                "required": ["campaign_id", "name", "target_segment", "offer"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_discover_lead",
            "description": "Add one unique, publicly sourced campaign lead; duplicate domains return the existing lead.",
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_id": {"type": "string"},
                    "company_name": {"type": "string"},
                    "domain": {"type": "string"},
                    "source_url": {"type": "string"},
                    "country": {"type": "string"},
                    "industry": {"type": "string"},
                },
                "required": ["campaign_id", "company_name", "domain", "source_url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_score_lead",
            "description": "Apply the deterministic 100-point acquisition rubric to a researched lead.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lead_id": {"type": "string"},
                    "campaign_fit": {"type": "integer", "minimum": 0, "maximum": 25},
                    "visible_need": {"type": "integer", "minimum": 0, "maximum": 25},
                    "ability_to_pay": {"type": "integer", "minimum": 0, "maximum": 20},
                    "contactability": {"type": "integer", "minimum": 0, "maximum": 15},
                    "portfolio_match": {"type": "integer", "minimum": 0, "maximum": 15},
                },
                "required": [
                    "lead_id",
                    "campaign_fit",
                    "visible_need",
                    "ability_to_pay",
                    "contactability",
                    "portfolio_match",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_list_tasks",
            "description": "List company tasks, optionally filtered by workflow state or employee ID.",
            "parameters": {
                "type": "object",
                "properties": {"state": {"type": "string"}, "owner_id": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_task_packet",
            "description": "Have JARVIS issue the exact governed context, tools, data, budget, model route, dependencies, and criteria for one task.",
            "parameters": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_run_task",
            "description": "Have JARVIS dispatch one ready task to its assigned specialist employee inside the governed tool, cost, data, evidence, and review boundaries.",
            "parameters": {
                "type": "object",
                "properties": {"task_id": {"type": "string"}, "max_iterations": {"type": "integer", "default": 12}},
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_supervisor_status",
            "description": "Read durable execution leases, queue depth, retries, reviews, and founder approval waits.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_supervisor_tick",
            "description": "Have JARVIS atomically advance one dependency-ready task or independent review with crash recovery.",
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {"type": "string"},
                    "automatic_reviews": {"type": "boolean", "default": True},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_review_task",
            "description": "Trigger the automated independent reviewer for a task. The reviewer identity and decision are derived automatically.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_pending_approvals",
            "description": "List founder approval requests for external, medium-, high-, or critical-risk company actions.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_pause_agent",
            "description": "Have JARVIS immediately pause a misbehaving employee and block its in-progress work while preserving evidence and audit history.",
            "parameters": {
                "type": "object",
                "properties": {"agent_id": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["agent_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_record_decision",
            "description": "Write an institutional decision with context, options, rationale, owner, and review date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "decision": {"type": "string"},
                    "context": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "chosen_option": {"type": "string"},
                    "reason": {"type": "string"},
                    "review_date": {"type": "string"},
                },
                "required": ["decision", "context", "options", "chosen_option", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_daily_briefing",
            "description": "Generate the founder's daily company briefing with costs, blockers, results, risks, and top decisions.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_read_evidence",
            "description": "Read the contents of an evidence record from the vault by its reference.",
            "parameters": {
                "type": "object",
                "properties": {"reference": {"type": "string"}},
                "required": ["reference"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_get_campaign_context",
            "description": "Get detailed context for a campaign.",
            "parameters": {
                "type": "object",
                "properties": {"campaign_id": {"type": "string"}},
                "required": ["campaign_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_record_lead_evidence",
            "description": "Record verified evidence for a lead.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lead_id": {"type": "string"},
                    "claim_type": {"type": "string"},
                    "claim": {"type": "string"},
                    "source_url": {"type": "string"},
                    "source_excerpt": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["lead_id", "claim_type", "claim", "source_url", "source_excerpt", "confidence"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_transition_lead",
            "description": "Transition a lead to a new stage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lead_id": {"type": "string"},
                    "to_stage": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["lead_id", "to_stage", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_stage_outreach",
            "description": "Stage an outreach message for approval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lead_id": {"type": "string"},
                    "recipient": {"type": "string"},
                    "channel": {"type": "string"},
                    "message_type": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["lead_id", "recipient", "channel", "message_type", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_register_content_asset",
            "description": "Register a new content asset.",
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_id": {"type": "string"},
                    "asset_type": {"type": "string"},
                    "uri": {"type": "string"},
                    "sha256": {"type": "string"},
                    "source_url": {"type": "string"},
                    "creator": {"type": "string"},
                    "licence": {"type": "string"},
                    "status": {"type": "string"},
                },
                "required": ["campaign_id", "asset_type", "uri"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_record_content_metrics",
            "description": "Record governed content performance metrics for a measured window.",
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_id": {"type": "string"},
                    "platform": {"type": "string"},
                    "window": {"type": "string", "enum": ["24h", "72h", "7d", "30d"]},
                    "metrics": {"type": "object"},
                    "captured_at": {"type": "string"},
                },
                "required": ["campaign_id", "platform", "window", "metrics"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_send_email",
            "description": "Send a founder-approved email using the configured external integration (n8n or Gmail).",
            "parameters": {
                "type": "object",
                "properties": {"message_id": {"type": "string"}, "recipient": {"type": "string"}},
                "required": ["message_id", "recipient"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_update_crm",
            "description": "Update the external CRM with the latest lead status, expected value, probability, and follow-up date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lead_id": {"type": "string"},
                    "fields": {
                        "type": "object",
                        "description": "CRM fields to update (e.g. status, expected_value, probability, follow_up_date)",
                    },
                },
                "required": ["lead_id", "fields"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_venture_dashboard",
            "description": "Read the separate Amaura Ventures opportunity, experiment, metric, constraint, and portfolio-decision dashboard.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_register_venture_opportunity",
            "description": "Register and deterministically score one source-backed, non-service venture product opportunity that is testable within fourteen days.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "problem": {"type": "string"},
                    "target_user": {"type": "string"},
                    "product_type": {
                        "type": "string",
                        "enum": [
                            "mobile_app",
                            "micro_saas",
                            "web_app",
                            "browser_extension",
                            "developer_tool",
                            "template",
                            "game",
                            "ai_utility",
                            "kdp_book",
                            "digital_download",
                            "template_pack",
                            "content_asset",
                            "affiliate_content",
                            "newsletter",
                        ],
                    },
                    "source": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "object"}},
                    "score_components": {"type": "object"},
                    "estimated_build_days": {"type": "integer", "minimum": 1, "maximum": 14},
                    "monetization": {"type": "string"},
                    "distribution_channel": {"type": "string"},
                    "strategic_fit": {"type": "string"},
                },
                "required": [
                    "title",
                    "problem",
                    "target_user",
                    "product_type",
                    "source",
                    "evidence",
                    "score_components",
                    "estimated_build_days",
                    "monetization",
                    "distribution_channel",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_record_venture_metric",
            "description": "Record one source-backed primary metric for an active Amaura Ventures experiment and calculate the current threshold recommendation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "experiment_id": {"type": "string"},
                    "metric_name": {"type": "string"},
                    "value": {"type": "number"},
                    "source": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "object"}},
                    "captured_at": {"type": "string"},
                },
                "required": ["experiment_id", "metric_name", "value", "source", "evidence"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_capability_plan",
            "description": "Choose the recommended free-first OSS pipeline for research, documents, memory, audio, reels, video, images, or engineering without executing it.",
            "parameters": {
                "type": "object",
                "properties": {"intent": {"type": "string"}},
                "required": ["intent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_capability_health",
            "description": "Inspect OSS capability installed/configured/healthy/execution-ready state and live RAM pressure. Set deep=true for explicit non-destructive smoke probes.",
            "parameters": {
                "type": "object",
                "properties": {"capability": {"type": "string"}, "deep": {"type": "boolean"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_execute_capability",
            "description": "Execute one closed, governed OSS capability operation. Heavy workers start on demand and are serialized on small Macs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "capability": {
                        "type": "string",
                        "enum": [
                            "playwright",
                            "crawl4ai",
                            "browser_use",
                            "searxng",
                            "docling",
                            "pymupdf",
                            "paddleocr",
                            "llamaindex",
                            "qdrant_fastembed",
                            "faster_whisper",
                            "kokoro",
                            "ffmpeg",
                            "remotion",
                            "image_tools",
                            "yt_dlp",
                            "comfyui",
                            "mcp",
                            "langfuse",
                            "antigravity",
                        ],
                    },
                    "operation": {"type": "string"},
                    "params": {"type": "object"},
                },
                "required": ["capability", "operation", "params"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_cashflow_dashboard",
            "description": "Read the Amaura Ventures low-capital cash-flow portfolio, ranked opportunities, economics, founder-time load and action queue.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_cashflow_tick",
            "description": "Generate bounded internal next-action proposals for active Amaura Ventures cash-flow streams. It cannot publish, spend, change pricing or approve external actions.",
            "parameters": {
                "type": "object",
                "properties": {"proposal_limit": {"type": "integer", "minimum": 1, "maximum": 20}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_record_cashflow_financial",
            "description": "Record one source-backed cash-flow financial event (revenue, refund, fee, cost or payout) for an existing Amaura Ventures stream.",
            "parameters": {
                "type": "object",
                "properties": {
                    "stream_id": {"type": "string"},
                    "event_type": {"type": "string", "enum": ["revenue", "refund", "fee", "cost", "payout"]},
                    "amount_cents": {"type": "integer", "minimum": 0},
                    "source": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "object"}},
                    "currency": {"type": "string"},
                    "occurred_at": {"type": "string"},
                },
                "required": ["stream_id", "event_type", "amount_cents", "source", "evidence"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "amaura_venture_recommendation",
            "description": "Calculate the evidence and threshold based continue, kill, iterate, or double-down recommendation for a venture experiment. This does not make the founder decision.",
            "parameters": {
                "type": "object",
                "properties": {"experiment_id": {"type": "string"}},
                "required": ["experiment_id"],
            },
        },
    },
]


def company_blueprint_tool() -> str:
    from jarvis.amaura.company import company_blueprint

    return _json(company_blueprint())


def resource_inventory() -> str:
    from jarvis.amaura.capability_runtime import get_capability_runtime
    from jarvis.amaura.resources import CapabilityRouter

    return _json(
        {
            "resources": CapabilityRouter().inventory(),
            "executors": get_capability_runtime().inventory(),
            "mac_8gb_profile": CapabilityRouter().mac_8gb_profile(),
        }
    )


def capability_plan(intent: str) -> str:
    from jarvis.amaura.capability_runtime import get_capability_runtime

    return _json(get_capability_runtime().plan(intent))


def capability_health(capability: str = "", deep: bool = False) -> str:
    from jarvis.amaura.capability_runtime import get_capability_runtime

    return _json(get_capability_runtime().health(capability, deep=bool(deep)))


def execute_capability(capability: str, operation: str, params: dict) -> str:
    from jarvis.amaura.capability_runtime import get_capability_runtime

    return _json(get_capability_runtime().execute(capability, operation, params))


def company_status() -> str:
    return _json(get_control_plane().dashboard())


def revenue_dashboard() -> str:
    return _json(get_control_plane().acquisition.dashboard())


def create_campaign(
    campaign_id: str,
    name: str,
    target_segment: str,
    offer: str,
    minimum_score: int = 70,
    daily_lead_limit: int = 10,
    daily_outreach_limit: int = 3,
) -> str:
    return _json(
        get_amaura_bus().execute(
            cmd.CreateCampaignCommand(
                campaign_id=campaign_id,
                name=name,
                target_segment=target_segment,
                offer=offer,
                minimum_score=minimum_score,
                daily_lead_limit=daily_lead_limit,
                daily_outreach_limit=daily_outreach_limit,
                daily_followup_limit=0,
                maximum_followups=0,
                config={},
            )
        )
    )


def discover_lead(
    campaign_id: str, company_name: str, domain: str, source_url: str, country: str = "", industry: str = ""
) -> str:
    return _json(
        get_amaura_bus().execute(
            cmd.DiscoverLeadCommand(
                campaign_id=campaign_id,
                company_name=company_name,
                domain=domain,
                source_url=source_url,
                country=country,
                industry=industry,
            )
        )
    )


def score_lead(
    lead_id: str, campaign_fit: int, visible_need: int, ability_to_pay: int, contactability: int, portfolio_match: int
) -> str:
    return _json(
        get_amaura_bus().execute(
            cmd.ScoreLeadCommand(
                lead_id=lead_id,
                components={
                    "campaign_fit": campaign_fit,
                    "visible_need": visible_need,
                    "ability_to_pay": ability_to_pay,
                    "contactability": contactability,
                    "portfolio_match": portfolio_match,
                },
            )
        )
    )


def list_agents() -> str:
    return _json(get_control_plane().store.list_agents())


def create_program(
    objective: str,
    success_metric: str,
    workflow_key: str,
    title: str = "",
    priority: int = 3,
    deadline: str = "",
    inputs: dict | None = None,
) -> str:
    result = get_amaura_bus().execute(
        cmd.CreateProgramCommand(
            objective=objective,
            success_metric=success_metric,
            workflow_key=workflow_key,
            title=title or None,
            priority=priority,
            deadline=deadline or None,
            inputs=inputs or {},
            actor="jarvis",
        )
    )
    return _json(result)


def list_tasks(state: str = "", owner_id: str = "") -> str:
    return _json(get_control_plane().list_tasks(state or None, owner_id or None))


def task_packet(task_id: str) -> str:
    return _json(get_control_plane().task_packet(task_id, actor="jarvis"))


def run_task(task_id: str, max_iterations: int = 12) -> str:
    return _json(GovernedTaskRunner(get_control_plane()).run(task_id, max_iterations))


def supervisor_status() -> str:
    return _json(AmauraSupervisor(get_control_plane(), worker_id="jarvis-tool").status())


def supervisor_tick(workflow_id: str = "", automatic_reviews: bool = True) -> str:
    return _json(
        AmauraSupervisor(
            get_control_plane(),
            worker_id="jarvis-tool",
            automatic_reviews=automatic_reviews,
        ).tick(workflow_id=workflow_id or None)
    )


def review_task(task_id: str) -> str:
    from jarvis.amaura.executor import GovernedReviewRunner

    control = get_control_plane()
    result = GovernedReviewRunner(control).run(task_id)
    return _json(result)


def pending_approvals() -> str:
    return _json(get_control_plane().store.list_approvals("pending"))


def pause_agent(agent_id: str, reason: str) -> str:
    return _json(get_amaura_bus().execute(cmd.PauseAgentCommand(agent_id=agent_id, reason=reason, actor="jarvis")))


def record_decision(
    decision: str, context: str, options: list[str], chosen_option: str, reason: str, review_date: str = ""
) -> str:
    decision_id = get_amaura_bus().execute(
        cmd.RecordDecisionCommand(
            decision=decision,
            context=context,
            options=options,
            chosen_option=chosen_option,
            reason=reason,
            actor="jarvis",
            review_date=review_date or None,
        )
    )
    return _json({"decision_id": decision_id})


def daily_briefing() -> str:
    return _json(get_control_plane().daily_briefing())


def read_evidence(reference: str) -> str:
    try:
        return _json({"content": get_control_plane().evidence.get_text(reference)})
    except Exception as exc:
        return _json({"error": str(exc)})


def get_campaign_context(campaign_id: str) -> str:
    return _json(get_control_plane().store.get_campaign(campaign_id))


def record_lead_evidence(
    lead_id: str, claim_type: str, claim: str, source_url: str, source_excerpt: str, confidence: float
) -> str:
    return _json(
        get_amaura_bus().execute(
            cmd.AddEvidenceCommand(
                lead_id=lead_id,
                claim_type=claim_type,
                claim=claim,
                source_url=source_url,
                source_excerpt=source_excerpt,
                confidence=confidence,
                actor="jarvis",
            )
        )
    )


def transition_lead(lead_id: str, to_stage: str, reason: str) -> str:
    return _json(
        get_amaura_bus().execute(
            cmd.TransitionLeadCommand(lead_id=lead_id, to_stage=to_stage, actor="jarvis", reason=reason)
        )
    )


def stage_outreach(lead_id: str, recipient: str, channel: str, message_type: str, subject: str, body: str) -> str:
    return _json(
        get_amaura_bus().execute(
            cmd.StageMessageCommand(
                lead_id=lead_id,
                recipient=recipient,
                channel=channel,
                message_type=message_type,
                subject=subject,
                body=body,
            )
        )
    )


def register_content_asset(
    campaign_id: str,
    asset_type: str,
    uri: str,
    sha256: str = "",
    source_url: str = "",
    creator: str = "",
    licence: str = "",
    status: str = "draft",
) -> str:
    return _json(
        get_amaura_bus().execute(
            cmd.RegisterAssetCommand(
                campaign_id=campaign_id,
                asset_type=asset_type,
                uri=uri,
                sha256=sha256,
                source_url=source_url,
                creator=creator,
                licence=licence,
                status=status,
            )
        )
    )


def record_content_metrics(campaign_id: str, platform: str, window: str, metrics: dict, captured_at: str = "") -> str:
    return _json(
        get_amaura_bus().execute(
            cmd.RecordMetricsCommand(
                campaign_id=campaign_id,
                platform=platform,
                window=window,
                metrics=metrics,
                captured_at=captured_at or None,
            )
        )
    )


def venture_dashboard() -> str:
    from jarvis.amaura.ventures import VentureStudio

    return _json(VentureStudio(get_control_plane()).dashboard())


def register_venture_opportunity(
    title: str,
    problem: str,
    target_user: str,
    product_type: str,
    source: str,
    evidence: list[dict],
    score_components: dict,
    estimated_build_days: int,
    monetization: str,
    distribution_channel: str,
    strategic_fit: str = "",
) -> str:
    from jarvis.amaura.ventures import VentureStudio

    return _json(
        VentureStudio(get_control_plane()).create_opportunity(
            title=title,
            problem=problem,
            target_user=target_user,
            product_type=product_type,
            source=source,
            evidence=evidence,
            score_components=score_components,
            estimated_build_days=estimated_build_days,
            monetization=monetization,
            distribution_channel=distribution_channel,
            strategic_fit=strategic_fit,
            actor="jarvis",
        )
    )


def record_venture_metric(
    experiment_id: str,
    metric_name: str,
    value: float,
    source: str,
    evidence: list[dict],
    captured_at: str = "",
) -> str:
    from jarvis.amaura.ventures import VentureStudio

    return _json(
        VentureStudio(get_control_plane()).record_metric(
            experiment_id,
            metric_name=metric_name,
            value=value,
            source=source,
            evidence=evidence,
            captured_at=captured_at or None,
            actor="jarvis",
        )
    )


def cashflow_dashboard() -> str:
    from jarvis.amaura.ventures_cashflow import CashflowEngine

    return _json(CashflowEngine(get_control_plane()).dashboard())


def cashflow_tick(proposal_limit: int = 8) -> str:
    from jarvis.amaura.ventures_cashflow import CashflowEngine

    return _json(CashflowEngine(get_control_plane()).tick(actor="jarvis", proposal_limit=proposal_limit))


def record_cashflow_financial(
    stream_id: str,
    event_type: str,
    amount_cents: int,
    source: str,
    evidence: list[dict],
    currency: str = "",
    occurred_at: str = "",
) -> str:
    from jarvis.amaura.ventures_cashflow import CashflowEngine

    return _json(
        CashflowEngine(get_control_plane()).record_financial_event(
            stream_id,
            event_type=event_type,
            amount_cents=amount_cents,
            source=source,
            evidence=evidence,
            currency=currency,
            occurred_at=occurred_at or None,
            actor="jarvis",
        )
    )


def venture_recommendation(experiment_id: str) -> str:
    from jarvis.amaura.ventures import VentureStudio

    return _json(VentureStudio(get_control_plane()).recommend(experiment_id))


def send_email(message_id: str, recipient: str) -> str:
    return _json(
        get_amaura_bus().execute(
            cmd.DeliverApprovedMessageCommand(message_id=message_id, recipient=recipient, actor="jarvis")
        )
    )


def update_crm(lead_id: str, fields: dict) -> str:
    return _json(get_amaura_bus().execute(cmd.UpdateCRMCommand(lead_id=lead_id, fields=fields, actor="jarvis")))


AMAURA_DISPATCH = {
    "amaura_company_blueprint": company_blueprint_tool,
    "amaura_resource_inventory": resource_inventory,
    "amaura_capability_plan": capability_plan,
    "amaura_capability_health": capability_health,
    "amaura_execute_capability": execute_capability,
    "amaura_company_status": company_status,
    "amaura_revenue_dashboard": revenue_dashboard,
    "amaura_create_campaign": create_campaign,
    "amaura_discover_lead": discover_lead,
    "amaura_score_lead": score_lead,
    "amaura_list_agents": list_agents,
    "amaura_create_program": create_program,
    "amaura_list_tasks": list_tasks,
    "amaura_task_packet": task_packet,
    "amaura_run_task": run_task,
    "amaura_supervisor_status": supervisor_status,
    "amaura_supervisor_tick": supervisor_tick,
    "amaura_review_task": review_task,
    "amaura_pending_approvals": pending_approvals,
    "amaura_pause_agent": pause_agent,
    "amaura_record_decision": record_decision,
    "amaura_daily_briefing": daily_briefing,
    "amaura_read_evidence": read_evidence,
    "amaura_get_campaign_context": get_campaign_context,
    "amaura_record_lead_evidence": record_lead_evidence,
    "amaura_transition_lead": transition_lead,
    "amaura_stage_outreach": stage_outreach,
    "amaura_register_content_asset": register_content_asset,
    "amaura_record_content_metrics": record_content_metrics,
    "amaura_send_email": send_email,
    "amaura_update_crm": update_crm,
    "amaura_venture_dashboard": venture_dashboard,
    "amaura_register_venture_opportunity": register_venture_opportunity,
    "amaura_record_venture_metric": record_venture_metric,
    "amaura_cashflow_dashboard": cashflow_dashboard,
    "amaura_cashflow_tick": cashflow_tick,
    "amaura_record_cashflow_financial": record_cashflow_financial,
    "amaura_venture_recommendation": venture_recommendation,
}
