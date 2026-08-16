"""
Project Fable-5 Engine Module for JARVIS.

Provides:
- MultiProviderRouter: Zero-cost priority failover across NVIDIA NIM, Gemini 2.0 Flash, Groq, Ollama, and local fallbacks.
- FablePlanner: Claude Fable 5 Mythos-Class Adaptive Reasoning Planner with CoT thinking traces.
- ASTIndexer: Surgical AST parser & symbol graph generator for Python/JS/TS codebases.
- WorkspaceExecutor: File & terminal execution context engine.
- SelfHealingDebugger: Closed-loop test verification & auto-repair debugger.
- FableControlCenter: Lightweight dashboard server handler.
"""

import ast
import hmac
import http.server
import json
import os
import shlex
import socketserver
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import certifi

# Base Paths
JARVIS_DIR = Path(__file__).parent.parent.resolve()
AIMODEL_DIR = JARVIS_DIR / "aimodel"
CONFIG_FILE = AIMODEL_DIR / "config.json"

DEFAULT_CONFIG = {
    "nvidia_api_key": os.getenv("NVIDIA_API_KEY", ""),
    "nvidia_api_keys": [],
    "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
    "groq_api_key": os.getenv("GROQ_API_KEY", ""),
    "cerebras_api_key": os.getenv("CEREBRAS_API_KEY", ""),
    "openrouter_api_key": os.getenv("OPENROUTER_API_KEY", ""),
    "ollama_url": os.getenv("OLLAMA_URL", "http://localhost:11434"),
    "default_provider": "auto",
    "max_thinking_budget": 8000,
    "auto_self_heal": True,
    "max_heal_attempts": 5,
}


def load_config() -> dict:
    """Load configuration from config.json or environment, merging all API keys."""
    from jarvis.api import _load_env_file

    _load_env_file()

    config = DEFAULT_CONFIG.copy()

    # Read config.json if present
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                user_conf = json.load(f)
                config.update(user_conf)
        except Exception as e:
            print(f"[Fable Engine Warning] Failed to read config.json: {e}")

    # Gather all NVIDIA keys into nvidia_api_keys list
    all_keys = list(config.get("nvidia_api_keys", []))
    primary_key = config.get("nvidia_api_key", "") or os.getenv("NVIDIA_API_KEY", "")
    if primary_key and primary_key not in all_keys:
        all_keys.insert(0, primary_key)

    for k in sorted(os.environ.keys()):
        if (
            k.startswith("NVIDIA_API_KEY") or k.startswith("NVIDIA_FALLBACK_API_KEY") or k.startswith("NVIDIA_KEY")
        ) and os.environ[k]:
            if os.environ[k] not in all_keys:
                all_keys.append(os.environ[k])

    config["nvidia_api_keys"] = all_keys
    if all_keys and not config.get("nvidia_api_key"):
        config["nvidia_api_key"] = all_keys[0]

    for p_key in ["gemini_api_key", "groq_api_key", "cerebras_api_key", "openrouter_api_key"]:
        env_val = os.getenv(p_key.upper())
        if env_val and not config.get(p_key):
            config[p_key] = env_val

    return config


def save_config(config_data: dict) -> bool:
    """Save configuration to config.json."""
    try:
        AIMODEL_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2)
        return True
    except Exception as e:
        print(f"[Fable Engine Error] Failed to save config.json: {e}")
        return False


def _get_ssl_context():
    try:
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


# ── MultiProviderRouter ───────────────────────────────────────────────────────


