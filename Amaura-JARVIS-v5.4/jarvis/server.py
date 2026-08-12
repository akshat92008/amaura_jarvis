"""
JARVIS Server — Full-featured backend with WebSocket streaming, REST API,
and voice command processing for the dedicated desktop app.

Provides:
  - WebSocket streaming for real-time Jarvis responses
  - REST endpoints for chat, tools, system status, memory
  - Voice command processing pipeline
  - Multi-session support
  - Tool execution with live feedback
"""

import asyncio
from contextlib import asynccontextmanager
import hmac
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from jarvis.agent import JarvisAgent
from jarvis.amaura import commands as cmd
from jarvis.amaura.runtime import load_amaura_env
from jarvis.memory import ConversationMemory
from jarvis.models import DEFAULT_MODEL, list_models
from jarvis.network_security import (
    MIN_API_KEY_LENGTH,
    api_key_matches,
    effective_bind_host,
    is_loopback_host,
    scope_is_remote,
    supplied_api_key,
    validate_bind_security,
)
from jarvis.tools.registry import ALL_TOOL_DEFINITIONS, execute_tool, get_tool_count
from jarvis.amaura.tool_governance import legacy_tool_allowed, legacy_tool_mode
from jarvis.user_memory import UserMemory
from jarvis.voice.engine import VoiceEngine
from jarvis.voice.speaker import Speaker, get_speaker

load_amaura_env()

_RUNTIME_OBSERVABILITY: dict[str, str] = {
    "company_autopilot_state": "stopped",
    "company_autopilot_started_at": "",
    "company_autopilot_last_tick_at": "",
    "company_autopilot_last_status": "",
    "company_autopilot_last_error": "",
    "mission_runner_last_error": "",
    "mission_runner_last_tick_at": "",
    "mission_runner_last_status": "",
    "proactive_last_error": "",
}

# ── App Setup ──────────────────────────────────────────────────────────────────

