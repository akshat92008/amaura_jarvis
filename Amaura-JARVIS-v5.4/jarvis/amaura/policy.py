"""Central policy enforcement for Amaura agent actions."""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Any

from jarvis.amaura.models import RISK_ORDER, GovernanceError, PolicyDecision, RiskLevel
from jarvis.amaura.network import validate_public_url
from jarvis.amaura.registry import get_agent

SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[A-Za-z0-9_./+-]{16,}", re.IGNORECASE),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9_]{36}\b"),
    re.compile(r"\bgho_[A-Za-z0-9_]{36}\b"),
    re.compile(r"\bghs_[A-Za-z0-9_]{36}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{82}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9]{10,}\b"),
    re.compile(r"\bsk_live_[A-Za-z0-9]{24,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z-_]{35}\b"),
)

EXTERNAL_ACTIONS = {
    "external_proposal",
    "client_commitment",
    "public_content",
    "public_publish",
    "production_deployment",
    "model_release",
    "payment",
    "refund",
    "contract_acceptance",
    "external_outreach",
}

TOOL_RISK_CLASSES = {
    "R0": {
        "read_file",
        "search_code",
        "find_files",
        "get_project_structure",
        "recall_memory",
        "search_project_memory",
        "search_symbol",
        "amaura_venture_dashboard",
        "amaura_cashflow_dashboard",
        "amaura_venture_recommendation",
    },
    "R1": {"web_search", "web_fetch", "read_pdf"},
    "R2": {
        "write_file",
        "edit_file",
        "create_document",
        "create_presentation",
        "run_command",
        "run_tests",
        "amaura_discover_lead",
        "amaura_record_lead_evidence",
        "amaura_score_lead",
        "amaura_transition_lead",
        "amaura_stage_outreach",
        "amaura_register_content_asset",
        "amaura_record_content_metrics",
        "amaura_update_crm",
        "amaura_register_venture_opportunity",
        "amaura_execute_capability",
        "amaura_record_venture_metric",
        "amaura_cashflow_tick",
        "amaura_record_cashflow_financial",
    },
    "R3": {"send_email", "send_message", "schedule_post", "publish_content", "create_gmail_draft"},
    "R4": {"payment", "refund", "delete_data", "production_deploy"},
}

FORBIDDEN_FILE_PATTERNS = (
    re.compile(r"(^|[/\\])\.env(\..+)?$", re.IGNORECASE),
    re.compile(r".*\.(pem|key|p12|pfx|asc|gpg)$", re.IGNORECASE),
    re.compile(r"(^|[/\\])credentials\.[^/\\]+$", re.IGNORECASE),
    re.compile(r"(^|[/\\])service[-_]account.*\.json$", re.IGNORECASE),
    re.compile(r"(^|[/\\])\.(aws|ssh|gnupg|docker)([/\\]|$)", re.IGNORECASE),
    re.compile(r"(^|[/\\])\.?(npmrc|pypirc|netrc)$", re.IGNORECASE),
)