class MultiProviderRouter:
    """Multi-provider zero-cost priority fallback router."""

    def __init__(self):
        self.config = load_config()

    def get_available_providers(self) -> list[str]:
        providers = []
        if self.config.get("nvidia_api_key"):
            providers.append("nvidia_nim")
        if self.config.get("gemini_api_key"):
            providers.append("gemini_vertex")
        if self.config.get("groq_api_key"):
            providers.append("groq")
        if self.config.get("cerebras_api_key"):
            providers.append("cerebras")
        if self.config.get("openrouter_api_key"):
            providers.append("openrouter")
        providers.append("ollama_local")
        providers.append("mlx_local")
        return providers

    def call_nvidia(
        self, prompt: str, system_prompt: str = "", model_name: str = "meta/llama-3.3-70b-instruct"
    ) -> dict:
        keys = self.config.get("nvidia_api_keys", [])
        primary_key = self.config.get("nvidia_api_key", "")
        if primary_key and primary_key not in keys:
            keys.insert(0, primary_key)

        if not keys:
            raise ValueError("NVIDIA API key missing")

        errors = []
        url = "https://integrate.api.nvidia.com/v1/chat/completions"
        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt or "You are an elite autonomous coding AI engine powered by NVIDIA NIM.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 4096,
        }

        ctx = _get_ssl_context()
        for idx, key in enumerate(keys[:2]):  # Try max 2 keys to avoid delay accumulation
            try:
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {key}",
                    },
                )
                with urllib.request.urlopen(req, context=ctx, timeout=10.0) as response:
                    res_data = json.loads(response.read().decode("utf-8"))
                    content = res_data["choices"][0]["message"]["content"]
                    key_tag = f"Key #{idx + 1}"
                    return {"content": content, "provider": f"NVIDIA NIM ({model_name} via {key_tag})"}
            except Exception as e:
                errors.append(f"Key #{idx + 1} Error: {e}")
                # If network timeout or SSL error occurred, break early to proceed to instant Groq fallback
                if "timed out" in str(e).lower() or "certificate" in str(e).lower() or "ssl" in str(e).lower():
                    break

        raise ValueError(f"All NVIDIA API keys failed: {'; '.join(errors)}")

    def call_gemini(self, prompt: str, system_prompt: str = "") -> dict:
        api_key = self.config.get("gemini_api_key")
        if not api_key:
            raise ValueError("Gemini API key missing")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"System: {system_prompt}\n\nUser: {prompt}"}],
                }
            ]
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

        ctx = _get_ssl_context()
        with urllib.request.urlopen(req, context=ctx, timeout=5) as response:
            res = json.loads(response.read().decode("utf-8"))
            text = res["candidates"][0]["content"]["parts"][0]["text"]
            return {"content": text, "provider": "Gemini 2.0 Flash (Cloud Engine)"}

    def call_groq(self, prompt: str, system_prompt: str = "") -> dict:
        api_key = self.config.get("groq_api_key")
        if not api_key:
            raise ValueError("Groq API key missing")

        url = "https://api.groq.com/openai/v1/chat/completions"
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": system_prompt or "You are an elite autonomous coding AI."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )

        ctx = _get_ssl_context()
        with urllib.request.urlopen(req, context=ctx, timeout=5) as response:
            res = json.loads(response.read().decode("utf-8"))
            content = res["choices"][0]["message"]["content"]
            return {"content": content, "provider": "Groq (Llama-3.3-70B)"}

    def call_ollama(self, prompt: str, system_prompt: str = "", model_name: str = "qwen2.5-coder:1.5b") -> dict:
        ollama_url = self.config.get("ollama_url", "http://localhost:11434")
        url = f"{ollama_url}/api/chat"
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt or "You are a local coding assistant."},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

        with urllib.request.urlopen(req, timeout=3) as response:
            res = json.loads(response.read().decode("utf-8"))
            content = res["message"]["content"]
            return {"content": content, "provider": f"Local Ollama ({model_name})"}

    def generate(self, prompt: str, system_prompt: str = "") -> dict:
        """Attempts generation across providers in priority order with instant fallback."""
        errors = []

        # 1. NVIDIA NIM High-Performance API Tier
        if self.config.get("nvidia_api_key"):
            try:
                return self.call_nvidia(prompt, system_prompt)
            except Exception as e:
                errors.append(f"NVIDIA API error: {e}")

        # 2. Groq Llama-3.3-70B (Ultra-Fast Cloud Fallback)
        if self.config.get("groq_api_key"):
            try:
                return self.call_groq(prompt, system_prompt)
            except Exception as e:
                errors.append(f"Groq error: {e}")

        # 3. Gemini Flash (Cloud Engine Fallback)
        if self.config.get("gemini_api_key"):
            try:
                return self.call_gemini(prompt, system_prompt)
            except Exception as e:
                errors.append(f"Gemini error: {e}")

        # 4. Local Ollama Model
        try:
            return self.call_ollama(prompt, system_prompt)
        except Exception as e:
            errors.append(f"Ollama error: {e}")

        # 5. Synthetic Fallback Engine Output
        return {
            "content": f"[Autonomous Local Harness Mode]\n\n"
            f"Task Received: {prompt[:100]}...\n\n"
            f"System Note: Provide your NVIDIA API key in config.json or start Ollama (`ollama run qwen2.5-coder:1.5b`) for full autonomous generation.",
            "provider": "Local Autonomous Engine",
            "warnings": errors,
        }