async def _mission_runner_loop() -> None:
    """Advance durable JARVIS missions independently of originating requests."""
    interval = max(1, min(float(os.environ.get("AMAURA_JARVIS_MISSION_POLL_SECONDS", "5")), 60.0))
    max_goals = max(1, min(int(os.environ.get("AMAURA_JARVIS_MISSION_MAX_GOALS", "3")), 20))
    while True:
        try:
            from jarvis.amaura.mission_runner import MissionRunner
            result = await asyncio.to_thread(MissionRunner(_amaura_control()).tick, max_goals=max_goals)
            _RUNTIME_OBSERVABILITY["mission_runner_last_error"] = ""
            _RUNTIME_OBSERVABILITY["mission_runner_last_tick_at"] = datetime.now().isoformat()
            _RUNTIME_OBSERVABILITY["mission_runner_last_status"] = str(result.get("status") or "unknown")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Durable state is preserved; the next cycle retries. Runner errors
            # are also written by MissionRunner when a specific goal fails.
            _RUNTIME_OBSERVABILITY["mission_runner_last_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
            _RUNTIME_OBSERVABILITY["mission_runner_last_tick_at"] = datetime.now().isoformat()
            _RUNTIME_OBSERVABILITY["mission_runner_last_status"] = "failed"
        await asyncio.sleep(interval)


async def _proactive_cognition_loop() -> None:
    """Continuously refresh JARVIS world insights while the backend is alive."""
    interval = max(15, min(int(os.environ.get("AMAURA_JARVIS_PROACTIVE_INTERVAL_SECONDS", "120")), 3600))
    auto_investigate = os.environ.get("AMAURA_JARVIS_PROACTIVE_INVESTIGATIONS", "0") == "1"
    while True:
        try:
            from jarvis.amaura.cognition import ProactiveCognition
            await asyncio.to_thread(
                ProactiveCognition(_amaura_control()).tick,
                auto_investigate=auto_investigate,
            )
            _RUNTIME_OBSERVABILITY["proactive_last_error"] = ""
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Ambient cognition must never take down the assistant process. The
            # next cycle retries from authoritative CompanyStore state.
            _RUNTIME_OBSERVABILITY["proactive_last_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
        await asyncio.sleep(interval)


async def _company_autopilot_loop() -> None:
    """Run the same durable Company Autopilot used by the daemon while desktop/server is alive."""
    interval = max(15, min(float(os.environ.get("AMAURA_COMPANY_AUTOPILOT_POLL_SECONDS", "60")), 3600.0))
    _RUNTIME_OBSERVABILITY.update({
        "company_autopilot_state": "starting",
        "company_autopilot_started_at": datetime.now().isoformat(),
        "company_autopilot_last_error": "",
    })
    while True:
        await asyncio.sleep(interval)
        try:
            from jarvis.amaura.autopilot import AutonomousCompanyRuntime
            result = await asyncio.to_thread(
                AutonomousCompanyRuntime(_amaura_control(), worker_id="jarvis-desktop-autopilot").tick,
                max_work_units=max(1, min(int(os.environ.get("AMAURA_COMPANY_AUTOPILOT_WORK_UNITS", "1")), 10)),
                max_new_programmes=max(1, min(int(os.environ.get("AMAURA_COMPANY_AUTOPILOT_NEW_PROGRAMMES", "2")), 10)),
                max_signals=max(1, min(int(os.environ.get("AMAURA_COMPANY_AUTOPILOT_SIGNALS", "2")), 10)),
            )
            _RUNTIME_OBSERVABILITY.update({
                "company_autopilot_state": "online" if result.get("status") != "standby" else "standby",
                "company_autopilot_last_tick_at": datetime.now().isoformat(),
                "company_autopilot_last_status": str(result.get("status") or "completed"),
                "company_autopilot_last_error": "",
            })
        except asyncio.CancelledError:
            _RUNTIME_OBSERVABILITY["company_autopilot_state"] = "stopped"
            raise
        except Exception as exc:
            # Keep the desktop/server alive, but expose the real failure instead of
            # making a configured runtime look healthy. The next cycle retries.
            _RUNTIME_OBSERVABILITY.update({
                "company_autopilot_state": "degraded",
                "company_autopilot_last_tick_at": datetime.now().isoformat(),
                "company_autopilot_last_status": "failed",
                "company_autopilot_last_error": f"{type(exc).__name__}: {str(exc)[:500]}",
            })


@asynccontextmanager
async def app_lifespan(_app: FastAPI):
    """Close process-global resources during server shutdown and Mac restarts."""
    proactive_task = None
    mission_task = None
    company_task = None
    if os.environ.get("AMAURA_JARVIS_PROACTIVE", "1") == "1":
        proactive_task = asyncio.create_task(_proactive_cognition_loop(), name="amaura-jarvis-proactive")
    if os.environ.get("AMAURA_JARVIS_MISSION_RUNNER", "1") == "1":
        mission_task = asyncio.create_task(_mission_runner_loop(), name="amaura-jarvis-mission-runner")
    if os.environ.get("AMAURA_COMPANY_AUTOPILOT_RUNTIME", "1") == "1":
        company_task = asyncio.create_task(_company_autopilot_loop(), name="amaura-company-autopilot")
    try:
        yield
    finally:
        for background_task in (company_task, mission_task, proactive_task):
            if background_task is not None:
                background_task.cancel()
                try:
                    await background_task
                except asyncio.CancelledError:
                    pass
        voice_engine.disable()
        speaker.shutdown(timeout=2.0)
        sessions.clear()
        try:
            from jarvis.tools.amaura import reset_control_plane
            reset_control_plane()
        except Exception:
            pass



app = FastAPI(
    title="J.A.R.V.I.S. Server",
    description="Just A Rather Very Intelligent System — Backend API",
    version="5.4.1",
    lifespan=app_lifespan,
)

_cors_origins = [
    origin.strip() for origin in os.environ.get(
        "JARVIS_CORS_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000"
    ).split(",") if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── Global State ───────────────────────────────────────────────────────────────

# Agent sessions (one per WebSocket connection)
sessions: dict[str, JarvisAgent] = {}
voice_engine = VoiceEngine()
speaker = get_speaker()
user_memory = UserMemory()

_GENERAL_MUTATION_PATHS = (
    "/api/chat", "/api/tool", "/api/system/command", "/api/memory",
    "/api/voice/", "/api/fable/generate",
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self' ws: wss:; "
        "object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), geolocation=(), payment=()"
    return response


@app.middleware("http")
async def protect_http_api(request: Request, call_next):
    """Protect every privileged surface and derive remoteness from real sockets."""
    path = request.url.path

    if path.startswith("/api/amaura"):
        if path == "/api/amaura/webhooks/meta":
            return await call_next(request)
        founder_surface = (
            (path.startswith("/api/amaura/approvals/") and path != "/api/amaura/approvals/")
            or path.endswith("/decision")
            or path.endswith("/kill-switch")
            or path.endswith("/deliver")
            or path.endswith("/private-draft")
            or path.endswith("/assisted-sent")
            or path == "/api/amaura/company/bootstrap"
            or path == "/api/amaura/company/autopilot"
            or path.startswith("/api/amaura/company/departments/")
            or path.startswith("/api/amaura/ventures/founder/")
            or path.startswith("/api/amaura/ventures/cashflow/founder/")
        )
        if request.method not in {"OPTIONS"}:
            environment_name = "AMAURA_APPROVAL_KEY" if founder_surface else "AMAURA_OPERATOR_KEY"
            header_name = "X-Amaura-Approval-Key" if founder_surface else "X-Amaura-Operator-Key"
            expected = os.environ.get(environment_name, "")
            if not expected:
                return JSONResponse(status_code=503, content={"detail": f"{environment_name} is not configured"})
            if not hmac.compare_digest(request.headers.get(header_name, ""), expected):
                return JSONResponse(status_code=403, content={"detail": f"Invalid {header_name}"})
        return await call_next(request)

    protected_documentation = path in {"/docs", "/redoc", "/openapi.json"}
    if (path.startswith("/api/") and path != "/api/health") or protected_documentation:
        expected = os.environ.get("JARVIS_API_KEY", "").strip()
        supplied = request.headers.get("X-Jarvis-Key", "").strip()
        remote = scope_is_remote(request.scope)
        local_auth_enabled = os.environ.get("JARVIS_REQUIRE_LOCAL_AUTH", "1") == "1"

        if remote:
            if len(expected) < MIN_API_KEY_LENGTH:
                return JSONResponse(status_code=503, content={"detail": "Strong JARVIS_API_KEY is required for remote access"})
            if not api_key_matches(supplied, expected):
                return JSONResponse(status_code=403, content={"detail": "Invalid JARVIS API key"})
        elif expected and local_auth_enabled:
            if not api_key_matches(supplied, expected):
                return JSONResponse(status_code=403, content={"detail": "Local API authentication required"})
        elif expected and supplied and not api_key_matches(supplied, expected):
            return JSONResponse(status_code=403, content={"detail": "Invalid JARVIS API key"})
        elif request.method not in {"GET", "HEAD", "OPTIONS"} and local_auth_enabled:
            return JSONResponse(status_code=503, content={"detail": "JARVIS_API_KEY is not configured"})

    return await call_next(request)

# ── Models ─────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    model: str = DEFAULT_MODEL
    workspace: str = ""
    autonomy: str = "execute_until_approval"
    coding_backend: str = "antigravity"

class ToolRequest(BaseModel):
    name: str
    args: dict = {}

class VoiceRequest(BaseModel):
    text: str = ""
    session_id: str = "default"
    workspace: str = ""
    autonomy: str = "execute_until_approval"
    coding_backend: str = "antigravity"
    wake_word: str = "Hey JARVIS"

class MemoryRequest(BaseModel):
    fact: str = ""
    key: str = ""
    value: str = ""

class SystemCommand(BaseModel):
    command: str
    args: dict = {}

class AmauraProgrammeRequest(BaseModel):
    objective: str
    success_metric: str
    workflow_key: str
    title: str = ""
    priority: int = 3
    deadline: str = ""
    inputs: dict = {}

class AmauraRunRequest(BaseModel):
    max_iterations: int = 12

class AmauraSupervisorRequest(BaseModel):
    workflow_id: str = ""
    automatic_reviews: bool = True


class AmauraCompanyBootstrapRequest(BaseModel):
    repository_path: str
    product_name: str = "Amaura Labs"
    audience: str = "AI builders, students, developers, researchers and founders"
    target_user: str = "Indian developers, students, researchers and resource-constrained teams"


class AmauraCompanySignalRequest(BaseModel):
    signal_type: str
    source: str
    severity: str = "medium"
    payload: dict = {}
    idempotency_key: str = ""


class AmauraCompanyRunRequest(BaseModel):
    max_work_units: int = 4
    max_new_programmes: int = 3
    max_signals: int = 3
    automatic_reviews: bool = True


class AmauraDepartmentStateRequest(BaseModel):
    enabled: bool
    reason: str


class AmauraAutopilotStateRequest(BaseModel):
    enabled: bool
    reason: str

class AmauraVentureOpportunityRequest(BaseModel):
    title: str
    problem: str
    target_user: str
    product_type: str
    source: str
    evidence: list[dict]
    score_components: dict
    estimated_build_days: int = 14
    monetization: str
    distribution_channel: str
    strategic_fit: str = ""


class AmauraVentureStartRequest(BaseModel):
    opportunity_id: str
    product_name: str
    hypothesis: str
    primary_metric: str
    target_value: float
    kill_threshold: float
    budget_cents: int = 0
    timebox_days: int = 14


class AmauraVentureMetricRequest(BaseModel):
    experiment_id: str
    metric_name: str
    value: float
    source: str
    evidence: list[dict]
    captured_at: str = ""


class AmauraVentureDecisionRequest(BaseModel):
    experiment_id: str
    decision: str
    reason: str


class AmauraCashflowStreamRequest(BaseModel):
    opportunity_id: str
    name: str
    lane: str
    platform: str
    offer: str
    target_user: str
    distribution_channel: str
    price_cents: int = 0
    unit_cost_cents: int = 0
    currency: str = "INR"
    founder_minutes_per_week: int = 60
    automation_level: int = 80
    experiment_id: str = ""


class AmauraCashflowStreamStatusRequest(BaseModel):
    stream_id: str
    status: str
    reason: str


class AmauraCashflowFinancialEventRequest(BaseModel):
    stream_id: str
    event_type: str
    amount_cents: int
    source: str
    evidence: list[dict]
    currency: str = ""
    occurred_at: str = ""
    metadata: dict = Field(default_factory=dict)


class AmauraCashflowActionRequest(BaseModel):
    action_id: str
    status: str
    reason: str
    result: dict = Field(default_factory=dict)


class AmauraReviewRequest(BaseModel):
    reviewer_id: str
    approve: bool
    findings: str
    attestation: dict | None = None

class AmauraApprovalRequest(BaseModel):
    decision: str
    reason: str

class AmauraCampaignRequest(BaseModel):
    campaign_id: str
    name: str
    target_segment: str
    offer: str
    minimum_score: int = 70
    daily_lead_limit: int = 10
    daily_outreach_limit: int = 3
    daily_followup_limit: int = 5
    maximum_followups: int = 2
    config: dict = {}

class AmauraLeadRequest(BaseModel):
    campaign_id: str
    company_name: str
    domain: str
    source_url: str
    country: str = ""
    industry: str = ""
    metadata: dict = Field(default_factory=dict)

class AmauraEvidenceRequest(BaseModel):
    claim_type: str
    claim: str
    source_url: str
    source_excerpt: str
    confidence: float

class AmauraLeadScoreRequest(BaseModel):
    campaign_fit: int
    visible_need: int
    ability_to_pay: int
    contactability: int
    portfolio_match: int

class AmauraTransitionRequest(BaseModel):
    to_stage: str
    actor: str = "jarvis"
    reason: str

class AmauraMessageRequest(BaseModel):
    recipient: str
    channel: str
    message_type: str
    subject: str = ""
    body: str

class AmauraMessageDecisionRequest(BaseModel):
    approve: bool
    reason: str

class AmauraSendConfirmationRequest(BaseModel):
    provider_receipt: dict = {}
    external_message_id: str = ""
    thread_id: str = ""
    actor: str = "jarvis"

class AmauraDeliverMessageRequest(BaseModel):
    recipient: str
    actor: str = "jarvis"

class AmauraKillSwitchRequest(BaseModel):
    enabled: bool
    reason: str

class AmauraIntegrationActionRequest(BaseModel):
    provider: str
    operation: str
    payload: dict
    risk: str | None = None
    idempotency_key: str = ""

class AmauraIntegrationDecisionRequest(BaseModel):
    approve: bool
    reason: str

class AmauraAssistedSendRequest(BaseModel):
    external_message_id: str
    thread_id: str = ""

class AmauraDiscoveryRunRequest(BaseModel):
    campaign_id: str
    query: str
    max_results: int = 10
    country: str = ""
    industry: str = ""

class AmauraInboxSyncRequest(BaseModel):
    max_results: int = 25
    query: str = "is:unread"
    mark_read: bool = True

class AmauraInvoiceRequest(BaseModel):
    client_name: str
    line_items: list[dict]
    due_date: str | None = None
    client_email: str = ""
    currency: str = "INR"
    tax_minor: int = 0
    note: str = ""
    idempotency_key: str = ""

class AmauraInvoiceStatusRequest(BaseModel):
    status: str
    reference: str = ""

class AmauraOutboxReconciliationRequest(BaseModel):
    resolution: str
    reason: str
    provider_receipt: dict = {}

class AmauraContentCampaignRequest(BaseModel):
    campaign_id: str
    title: str
    audience: str
    business_objective: str
    config: dict = {}

class AmauraContentAssetRequest(BaseModel):
    asset_type: str
    uri: str
    sha256: str
    source_url: str = ""
    creator: str = ""
    licence: str = ""
    status: str = "draft"
    metadata: dict = Field(default_factory=dict)

class AmauraContentMetricsRequest(BaseModel):
    platform: str
    window: str
    metrics: dict[str, float]
    captured_at: str = ""

class AmauraPrivatePublicationRequest(BaseModel):
    payload: dict
    idempotency_key: str


class JarvisGoalRequest(BaseModel):
    objective: str
    success_criteria: list[str] = Field(default_factory=list)
    workspace: str = ""
    constraints: list[str] = Field(default_factory=list)
    autonomy: str = "execute_until_approval"
    coding_backend: str = "antigravity"
    priority: int = 3
    max_steps: int = 8
    max_replans: int = 2
    title: str = ""
    metadata: dict = Field(default_factory=dict)


class JarvisGoalRunRequest(BaseModel):
    max_ticks: int = 30
    auto_replan: bool = True


class JarvisGoalLifecycleRequest(BaseModel):
    reason: str = "Founder request"


class JarvisMemoryWriteRequest(BaseModel):
    key: str
    value: object
    scope: str = "project"
    sensitivity: str = "internal"


class JarvisMemoryForgetRequest(BaseModel):
    key: str
    scope: str = "project"


class JarvisAntigravityHandoffRequest(BaseModel):
    objective: str
    repository: str
    plan: list[str]
    acceptance_criteria: list[str]
    allowed_paths: list[str] = Field(default_factory=lambda: ["."])


AMAURA_MUTATING_TOOLS = {
    "amaura_create_program", "amaura_run_task", "amaura_review_task", "amaura_record_decision", "amaura_pause_agent",
    "amaura_create_campaign", "amaura_discover_lead", "amaura_score_lead",
    "amaura_supervisor_tick",
    # Previously missing mutation tools (P0-4)
    "amaura_record_lead_evidence", "amaura_transition_lead",
    "amaura_stage_outreach", "amaura_register_content_asset",
}
AMAURA_PROTECTED_TOOLS = AMAURA_MUTATING_TOOLS | {
    "amaura_list_agents", "amaura_list_tasks", "amaura_task_packet",
    "amaura_pending_approvals", "amaura_daily_briefing", "amaura_revenue_dashboard",
    "amaura_supervisor_status",
    # Sensitive reads also require operator authentication
    "amaura_read_evidence", "amaura_get_campaign_context",
}

# ── Helper Functions ───────────────────────────────────────────────────────────

def get_or_create_agent(session_id: str, model_key: str = DEFAULT_MODEL) -> JarvisAgent:
    """Get or create a bounded local agent session."""
    normalized = "".join(ch for ch in str(session_id) if ch.isalnum() or ch in {"-", "_"})[:96] or "default"
    maximum = max(1, int(os.environ.get("JARVIS_MAX_SESSIONS", "32")))
    if normalized not in sessions and len(sessions) >= maximum:
        # Dict order is insertion order; retire the oldest in-memory session.
        sessions.pop(next(iter(sessions)))
    if normalized not in sessions:
        sessions[normalized] = JarvisAgent(
            model_key=model_key,
            working_dir=os.getcwd(),
        )
    return sessions[normalized]

# ── REST Endpoints ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main HUD interface."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return index_file.read_text()
    return "<h1>J.A.R.V.I.S. HUD — Static files not found.</h1>"


@app.get("/favicon.ico")
async def favicon():
    """Favicon endpoint to prevent 404 noise."""
    from fastapi.responses import Response
    return Response(content="", media_type="image/x-icon")


@app.get("/api/health")
async def health(
    bootstrap_challenge: str = Header(default="", alias="X-Amaura-Bootstrap-Challenge"),
    service_challenge: str = Header(default="", alias="X-Amaura-Service-Challenge"),
    jarvis_key: str = Header(default="", alias="X-Jarvis-Key"),
):
    """Health check with an optional parent/child authenticity proof.

    The desktop parent never sends the bootstrap secret over HTTP.  It sends a
    one-time challenge and verifies an HMAC produced by the child process from
    the secret inherited through its environment.  A process that merely
    pre-binds the loopback port cannot impersonate the backend.
    """
    bootstrap_secret = os.environ.get("AMAURA_DESKTOP_BOOTSTRAP_TOKEN", "")
    proof = ""
    service_proof = ""
    if bootstrap_secret:
        # Startup identity verification must use the inherited bootstrap
        # secret.  Once the desktop has verified that sidecar, its renderer
        # reaches this endpoint only through the authenticated Electron main
        # process bridge, which supplies the regular local API credential.
        # This avoids exposing the bootstrap secret to the renderer while
        # keeping an unauthenticated caller out.
        api_secret = os.environ.get("JARVIS_API_KEY", "")
        bootstrap_authenticated = len(bootstrap_challenge) >= 32
        api_authenticated = bool(api_secret) and api_key_matches(jarvis_key, api_secret)
        if not bootstrap_authenticated and not api_authenticated:
            raise HTTPException(status_code=403, detail="Desktop bootstrap challenge required")
        if bootstrap_authenticated:
            proof = hmac.new(
                bootstrap_secret.encode("utf-8"),
                bootstrap_challenge.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
    if service_challenge:
        service_secret = os.environ.get("JARVIS_API_KEY", "")
        if len(service_secret) < MIN_API_KEY_LENGTH or len(service_challenge) < 32:
            raise HTTPException(status_code=403, detail="Authenticated service challenge required")
        service_proof = hmac.new(
            service_secret.encode("utf-8"),
            service_challenge.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    return {
        "status": "online",
        "version": "5.4.1",
        "timestamp": datetime.now().isoformat(),
        "sessions": len(sessions),
        "tools": get_tool_count(),
        "pid": os.getpid(),
        "bootstrap_proof": proof,
        "service_proof": service_proof,
    }


@app.get("/api/models")
async def get_models():
    """List all available AI models."""
    models = list_models()
    return {"models": models, "default": DEFAULT_MODEL}


@app.post("/api/chat")
async def chat(
    req: ChatRequest,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Unified founder-facing JARVIS endpoint.

    Conversation and executable missions enter the same ExecutiveKernel. A
    mission is only materialized when the Amaura operator credential is valid;
    ordinary conversation remains available under normal JARVIS API auth.
    """
    agent = get_or_create_agent(req.session_id, req.model)
    expected_operator = os.environ.get("AMAURA_OPERATOR_KEY", "")
    operator_valid = bool(
        operator_key and expected_operator and hmac.compare_digest(operator_key, expected_operator)
    )
    if operator_key and not operator_valid:
        raise HTTPException(status_code=403, detail="Invalid Amaura operator key")
    if operator_valid:
        agent.set_amaura_session_token(operator_key)
    try:
        executive = await asyncio.to_thread(
            agent.run_executive,
            req.message,
            control=_amaura_control(),
            session_id=req.session_id,
            workspace=req.workspace,
            autonomy=req.autonomy,
            coding_backend=req.coding_backend,
            allow_missions=operator_valid,
            allow_memory_mutation=operator_valid,
        )
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    provenance = executive.get("model_provenance") or {}
    return {
        "response": executive.get("message", ""),
        "session_id": req.session_id,
        "model": provenance.get("model") or agent.model_cfg["name"],
        "model_key": provenance.get("model") or agent.model_key,
        "model_provider": provenance.get("provider") or "legacy",
        "model_fallback_used": bool(provenance.get("fallback_used")),
        "model_fallback_reason": provenance.get("fallback_reason") or "",
        "model_latency_ms": int(provenance.get("latency_ms") or 0),
        "model_ttft_ms": int(provenance.get("ttft_ms") or 0),
        "intent": executive.get("intent", "conversation"),
        "goal_id": executive.get("goal_id", ""),
        "state": executive.get("state", ""),
        "executive": executive,
    }


@app.post("/api/chat/stream")
async def chat_stream(
    req: ChatRequest,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """NDJSON token stream for the desktop; missions may still emit one final chunk."""
    agent = get_or_create_agent(req.session_id, req.model)
    expected_operator = os.environ.get("AMAURA_OPERATOR_KEY", "")
    operator_valid = bool(
        operator_key and expected_operator and hmac.compare_digest(operator_key, expected_operator)
    )
    if operator_key and not operator_valid:
        raise HTTPException(status_code=403, detail="Invalid Amaura operator key")
    if operator_valid:
        agent.set_amaura_session_token(operator_key)

    async def events():
        loop = asyncio.get_running_loop()
        token_queue: asyncio.Queue[dict | None] = asyncio.Queue()

        def on_token(token: str) -> None:
            loop.call_soon_threadsafe(token_queue.put_nowait, {"type": "token", "content": token})

        async def execute() -> None:
            try:
                executive = await asyncio.to_thread(
                    agent.run_executive,
                    req.message,
                    control=_amaura_control(),
                    session_id=req.session_id,
                    workspace=req.workspace,
                    autonomy=req.autonomy,
                    coding_backend=req.coding_backend,
                    allow_missions=operator_valid,
                    allow_memory_mutation=operator_valid,
                    on_token=on_token,
                )
                provenance = executive.get("model_provenance") or {}
                await token_queue.put({
                    "type": "complete",
                    "response": executive.get("message", ""),
                    "session_id": req.session_id,
                    "model": provenance.get("model") or agent.model_cfg["name"],
                    "model_key": provenance.get("model") or agent.model_key,
                    "model_provider": provenance.get("provider") or "legacy",
                    "model_fallback_used": bool(provenance.get("fallback_used")),
                    "model_fallback_reason": provenance.get("fallback_reason") or "",
                    "model_latency_ms": int(provenance.get("latency_ms") or 0),
                    "model_ttft_ms": int(provenance.get("ttft_ms") or 0),
                    "intent": executive.get("intent", "conversation"),
                    "goal_id": executive.get("goal_id", ""),
                    "state": executive.get("state", ""),
                    "executive": executive,
                })
            except Exception as exc:
                await token_queue.put({"type": "error", "error": str(exc)})
            finally:
                await token_queue.put(None)

        task = asyncio.create_task(execute())
        try:
            while True:
                item = await token_queue.get()
                if item is None:
                    break
                yield json.dumps(item, ensure_ascii=False) + "\n"
        finally:
            await task

    return StreamingResponse(events(), media_type="application/x-ndjson")


@app.post("/api/tool")
async def execute_tool_endpoint(
    req: ToolRequest,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Break-glass direct execution for authenticated local debugging only."""
    direct_enabled = os.environ.get("JARVIS_ENABLE_LEGACY_DIRECT_TOOLS", "0") == "1"
    break_glass = os.environ.get("AMAURA_ENABLE_BREAK_GLASS_LEGACY_TOOLS", "0") == "1"
    if not direct_enabled or not break_glass or legacy_tool_mode() != "full":
        raise HTTPException(
            status_code=403,
            detail="Direct tool execution is disabled. Use a governed Amaura programme.",
        )
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    if not legacy_tool_allowed(req.name):
        raise HTTPException(status_code=403, detail="Tool is not permitted by the active legacy policy")
    result = execute_tool(req.name, req.args)
    return {"result": result, "tool": req.name}


@app.get("/api/tools")
async def list_tools():
    """List all available tools with descriptions."""
    tools = []
    for t in ALL_TOOL_DEFINITIONS:
        name = t["function"]["name"]
        if not legacy_tool_allowed(name):
            continue
        tools.append({
            "name": name,
            "description": t["function"]["description"],
        })
    return {"tools": tools, "count": len(tools)}


@app.get("/api/system")
async def system_info():
    """Get system information."""
    from jarvis.tools.desktop import tool_get_system_info
    info = tool_get_system_info()
    return {"info": info}


@app.post("/api/system/command")
async def system_command(
    req: SystemCommand,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Execute a desktop command only through explicit authenticated break-glass mode."""
    direct_enabled = os.environ.get("JARVIS_ENABLE_LEGACY_DIRECT_TOOLS", "0") == "1"
    break_glass = os.environ.get("AMAURA_ENABLE_BREAK_GLASS_LEGACY_TOOLS", "0") == "1"
    if not direct_enabled or not break_glass or legacy_tool_mode() != "full":
        raise HTTPException(status_code=403, detail="Desktop command execution is disabled")
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.tools.desktop import DESKTOP_DISPATCH
    if req.command in DESKTOP_DISPATCH and legacy_tool_allowed(req.command):
        result = execute_tool(req.command, req.args)
        return {"result": result}
    return JSONResponse(
        status_code=404,
        content={"error": f"Unknown command: {req.command}"},
    )


@app.get("/api/memory")
async def get_memory():
    """Read the unified JARVIS personal-memory surface.

    Legacy UserMemory data remains queryable through UnifiedMemoryService, but
    new writes use CompanyStore as the canonical executive memory authority.
    """
    from jarvis.amaura.cognition import UnifiedMemoryService

    service = UnifiedMemoryService(_amaura_control())
    items = service.list(scope="personal", limit=300)
    return {"summary": f"{len(items)} personal memory item(s)", "items": items, "facts": [row.get("value") for row in items]}


@app.post("/api/memory")
async def update_memory(
    req: MemoryRequest,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Update canonical personal memory through the unified memory service."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.cognition import UnifiedMemoryService

    service = UnifiedMemoryService(_amaura_control())
    if req.fact:
        key = hashlib.sha256(req.fact.encode("utf-8")).hexdigest()[:20]
        item = service.remember(key=f"fact_{key}", value=req.fact, scope="personal", actor="founder", source="legacy_api")
        return {"status": "added", "fact": req.fact, "memory": item}
    if req.key:
        item = service.remember(key=req.key, value=req.value, scope="personal", actor="founder", source="legacy_api")
        return {"status": "updated", "key": req.key, "value": req.value, "memory": item}
    return JSONResponse(status_code=400, content={"error": "Provide fact or key/value"})


@app.delete("/api/memory")
async def clear_memory(
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Clear personal executive memory only; company truth/audit data is preserved."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.cognition import UnifiedMemoryService

    removed = UnifiedMemoryService(_amaura_control()).clear_scope(scope="personal", actor="founder")
    return {"status": "cleared", "removed": removed}


@app.get("/api/conversations")
async def list_conversations():
    """List saved conversations."""
    mem = ConversationMemory()
    convs = mem.list_conversations(limit=20)
    return {"conversations": convs}


@app.post("/api/voice/speak")
async def voice_speak(req: VoiceRequest):
    """Make Jarvis speak text aloud."""
    speaker.speak_async(req.text)
    return {"status": "speaking", "text": req.text[:100]}


@app.post("/api/voice/stop")
async def voice_stop():
    """Stop current speech."""
    speaker.stop()
    return {"status": "stopped"}


@app.post("/api/voice/command")
async def voice_command(
    req: VoiceRequest,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Route transcribed speech through the same ExecutiveKernel as text chat."""
    agent = get_or_create_agent(req.session_id, DEFAULT_MODEL)
    expected = os.environ.get("AMAURA_OPERATOR_KEY", "")
    operator_valid = bool(operator_key and expected and hmac.compare_digest(operator_key, expected))
    if operator_key and not operator_valid:
        raise HTTPException(status_code=403, detail="Invalid Amaura operator key")
    if operator_valid:
        agent.set_amaura_session_token(operator_key)
    executive = await asyncio.to_thread(
        agent.run_executive,
        req.text,
        control=_amaura_control(),
        session_id=req.session_id,
        workspace=req.workspace,
        autonomy=req.autonomy,
        coding_backend=req.coding_backend,
        allow_missions=operator_valid,
        allow_memory_mutation=operator_valid,
    )
    response_text = str(executive.get("message") or "")
    if response_text:
        speaker.speak_async(response_text)
    return executive


@app.post("/api/voice/session/start")
async def start_voice_session(
    req: VoiceRequest,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Start the backend microphone loop routed through the authenticated ExecutiveKernel."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.voice.duplex_voice import configure_voice_command_handler, start_duplex_voice_session

    agent = get_or_create_agent(req.session_id, DEFAULT_MODEL)
    agent.set_amaura_session_token(operator_key)
    control = _amaura_control()

    def handle_voice_text(text: str) -> str:
        result = agent.run_executive(
            text,
            control=control,
            session_id=req.session_id,
            workspace=req.workspace,
            autonomy=req.autonomy,
            coding_backend=req.coding_backend,
            allow_missions=True,
            allow_memory_mutation=True,
        )
        return str(result.get("message") or "")

    configure_voice_command_handler(handle_voice_text)
    return {"status": "started", "detail": start_duplex_voice_session(req.wake_word)}


@app.post("/api/voice/session/stop")
async def stop_voice_session(
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.voice.duplex_voice import configure_voice_command_handler, stop_duplex_voice_session

    detail = stop_duplex_voice_session()
    configure_voice_command_handler(None)
    return {"status": "stopped", "detail": detail}


@app.get("/api/voice/session/status")
async def voice_session_status(
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.voice.duplex_voice import get_voice_session_status

    return {"status": get_voice_session_status()}


@app.get("/api/voice/voices")
async def list_voices():
    """List available macOS voices."""
    voices = Speaker.list_voices()
    return {"voices": voices}


@app.post("/api/voice/set")
async def set_voice(req: VoiceRequest):
    """Change the TTS voice."""
    speaker.set_voice(req.text)
    return {"status": "set", "voice": speaker.voice}


# ── Fable-5 Engine REST Endpoints ──────────────────────────────────────────────

def _require_fable_enabled() -> None:
    if os.environ.get("JARVIS_ENABLE_FABLE", "0") != "1":
        raise HTTPException(
            status_code=403,
            detail="Legacy Fable execution is disabled. Use a governed Amaura engineering programme.",
        )


@app.get("/api/fable/status")
async def fable_status():
    """Check Fable-5 Engine status."""
    _require_fable_enabled()
    from jarvis.fable_engine import MultiProviderRouter
    router = MultiProviderRouter()
    return {
        "status": "online",
        "engine": "Claude Fable 5 Mythos-Class Adaptive Reasoning Engine",
        "providers": router.get_available_providers(),
    }


@app.get("/api/fable/workspace")
async def fable_workspace():
    """Get AST symbol graph and workspace files."""
    _require_fable_enabled()
    from jarvis.fable_engine import ASTIndexer, WorkspaceExecutor
    executor = WorkspaceExecutor()
    indexer = ASTIndexer()
    files = executor.list_workspace()
    symbols = indexer.build_symbol_graph()
    return {"files": files, "symbols": symbols}


@app.post("/api/fable/generate")
async def fable_generate(req: ChatRequest):
    """Run Fable-5 CoT reasoning planning, generation, and self-healing verification."""
    _require_fable_enabled()
    agent = get_or_create_agent(req.session_id, model_key="fable-5-reasoning")
    result = await asyncio.to_thread(agent.run_fable_reasoning, req.message)
    return result


# ── Amaura Studio Company OS ──────────────────────────────────────────────────

def _amaura_bus():
    from jarvis.amaura.bus import CommandBus
    return CommandBus(_amaura_control())


def _amaura_control():
    from jarvis.tools.amaura import get_control_plane
    return get_control_plane()


def _require_amaura_key(environment_name: str, supplied: str, authority: str) -> None:
    expected = os.environ.get(environment_name, "")
    if not expected:
        raise HTTPException(status_code=503, detail=f"{environment_name} is not configured")
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail=f"Invalid Amaura {authority} key")


def _resolve_reviewer_from_key(reviewer_key: str) -> str | None:
    """Resolve reviewer identity exclusively from a configured secret key."""
    from jarvis.amaura.auth import resolve_reviewer_identity
    return resolve_reviewer_identity(reviewer_key)



@app.get("/api/amaura/company/status")
async def amaura_company_status(
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Return the full objective, signal, circuit-breaker and run state."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.company_autonomy import CompanyAutonomyEngine

    return CompanyAutonomyEngine(_amaura_control()).status()


@app.post("/api/amaura/company/bootstrap")
async def amaura_company_bootstrap(
    req: AmauraCompanyBootstrapRequest,
    approval_key: str = Header(default="", alias="X-Amaura-Approval-Key"),
):
    """Create the founder-approved objective portfolio for every company department."""
    _require_amaura_key("AMAURA_APPROVAL_KEY", approval_key, "founder approval")
    from jarvis.amaura.company_autonomy import CompanyAutonomyEngine

    try:
        return CompanyAutonomyEngine(_amaura_control()).bootstrap_company(
            repository_path=req.repository_path,
            product_name=req.product_name,
            audience=req.audience,
            target_user=req.target_user,
        )
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/amaura/company/signals")
async def amaura_company_signals(
    status: str = "",
    signal_type: str = "",
    limit: int = 100,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """List durable company signals and their generated programmes."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    return {
        "signals": _amaura_control().store.list_company_signals(
            status=status or None,
            signal_type=signal_type or None,
            limit=limit,
        )
    }


@app.post("/api/amaura/company/signals")
async def amaura_company_ingest_signal(
    req: AmauraCompanySignalRequest,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Ingest a source-linked, idempotent company signal."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.company_autonomy import CompanyAutonomyEngine

    try:
        return CompanyAutonomyEngine(_amaura_control()).ingest_signal(
            signal_type=req.signal_type,
            source=req.source,
            severity=req.severity,
            payload=req.payload,
            idempotency_key=req.idempotency_key or None,
            actor="jarvis",
        )
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/amaura/ventures/status")
async def amaura_ventures_status(
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Read the separate Amaura Ventures portfolio and operating constraints."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.ventures import VentureStudio
    return VentureStudio(_amaura_control()).dashboard()


@app.get("/api/amaura/ventures/opportunities")
async def amaura_ventures_opportunities(
    status: str = "",
    limit: int = 100,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    return {"opportunities": _amaura_control().store.list_venture_opportunities(status=status or None, limit=limit)}


@app.post("/api/amaura/ventures/opportunities")
async def amaura_ventures_add_opportunity(
    req: AmauraVentureOpportunityRequest,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.ventures import VentureStudio
    try:
        return VentureStudio(_amaura_control()).create_opportunity(
            title=req.title,
            problem=req.problem,
            target_user=req.target_user,
            product_type=req.product_type,
            source=req.source,
            evidence=req.evidence,
            score_components=req.score_components,
            estimated_build_days=req.estimated_build_days,
            monetization=req.monetization,
            distribution_channel=req.distribution_channel,
            strategic_fit=req.strategic_fit,
            actor="jarvis",
        )
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/ventures/founder/start")
async def amaura_ventures_start(
    req: AmauraVentureStartRequest,
    approval_key: str = Header(default="", alias="X-Amaura-Approval-Key"),
):
    _require_amaura_key("AMAURA_APPROVAL_KEY", approval_key, "founder approval")
    from jarvis.amaura.ventures import VentureStudio
    try:
        return VentureStudio(_amaura_control()).start_validation(
            opportunity_id=req.opportunity_id,
            product_name=req.product_name,
            hypothesis=req.hypothesis,
            primary_metric=req.primary_metric,
            target_value=req.target_value,
            kill_threshold=req.kill_threshold,
            budget_cents=req.budget_cents,
            timebox_days=req.timebox_days,
        )
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/ventures/metrics")
async def amaura_ventures_metric(
    req: AmauraVentureMetricRequest,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.ventures import VentureStudio
    try:
        return VentureStudio(_amaura_control()).record_metric(
            req.experiment_id,
            metric_name=req.metric_name,
            value=req.value,
            source=req.source,
            evidence=req.evidence,
            captured_at=req.captured_at or None,
            actor="jarvis",
        )
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/ventures/founder/decision")
async def amaura_ventures_decision(
    req: AmauraVentureDecisionRequest,
    approval_key: str = Header(default="", alias="X-Amaura-Approval-Key"),
):
    _require_amaura_key("AMAURA_APPROVAL_KEY", approval_key, "founder approval")
    from jarvis.amaura.ventures import VentureStudio
    try:
        return VentureStudio(_amaura_control()).decide(
            req.experiment_id, decision=req.decision, reason=req.reason
        )
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/amaura/ventures/cashflow")
async def amaura_ventures_cashflow_dashboard(
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.ventures_cashflow import CashflowEngine
    return CashflowEngine(_amaura_control()).dashboard()


@app.post("/api/amaura/ventures/cashflow/tick")
async def amaura_ventures_cashflow_tick(
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.ventures_cashflow import CashflowEngine
    try:
        return CashflowEngine(_amaura_control()).tick(actor="jarvis")
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/ventures/cashflow/founder/streams")
async def amaura_ventures_cashflow_create_stream(
    req: AmauraCashflowStreamRequest,
    approval_key: str = Header(default="", alias="X-Amaura-Approval-Key"),
):
    _require_amaura_key("AMAURA_APPROVAL_KEY", approval_key, "founder approval")
    from jarvis.amaura.ventures_cashflow import CashflowEngine
    try:
        return CashflowEngine(_amaura_control()).create_stream(**req.model_dump())
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/ventures/cashflow/founder/stream-status")
async def amaura_ventures_cashflow_stream_status(
    req: AmauraCashflowStreamStatusRequest,
    approval_key: str = Header(default="", alias="X-Amaura-Approval-Key"),
):
    _require_amaura_key("AMAURA_APPROVAL_KEY", approval_key, "founder approval")
    from jarvis.amaura.ventures_cashflow import CashflowEngine
    try:
        return CashflowEngine(_amaura_control()).set_stream_status(req.stream_id, status=req.status, reason=req.reason)
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/ventures/cashflow/financial-events")
async def amaura_ventures_cashflow_financial_event(
    req: AmauraCashflowFinancialEventRequest,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.ventures_cashflow import CashflowEngine
    try:
        payload = req.model_dump()
        stream_id = payload.pop("stream_id")
        if not payload.get("occurred_at"):
            payload["occurred_at"] = None
        return CashflowEngine(_amaura_control()).record_financial_event(stream_id, actor="jarvis", **payload)
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/ventures/cashflow/founder/financial-events")
async def amaura_ventures_cashflow_founder_financial_event(
    req: AmauraCashflowFinancialEventRequest,
    approval_key: str = Header(default="", alias="X-Amaura-Approval-Key"),
):
    """Founder-certified manual transaction path, kept distinct from provider-verified automation."""
    _require_amaura_key("AMAURA_APPROVAL_KEY", approval_key, "founder approval")
    from jarvis.amaura.ventures_cashflow import CashflowEngine
    try:
        payload = req.model_dump()
        stream_id = payload.pop("stream_id")
        if not payload.get("occurred_at"):
            payload["occurred_at"] = None
        return CashflowEngine(_amaura_control()).record_financial_event(
            stream_id, actor=_amaura_control().founder_id, **payload
        )
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/ventures/cashflow/actions")
async def amaura_ventures_cashflow_action_status(
    req: AmauraCashflowActionRequest,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    if req.status in {"approved", "cancelled"}:
        raise HTTPException(status_code=403, detail="Founder approval endpoint is required for approval/cancellation")
    from jarvis.amaura.ventures_cashflow import CashflowEngine
    try:
        return CashflowEngine(_amaura_control()).set_action_status(req.action_id, status=req.status, reason=req.reason, result=req.result, actor="jarvis")
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/ventures/cashflow/founder/actions")
async def amaura_ventures_cashflow_founder_action_status(
    req: AmauraCashflowActionRequest,
    approval_key: str = Header(default="", alias="X-Amaura-Approval-Key"),
):
    _require_amaura_key("AMAURA_APPROVAL_KEY", approval_key, "founder approval")
    from jarvis.amaura.ventures_cashflow import CashflowEngine
    try:
        return CashflowEngine(_amaura_control()).set_action_status(req.action_id, status=req.status, reason=req.reason, result=req.result, actor=_amaura_control().founder_id)
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/amaura/runtime/status")
async def amaura_runtime_status(
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Expose whether the unified JARVIS/company/Ventures runtimes are configured to stay active."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    control = _amaura_control()
    from jarvis.amaura.antigravity_bridge import AntigravityDeliveryAdapter
    antigravity = AntigravityDeliveryAdapter()
    configured = os.environ.get("AMAURA_COMPANY_AUTOPILOT_RUNTIME", "1") == "1"
    return {
        "jarvis_server": "online",
        "mission_runner": os.environ.get("AMAURA_JARVIS_MISSION_RUNNER", "1") == "1",
        "mission_runner_last_error": _RUNTIME_OBSERVABILITY["mission_runner_last_error"],
        "mission_runner_last_tick_at": _RUNTIME_OBSERVABILITY["mission_runner_last_tick_at"],
        "mission_runner_last_status": _RUNTIME_OBSERVABILITY["mission_runner_last_status"],
        "proactive_cognition": os.environ.get("AMAURA_JARVIS_PROACTIVE", "1") == "1",
        "company_autopilot_runtime": configured,
        "company_autopilot_enabled": control.store.get_control("autopilot_enabled", "1") == "1",
        "company_autopilot_state": _RUNTIME_OBSERVABILITY["company_autopilot_state"] if configured else "disabled",
        "company_autopilot_started_at": _RUNTIME_OBSERVABILITY["company_autopilot_started_at"],
        "company_autopilot_last_tick_at": _RUNTIME_OBSERVABILITY["company_autopilot_last_tick_at"],
        "company_autopilot_last_status": _RUNTIME_OBSERVABILITY["company_autopilot_last_status"],
        "company_autopilot_last_error": _RUNTIME_OBSERVABILITY["company_autopilot_last_error"],
        "ventures_cashflow": True,
        "antigravity_configured": bool(antigravity.configured),
        "financial_provider_receipts_configured": len(os.environ.get("AMAURA_PROVIDER_RECEIPT_KEY", "")) >= 32,
    }


@app.get("/api/amaura/cognition/status")
async def amaura_cognition_status(
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Return OmniRoute / cognition gateway status for the HUD.

    Security: API keys are NEVER returned — only safe metadata is exposed.
    """
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.model_gateway import CognitiveModelGateway
    provider = (
        os.environ.get("AMAURA_MODEL_PROVIDER", "").strip()
        or os.environ.get("AMAURA_JARVIS_PROVIDER", "").strip()
    )
    try:
        status = CognitiveModelGateway.status(purpose="general")
    except Exception as exc:
        status = {"available": False, "gateway": "unknown", "status": "ERROR", "error": str(exc)[:120]}
    # Strip any accidental key bleed
    key_val = (os.environ.get("AMAURA_OMNIROUTE_API_KEY", "")
               or os.environ.get("OMNIROUTE_API_KEY", ""))
    if key_val:
        status = {k: str(v).replace(key_val, "[REDACTED]") if isinstance(v, str) else v
                  for k, v in status.items()}
    return {
        "provider": provider or status.get("provider", "unset"),
        "gateway": status.get("gateway", "unknown"),
        "model": status.get("requested_model", status.get("model", "unset")),
        "fallback_model": os.environ.get("AMAURA_OMNIROUTE_FALLBACK_MODEL", "").strip() or None,
        "status": status.get("status", "UNKNOWN"),
        "available": bool(status.get("available")),
        "reason": status.get("reason", ""),
        "omniroute_configured": bool(
            os.environ.get("AMAURA_OMNIROUTE_API_KEY", "").strip()
            or os.environ.get("OMNIROUTE_API_KEY", "")
        ) and bool(
            os.environ.get("AMAURA_OMNIROUTE_BASE_URL", "").strip()
            or os.environ.get("OMNIROUTE_BASE_URL", "")
        ),
    }


@app.get("/api/amaura/capabilities/status")
async def amaura_capabilities_status(
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Return lazy capability health for the desktop status view.

    This endpoint deliberately performs only shallow checks: it never starts a
    model, browser, renderer, database service, or remote integration merely to
    paint a dashboard indicator.  Deep qualification remains an explicit
    operator action through the governed capability tool.
    """
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.capability_runtime import CapabilityRuntime

    report = CapabilityRuntime().health(deep=False)
    return {
        "capabilities": report["capabilities"],
        "scheduler": report["scheduler"],
        "mode": "shallow",
    }


@app.post("/api/amaura/company/run-once")
async def amaura_company_run_once(
    req: AmauraCompanyRunRequest,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Run one bounded company-autonomy cycle."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.autopilot import AutonomousCompanyRuntime

    runtime = AutonomousCompanyRuntime(
        _amaura_control(),
        worker_id="jarvis-company-api",
        automatic_reviews=req.automatic_reviews,
    )
    try:
        return await asyncio.to_thread(
            runtime.tick,
            max_work_units=req.max_work_units,
            max_new_programmes=req.max_new_programmes,
            max_signals=req.max_signals,
        )
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/company/departments/{department}")
async def amaura_company_department_state(
    department: str,
    req: AmauraDepartmentStateRequest,
    approval_key: str = Header(default="", alias="X-Amaura-Approval-Key"),
):
    """Founder-only pause or resume for a department autonomy circuit."""
    _require_amaura_key("AMAURA_APPROVAL_KEY", approval_key, "founder approval")
    from jarvis.amaura.company_autonomy import CompanyAutonomyEngine

    try:
        return CompanyAutonomyEngine(_amaura_control()).set_department(
            department,
            enabled=req.enabled,
            reason=req.reason,
        )
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/company/autopilot")
async def amaura_company_autopilot_state(
    req: AmauraAutopilotStateRequest,
    approval_key: str = Header(default="", alias="X-Amaura-Approval-Key"),
):
    """Founder-only global company kill switch."""
    _require_amaura_key("AMAURA_APPROVAL_KEY", approval_key, "founder approval")
    from jarvis.amaura.mission_control import MissionControl

    return MissionControl(_amaura_control()).set_autopilot(
        req.enabled,
        reason=req.reason,
    )


@app.post("/api/amaura/jarvis/goals")
async def jarvis_submit_goal(
    req: JarvisGoalRequest,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Turn one founder instruction into a governed dynamic mission and optionally execute it."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.brain import GoalRequest, JarvisBrain

    try:
        goal = GoalRequest.model_validate(req.model_dump())
        return await asyncio.to_thread(JarvisBrain(_amaura_control()).submit, goal)
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/amaura/jarvis/goals")
async def jarvis_list_goals(
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """List dynamic JARVIS missions created from natural-language founder goals."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    goals = [
        item for item in _amaura_control().store.list_work_items(item_type="programme", limit=500)
        if (item.get("metadata") or {}).get("dynamic_goal")
    ]
    return {"goals": goals}


@app.get("/api/amaura/jarvis/goals/{goal_id}")
async def jarvis_goal_status(
    goal_id: str,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.brain import JarvisBrain

    try:
        return JarvisBrain(_amaura_control()).status(goal_id)
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/amaura/jarvis/goals/{goal_id}/run")
async def jarvis_run_goal(
    goal_id: str,
    req: JarvisGoalRunRequest,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.brain import JarvisBrain

    try:
        result = await asyncio.to_thread(
            JarvisBrain(_amaura_control()).run_goal,
            goal_id,
            max_ticks=req.max_ticks,
            auto_replan=req.auto_replan,
        )
        return result.to_dict()
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/jarvis/goals/{goal_id}/activate")
async def jarvis_activate_goal(
    goal_id: str,
    req: JarvisGoalLifecycleRequest,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.brain import JarvisBrain
    try:
        return JarvisBrain(_amaura_control()).activate(goal_id, actor="founder")
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/jarvis/goals/{goal_id}/pause")
async def jarvis_pause_goal(
    goal_id: str,
    req: JarvisGoalLifecycleRequest,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.brain import JarvisBrain
    try:
        return JarvisBrain(_amaura_control()).pause(goal_id, actor="founder", reason=req.reason)
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/jarvis/goals/{goal_id}/cancel")
async def jarvis_cancel_goal(
    goal_id: str,
    req: JarvisGoalLifecycleRequest,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.brain import JarvisBrain
    try:
        return JarvisBrain(_amaura_control()).cancel(goal_id, actor="founder", reason=req.reason)
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/amaura/jarvis/engineering")
async def jarvis_engineering_status(
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Report coding-backend and executive-cognition readiness without exposing secrets."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.antigravity_bridge import AntigravityDeliveryAdapter
    from jarvis.amaura.model_gateway import CognitiveModelGateway
    from jarvis.amaura.noryx_bridge import NoryxDeliveryAdapter

    antigravity = AntigravityDeliveryAdapter().readiness()
    noryx = NoryxDeliveryAdapter()
    return {
        "primary_coding_backend": "antigravity",
        "antigravity": antigravity,
        "noryx": {
            "configured": noryx.configured,
            "enabled": os.environ.get("AMAURA_ENABLE_EXPERIMENTAL_NORYX", "0").strip().lower() in {"1", "true", "yes", "on"},
            "role": "experimental_disabled_by_default",
        },
        "executive_cognition": CognitiveModelGateway.status(purpose="general"),
        "planner_cognition": CognitiveModelGateway.status(purpose="planner"),
        "verifier_mode": os.environ.get("AMAURA_VERIFIER_MODE", "auto"),
    }


@app.get("/api/amaura/jarvis/runner")
async def jarvis_runner_status(
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.mission_runner import MissionRunner
    runner = MissionRunner(_amaura_control())
    goals = runner.runnable_goals(limit=100)
    return {"enabled": os.environ.get("AMAURA_JARVIS_MISSION_RUNNER", "1") == "1", "runnable_goals": goals}


@app.get("/api/amaura/jarvis/memory")
async def jarvis_memory_list(
    scope: str = "all",
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.cognition import UnifiedMemoryService

    if scope not in {"all", "personal", "project", "episodic"}:
        raise HTTPException(status_code=400, detail="scope must be all, personal, project, or episodic")
    return {"memory": UnifiedMemoryService(_amaura_control()).list(scope=scope)}


@app.post("/api/amaura/jarvis/memory")
async def jarvis_memory_write(
    req: JarvisMemoryWriteRequest,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.cognition import UnifiedMemoryService

    if req.scope not in {"personal", "project", "episodic"}:
        raise HTTPException(status_code=400, detail="scope must be personal, project, or episodic")
    try:
        return UnifiedMemoryService(_amaura_control()).remember(
            key=req.key, value=req.value, scope=req.scope, sensitivity=req.sensitivity, actor="founder", source="api"
        )
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/jarvis/memory/forget")
async def jarvis_memory_forget(
    req: JarvisMemoryForgetRequest,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.cognition import UnifiedMemoryService

    if req.scope not in {"personal", "project", "episodic"}:
        raise HTTPException(status_code=400, detail="scope must be personal, project, or episodic")
    return {"removed": UnifiedMemoryService(_amaura_control()).forget(key=req.key, scope=req.scope, actor="founder")}


@app.get("/api/amaura/jarvis/world")
async def jarvis_world_state(
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.cognition import WorldModel

    return WorldModel(_amaura_control()).refresh()


@app.get("/api/amaura/jarvis/proactive")
async def jarvis_proactive_insights(
    refresh: bool = False,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    control = _amaura_control()
    if refresh:
        from jarvis.amaura.cognition import ProactiveCognition
        return {"insights": ProactiveCognition(control).scan()}
    try:
        latest = control.store.get_knowledge("jarvis.proactive", "latest").get("value") or {}
        return {"insights": list(latest.get("insights") or [])[:25]}
    except KeyError:
        return {"insights": []}


@app.post("/api/amaura/jarvis/execute")
async def jarvis_execute_unified(
    req: ChatRequest,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Explicit authenticated alias for the same ExecutiveKernel used by chat."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    agent = get_or_create_agent(req.session_id, req.model)
    agent.set_amaura_session_token(operator_key)
    result = await asyncio.to_thread(
        agent.run_executive,
        req.message,
        control=_amaura_control(),
        session_id=req.session_id,
        workspace=req.workspace,
        autonomy=req.autonomy,
        coding_backend=req.coding_backend,
        allow_missions=True,
    )
    return result


@app.post("/api/amaura/jarvis/antigravity/handoff")
async def jarvis_antigravity_handoff(
    req: JarvisAntigravityHandoffRequest,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Prepare a bounded Antigravity engineering packet without pretending to automate its UI."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.handoffs import create_antigravity_packet

    try:
        packet = create_antigravity_packet(
            objective=req.objective,
            repository=req.repository,
            plan=req.plan,
            acceptance_criteria=req.acceptance_criteria,
            allowed_paths=req.allowed_paths,
        )
        return packet.to_dict() if hasattr(packet, "to_dict") else packet.__dict__
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/amaura/dashboard")
async def amaura_dashboard(operator_key: str = Header(default="", alias="X-Amaura-Operator-Key")):
    """Executive company dashboard governed by JARVIS."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    return _amaura_control().dashboard()


@app.get("/api/amaura/agents")
async def amaura_agents(operator_key: str = Header(default="", alias="X-Amaura-Operator-Key")):
    """Return the complete governed v1 workforce registry."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    return {"agents": _amaura_control().store.list_agents(), "master": "jarvis"}


@app.get("/api/amaura/tasks")
async def amaura_tasks(
    state: str = "", owner_id: str = "",
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """List company tasks with optional state and employee filters."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    return {"tasks": _amaura_control().list_tasks(state or None, owner_id or None)}


@app.get("/api/amaura/tasks/{task_id}")
async def amaura_task(task_id: str, operator_key: str = Header(default="", alias="X-Amaura-Operator-Key")):
    """Return a task and its JARVIS-issued execution packet."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    try:
        return {
            "task": _amaura_control().store.get_work_item(task_id),
            "packet": _amaura_control().task_packet(task_id),
        }
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/amaura/programmes")
async def amaura_create_programme(
    req: AmauraProgrammeRequest,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Have JARVIS translate a founder objective into governed work."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    try:
        cmd_obj = cmd.CreateProgramCommand(
            
            objective=req.objective,
            success_metric=req.success_metric,
            workflow_key=req.workflow_key,
            title=req.title or None,
            priority=req.priority,
            deadline=req.deadline or None,
            inputs=req.inputs,
            actor="jarvis",
        )
        return _amaura_bus().execute(cmd_obj)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/tasks/{task_id}/run")
async def amaura_run_task(
    task_id: str, req: AmauraRunRequest,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Dispatch a ready task to its specialist inside JARVIS policy boundaries."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.executor import GovernedTaskRunner
    try:
        return await asyncio.to_thread(GovernedTaskRunner(_amaura_control()).run, task_id, req.max_iterations)
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/amaura/supervisor/status")
async def amaura_supervisor_status(
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Return durable worker leases, queue depth, and approval boundaries."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.supervisor import AmauraSupervisor
    return AmauraSupervisor(_amaura_control(), worker_id="jarvis-api").status()


@app.post("/api/amaura/supervisor/tick")
async def amaura_supervisor_tick(
    req: AmauraSupervisorRequest,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Advance one crash-resumable execution or independent review."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.supervisor import AmauraSupervisor
    supervisor = AmauraSupervisor(
        _amaura_control(),
        worker_id="jarvis-api",
        automatic_reviews=req.automatic_reviews,
    )
    try:
        return await asyncio.to_thread(
            supervisor.tick,
            workflow_id=req.workflow_id or None,
        )
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/tasks/{task_id}/review")
async def amaura_review_task(
    task_id: str, req: AmauraReviewRequest,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
    reviewer_key: str = Header(default="", alias="X-Amaura-Reviewer-Key"),
):
    """Record independent QA; reviewer identity comes from authenticated header (P0-5)."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    # P0-5: resolve reviewer from the authenticated key header, not from request body.
    if not os.environ.get("AMAURA_REVIEWER_KEYS", "").strip():
        raise HTTPException(status_code=503, detail="AMAURA_REVIEWER_KEYS is not configured")
    try:
        reviewer_id = _resolve_reviewer_from_key(reviewer_key)
    except Exception as exc:
        from jarvis.amaura.models import GovernanceError
        if not isinstance(exc, (ValueError, GovernanceError)):
            raise
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if reviewer_id is None:
        raise HTTPException(status_code=403, detail="Invalid Amaura reviewer key")
    try:
        return _amaura_bus().execute(cmd.ReviewTaskCommand(task_id=task_id, actor=reviewer_id, approve=req.approve, findings=req.findings, attestation=req.attestation))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc



@app.get("/api/amaura/approvals")
async def amaura_approvals(
    status: str = "pending",
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """List approval requests waiting for founder authority."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    return {"approvals": _amaura_control().store.list_approvals(status or None)}


@app.post("/api/amaura/approvals/{approval_id}")
async def amaura_decide_approval(
    approval_id: str,
    req: AmauraApprovalRequest,
    approval_key: str = Header(default="", alias="X-Amaura-Approval-Key"),
):
    """Record a founder decision only through the separately authenticated approval surface."""
    _require_amaura_key("AMAURA_APPROVAL_KEY", approval_key, "founder approval")
    control = _amaura_control()
    try:
        return control.decide_approval(approval_id, control.founder_id, req.decision, req.reason)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/amaura/events")
async def amaura_events(
    event_type: str = "", limit: int = 100,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Return the durable company event stream."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    return {"events": _amaura_control().store.list_events(event_type or None, limit)}


@app.get("/api/amaura/audit")
async def amaura_audit(
    limit: int = 100,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Return immutable authority and policy audit entries."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    return {"audit": _amaura_control().store.list_audit(limit)}


@app.get("/api/amaura/briefing")
async def amaura_briefing(operator_key: str = Header(default="", alias="X-Amaura-Operator-Key")):
    """Generate the daily founder operating briefing."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    return _amaura_control().daily_briefing()


@app.get("/api/amaura/readiness")
async def amaura_readiness(operator_key: str = Header(default="", alias="X-Amaura-Operator-Key")):
    """Report real configuration blockers without exposing credential values."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    return _amaura_control().production_readiness()


@app.get("/api/amaura/telemetry")
async def amaura_telemetry(
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Return durable operational metrics, traces, and open alerts."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    return _amaura_control().telemetry.snapshot()


@app.get("/api/amaura/metrics", response_class=PlainTextResponse)
async def amaura_prometheus_metrics(
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """Render durable Amaura metrics in Prometheus text format."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    return PlainTextResponse(
        _amaura_control().telemetry.prometheus(),
        media_type="text/plain; version=0.0.4",
    )


# -- Free-first integrations and inbound webhooks -----------------------------

@app.get("/api/amaura/webhooks/meta")
async def amaura_meta_webhook_verify(request: Request):
    mode = request.query_params.get("hub.mode", "")
    token = request.query_params.get("hub.verify_token", "")
    challenge = request.query_params.get("hub.challenge", "")
    expected = os.environ.get("AMAURA_META_VERIFY_TOKEN", "")
    if not expected or mode != "subscribe" or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Meta webhook verification failed")
    return PlainTextResponse(challenge)

@app.post("/api/amaura/webhooks/meta")
async def amaura_meta_webhook(request: Request):
    length = int(request.headers.get("content-length", "0") or 0)
    if length > 1_000_000:
        raise HTTPException(status_code=413, detail="Webhook body too large")
    raw = await request.body()
    if len(raw) > 1_000_000:
        raise HTTPException(status_code=413, detail="Webhook body too large")
    from jarvis.amaura.inbox import InboxService, parse_meta_webhook, verify_meta_signature
    try:
        verify_meta_signature(raw, request.headers.get("x-hub-signature-256", ""))
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Webhook payload must be an object")
        service = InboxService(_amaura_control().store, _amaura_control().founder_id)
        records = []
        for message in parse_meta_webhook(payload):
            record, inserted = service.ingest(message)
            if inserted:
                record = service.process(record["id"], stage_reply=True)
            records.append({"id": record["id"], "inserted": inserted, "status": record["status"]})
        return {"accepted": True, "messages": records}
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, Exception) as exc:
        from jarvis.amaura.models import GovernanceError
        if isinstance(exc, GovernanceError):
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.get("/api/amaura/integration-actions")
async def amaura_list_integration_actions(status: str = "", operator_key: str = Header(default="", alias="X-Amaura-Operator-Key")):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    return {"actions": _amaura_control().store.list_integration_actions(status=status or None)}

@app.post("/api/amaura/integration-actions")
async def amaura_stage_integration_action(req: AmauraIntegrationActionRequest, operator_key: str = Header(default="", alias="X-Amaura-Operator-Key")):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.integration_control import IntegrationActionController
    try:
        return IntegrationActionController(_amaura_control().store, _amaura_control().founder_id).stage(
            provider=req.provider, operation=req.operation, payload=req.payload, risk=req.risk,
            idempotency_key=req.idempotency_key, requested_by="jarvis",
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.post("/api/amaura/integration-actions/{action_id}/decision")
async def amaura_decide_integration_action(action_id: str, req: AmauraIntegrationDecisionRequest, approval_key: str = Header(default="", alias="X-Amaura-Approval-Key")):
    _require_amaura_key("AMAURA_APPROVAL_KEY", approval_key, "founder approval")
    from jarvis.amaura.integration_control import IntegrationActionController
    control = _amaura_control()
    try:
        return IntegrationActionController(control.store, control.founder_id).decide(
            action_id, approve=req.approve, actor=control.founder_id, reason=req.reason
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.post("/api/amaura/inbox/gmail/sync")
async def amaura_sync_gmail_inbox(req: AmauraInboxSyncRequest, operator_key: str = Header(default="", alias="X-Amaura-Operator-Key")):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.inbox import InboxService
    control = _amaura_control()
    records = InboxService(control.store, control.founder_id).sync_gmail(
        max_results=req.max_results,
        query=req.query,
        mark_read=req.mark_read,
    )
    return {"inserted": len(records), "messages": records}

@app.post("/api/amaura/inbox/{inbound_id}/process")
async def amaura_process_inbound(inbound_id: str, operator_key: str = Header(default="", alias="X-Amaura-Operator-Key")):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.inbox import InboxService
    control = _amaura_control()
    try:
        return InboxService(control.store, control.founder_id).process(inbound_id, stage_reply=True)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.post("/api/amaura/invoices")
async def amaura_create_invoice(req: AmauraInvoiceRequest, operator_key: str = Header(default="", alias="X-Amaura-Operator-Key")):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.billing import InvoiceService
    try:
        return InvoiceService(_amaura_control().store).create(**req.model_dump())
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.get("/api/amaura/invoices")
async def amaura_list_invoices(status: str = "", operator_key: str = Header(default="", alias="X-Amaura-Operator-Key")):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    return {"invoices": _amaura_control().store.list_invoices(status=status or None)}

@app.post("/api/amaura/invoices/{invoice_id}/status")
async def amaura_update_invoice_status(
    invoice_id: str,
    req: AmauraInvoiceStatusRequest,
    approval_key: str = Header(default="", alias="X-Amaura-Approval-Key"),
):
    _require_amaura_key("AMAURA_APPROVAL_KEY", approval_key, "founder approval")
    from jarvis.amaura.billing import InvoiceService
    from jarvis.amaura.models import GovernanceError
    control = _amaura_control()
    try:
        return InvoiceService(control.store).mark_status(
            invoice_id,
            status=req.status,
            actor=control.founder_id,
            reference=req.reference,
        )
    except (GovernanceError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

# -- Revenue pipeline ----------------------------------------------------------

@app.get("/api/amaura/revenue")
async def amaura_revenue_dashboard(operator_key: str = Header(default="", alias="X-Amaura-Operator-Key")):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    return _amaura_control().acquisition.dashboard()


@app.post("/api/amaura/revenue/campaigns")
async def amaura_create_campaign(req: AmauraCampaignRequest, operator_key: str = Header(default="", alias="X-Amaura-Operator-Key")):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    try:
        return _amaura_bus().execute(cmd.CreateCampaignCommand(**req.model_dump()))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/revenue/discovery/run")
async def amaura_run_free_discovery(req: AmauraDiscoveryRunRequest, operator_key: str = Header(default="", alias="X-Amaura-Operator-Key")):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    from jarvis.amaura.public_sources import AcquisitionDiscoveryRunner
    control = _amaura_control()
    return {"results": AcquisitionDiscoveryRunner(control.acquisition).run(**req.model_dump())}

@app.get("/api/amaura/revenue/leads")
async def amaura_list_leads(campaign_id: str = "", stage: str = "", operator_key: str = Header(default="", alias="X-Amaura-Operator-Key")):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    return {"leads": _amaura_control().store.list_leads(campaign_id or None, stage or None)}


@app.post("/api/amaura/revenue/leads")
async def amaura_discover_pipeline_lead(req: AmauraLeadRequest, operator_key: str = Header(default="", alias="X-Amaura-Operator-Key")):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    try:
        return _amaura_bus().execute(cmd.DiscoverLeadCommand(**req.model_dump()))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/revenue/leads/{lead_id}/evidence")
async def amaura_add_lead_evidence(lead_id: str, req: AmauraEvidenceRequest, operator_key: str = Header(default="", alias="X-Amaura-Operator-Key")):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    try:
        return _amaura_bus().execute(cmd.AddEvidenceCommand(lead_id=lead_id, **req.model_dump()))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/revenue/leads/{lead_id}/score")
async def amaura_score_pipeline_lead(lead_id: str, req: AmauraLeadScoreRequest, operator_key: str = Header(default="", alias="X-Amaura-Operator-Key")):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    try:
        return _amaura_bus().execute(cmd.ScoreLeadCommand(lead_id=lead_id, components=req.model_dump(), actor="qualification_bot"))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/revenue/leads/{lead_id}/transition")
async def amaura_transition_pipeline_lead(lead_id: str, req: AmauraTransitionRequest, operator_key: str = Header(default="", alias="X-Amaura-Operator-Key")):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    try:
        return _amaura_bus().execute(cmd.TransitionLeadCommand(lead_id=lead_id, **req.model_dump()))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/revenue/leads/{lead_id}/messages")
async def amaura_stage_pipeline_message(lead_id: str, req: AmauraMessageRequest, operator_key: str = Header(default="", alias="X-Amaura-Operator-Key")):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    try:
        return _amaura_bus().execute(cmd.StageMessageCommand(lead_id=lead_id, **req.model_dump()))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/revenue/messages/{message_id}/decision")
async def amaura_decide_pipeline_message(message_id: str, req: AmauraMessageDecisionRequest,
                                         approval_key: str = Header(default="", alias="X-Amaura-Approval-Key")):
    _require_amaura_key("AMAURA_APPROVAL_KEY", approval_key, "founder approval")
    control = _amaura_control()
    try:
        return control.acquisition.decide_message(message_id, actor=control.founder_id, **req.model_dump())
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/revenue/messages/{message_id}/assisted-sent")
async def amaura_confirm_assisted_send(message_id: str, req: AmauraAssistedSendRequest, approval_key: str = Header(default="", alias="X-Amaura-Approval-Key")):
    _require_amaura_key("AMAURA_APPROVAL_KEY", approval_key, "founder approval")
    control = _amaura_control()
    try:
        return control.acquisition.record_assisted_send(
            message_id, actor=control.founder_id, external_message_id=req.external_message_id, thread_id=req.thread_id
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.post("/api/amaura/revenue/messages/{message_id}/sent")
async def amaura_confirm_pipeline_send(message_id: str, req: AmauraSendConfirmationRequest,
                                       operator_key: str = Header(default="", alias="X-Amaura-Operator-Key")):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    try:
        values = req.model_dump()
        values["provider_receipt"] = values["provider_receipt"] or None
        return _amaura_control().acquisition.confirm_external_send(
            message_id,
            **values,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/revenue/messages/{message_id}/deliver")
async def amaura_deliver_pipeline_message(
    message_id: str,
    req: AmauraDeliverMessageRequest,
    approval_key: str = Header(default="", alias="X-Amaura-Approval-Key"),
):
    """Deliver an approved message through Gmail and persist its signed receipt."""
    _require_amaura_key("AMAURA_APPROVAL_KEY", approval_key, "founder approval")
    try:
        return _amaura_control().acquisition.deliver_approved_message(
            message_id,
            **req.model_dump(),
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/revenue/kill-switch")
async def amaura_pipeline_kill_switch(req: AmauraKillSwitchRequest,
                                      approval_key: str = Header(default="", alias="X-Amaura-Approval-Key")):
    _require_amaura_key("AMAURA_APPROVAL_KEY", approval_key, "founder approval")
    control = _amaura_control()
    return control.acquisition.set_kill_switch(req.enabled, actor=control.founder_id, reason=req.reason)


@app.get("/api/amaura/outbox")
async def amaura_list_outbox_events(
    status: str = "",
    limit: int = 100,
    operator_key: str = Header(default="", alias="X-Amaura-Operator-Key"),
):
    """List durable provider operations, including quarantined ambiguous sends."""
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    try:
        return {
            "events": _amaura_control().store.list_outbox_events(
                status=status.strip() or None,
                limit=limit,
            )
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/outbox/{event_id}/reconcile")
async def amaura_reconcile_outbox_event(
    event_id: str,
    req: AmauraOutboxReconciliationRequest,
    approval_key: str = Header(default="", alias="X-Amaura-Approval-Key"),
):
    """Resolve an uncertain provider attempt through founder authority."""
    _require_amaura_key("AMAURA_APPROVAL_KEY", approval_key, "founder approval")
    control = _amaura_control()
    try:
        return control.reconcile_outbox_event(
            event_id,
            resolution=req.resolution,
            reason=req.reason,
            provider_receipt=req.provider_receipt or None,
            actor=control.founder_id,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# -- Content factory -----------------------------------------------------------

@app.post("/api/amaura/content/campaigns")
async def amaura_create_content_campaign(req: AmauraContentCampaignRequest,
                                         operator_key: str = Header(default="", alias="X-Amaura-Operator-Key")):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    try:
        return _amaura_bus().execute(cmd.ContentCreateCampaignCommand(**req.model_dump()))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/content/campaigns/{campaign_id}/assets")
async def amaura_register_content_asset(campaign_id: str, req: AmauraContentAssetRequest,
                                        operator_key: str = Header(default="", alias="X-Amaura-Operator-Key")):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    try:
        return _amaura_bus().execute(cmd.RegisterAssetCommand(
            campaign_id=campaign_id,
            asset_type=req.asset_type,
            uri=req.uri,
            sha256=req.sha256,
            source_url=req.source_url,
            creator=req.creator,
            licence=req.licence,
            status=req.status,
            metadata=req.metadata,
        ))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/amaura/content/campaigns/{campaign_id}/readiness")
async def amaura_content_readiness(campaign_id: str, operator_key: str = Header(default="", alias="X-Amaura-Operator-Key")):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    try:
        return _amaura_control().content_factory.publication_readiness(campaign_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/amaura/content/campaigns/{campaign_id}/metrics")
async def amaura_record_content_metrics(campaign_id: str, req: AmauraContentMetricsRequest,
                                        operator_key: str = Header(default="", alias="X-Amaura-Operator-Key")):
    _require_amaura_key("AMAURA_OPERATOR_KEY", operator_key, "operator")
    data = req.model_dump()
    data["captured_at"] = data["captured_at"] or None
    try:
        return _amaura_bus().execute(cmd.RecordMetricsCommand(campaign_id=campaign_id, **data))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/amaura/content/campaigns/{campaign_id}/private-draft")
async def amaura_create_private_publication_draft(
    campaign_id: str,
    req: AmauraPrivatePublicationRequest,
    approval_key: str = Header(default="", alias="X-Amaura-Approval-Key"),
):
    """Create a provider-confirmed private draft; this endpoint never publishes."""
    _require_amaura_key("AMAURA_APPROVAL_KEY", approval_key, "founder approval")
    control = _amaura_control()
    readiness = control.content_factory.publication_readiness(campaign_id)
    if not readiness["ready"]:
        raise HTTPException(
            status_code=409,
            detail="Content campaign has not passed publication readiness",
        )
    from jarvis.amaura.integrations import PrivatePublicationAdapter

    try:
        receipt = PrivatePublicationAdapter().create_private_draft(
            payload=req.payload,
            idempotency_key=req.idempotency_key,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    control.store.record_idempotency(
        req.idempotency_key,
        "create_private_publication_draft",
        receipt.external_id,
        receipt.payload_sha256,
    )
    return {"campaign_id": campaign_id, "receipt": receipt.to_dict()}


# ── WebSocket — Streaming Chat ─────────────────────────────────────────────────

@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket endpoint for real-time streaming chat with Jarvis."""
    expected = os.environ.get("JARVIS_API_KEY", "").strip()
    supplied = supplied_api_key(websocket.headers, websocket.query_params)
    allowed_origins = {origin.strip() for origin in os.environ.get(
        "JARVIS_WS_ORIGINS",
        "http://127.0.0.1:8000,http://localhost:8000",
    ).split(",") if origin.strip()}
    origin = websocket.headers.get("origin", "")
    if origin and origin not in allowed_origins:
        await websocket.close(code=1008, reason="Origin is not allowed")
        return
    if len(expected) < MIN_API_KEY_LENGTH or not api_key_matches(supplied, expected):
        await websocket.close(code=1008, reason="Authentication required")
        return
    offered_protocols = {
        item.strip() for item in websocket.headers.get("sec-websocket-protocol", "").split(",") if item.strip()
    }
    await websocket.accept(subprotocol="jarvis" if "jarvis" in offered_protocols else None)

    session_id = f"ws_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    agent = get_or_create_agent(session_id)

    # Send welcome
    await websocket.send_json({
        "type": "system",
        "content": "J.A.R.V.I.S. interface online. Governed operations remain readiness-gated.",
        "session_id": session_id,
        "model": agent.model_cfg["name"],
        "timestamp": datetime.now().isoformat(),
    })

    try:
        while True:
            # Receive message
            raw = await websocket.receive_text()
            data = json.loads(raw)

            msg_type = data.get("type", "chat")
            content = data.get("content", "")

            if msg_type in ("chat", "voice") and content:
                # Send acknowledgment
                await websocket.send_json({
                    "type": "user_echo" if msg_type == "chat" else "voice_echo",
                    "content": content,
                    "timestamp": datetime.now().isoformat(),
                })

                loop = asyncio.get_running_loop()
                def on_event(evt, loop=loop):
                    asyncio.run_coroutine_threadsafe(
                        websocket.send_json({
                            "type": "agent_event",
                            "event": evt,
                            "timestamp": datetime.now().isoformat(),
                        }),
                        loop
                    )

                # Process with agent
                try:
                    supplied_operator = str(data.get("operator_key") or "")
                    expected_operator = os.environ.get("AMAURA_OPERATOR_KEY", "")
                    operator_valid = bool(
                        supplied_operator and expected_operator
                        and hmac.compare_digest(supplied_operator, expected_operator)
                    )
                    if supplied_operator and not operator_valid:
                        raise ValueError("Invalid Amaura operator key")
                    if operator_valid:
                        agent.set_amaura_session_token(supplied_operator)
                    executive = await asyncio.to_thread(
                        agent.run_executive, content, control=_amaura_control(), session_id=session_id,
                        workspace=str(data.get("workspace") or ""),
                        autonomy=str(data.get("autonomy") or "execute_until_approval"),
                        coding_backend=str(data.get("coding_backend") or "antigravity"),
                        allow_missions=operator_valid,
                    )
                    response = str(executive.get("message") or "")

                    await websocket.send_json({
                        "type": "response",
                        "content": response,
                        "executive": executive,
                        "timestamp": datetime.now().isoformat(),
                    })

                    if voice_engine.enabled and response:
                        speaker.speak_async(response)

                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "content": f"Error processing request: {str(e)}",
                        "timestamp": datetime.now().isoformat(),
                    })

            elif msg_type == "command":
                # Handle slash commands
                cmd = content.strip().lower()
                result = await _handle_ws_command(cmd, agent, websocket)
                if result:
                    await websocket.send_json(result)

            elif msg_type == "tool":
                await websocket.send_json({
                    "type": "error",
                    "content": "Direct WebSocket tool execution is disabled. Create a governed Amaura programme.",
                    "timestamp": datetime.now().isoformat(),
                })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({
                "type": "error",
                "content": f"WebSocket error: {str(e)}",
            })
        except Exception:
            pass


async def _handle_ws_command(cmd: str, agent: JarvisAgent, websocket: WebSocket) -> dict | None:
    """Handle slash commands over WebSocket."""
    parts = cmd.split(maxsplit=1)
    command = parts[0]
    arg = parts[1] if len(parts) > 1 else ""

    if command == "/help":
        return {
            "type": "help",
            "commands": [
                {"cmd": "/help", "desc": "Show this help"},
                {"cmd": "/voice", "desc": "Toggle voice mode"},
                {"cmd": "/model <name>", "desc": "Switch AI model"},
                {"cmd": "/models", "desc": "List available models"},
                {"cmd": "/memory", "desc": "View personal memory"},
                {"cmd": "/remember <fact>", "desc": "Teach Jarvis a fact"},
                {"cmd": "/clear", "desc": "Clear conversation"},
                {"cmd": "/status", "desc": "System status"},
                {"cmd": "/tools", "desc": "List all tools"},
                {"cmd": "/company", "desc": "Amaura executive dashboard"},
                {"cmd": "/briefing", "desc": "Daily founder briefing"},
                {"cmd": "/approvals", "desc": "Pending founder decisions"},
            ],
        }

    elif command == "/voice":
        new_state = voice_engine.toggle()
        agent.voice_mode = new_state
        return {
            "type": "system",
            "content": f"Voice mode {'enabled' if new_state else 'disabled'}, sir.",
            "voice_enabled": new_state,
        }

    elif command == "/models":
        models = list_models()
        return {"type": "models", "models": models, "current": agent.model_key}

    elif command == "/model" and arg:
        if agent.set_model(arg):
            return {
                "type": "system",
                "content": f"Switched to {agent.model_cfg['name']}, sir.",
                "model": agent.model_key,
            }
        return {"type": "error", "content": f"Unknown model: {arg}"}

    elif command == "/clear":
        agent.clear_history()
        return {"type": "system", "content": "Conversation cleared. Fresh start, sir."}

    elif command == "/memory":
        summary = user_memory.get_summary()
        return {"type": "memory", "content": summary}

    elif command == "/remember" and arg:
        user_memory.add_fact(arg)
        return {"type": "system", "content": f"Noted and remembered: \"{arg}\""}

    elif command == "/status":
        from jarvis.tools.desktop import tool_get_system_info
        info = tool_get_system_info()
        return {"type": "system_info", "content": info}

    elif command == "/tools":
        tools = []
        for t in ALL_TOOL_DEFINITIONS:
            tools.append({
                "name": t["function"]["name"],
                "desc": t["function"]["description"][:100],
            })
        return {"type": "tools_list", "tools": tools, "count": len(tools)}

    elif command == "/company":
        return {"type": "system", "content": json.dumps(_amaura_control().dashboard(), indent=2)}

    elif command == "/briefing":
        return {"type": "system", "content": json.dumps(_amaura_control().daily_briefing(), indent=2)}

    elif command == "/approvals":
        approvals = _amaura_control().store.list_approvals("pending")
        return {"type": "system", "content": json.dumps({"pending_approvals": approvals}, indent=2)}

    return None


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    """Start the JARVIS server."""
    port = int(os.environ.get("JARVIS_PORT", "8000"))
    host = os.environ.get("JARVIS_HOST", "127.0.0.1").strip() or "127.0.0.1"
    validate_bind_security(host)
    os.environ["JARVIS_EFFECTIVE_BIND_HOST"] = host

    print(f"""
  ╔══════════════════════════════════════════╗
  ║  ◉  J.A.R.V.I.S.  Server  v3.5  ◉      ║
  ╠══════════════════════════════════════════╣
  ║  REST API  : http://{host}:{port}         ║
  ║  WebSocket : ws://{host}:{port}/ws/chat   ║
  ║  HUD App   : http://{host}:{port}         ║
  ║  Docs      : http://{host}:{port}/docs    ║
  ╚══════════════════════════════════════════╝
""")

    reload_enabled = os.environ.get("JARVIS_RELOAD", "0") == "1"
    uvicorn.run(
        "jarvis.server:app" if reload_enabled else app,
        host=host,
        port=port,
        reload=reload_enabled,
        log_level="info",
    )


if __name__ == "__main__":
    main()