CAPABILITY_RULES: dict[str, set[str]] = {
    "plan": {
        "amaura_create_program",
        "amaura_task_packet",
        "amaura_list_tasks",
        "amaura_company_status",
        "amaura_company_blueprint",
        "amaura_resource_inventory",
        "amaura_capability_health",
        "amaura_capability_plan",
        "amaura_execute_capability",
        "amaura_cashflow_dashboard",
        "amaura_cashflow_tick",
        "read_file",
        "search_code",
        "get_project_structure",
        "web_search",
        "create_document",
    },
    "delegate": {"amaura_run_task", "amaura_create_program", "amaura_supervisor_tick"},
    "pause": {"amaura_pause_agent"},
    "escalate": {"amaura_review_task"},
    "request_approval": {"amaura_review_task", "amaura_record_decision", "amaura_pending_approvals", "read_file"},
    "configure_campaign": {"amaura_create_campaign", "read_file", "recall_memory"},
    "research": {
        "web_search",
        "web_fetch",
        "read_file",
        "read_pdf",
        "amaura_discover_lead",
        "amaura_record_lead_evidence",
        "search_code",
        "find_files",
        "get_project_structure",
        "amaura_register_content_asset",
        "amaura_register_venture_opportunity",
        "amaura_execute_capability",
    },
    "extract": {"amaura_record_lead_evidence", "web_fetch", "read_file", "amaura_execute_capability"},
    "analyse": {
        "amaura_score_lead",
        "amaura_transition_lead",
        "amaura_record_content_metrics",
        "read_file",
        "recall_memory",
        "analyze_code",
        "web_search",
        "web_fetch",
        "amaura_company_status",
        "amaura_list_tasks",
        "amaura_venture_dashboard",
        "amaura_cashflow_dashboard",
        "amaura_record_venture_metric",
        "amaura_record_cashflow_financial",
        "amaura_venture_recommendation",
    },
    "draft": {"read_file", "create_document", "write_file"},
    "draft_external": {"amaura_stage_outreach", "read_file", "create_document", "amaura_register_content_asset"},
    "draft_public": {
        "amaura_register_content_asset",
        "read_file",
        "create_document",
        "create_presentation",
        "run_command",
    },
    "download_approved_assets": {
        "amaura_register_content_asset",
        "web_search",
        "web_fetch",
        "read_file",
        "amaura_execute_capability",
    },
    "render_media": {"amaura_register_content_asset", "read_file", "run_command", "amaura_execute_capability"},
    "approve_or_reject": {
        "amaura_execute_capability",
        "amaura_transition_lead",
        "amaura_register_content_asset",
        "read_file",
        "search_code",
        "run_tests",
        "lint_code",
        "analyze_code",
        "git_diff",
        "recall_memory",
    },
    "update_crm": {"amaura_transition_lead", "amaura_update_crm", "read_file", "write_file"},
    "read_crm": {"read_file", "write_file", "amaura_transition_lead"},
    "recommend": {
        "read_file",
        "recall_memory",
        "web_fetch",
        "search_code",
        "get_project_structure",
        "analyze_code",
        "amaura_venture_dashboard",
        "amaura_cashflow_dashboard",
        "amaura_venture_recommendation",
    },
    "define_acceptance_criteria": {"read_file", "search_code", "get_project_structure"},
    "analyse_repo": {"read_file", "search_code", "get_project_structure", "analyze_code"},
    "author_adr": {"read_file", "search_code", "get_project_structure", "analyze_code"},
    "read_repo": {
        "read_file",
        "search_code",
        "find_files",
        "get_project_structure",
        "index_codebase_ast",
        "search_symbol",
    },
    "index_repo": {
        "index_codebase_ast",
        "search_symbol",
        "read_file",
        "search_code",
        "find_files",
        "get_project_structure",
    },
    "write_branch": {"write_file", "run_command", "run_tests", "read_file", "search_code"},
    "write_exact_patch": {"edit_file", "diff_files", "read_file"},
    "run_safe_commands": {
        "run_command",
        "run_tests",
        "lint_code",
        "analyze_code",
        "git_diff",
        "read_file",
        "amaura_register_content_asset",
        "create_document",
    },
    "run_sandboxed_experiment": {"run_command", "run_tests"},
    "evaluate": {
        "read_file",
        "read_pdf",
        "web_search",
        "web_fetch",
        "run_command",
        "run_tests",
        "amaura_execute_capability",
    },
    "prioritise": {"read_file", "recall_memory", "amaura_company_status", "amaura_list_tasks"},
    "recommend_pricing": {"read_file", "recall_memory", "amaura_company_status", "amaura_list_tasks"},
    "create_draft_after_approval": {"read_file"},
    "schedule_after_approval": {"read_file"},
    "create_delivery_packet": {"read_file", "write_file", "create_document"},
    "record_demo": {"read_file", "run_command", "amaura_register_content_asset", "amaura_execute_capability"},
    "render_audio": {"read_file", "run_command", "amaura_register_content_asset", "amaura_execute_capability"},
}