# ── FablePlanner ─────────────────────────────────────────────────────────────


class FablePlanner:
    """Claude Fable 5 Mythos-Class Adaptive Reasoning Planner Engine."""

    def __init__(self, router: MultiProviderRouter | None = None):
        self.router = router or MultiProviderRouter()

    def generate_plan_and_code(self, task_prompt: str, workspace_files: dict | None = None) -> dict:
        system_prompt = (
            "You are the Claude Fable 5 Mythos-Class Autonomous Software Engineering Engine.\n"
            "Your objective is to produce production-grade, long-horizon, zero-bug code.\n\n"
            "MANDATORY FABLE-5 EXECUTION FORMAT:\n"
            "1. <<THINKING>>: Multi-stage CoT architectural trace analyzing component boundaries, "
            "data flow, potential edge cases, and self-verification test strategy.\n"
            "2. <<FILES>>: JSON array of target file actions containing 'path', 'action' ('write'/'edit'), "
            "and complete, non-truncated 'content'.\n"
            "3. <<TEST_COMMAND>>: Exact terminal command line required to verify execution success (e.g. 'python3 test_engine.py')."
        )

        full_prompt = f"Fable-5 Engineering Task Request: {task_prompt}\n"
        if workspace_files:
            full_prompt += f"\nWorkspace File Tree & Symbol Context:\n{json.dumps(workspace_files, indent=2)}\n"

        result = self.router.generate(full_prompt, system_prompt=system_prompt)
        raw_output = result["content"]

        thinking_trace = ""
        files_to_create = []
        test_command = "python3 -m unittest test_engine.py"

        if "<<THINKING>>" in raw_output:
            parts = raw_output.split("<<FILES>>")
            thinking_trace = parts[0].replace("<<THINKING>>", "").strip()

            if len(parts) > 1:
                files_part = parts[1].split("<<TEST_COMMAND>>")[0].strip()
                try:
                    clean_json = files_part.replace("```json", "").replace("```", "").strip()
                    files_to_create = json.loads(clean_json)
                except Exception as e:
                    print(f"[Fable-5 Planner Warning] Failed to parse JSON files: {e}")

                if "<<TEST_COMMAND>>" in parts[1]:
                    test_command = parts[1].split("<<TEST_COMMAND>>")[1].strip()
        else:
            thinking_trace = (
                f"Fable-5 CoT Plan generated for task request: {task_prompt}\n"
                f"- Analyzing requirement: {task_prompt}\n"
                f"- Emitting target python application code..."
            )
            if "```python" in raw_output:
                code_block = raw_output.split("```python")[1].split("```")[0].strip()
                files_to_create = [{"path": "main.py", "action": "write", "content": code_block}]

        if not files_to_create:
            files_to_create = [
                {"path": "main.py", "action": "write", "content": raw_output or "# Generated Application"}
            ]

        if not test_command or "\n" in test_command or test_command.startswith("*") or len(test_command) > 200:
            test_command = "python3 main.py"

        return {
            "thinking": thinking_trace,
            "files": files_to_create,
            "test_command": test_command,
            "raw_response": raw_output,
            "provider": result.get("provider", "Claude Fable 5 Harness"),
        }


