"""Explicit authority classification for the conversational tool surface.

General chat is intentionally incapable of mutating company or external state.
All consequential work remains available through the governed command bus,
programmes, supervisor, approvals, durable outbox, and reconciliation paths.
"""

from __future__ import annotations

import os
from collections.abc import Iterable

READ_ONLY_TOOLS = frozenset(
    {
        "read_file",
        "list_directory",
        "find_files",
        "search_code",
        "get_project_structure",
        "web_search",
        "web_fetch",
        "read_pdf",
        "recall_memory",
        "search_project_memory",
        "search_symbol",
        "index_codebase_ast",
        "analyze_code",
        "git_status",
        "generate_morning_briefing",
        "amaura_company_status",
        "amaura_company_blueprint",
        "amaura_resource_inventory",
        "amaura_capability_health",
        "amaura_capability_plan",
        "amaura_revenue_dashboard",
        "amaura_list_agents",
        "amaura_list_tasks",
        "amaura_task_packet",
        "amaura_supervisor_status",
        "amaura_pending_approvals",
        "amaura_daily_briefing",
        "amaura_read_evidence",
        "amaura_get_campaign_context",
        "amaura_venture_dashboard",
        "amaura_cashflow_dashboard",
        "amaura_venture_recommendation",
    }
)

GOVERNED_ONLY_TOOLS = frozenset(
    {
        "amaura_create_campaign",
        "amaura_discover_lead",
        "amaura_score_lead",
        "amaura_create_program",
        "amaura_run_task",
        "amaura_supervisor_tick",
        "amaura_review_task",
        "amaura_pause_agent",
        "amaura_record_decision",
        "amaura_record_lead_evidence",
        "amaura_transition_lead",
        "amaura_stage_outreach",
        "amaura_register_content_asset",
        "amaura_record_content_metrics",
        "amaura_send_email",
        "amaura_update_crm",
        "amaura_register_venture_opportunity",
        "amaura_record_venture_metric",
        "amaura_cashflow_tick",
        "amaura_record_cashflow_financial",
        "amaura_execute_capability",
        "write_file",
        "edit_file",
        "run_command",
        "run_tests",
        "lint_code",
        "create_document",
        "create_presentation",
        "send_email",
        "send_message",
        "send_imessage",
        "add_reminder",
        "add_calendar_event",
        "schedule_post",
        "publish_content",
        "create_gmail_draft",
        "payment",
        "refund",
        "delete_data",
        "production_deploy",
        "automate_macos_app",
    }
)


def legacy_tool_mode() -> str:
    mode = os.environ.get("JARVIS_LEGACY_TOOL_MODE", "disabled").strip().lower()
    return mode if mode in {"disabled", "read_only", "full"} else "disabled"


def legacy_tool_allowed(name: str) -> bool:
    if os.environ.get("JARVIS_ENABLE_LEGACY_DIRECT_TOOLS", "0") == "1":
        return True
    mode = legacy_tool_mode()
    if mode == "full":
        return os.environ.get("AMAURA_ENABLE_BREAK_GLASS_LEGACY_TOOLS", "0") == "1"
    if mode == "read_only":
        return name in READ_ONLY_TOOLS
    return False


def unsafe_legacy_tools_exposed(names: Iterable[str]) -> set[str]:
    return {name for name in names if name not in READ_ONLY_TOOLS and legacy_tool_allowed(name)}


__all__ = [
    "GOVERNED_ONLY_TOOLS",
    "READ_ONLY_TOOLS",
    "legacy_tool_allowed",
    "legacy_tool_mode",
    "unsafe_legacy_tools_exposed",
]