# A generic capability executor is intentionally narrowed by capability+operation.
# This prevents a role that can, for example, crawl the web from also invoking
# media generation, engineering handoffs, or arbitrary MCP side effects.
CAPABILITY_OPERATION_PERMISSIONS: dict[tuple[str, str], set[str]] = {
    ("playwright", "extract"): {"research", "extract", "record_demo", "evaluate"},
    ("playwright", "screenshot"): {"research", "record_demo", "render_media", "evaluate", "approve_or_reject"},
    ("crawl4ai", "crawl"): {"research", "extract"},
    ("browser_use", "research"): {"research"},
    ("searxng", "search"): {"research"},
    ("docling", "convert"): {"research", "extract", "evaluate"},
    ("pymupdf", "extract_text"): {"research", "extract", "evaluate", "approve_or_reject"},
    ("pymupdf", "render_page"): {"research", "extract", "evaluate", "approve_or_reject"},
    ("paddleocr", "ocr"): {"research", "extract", "evaluate", "approve_or_reject"},
    ("llamaindex", "chunk"): {"research", "extract", "analyse"},
    ("qdrant_fastembed", "upsert"): {"research", "extract", "analyse"},
    ("qdrant_fastembed", "query"): {"research", "analyse", "recommend", "plan"},
    ("faster_whisper", "transcribe"): {"render_audio", "render_media", "evaluate", "approve_or_reject"},
    ("kokoro", "synthesize"): {"render_audio"},
    ("ffmpeg", "probe"): {"render_audio", "render_media", "record_demo", "evaluate", "approve_or_reject"},
    ("ffmpeg", "transcode"): {"render_audio", "render_media", "record_demo"},
    ("ffmpeg", "burn_subtitles"): {"render_media"},
    ("ffmpeg", "concat"): {"render_media"},
    ("ffmpeg", "mux_audio"): {"render_media", "render_audio"},
    ("remotion", "bootstrap_project"): {"render_media"},
    ("remotion", "lock_project"): {"render_media"},
    ("remotion", "render"): {"render_media"},
    ("image_tools", "resize"): {"render_media", "download_approved_assets", "record_demo"},
    ("image_tools", "thumbnail"): {"render_media", "download_approved_assets"},
    ("yt_dlp", "metadata"): {"research", "download_approved_assets", "render_media"},
    ("yt_dlp", "download"): {"download_approved_assets"},
    ("comfyui", "queue_workflow"): {"render_media"},
    ("comfyui", "run_workflow"): {"render_media"},
    ("comfyui", "history"): {"render_media", "approve_or_reject"},
    ("mcp", "list_tools"): {"plan", "research", "evaluate"},
    # MCP call_tool is deliberately absent: arbitrary MCP side effects are not
    # executable by AI employees. Dedicated, typed adapters should be created
    # for any MCP server that is allowed to mutate external state.
    ("langfuse", "health"): {"plan", "evaluate"},
    ("langfuse", "event"): {"plan", "evaluate"},
    ("antigravity", "prepare_handoff"): {"plan", "define_acceptance_criteria", "analyse_repo", "author_adr"},
}


def tool_risk_class(tool_name: str) -> str:
    for risk_class, names in TOOL_RISK_CLASSES.items():
        if tool_name in names:
            return risk_class
    return "R2"


PATH_ARGUMENTS = {
    "path",
    "file_path",
    "directory",
    "cwd",
    "repo_path",
    "root_dir",
    "project_path",
    "output_path",
}
SHELL_METACHARACTERS = re.compile(r"[;&|><`\n\r]|\$")
SHELL_BACKED_ARGUMENTS = {"run_tests": {"framework", "filter"}, "lint_code": {"linter"}, "git_diff": {"target"}}
SAFE_COMMAND_PREFIXES = (
    ("pytest",),
    ("python", "-m", "pytest"),
    ("python3", "-m", "pytest"),
    ("ruff",),
    ("mypy",),
    ("tsc",),
    ("rg",),
    ("ls",),
    ("git", "status"),
    ("git", "diff"),
    ("git", "log"),
    ("npm", "test"),
    ("npm", "run", "test"),
    ("npm", "run", "build"),
    ("npm", "run", "lint"),
    ("pnpm", "test"),
    ("pnpm", "build"),
    ("pnpm", "lint"),
    ("cargo", "test"),
    ("cargo", "check"),
    ("go", "test"),
)