# ── ASTIndexer ───────────────────────────────────────────────────────────────


class ASTIndexer:
    """Surgical AST Indexer Module for Python/JS/TS codebases."""

    def __init__(self, workspace_dir: str | None = None):
        self.workspace_dir = Path(workspace_dir or os.getcwd()).resolve()

    def parse_file(self, relative_path: str) -> dict | None:
        full_path = self.workspace_dir / relative_path
        if not full_path.exists() or not relative_path.endswith(".py"):
            return None

        try:
            with open(full_path, encoding="utf-8") as f:
                code = f.read()
            tree = ast.parse(code)
        except Exception as e:
            return {"error": f"Failed to parse AST: {e}"}

        symbols: dict[str, list[Any]] = {"classes": [], "functions": [], "imports": []}

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                methods = [m.name for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
                symbols["classes"].append(
                    {
                        "name": node.name,
                        "methods": methods,
                        "line": node.lineno,
                    }
                )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = [a.arg for a in node.args.args]
                symbols["functions"].append(
                    {
                        "name": node.name,
                        "args": args,
                        "line": node.lineno,
                    }
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    symbols["imports"].append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    symbols["imports"].append(f"{module}.{alias.name}")

        return symbols

    def build_symbol_graph(self) -> dict:
        graph = {}
        for root, _, files in os.walk(self.workspace_dir):
            for file in files:
                if file.endswith(".py") and "__pycache__" not in root:
                    rel_path = os.path.relpath(os.path.join(root, file), self.workspace_dir)
                    symbols = self.parse_file(rel_path)
                    if symbols and "error" not in symbols:
                        graph[rel_path] = symbols
        return graph


# ── WorkspaceExecutor ─────────────────────────────────────────────────────────


class WorkspaceExecutor:
    """Constrained legacy workspace executor. Prefer Amaura sandbox execution."""

    _ALLOWED_EXECUTABLES = {
        "python",
        "python3",
        "pytest",
        "ruff",
        "mypy",
        "npm",
        "npx",
        "node",
        "pnpm",
        "yarn",
        "git",
    }
    _SHELL_META = {";", "&&", "||", "|", ">", "<", "`", "$(", "${"}

    def __init__(self, workspace_dir: str | None = None):
        self.workspace_dir = Path(workspace_dir or os.getcwd()).resolve()

    def _resolve(self, relative_path: str) -> Path:
        candidate = Path(relative_path)
        if candidate.is_absolute():
            raise ValueError("Absolute paths are not allowed")
        target = (self.workspace_dir / candidate).resolve(strict=False)
        try:
            target.relative_to(self.workspace_dir)
        except ValueError as exc:
            raise ValueError("Path escapes the configured workspace") from exc
        return target

    def write_file(self, relative_path: str, content: str) -> str:
        target_path = self._resolve(relative_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path = self._resolve(relative_path)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)
        return str(target_path)

    def read_file(self, relative_path: str) -> str | None:
        target_path = self._resolve(relative_path)
        if not target_path.exists() or not target_path.is_file():
            return None
        with open(target_path, encoding="utf-8") as f:
            return f.read()

    def list_workspace(self) -> list[str]:
        items = []
        for root, dirs, files in os.walk(self.workspace_dir, followlinks=False):
            dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "venv", ".venv"}]
            for file in files:
                full = Path(root) / file
                try:
                    full.resolve(strict=False).relative_to(self.workspace_dir)
                except (OSError, ValueError):
                    continue
                rel = os.path.relpath(full, self.workspace_dir)
                if not rel.startswith(".") and "__pycache__" not in rel:
                    items.append(rel)
        return sorted(items)

    def _parse_command(self, command_str: str) -> list[str]:
        if not isinstance(command_str, str) or not command_str.strip():
            raise ValueError("Command must be a non-empty string")
        if any(token in command_str for token in self._SHELL_META):
            raise ValueError("Shell operators and interpolation are not allowed")
        args = shlex.split(command_str, posix=True)
        if not args:
            raise ValueError("Command must not be empty")
        executable = Path(args[0]).name
        if executable not in self._ALLOWED_EXECUTABLES:
            raise ValueError(f"Executable '{executable}' is not allowlisted")
        return args

    def run_command(self, command_str: str, timeout: int = 30) -> dict:
        try:
            args = self._parse_command(command_str)
            res = subprocess.run(
                args,
                shell=False,
                cwd=self.workspace_dir,
                capture_output=True,
                text=True,
                timeout=min(max(int(timeout), 1), 300),
            )
            return {
                "exit_code": res.returncode,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "success": res.returncode == 0,
            }
        except subprocess.TimeoutExpired:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command timed out after {timeout}s",
                "success": False,
            }
        except Exception as exc:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": str(exc),
                "success": False,
            }


