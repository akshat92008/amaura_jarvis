# Evidence Index

Run ID: `20260812_230450`

{
  "REGISTERED_TOOLS": 137,
  "CAPABILITY_ADAPTERS": 46,
  "AGENTS": 15,
  "WORKFLOWS": 22,
  "tool_categories": {
    "coding": 14,
    "advanced_coding": 18,
    "agent_factory": 8,
    "desktop": 12,
    "research": 4,
    "documents": 3,
    "communication": 5,
    "app_builder": 1,
    "tdd_loop": 1,
    "ast_indexer": 3,
    "vision": 7,
    "vector_memory": 6,
    "fleet": 4,
    "browser": 9,
    "hud": 1,
    "duplex_voice": 5,
    "amaura_company_os": 38,
    "total": 137
  }
}

- E-CLI-001: JARVIS CLI help entrypoint => PASS_REAL_E2E
- E-AMA-STATUS-001: Amaura status command => PASS_REAL_E2E
- E-PYTEST-001: Repository pytest suite => FAIL
- E-TOOL-001: tool:get_project_structure => PASS_CONTROLLED_FIXTURE
- E-TOOL-002: tool:find_files => PASS_CONTROLLED_FIXTURE
- E-TOOL-003: tool:search_code => PASS_CONTROLLED_FIXTURE
- E-TOOL-004: tool:read_file => PASS_CONTROLLED_FIXTURE
- E-TOOL-005: tool:git_diff => PASS_CONTROLLED_FIXTURE
- E-TOOL-006: tool:amaura_company_status => PASS_CONTROLLED_FIXTURE
- E-TOOL-007: tool:amaura_company_blueprint => PASS_CONTROLLED_FIXTURE
- E-TOOL-008: tool:amaura_capability_health => PASS_CONTROLLED_FIXTURE
- E-TOOL-009: tool:amaura_resource_inventory => PASS_CONTROLLED_FIXTURE
- E-TOOL-010: tool:amaura_daily_briefing => PASS_CONTROLLED_FIXTURE
- E-TOOL-011: tool:amaura_supervisor_status => PASS_CONTROLLED_FIXTURE
- E-AGENT-jarvis: agent:jarvis => CONFIG_ONLY
- E-AGENT-opportunity_scout: agent:opportunity_scout => CONFIG_ONLY
- E-AGENT-lead_qualification: agent:lead_qualification => CONFIG_ONLY
- E-AGENT-proposal: agent:proposal => CONFIG_ONLY
- E-AGENT-crm: agent:crm => CONFIG_ONLY
- E-AGENT-client_communication: agent:client_communication => CONFIG_ONLY
- E-AGENT-product_manager: agent:product_manager => CONFIG_ONLY
- E-AGENT-technical_architect: agent:technical_architect => CONFIG_ONLY
- E-AGENT-repository_intelligence: agent:repository_intelligence => CONFIG_ONLY
- E-AGENT-builder: agent:builder => CONFIG_ONLY
- E-AGENT-patch_engineer: agent:patch_engineer => CONFIG_ONLY
- E-AGENT-qa: agent:qa => CONFIG_ONLY
- E-AGENT-content_strategy: agent:content_strategy => CONFIG_ONLY
- E-AGENT-content_production: agent:content_production => CONFIG_ONLY
- E-AGENT-research_evaluation: agent:research_evaluation => CONFIG_ONLY
- E-WORKFLOW-client_acquisition: workflow:client_acquisition => FAIL
- E-WORKFLOW-content_factory: workflow:content_factory => FAIL
- E-WORKFLOW-lead_to_revenue: workflow:lead_to_revenue => CONFIG_ONLY
- E-WORKFLOW-software_delivery: workflow:software_delivery => CONFIG_ONLY
- E-WORKFLOW-content_campaign: workflow:content_campaign => CONFIG_ONLY
- E-WORKFLOW-research_experiment: workflow:research_experiment => CONFIG_ONLY
- E-WORKFLOW-company_operating_review: workflow:company_operating_review => FAIL
- E-WORKFLOW-product_discovery: workflow:product_discovery => FAIL
- E-WORKFLOW-incident_response: workflow:incident_response => FAIL
- E-WORKFLOW-research_intelligence_cycle: workflow:research_intelligence_cycle => FAIL
- E-WORKFLOW-engineering_reliability_cycle: workflow:engineering_reliability_cycle => CONFIG_ONLY
- E-WORKFLOW-distribution_optimization_cycle: workflow:distribution_optimization_cycle => FAIL
- E-WORKFLOW-customer_feedback_cycle: workflow:customer_feedback_cycle => FAIL
- E-WORKFLOW-community_growth_cycle: workflow:community_growth_cycle => FAIL
- E-WORKFLOW-financial_control_cycle: workflow:financial_control_cycle => FAIL
- E-WORKFLOW-open_source_release_cycle: workflow:open_source_release_cycle => CONFIG_ONLY
- E-WORKFLOW-product_revenue_cycle: workflow:product_revenue_cycle => FAIL
- E-WORKFLOW-security_watch_cycle: workflow:security_watch_cycle => FAIL
- E-WORKFLOW-venture_opportunity_cycle: workflow:venture_opportunity_cycle => FAIL
- E-WORKFLOW-venture_validation_sprint: workflow:venture_validation_sprint => FAIL
- E-WORKFLOW-venture_cashflow_cycle: workflow:venture_cashflow_cycle => FAIL
- E-WORKFLOW-venture_portfolio_review: workflow:venture_portfolio_review => FAIL
- E-PRIORITY-001: priority:Crawl4AI => CONFIG_ONLY
- E-PRIORITY-002: priority:Browser Use => CONFIG_ONLY
- E-PRIORITY-003: priority:SearXNG => NOT_CONFIGURED
- E-PRIORITY-004: priority:Docling => CONFIG_ONLY
- E-PRIORITY-005: priority:PaddleOCR => CONFIG_ONLY
- E-PRIORITY-006: priority:LlamaIndex => CONFIG_ONLY
- E-PRIORITY-007: priority:FFmpeg => PASS_REAL_E2E
- E-PRIORITY-008: priority:Remotion => CONFIG_ONLY
- E-PRIORITY-009: priority:faster-whisper => CONFIG_ONLY
- E-PRIORITY-010: priority:Kokoro => CONFIG_ONLY
- E-PRIORITY-011: priority:ComfyUI => NOT_CONFIGURED
- E-PRIORITY-012: priority:Langfuse => CONFIG_ONLY
- E-PRIORITY-013: priority:MCP => CONFIG_ONLY
- E-PRIORITY-014: priority:yt-dlp => CONFIG_ONLY
- E-PRIORITY-015: priority:voice hardware => CONFIG_ONLY
- E-PRIORITY-016: priority:vision/camera hardware => CONFIG_ONLY
- E-PRIORITY-017: priority:email => NOT_CONFIGURED
- E-PRIORITY-018: priority:Telegram => NOT_CONFIGURED
- E-PRIORITY-019: priority:WhatsApp/webhooks => NOT_CONFIGURED
- E-PRIORITY-020: priority:CRM => CONFIG_ONLY
- E-PRIORITY-021: priority:n8n => NOT_CONFIGURED
