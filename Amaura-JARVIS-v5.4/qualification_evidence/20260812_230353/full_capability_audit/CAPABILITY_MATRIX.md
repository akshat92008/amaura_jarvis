# Capability Matrix

Run ID: `20260812_230353`

| Capability | Status | Evidence | Summary |
|---|---|---|---|
| JARVIS CLI help entrypoint | PASS_REAL_E2E | E-CLI-001 | CLI entrypoint responds locally. |
| Amaura status command | PASS_REAL_E2E | E-AMA-STATUS-001 | Control-plane status executed through CLI. |
| Repository pytest suite | FAIL | E-PYTEST-001 | Full checked-in pytest suite. |
| tool:get_project_structure | PASS_CONTROLLED_FIXTURE | E-TOOL-001 | get_project_structure dispatched via registry. |
| tool:find_files | FAIL | E-TOOL-002 | find_files dispatched via registry. |
| tool:search_code | FAIL | E-TOOL-003 | search_code dispatched via registry. |
| tool:read_file | PASS_CONTROLLED_FIXTURE | E-TOOL-004 | read_file dispatched via registry. |
| tool:git_diff | PASS_CONTROLLED_FIXTURE | E-TOOL-005 | git_diff dispatched via registry. |
| tool:amaura_company_status | PASS_CONTROLLED_FIXTURE | E-TOOL-006 | amaura_company_status dispatched via registry. |
| tool:amaura_company_blueprint | PASS_CONTROLLED_FIXTURE | E-TOOL-007 | amaura_company_blueprint dispatched via registry. |
| tool:amaura_capability_health | PASS_CONTROLLED_FIXTURE | E-TOOL-008 | amaura_capability_health dispatched via registry. |
| tool:amaura_resource_inventory | PASS_CONTROLLED_FIXTURE | E-TOOL-009 | amaura_resource_inventory dispatched via registry. |
| tool:amaura_daily_briefing | PASS_CONTROLLED_FIXTURE | E-TOOL-010 | amaura_daily_briefing dispatched via registry. |
| tool:amaura_supervisor_status | PASS_CONTROLLED_FIXTURE | E-TOOL-011 | amaura_supervisor_status dispatched via registry. |
| agent:jarvis | CONFIG_ONLY | E-AGENT-jarvis | Agent profile contract inspected; no live delegation performed. |
| agent:opportunity_scout | CONFIG_ONLY | E-AGENT-opportunity_scout | Agent profile contract inspected; no live delegation performed. |
| agent:lead_qualification | CONFIG_ONLY | E-AGENT-lead_qualification | Agent profile contract inspected; no live delegation performed. |
| agent:proposal | CONFIG_ONLY | E-AGENT-proposal | Agent profile contract inspected; no live delegation performed. |
| agent:crm | CONFIG_ONLY | E-AGENT-crm | Agent profile contract inspected; no live delegation performed. |
| agent:client_communication | CONFIG_ONLY | E-AGENT-client_communication | Agent profile contract inspected; no live delegation performed. |
| agent:product_manager | CONFIG_ONLY | E-AGENT-product_manager | Agent profile contract inspected; no live delegation performed. |
| agent:technical_architect | CONFIG_ONLY | E-AGENT-technical_architect | Agent profile contract inspected; no live delegation performed. |
| agent:repository_intelligence | CONFIG_ONLY | E-AGENT-repository_intelligence | Agent profile contract inspected; no live delegation performed. |
| agent:builder | CONFIG_ONLY | E-AGENT-builder | Agent profile contract inspected; no live delegation performed. |
| agent:patch_engineer | CONFIG_ONLY | E-AGENT-patch_engineer | Agent profile contract inspected; no live delegation performed. |
| agent:qa | CONFIG_ONLY | E-AGENT-qa | Agent profile contract inspected; no live delegation performed. |
| agent:content_strategy | CONFIG_ONLY | E-AGENT-content_strategy | Agent profile contract inspected; no live delegation performed. |
| agent:content_production | CONFIG_ONLY | E-AGENT-content_production | Agent profile contract inspected; no live delegation performed. |
| agent:research_evaluation | CONFIG_ONLY | E-AGENT-research_evaluation | Agent profile contract inspected; no live delegation performed. |
| workflow:client_acquisition | FAIL | E-WORKFLOW-client_acquisition | Workflow template inspected; no live external workflow executed. |
| workflow:content_factory | FAIL | E-WORKFLOW-content_factory | Workflow template inspected; no live external workflow executed. |
| workflow:lead_to_revenue | CONFIG_ONLY | E-WORKFLOW-lead_to_revenue | Workflow template inspected; no live external workflow executed. |
| workflow:software_delivery | CONFIG_ONLY | E-WORKFLOW-software_delivery | Workflow template inspected; no live external workflow executed. |
| workflow:content_campaign | CONFIG_ONLY | E-WORKFLOW-content_campaign | Workflow template inspected; no live external workflow executed. |
| workflow:research_experiment | CONFIG_ONLY | E-WORKFLOW-research_experiment | Workflow template inspected; no live external workflow executed. |
| workflow:company_operating_review | FAIL | E-WORKFLOW-company_operating_review | Workflow template inspected; no live external workflow executed. |
| workflow:product_discovery | FAIL | E-WORKFLOW-product_discovery | Workflow template inspected; no live external workflow executed. |
| workflow:incident_response | FAIL | E-WORKFLOW-incident_response | Workflow template inspected; no live external workflow executed. |
| workflow:research_intelligence_cycle | FAIL | E-WORKFLOW-research_intelligence_cycle | Workflow template inspected; no live external workflow executed. |
| workflow:engineering_reliability_cycle | CONFIG_ONLY | E-WORKFLOW-engineering_reliability_cycle | Workflow template inspected; no live external workflow executed. |
| workflow:distribution_optimization_cycle | FAIL | E-WORKFLOW-distribution_optimization_cycle | Workflow template inspected; no live external workflow executed. |
| workflow:customer_feedback_cycle | FAIL | E-WORKFLOW-customer_feedback_cycle | Workflow template inspected; no live external workflow executed. |
| workflow:community_growth_cycle | FAIL | E-WORKFLOW-community_growth_cycle | Workflow template inspected; no live external workflow executed. |
| workflow:financial_control_cycle | FAIL | E-WORKFLOW-financial_control_cycle | Workflow template inspected; no live external workflow executed. |
| workflow:open_source_release_cycle | CONFIG_ONLY | E-WORKFLOW-open_source_release_cycle | Workflow template inspected; no live external workflow executed. |
| workflow:product_revenue_cycle | FAIL | E-WORKFLOW-product_revenue_cycle | Workflow template inspected; no live external workflow executed. |
| workflow:security_watch_cycle | FAIL | E-WORKFLOW-security_watch_cycle | Workflow template inspected; no live external workflow executed. |
| workflow:venture_opportunity_cycle | FAIL | E-WORKFLOW-venture_opportunity_cycle | Workflow template inspected; no live external workflow executed. |
| workflow:venture_validation_sprint | FAIL | E-WORKFLOW-venture_validation_sprint | Workflow template inspected; no live external workflow executed. |
| workflow:venture_cashflow_cycle | FAIL | E-WORKFLOW-venture_cashflow_cycle | Workflow template inspected; no live external workflow executed. |
| workflow:venture_portfolio_review | FAIL | E-WORKFLOW-venture_portfolio_review | Workflow template inspected; no live external workflow executed. |
| priority:Crawl4AI | CONFIG_ONLY | E-PRIORITY-001 | Crawl4AI investigated for supported local availability. |
| priority:Browser Use | CONFIG_ONLY | E-PRIORITY-002 | Browser Use investigated for supported local availability. |
| priority:SearXNG | NOT_CONFIGURED | E-PRIORITY-003 | SearXNG investigated for supported local availability. |
| priority:Docling | CONFIG_ONLY | E-PRIORITY-004 | Docling investigated for supported local availability. |
| priority:PaddleOCR | CONFIG_ONLY | E-PRIORITY-005 | PaddleOCR investigated for supported local availability. |
| priority:LlamaIndex | CONFIG_ONLY | E-PRIORITY-006 | LlamaIndex investigated for supported local availability. |
| priority:FFmpeg | PASS_REAL_E2E | E-PRIORITY-007 | FFmpeg investigated for supported local availability. |
| priority:Remotion | CONFIG_ONLY | E-PRIORITY-008 | Remotion investigated for supported local availability. |
| priority:faster-whisper | CONFIG_ONLY | E-PRIORITY-009 | faster-whisper investigated for supported local availability. |
| priority:Kokoro | CONFIG_ONLY | E-PRIORITY-010 | Kokoro investigated for supported local availability. |
| priority:ComfyUI | NOT_CONFIGURED | E-PRIORITY-011 | ComfyUI investigated for supported local availability. |
| priority:Langfuse | CONFIG_ONLY | E-PRIORITY-012 | Langfuse investigated for supported local availability. |
| priority:MCP | CONFIG_ONLY | E-PRIORITY-013 | MCP investigated for supported local availability. |
| priority:yt-dlp | CONFIG_ONLY | E-PRIORITY-014 | yt-dlp investigated for supported local availability. |
| priority:voice hardware | CONFIG_ONLY | E-PRIORITY-015 | voice hardware investigated for supported local availability. |
| priority:vision/camera hardware | CONFIG_ONLY | E-PRIORITY-016 | vision/camera hardware investigated for supported local availability. |
| priority:email | NOT_CONFIGURED | E-PRIORITY-017 | email investigated for supported local availability. |
| priority:Telegram | NOT_CONFIGURED | E-PRIORITY-018 | Telegram investigated for supported local availability. |
| priority:WhatsApp/webhooks | NOT_CONFIGURED | E-PRIORITY-019 | WhatsApp/webhooks investigated for supported local availability. |
| priority:CRM | CONFIG_ONLY | E-PRIORITY-020 | CRM investigated for supported local availability. |
| priority:n8n | NOT_CONFIGURED | E-PRIORITY-021 | n8n investigated for supported local availability. |