# ── SelfHealingDebugger ───────────────────────────────────────────────────────


class SelfHealingDebugger:
    """Autonomous Self-Healing Verification & Debugger Engine."""

    def __init__(self, workspace_dir: str | None = None, max_attempts: int = 5):
        self.executor = WorkspaceExecutor(workspace_dir)
        self.planner = FablePlanner()
        self.max_attempts = max_attempts

    def extract_error_summary(self, stderr: str, stdout: str) -> str:
        full_log = f"{stdout}\n{stderr}"
        lines = full_log.strip().split("\n")
        relevant_lines = [
            line
            for line in lines
            if any(k in line.lower() for k in ["error", "exception", "failed", "assert", "traceback"])
        ]
        if not relevant_lines:
            relevant_lines = lines[-15:]
        return "\n".join(relevant_lines)

    def run_and_repair(self, test_command: str = "python3 -m unittest discover") -> dict:
        error_log = ""
        for attempt in range(1, self.max_attempts + 1):
            print(
                f"[Self-Healer] Execution Verification Attempt {attempt}/{self.max_attempts}: running '{test_command}'..."
            )
            res = self.executor.run_command(test_command)

            if res["success"]:
                print(f"[Self-Healer] Verification SUCCESS on attempt {attempt}!")
                return {
                    "success": True,
                    "attempts": attempt,
                    "output": res["stdout"],
                }

            error_log = self.extract_error_summary(res["stderr"], res["stdout"])
            print(f"[Self-Healer] Build/Test Failure Detected:\n{error_log[:300]}...\n")

            if attempt == self.max_attempts:
                break

            repair_prompt = (
                f"AUTONOMOUS SELF-HEALING REPAIR REQUIRED (Attempt {attempt}/{self.max_attempts})\n\n"
                f"The test command '{test_command}' failed with the following traceback error:\n"
                f"```\n{error_log}\n```\n\n"
                f"Analyze the root cause error. Generate surgical file patches to fix this bug completely."
            )

            workspace_files = {}
            for item in self.executor.list_workspace():
                if item.endswith((".py", ".js", ".json", ".html", ".css")):
                    workspace_files[item] = self.executor.read_file(item)

            repair_plan = self.planner.generate_plan_and_code(repair_prompt, workspace_files)

            for file_item in repair_plan.get("files", []):
                path = file_item.get("path")
                content = file_item.get("content")
                if path and content:
                    print(f"[Self-Healer] Applying surgical repair patch to {path}...")
                    self.executor.write_file(path, content)

        return {
            "success": False,
            "attempts": self.max_attempts,
            "error_log": error_log,
        }