def _public_http_url(url: str) -> tuple[bool, str]:
    try:
        validate_public_url(url, resolve=False)
    except GovernanceError as exc:
        return False, str(exc)
    else:
        return True, ""


class PolicyEngine:
    """Evaluates authority, tool, data, cost, risk, and secret-handling rules."""

    @staticmethod
    def validate_assignment(task: dict[str, Any]) -> PolicyDecision:
        agent = get_agent(task["owner_id"])
        risk = RiskLevel(task["risk"])
        reasons: list[str] = []
        if RISK_ORDER[risk] > RISK_ORDER[agent.max_risk]:
            reasons.append(f"{agent.name} may not own {risk.value}-risk work")
        if task["budget_cents"] > agent.cost_limit_cents:
            reasons.append(
                f"Task budget {task['budget_cents']}c exceeds {agent.name}'s {agent.cost_limit_cents}c limit"
            )
        if task.get("reviewer_id") == task["owner_id"]:
            reasons.append("No agent may review its own work")
        return PolicyDecision(allowed=not reasons, reasons=tuple(reasons))

    @staticmethod
    def validate_employee_permissions(agent_id: str) -> PolicyDecision:
        agent = get_agent(agent_id)
        task = {
            "id": "contract_check",
            "owner_id": agent_id,
            "state": "in_progress",
            "risk": agent.max_risk.value,
            "budget_cents": 100,
            "action_type": "internal",
            "metadata": {"workspace": "."},
        }
        reasons: list[str] = []
        for tool_name in agent.tools:
            decision = PolicyEngine.validate_tool_action(task, agent_id, tool_name, {})
            for reason in decision.reasons:
                if "requires a matching agent permission scope" in reason or "outside" in reason:
                    reasons.append(f"Tool '{tool_name}' failed permission check for employee '{agent_id}': {reason}")
        return PolicyDecision(allowed=not reasons, reasons=tuple(reasons))

    @staticmethod
    def validate_tool_action(
        task: dict[str, Any], agent_id: str, tool_name: str, args: dict[str, Any]
    ) -> PolicyDecision:
        agent = get_agent(agent_id)
        reasons: list[str] = []
        if task.get("state") != "in_progress":
            reasons.append("Employee tools may run only while the assigned task is in progress")
        if task["owner_id"] != agent_id:
            reasons.append("Only the assigned employee may execute this task")
        if tool_name not in agent.tools:
            reasons.append(f"Tool '{tool_name}' is outside {agent.name}'s approved tool set")
        capability_scopes = {
            scope for permission in agent.permissions for scope in CAPABILITY_RULES.get(permission, set())
        }
        governed_business_tools = {tool for tools in CAPABILITY_RULES.values() for tool in tools}
        if tool_name in governed_business_tools and tool_name not in capability_scopes:
            reasons.append(f"Tool '{tool_name}' requires a matching agent permission scope")
        if tool_name == "amaura_execute_capability" and args:
            capability = str(args.get("capability", "")).strip()
            operation = str(args.get("operation", "")).strip()
            required_permissions = CAPABILITY_OPERATION_PERMISSIONS.get((capability, operation))
            if required_permissions is None:
                reasons.append(
                    f"Capability operation '{capability}.{operation}' is not approved for AI employee execution"
                )
            elif not (set(agent.permissions) & required_permissions):
                reasons.append(
                    f"Capability operation '{capability}.{operation}' requires one of: "
                    + ", ".join(sorted(required_permissions))
                )
        risk_class = tool_risk_class(tool_name)
        if risk_class in {"R3", "R4"}:
            reasons.append(
                f"{risk_class} tool '{tool_name}' must execute through an authenticated founder approval adapter"
            )
        serialized = json.dumps(args, default=str)
        if any(pattern.search(serialized) for pattern in SECRET_PATTERNS):
            reasons.append("Potential credential or secret detected in action payload")
        workspace = Path(task.get("metadata", {}).get("workspace", ".")).expanduser().resolve()
        for key, raw_value in args.items():
            if key not in PATH_ARGUMENTS or not isinstance(raw_value, str) or not raw_value:
                continue
            if SHELL_METACHARACTERS.search(raw_value):
                reasons.append(f"Path argument '{key}' contains unsafe shell characters")
                continue
            candidate = Path(raw_value).expanduser()
            if not candidate.is_absolute():
                candidate = workspace / candidate
            candidate = candidate.resolve()
            if candidate != workspace and workspace not in candidate.parents:
                reasons.append(f"Path argument '{key}' escapes the assigned workspace")
            if any(pattern.search(str(candidate)) for pattern in FORBIDDEN_FILE_PATTERNS) or any(
                pattern.search(raw_value) for pattern in FORBIDDEN_FILE_PATTERNS
            ):
                reasons.append(f"Access to secret/credential file in argument '{key}' is strictly forbidden")
        if tool_name == "web_fetch":
            safe_url, url_reason = _public_http_url(str(args.get("url", "")))
            if not safe_url:
                reasons.append(f"Web fetch blocked: {url_reason}")
        for argument in SHELL_BACKED_ARGUMENTS.get(tool_name, set()):
            value = args.get(argument)
            if isinstance(value, str) and SHELL_METACHARACTERS.search(value):
                reasons.append(f"Shell-backed argument '{argument}' contains unsafe characters")
        if tool_name == "run_tests":
            framework = str(args.get("framework", "")).strip()
            if framework and framework not in {
                "pytest",
                "unittest",
                "jest",
                "vitest",
                "mocha",
                "go",
                "cargo",
                "rspec",
                "phpunit",
            }:
                reasons.append("Test framework is outside the governed allowlist")
        if tool_name == "lint_code":
            linter = str(args.get("linter", "")).strip()
            if linter and linter not in {
                "ruff",
                "flake8",
                "eslint",
                "golangci-lint",
                "clippy",
            }:
                reasons.append("Linter is outside the governed allowlist")
        if tool_name == "git_diff":
            target = str(args.get("target", "")).strip()
            if target.startswith("-") or (target and not re.fullmatch(r"[A-Za-z0-9_./~^:@{}+-]+", target)):
                reasons.append("Git diff target is not a safe revision")
        if tool_name == "run_command":
            command = str(args.get("command", "")).strip()
            if SHELL_METACHARACTERS.search(command):
                reasons.append("Shell operators, substitutions, and redirections are not allowed for company employees")
            try:
                tokens = tuple(shlex.split(command))
            except ValueError:
                tokens = ()
                reasons.append("Command could not be parsed safely")
            if not tokens:
                reasons.append("Empty commands are not allowed")
            elif not any(tokens[: len(prefix)] == prefix for prefix in SAFE_COMMAND_PREFIXES):
                reasons.append("Command is outside the governed test/build/read-only allowlist")
        risk = RiskLevel(task["risk"])
        manual = risk is RiskLevel.CRITICAL or risk_class == "R4"
        requires_approval = (
            manual or risk in {RiskLevel.MEDIUM, RiskLevel.HIGH} or task["action_type"] in EXTERNAL_ACTIONS
        )
        return PolicyDecision(
            allowed=not reasons and not manual,
            requires_approval=requires_approval,
            manual_execution=manual,
            reasons=tuple(reasons or (["Critical actions require explicit manual execution"] if manual else [])),
        )

    @staticmethod
    def completion_gate(task: dict[str, Any]) -> PolicyDecision:
        risk = RiskLevel(task["risk"])
        evidence = task.get("evidence") or []
        reasons: list[str] = []
        if not evidence:
            reasons.append("Completion requires verifiable evidence")
        if task["action_type"] in EXTERNAL_ACTIONS and not evidence:
            reasons.append("No external claim or commitment may proceed without evidence")
        return PolicyDecision(
            allowed=not reasons,
            requires_approval=risk in {RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL}
            or task["action_type"] in EXTERNAL_ACTIONS,
            manual_execution=risk is RiskLevel.CRITICAL,
            reasons=tuple(reasons),
        )

    @staticmethod
    def require_allowed(decision: PolicyDecision) -> None:
        if not decision.allowed:
            raise GovernanceError("; ".join(decision.reasons))
