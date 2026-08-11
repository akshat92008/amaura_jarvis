"""
Lightweight Control Center Web Server for Non-Coder Users.
Runs on Python standard library http.server (< 50 MB RAM usage).
Provides JSON API endpoints for running prompts, reading thinking traces,
inspecting workspace files, and viewing self-healing verification status.
"""

import http.server
import hmac
import socketserver
import json
import urllib.parse
import os
from pathlib import Path

from config import load_config, save_config
from fable_planner import FablePlanner
from executor import WorkspaceExecutor
from debugger import SelfHealingDebugger
from ast_indexer import ASTIndexer

PORT = 8085
BIND_HOST = os.environ.get("FABLE_BIND_HOST", "127.0.0.1")
BASE_DIR = Path(__file__).parent.resolve()


class FableEngineHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def _authorized(self):
        expected = os.environ.get("FABLE_SERVER_KEY", "")
        supplied = self.headers.get("X-Fable-Key", "")
        if not expected:
            self.send_json({"error": "FABLE_SERVER_KEY is not configured"}, status=503)
            return False
        if not hmac.compare_digest(supplied, expected):
            self.send_json({"error": "Authentication required"}, status=403)
            return False
        return True

    @staticmethod
    def _redacted_config():
        config = load_config()
        for key in list(config):
            if "key" in key.lower() or "token" in key.lower() or "secret" in key.lower():
                value = config.get(key)
                config[key] = bool(value) if not isinstance(value, list) else len(value)
        return config

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/status":
            self.send_json({"status": "online", "model": "Claude Fable 5 Level Autonomous Engine", "port": PORT})
        elif parsed.path == "/api/workspace":
            if not self._authorized():
                return
            executor = WorkspaceExecutor(os.environ.get("FABLE_WORKSPACE", os.getcwd()))
            indexer = ASTIndexer()
            files = executor.list_workspace()
            symbols = indexer.build_symbol_graph()
            self.send_json({"files": files, "symbols": symbols})
        elif parsed.path == "/api/config":
            if not self._authorized():
                return
            self.send_json(self._redacted_config())
        elif parsed.path == "/" or parsed.path.endswith(".html") or parsed.path.endswith(".css") or parsed.path.endswith(".js"):
            super().do_GET()
        else:
            self.send_error(404, "Endpoint not found")

    def do_POST(self):
        if not self._authorized():
            return
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode('utf-8') if length > 0 else "{}"
        data = json.loads(body)

        if parsed.path == "/api/generate":
            prompt = data.get("prompt", "")
            print(f"\n🚀 [Fable-5 Engine] Received prompt: '{prompt}'")
            planner = FablePlanner()
            workspace = os.environ.get("FABLE_WORKSPACE", os.getcwd())
            executor = WorkspaceExecutor(workspace)
            debugger = SelfHealingDebugger(workspace)

            # 1. Workspace context
            print("🔍 [Fable-5 Engine] Step 1: Indexing workspace file context...")
            workspace_files = {}
            for item in executor.list_workspace():
                if item.endswith((".py", ".js", ".html", ".css", ".json")):
                    workspace_files[item] = executor.read_file(item)

            # 2. Planning & Generation
            print("🧠 [Fable-5 Engine] Step 2: Generating Fable-5 CoT reasoning & code structure...")
            plan = planner.generate_plan_and_code(prompt, workspace_files)

            # 3. Apply files
            print(f"✍️ [Fable-5 Engine] Step 3: Writing {len(plan.get('files', []))} generated files...")
            applied_files = []
            for f_item in plan.get("files", []):
                p = f_item.get("path")
                c = f_item.get("content")
                if p and c:
                    executor.write_file(p, c)
                    applied_files.append(p)

            # 4. Self-Healing Verification
            test_cmd = plan.get("test_command", "python3 -m unittest test_engine.py")
            print(f"⚡ [Fable-5 Engine] Step 4: Running self-healing verification ('{test_cmd}')...")
            verification = debugger.run_and_repair(test_cmd)

            print("✅ [Fable-5 Engine] Task complete! Sending response to dashboard.\n")
            self.send_json({
                "thinking": plan.get("thinking", ""),
                "applied_files": applied_files,
                "verification": verification,
                "provider": plan.get("provider", "Engine")
            })

        elif parsed.path == "/api/config/save":
            if os.environ.get("FABLE_ALLOW_CONFIG_WRITE", "0") != "1":
                self.send_json({"error": "Configuration writes are disabled"}, status=403)
                return
            success = save_config(data)
            self.send_json({"success": success})

        else:
            self.send_error(404, "Unknown API route")

    def send_json(self, data_dict, status=200):
        body = json.dumps(data_dict).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server(start_port=8085):
    if os.environ.get("FABLE_SERVER_ENABLED", "0") != "1":
        raise RuntimeError("Legacy Fable dashboard is disabled. Set FABLE_SERVER_ENABLED=1 explicitly to run it.")
    socketserver.TCPServer.allow_reuse_address = True
    port = start_port
    max_attempts = 10
    
    for attempt in range(max_attempts):
        try:
            with socketserver.TCPServer((BIND_HOST, port), FableEngineHandler) as httpd:
                print(f"🚀 Fable-5 Engine Web Dashboard running at http://localhost:{port}")
                httpd.serve_forever()
                break
        except OSError as e:
            if e.errno == 48:  # Address already in use
                print(f"[Server Warning] Port {port} is in use. Trying port {port + 1}...")
                port += 1
            else:
                raise e


if __name__ == "__main__":
    run_server()