# ── FableControlCenter Dashboard Handler ───────────────────────────────────────


class FableEngineHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(AIMODEL_DIR), **kwargs)

    def _authorized(self) -> bool:
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
    def _redacted_config() -> dict:
        config = load_config()
        for key in list(config):
            if "key" in key.lower() or "token" in key.lower() or "secret" in key.lower():
                value = config.get(key)
                config[key] = bool(value) if not isinstance(value, list) else len(value)
        return config

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/status":
            self.send_json({"status": "online", "model": "Claude Fable 5 Level Autonomous Engine", "port": 8085})
        elif parsed.path == "/api/workspace":
            if not self._authorized():
                return
            workspace = os.environ.get("FABLE_WORKSPACE", os.getcwd())
            executor = WorkspaceExecutor(workspace)
            indexer = ASTIndexer(workspace)
            files = executor.list_workspace()
            symbols = indexer.build_symbol_graph()
            self.send_json({"files": files, "symbols": symbols})
        elif parsed.path == "/api/config":
            if not self._authorized():
                return
            self.send_json(self._redacted_config())
        elif parsed.path == "/" or parsed.path.endswith((".html", ".css", ".js")):
            super().do_GET()
        else:
            self.send_error(404, "Endpoint not found")

    def do_POST(self):
        if not self._authorized():
            return
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        data = json.loads(body)

        if parsed.path == "/api/generate":
            prompt = data.get("prompt", "")
            print(f"\n🚀 [Fable-5 Engine] Received prompt: '{prompt}'")
            planner = FablePlanner()
            workspace = os.environ.get("FABLE_WORKSPACE", os.getcwd())
            executor = WorkspaceExecutor(workspace)
            debugger = SelfHealingDebugger(workspace)

            workspace_files = {}
            for item in executor.list_workspace():
                if item.endswith((".py", ".js", ".html", ".css", ".json")):
                    workspace_files[item] = executor.read_file(item)

            plan = planner.generate_plan_and_code(prompt, workspace_files)

            applied_files = []
            for f_item in plan.get("files", []):
                p = f_item.get("path")
                c = f_item.get("content")
                if p and c:
                    executor.write_file(p, c)
                    applied_files.append(p)

            test_cmd = plan.get("test_command", "python3 -m unittest discover")
            verification = debugger.run_and_repair(test_cmd)

            self.send_json(
                {
                    "thinking": plan.get("thinking", ""),
                    "applied_files": applied_files,
                    "verification": verification,
                    "provider": plan.get("provider", "Engine"),
                }
            )

        elif parsed.path == "/api/config/save":
            if os.environ.get("FABLE_ALLOW_CONFIG_WRITE", "0") != "1":
                self.send_json({"error": "Configuration writes are disabled"}, status=403)
                return
            success = save_config(data)
            self.send_json({"success": success})

        else:
            self.send_error(404, "Unknown API route")

    def send_json(self, data_dict: dict, status: int = 200):
        body = json.dumps(data_dict).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_fable_dashboard(start_port: int = 8085):
    if os.environ.get("FABLE_SERVER_ENABLED", "0") != "1":
        raise RuntimeError("Legacy Fable dashboard is disabled. Set FABLE_SERVER_ENABLED=1 explicitly to run it.")
    socketserver.TCPServer.allow_reuse_address = True
    port = start_port
    max_attempts = 10

    for _attempt in range(max_attempts):
        try:
            with socketserver.TCPServer(
                (os.environ.get("FABLE_BIND_HOST", "127.0.0.1"), port), FableEngineHandler
            ) as httpd:
                print(f"🚀 Fable-5 Engine Web Dashboard running at http://localhost:{port}")
                httpd.serve_forever()
                break
        except OSError as e:
            if e.errno == 48:
                print(f"[Server Warning] Port {port} is in use. Trying port {port + 1}...")
                port += 1
            else:
                raise e
