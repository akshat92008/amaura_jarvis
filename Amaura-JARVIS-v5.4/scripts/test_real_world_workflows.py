#!/usr/bin/env python3
"""Comprehensive Real-World Workflow Validation for Amaura JARVIS v5.4.

This test suite executes every major real-world path:
1. Executive Conversation, Intent Resolution, Streaming & Memory
2. Antigravity Autonomous Software Engineering Bridge
3. Ventures Cash-Flow Autopilot & Founder Approval Engine
4. FastAPI Server & API Endpoints
5. System Launchers & Diagnostic Certification
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Load governed environment
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis.amaura.runtime import load_amaura_env
load_amaura_env()

from jarvis.amaura.control_plane import AmauraControlPlane
from jarvis.amaura.model_gateway import CognitiveModelGateway
from jarvis.amaura.antigravity_bridge import AntigravityDeliveryAdapter
from jarvis.amaura.readiness import production_readiness
from jarvis.amaura.ventures_cashflow import CashflowEngine
from jarvis.server import app
from fastapi.testclient import TestClient

PASSED_STEPS = []
FAILED_STEPS = []

def record(name: str, success: bool, detail: str = ""):
    if success:
        PASSED_STEPS.append((name, detail))
        print(f"  [PASS] {name}: {detail}")
    else:
        FAILED_STEPS.append((name, detail))
        print(f"  [FAIL] {name}: {detail}")


def test_diagnostics_and_readiness(cp: AmauraControlPlane):
    print("\n--- 1. Testing System Diagnostics & Production Readiness ---")
    readiness = production_readiness(cp, live=True)
    blockers = readiness.get("blockers", [])
    record("Production Readiness Blockers", len(blockers) == 0, f"Blockers: {blockers}")
    record("Source Certification", readiness.get("source_certified") is True, "Source tree integrity verified")
    record("Interactive Cognition Live", readiness.get("live_checks", {}).get("interactive_cognition_ready") is True, "Live model probe passed")
    record("Verifier Healthy", readiness.get("live_checks", {}).get("docker_healthy") is True, "Isolated verifier active")


def test_executive_cognition(cp: AmauraControlPlane):
    print("\n--- 2. Testing Executive Cognition & Conversational Reasoning ---")
    gateway_status = CognitiveModelGateway.status(purpose="general")
    record("Model Gateway Available", gateway_status.get("available") is True, f"Provider: {gateway_status.get('provider')}, Model: {gateway_status.get('model')}")

    # Synchronous generation
    t0 = time.monotonic()
    res = CognitiveModelGateway.generate(
        messages=[
            {"role": "system", "content": "You are JARVIS, a concise executive AI. Answer clearly."},
            {"role": "user", "content": "Confirm your operational status in one sentence."}
        ],
        purpose="general",
        max_tokens=60
    )
    lat = int((time.monotonic() - t0) * 1000)
    record("Synchronous Chat Completion", bool(res.text.strip()), f"Latency: {lat}ms | Response: {res.text.strip()[:80]}...")

    # Streaming generation
    streamed_chunks = []
    def on_token(t: str):
        streamed_chunks.append(t)

    t0 = time.monotonic()
    stream_res = CognitiveModelGateway.generate_stream(
        messages=[{"role": "user", "content": "List 3 key principles of safe autonomous engineering."}],
        on_token=on_token,
        purpose="general",
        max_tokens=80
    )
    stream_lat = int((time.monotonic() - t0) * 1000)
    record("Streaming SSE Generation", len(streamed_chunks) > 0 and bool(stream_res.text), f"Streamed {len(streamed_chunks)} tokens in {stream_lat}ms")

    # Structured JSON generation
    json_val, json_res = CognitiveModelGateway.generate_json(
        prompt="Output a JSON object with keys 'status' (string 'READY'), 'version' (string '5.4'), and 'features' (list of 3 strings).",
        purpose="general",
        max_tokens=150
    )
    record("Structured JSON Generation", isinstance(json_val, dict) and json_val.get("status") == "READY", f"JSON Output: {json_val}")


def test_antigravity_engineering_bridge(cp: AmauraControlPlane):
    print("\n--- 3. Testing Antigravity Autonomous Engineering Bridge ---")
    adapter = AntigravityDeliveryAdapter()
    readiness = adapter.readiness()
    record("Antigravity CLI Configured", readiness.get("configured") is True, f"Version: {readiness.get('version')}")
    record("Antigravity Version Compatible", readiness.get("version_compatible") is True, f"Compatible CLI: {readiness.get('version')}")
    record("Antigravity Sandbox Settings", readiness.get("settings", {}).get("valid") is True, f"Tool Permission: {readiness.get('settings', {}).get('tool_permission')}")
    record("Project Permissions Safe", readiness.get("project_permissions", {}).get("unresolved") is False, "Project scopes verified")
    record("Executable Customizations Qualified", len(readiness.get("global_customizations", {}).get("executable", [])) == 0, "No unauthorized hooks")
    record("Antigravity Bridge Ready", readiness.get("ready") is True, "Autonomous repository delivery ready")


def test_ventures_cashflow_engine(cp: AmauraControlPlane):
    print("\n--- 4. Testing Amaura Ventures & Cash-Flow Autopilot ---")
    engine = CashflowEngine(cp)
    
    # 1. Dashboard & portfolio
    dashboard = engine.dashboard()
    record("Ventures Dashboard Query", isinstance(dashboard, dict) and "lanes" in dashboard and "portfolio" in dashboard, f"Dashboard retrieved | Lanes: {len(dashboard.get('lanes', []))} | Action Queue: {len(dashboard.get('action_queue', []))}")
    
    # 2. Portfolio metrics
    portfolio = engine.portfolio()
    record("Portfolio Unit Economics Ledger", isinstance(portfolio, dict), f"Balance: {portfolio.get('balance_cents', 0)} cents | Gross Profit: {portfolio.get('gross_profit_cents', 0)} cents")
    
    # 3. Lane profiles and adaptive ranking
    from jarvis.amaura.ventures_cashflow import LANE_PROFILES
    record("12-Lane Catalogue Verified", len(LANE_PROFILES) >= 12, f"Active lanes: {list(LANE_PROFILES.keys())[:4]}...")
    
    sample_opp = {
        "id": "opp-test-101",
        "title": "Automated Python Revision Pack",
        "lane": "digital_download",
        "summary": "Original cheatsheets and code examples for students",
        "target_user": "Engineering students",
        "venture_score": 82.5,
        "evidence": [{"source": "https://example.com/data", "claim": "High demand for fast revision materials"}],
        "estimated_build_days": 3,
        "monetization": "One-time download",
        "distribution_channel": "Organic social and direct landing page",
        "strategic_fit": "Low capital, bounded founder time",
    }
    ranking = engine.rank_opportunity(sample_opp, founder_minutes_per_week=60)
    record("Opportunity Discovery & Adaptive Ranking", float(ranking.get("cashflow_score", 0)) > 0, f"Ranked '{ranking.get('title')}' -> Cashflow Score: {ranking.get('cashflow_score')}")
    
    # 4. Cashflow tick
    tick_result = engine.tick(actor="jarvis", proposal_limit=4, auto_execute=False)
    record("Ventures Autonomous Tick", isinstance(tick_result, dict), f"Status: {tick_result.get('status')} | Proposals: {len(tick_result.get('proposals', []))}")


def test_fastapi_server_endpoints(cp: AmauraControlPlane):
    print("\n--- 5. Testing FastAPI Server Endpoints ---")
    headers = {
        "X-JARVIS-Key": os.environ.get("JARVIS_API_KEY", ""),
        "X-Amaura-Operator-Key": os.environ.get("AMAURA_OPERATOR_KEY", ""),
    }
    client = TestClient(app, headers=headers)
    
    # Health endpoint
    resp = client.get("/api/health")
    record("GET /api/health", resp.status_code == 200, f"Status: {resp.status_code} | Body: {resp.json().get('status')}")
    
    # System endpoint
    resp = client.get("/api/system")
    record("GET /api/system", resp.status_code == 200, f"Status: {resp.status_code} | System: {resp.json().get('platform', 'macos')}")
    
    # Models endpoint
    resp = client.get("/api/models")
    record("GET /api/models", resp.status_code == 200, f"Status: {resp.status_code} | Models: {len(resp.json().get('models', []))}")
    
    # Cognition status endpoint
    resp = client.get("/api/amaura/cognition/status")
    record("GET /api/amaura/cognition/status", resp.status_code == 200, f"Status: {resp.status_code} | Gateway: {resp.json().get('gateway')}")
    
    # Ventures cashflow endpoint
    resp = client.get("/api/amaura/ventures/cashflow")
    record("GET /api/amaura/ventures/cashflow", resp.status_code == 200, f"Status: {resp.status_code}")
    
    # Chat endpoint
    chat_payload = {"message": "Hello JARVIS, give me a status check."}
    resp = client.post("/api/chat", json=chat_payload)
    record("POST /api/chat", resp.status_code == 200, f"Status: {resp.status_code} | Response: {str(resp.json().get('response', ''))[:70]}...")


def test_desktop_and_launchers():
    print("\n--- 6. Testing Desktop App & Launch Scripts ---")
    desktop_main = ROOT / "desktop-app" / "main.js"
    desktop_preload = ROOT / "desktop-app" / "preload.js"
    desktop_package = ROOT / "desktop-app" / "package.json"
    
    record("Desktop main.js Exists", desktop_main.is_file(), f"Size: {desktop_main.stat().st_size} bytes")
    record("Desktop preload.js Exists", desktop_preload.is_file(), f"Size: {desktop_preload.stat().st_size} bytes")
    record("Desktop package.json Exists", desktop_package.is_file(), f"Size: {desktop_package.stat().st_size} bytes")
    
    # Verify launcher scripts
    launch_script = ROOT / "Launch_Amaura.command"
    launch_desktop = ROOT / "Launch_Amaura_Desktop.command"
    setup_agy = ROOT / "Setup_Amaura_Antigravity.command"
    jarvis_sh = ROOT / "jarvis.sh"
    
    record("Launch_Amaura.command", launch_script.is_file() and os.access(launch_script, os.X_OK), "Executable")
    record("Launch_Amaura_Desktop.command", launch_desktop.is_file() and os.access(launch_desktop, os.X_OK), "Executable")
    record("Setup_Amaura_Antigravity.command", setup_agy.is_file() and os.access(setup_agy, os.X_OK), "Executable")
    record("jarvis.sh", jarvis_sh.is_file() and os.access(jarvis_sh, os.X_OK), "Executable")


def main():
    print("=" * 70)
    print("  AMAURA JARVIS v5.4 — REAL-WORLD END-TO-END WORKFLOW QUALIFICATION")
    print("=" * 70)
    
    cp = AmauraControlPlane()
    
    test_diagnostics_and_readiness(cp)
    test_executive_cognition(cp)
    test_antigravity_engineering_bridge(cp)
    test_ventures_cashflow_engine(cp)
    test_fastapi_server_endpoints(cp)
    test_desktop_and_launchers()
    
    print("\n" + "=" * 70)
    print(f"  SUMMARY: {len(PASSED_STEPS)} PASSED / {len(FAILED_STEPS)} FAILED")
    print("=" * 70)
    
    if FAILED_STEPS:
        print("\nFailed steps:")
        for name, detail in FAILED_STEPS:
            print(f"  - {name}: {detail}")
        sys.exit(1)
    else:
        print("\n>>> ALL REAL-WORLD WORKFLOWS VERIFIED AND OPERATIONAL! JARVIS IS READY FOR PRODUCTION USAGE. <<<")
        sys.exit(0)


if __name__ == "__main__":
    main()
