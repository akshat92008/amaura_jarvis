"""
AI Agent Factory — create, manage, and deploy autonomous AI agents.

8 tools that let Jarvis create fully functional AI agents with custom
personalities, tools, and capabilities. Each agent can run autonomously
on tasks, coordinate with other agents, and be exported as standalone
Python projects.
"""

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from jarvis.paths import get_data_dir

# ── Agent Storage ────────────────────────────────────────────────────────────

AGENTS_DIR = get_data_dir() / "agents"
AGENTS_DIR.mkdir(parents=True, exist_ok=True)


class AgentDefinition:
    """Represents a created AI agent."""

    def __init__(
        self,
        name: str,
        agent_id: str = "",
        system_prompt: str = "",
        personality: str = "",
        tools: list = None,
        custom_tools: list = None,
        model: str = "",
        description: str = "",
        created_at: str = "",
        status: str = "ready",
        workspace: str = "",
    ):
        self.agent_id = agent_id or str(uuid.uuid4())[:8]
        self.name = name
        self.system_prompt = system_prompt
        self.personality = personality or "helpful and precise"
        self.tools = tools or []
        self.custom_tools = custom_tools or []
        self.model = model or "llama-3.1-70b"
        self.description = description
        self.created_at = created_at or datetime.now().isoformat()
        self.status = status
        self.workspace = workspace or os.getcwd()

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "system_prompt": self.system_prompt,
            "personality": self.personality,
            "tools": self.tools,
            "custom_tools": self.custom_tools,
            "model": self.model,
            "description": self.description,
            "created_at": self.created_at,
            "status": self.status,
            "workspace": self.workspace,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AgentDefinition":
        return cls(**d)

    def save(self):
        agent_dir = AGENTS_DIR / self.agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "agent.json").write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, agent_id: str) -> Optional["AgentDefinition"]:
        agent_file = AGENTS_DIR / agent_id / "agent.json"
        if not agent_file.exists():
            return None
        return cls.from_dict(json.loads(agent_file.read_text(encoding="utf-8")))


# ── Tool Definitions ─────────────────────────────────────────────────────────

AGENT_FACTORY_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "create_agent",
            "description": "Create a fully functional AI agent with custom system prompt, personality, tools, and model. The agent can later be run on tasks autonomously.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Agent name (e.g., 'CodeReviewer', 'DataAnalyst', 'SecurityAuditor').",
                    },
                    "description": {"type": "string", "description": "What this agent does."},
                    "system_prompt": {
                        "type": "string",
                        "description": "The agent's system prompt defining its behavior, expertise, and rules.",
                    },
                    "personality": {
                        "type": "string",
                        "description": "Personality traits (e.g., 'meticulous and thorough', 'fast and concise').",
                    },
                    "tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Which Jarvis tools this agent can use (e.g., ['read_file', 'write_file', 'run_command']). Use 'all' for all tools.",
                    },
                    "model": {
                        "type": "string",
                        "description": "Model to use (default: llama-3.1-70b). Options: deepseek-v4, kimi-k3, glm-5.2, etc.",
                    },
                    "workspace": {"type": "string", "description": "Working directory for the agent."},
                },
                "required": ["name", "description", "system_prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_agents",
            "description": "List all created AI agents with their status, model, and capabilities.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_agent",
            "description": "Execute a child agent on a specific task. The agent runs autonomously using its configured tools and model, then returns the result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID or name to run."},
                    "task": {"type": "string", "description": "The task/prompt to give the agent."},
                    "max_iterations": {"type": "integer", "description": "Maximum tool-use iterations (default: 20)."},
                },
                "required": ["agent_id", "task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agent_status",
            "description": "Get detailed status and configuration of a specific agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID or name."},
                },
                "required": ["agent_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_agent",
            "description": "Delete a created agent and all its data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID or name to delete."},
                },
                "required": ["agent_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_agent_tool",
            "description": "Define a custom tool for an agent. The tool is a shell command or Python function that the agent can invoke.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID to add the tool to."},
                    "tool_name": {"type": "string", "description": "Name of the custom tool."},
                    "description": {"type": "string", "description": "What the tool does."},
                    "tool_type": {
                        "type": "string",
                        "description": "Type: 'command' (shell command) or 'python' (Python function).",
                    },
                    "command_template": {
                        "type": "string",
                        "description": "For command type: shell command with {arg} placeholders.",
                    },
                    "python_code": {"type": "string", "description": "For python type: Python function code."},
                    "parameters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "type": {"type": "string"},
                                "description": {"type": "string"},
                                "required": {"type": "boolean"},
                            },
                        },
                        "description": "Tool parameters.",
                    },
                },
                "required": ["agent_id", "tool_name", "description", "tool_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_agent",
            "description": "Package an agent as a standalone Python project that can be run independently. Generates all files needed: main.py, config, requirements, README.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID or name to export."},
                    "output_path": {
                        "type": "string",
                        "description": "Directory to export to (default: ~/Desktop/agents/<name>).",
                    },
                    "include_api_key": {
                        "type": "boolean",
                        "description": "Include API key in config (default: false for security).",
                    },
                },
                "required": ["agent_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_multi_agent_system",
            "description": "Create a coordinated multi-agent system with an orchestrator and specialized worker agents. The orchestrator routes tasks to the appropriate worker.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "System name (e.g., 'DevTeam', 'ResearchLab')."},
                    "description": {"type": "string", "description": "What this agent system does."},
                    "agents": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Agent name."},
                                "role": {"type": "string", "description": "Agent's role/specialty."},
                                "system_prompt": {"type": "string", "description": "Agent's system prompt."},
                                "tools": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Tools this agent can use.",
                                },
                            },
                        },
                        "description": "List of worker agents to create.",
                    },
                    "orchestrator_prompt": {
                        "type": "string",
                        "description": "Custom orchestrator prompt (auto-generated if omitted).",
                    },
                },
                "required": ["name", "description", "agents"],
            },
        },
    },
]


# ── Helper Functions ─────────────────────────────────────────────────────────


def _find_agent(identifier: str) -> AgentDefinition | None:
    """Find an agent by ID or name."""
    # Try direct ID match
    agent = AgentDefinition.load(identifier)
    if agent:
        return agent

    # Search by name
    for agent_dir in AGENTS_DIR.iterdir():
        if not agent_dir.is_dir():
            continue
        agent_file = agent_dir / "agent.json"
        if agent_file.exists():
            try:
                data = json.loads(agent_file.read_text(encoding="utf-8"))
                if data.get("name", "").lower() == identifier.lower():
                    return AgentDefinition.from_dict(data)
            except Exception:
                continue
    return None


# ── Tool Implementations ─────────────────────────────────────────────────────


def tool_create_agent(
    name: str,
    description: str,
    system_prompt: str,
    personality: str = "",
    tools: list = None,
    model: str = "",
    workspace: str = "",
) -> str:
    """Create a new AI agent."""
    # Validate name
    if not name or not re.match(r"^[A-Za-z][A-Za-z0-9_-]*$", name):
        return "❌ Invalid agent name. Use alphanumeric characters, hyphens, and underscores."

    # Check for duplicate names
    existing = _find_agent(name)
    if existing:
        return (
            f"❌ Agent '{name}' already exists (ID: {existing.agent_id}). Delete it first or choose a different name."
        )

    agent = AgentDefinition(
        name=name,
        description=description,
        system_prompt=system_prompt,
        personality=personality,
        tools=tools or ["all"],
        model=model or "llama-3.1-70b",
        workspace=workspace,
    )

    agent.save()

    # Create agent's workspace
    agent_workspace = AGENTS_DIR / agent.agent_id / "workspace"
    agent_workspace.mkdir(parents=True, exist_ok=True)

    # Save conversation history placeholder
    (AGENTS_DIR / agent.agent_id / "history.json").write_text("[]", encoding="utf-8")

    tools_str = ", ".join(agent.tools[:10])
    if len(agent.tools) > 10:
        tools_str += f" ... (+{len(agent.tools) - 10} more)"

    return f"""✅ Agent Created Successfully!

🤖 **{agent.name}** (ID: `{agent.agent_id}`)
📝 {agent.description}
🧠 Model: {agent.model}
🛠️ Tools: {tools_str}
💾 Stored at: {AGENTS_DIR / agent.agent_id}

**Run it:** Use `run_agent` with ID `{agent.agent_id}` and a task.
**Export it:** Use `export_agent` to create a standalone project."""


def tool_list_agents() -> str:
    """List all created agents."""
    agents = []
    for agent_dir in sorted(AGENTS_DIR.iterdir()):
        if not agent_dir.is_dir():
            continue
        agent_file = agent_dir / "agent.json"
        if agent_file.exists():
            try:
                data = json.loads(agent_file.read_text(encoding="utf-8"))
                agents.append(data)
            except Exception:
                continue

    if not agents:
        return "No agents created yet. Use `create_agent` to create one."

    lines = [f"# Created Agents ({len(agents)})\n"]
    for a in agents:
        status_icon = {"ready": "🟢", "running": "🔵", "error": "🔴", "stopped": "⚪"}.get(
            a.get("status", "ready"), "⚪"
        )
        lines.append(f"{status_icon} **{a['name']}** (`{a['agent_id']}`)")
        lines.append(f"   {a.get('description', 'No description')}")
        lines.append(
            f"   Model: {a.get('model', 'default')} | Tools: {len(a.get('tools', []))} | Created: {a.get('created_at', '?')[:10]}"
        )
        lines.append("")

    return "\n".join(lines)


def tool_run_agent(agent_id: str, task: str, max_iterations: int = 20) -> str:
    """Run an agent on a task."""
    agent = _find_agent(agent_id)
    if not agent:
        return f"❌ Agent not found: {agent_id}. Use `list_agents` to see available agents."

    # Update status
    agent.status = "running"
    agent.save()

    # Build the agent's execution context
    result_lines = [
        f"# Agent Execution: {agent.name}",
        f"**Task:** {task}",
        f"**Model:** {agent.model}",
        "**Status:** Running...",
        "",
    ]

    try:
        # Use Jarvis's own API client to run the agent
        from jarvis.api import NvidiaClient
        from jarvis.models import resolve_model
        from jarvis.tools.registry import ALL_TOOL_DEFINITIONS, execute_tool

        client = NvidiaClient()
        model_cfg = resolve_model(agent.model)
        if not model_cfg:
            agent.status = "error"
            agent.save()
            return f"❌ Model '{agent.model}' not found."

        # Build messages
        messages = [
            {"role": "system", "content": agent.system_prompt},
            {"role": "user", "content": task},
        ]

        # Filter tools
        if "all" in agent.tools:
            tools = list(ALL_TOOL_DEFINITIONS)
        else:
            tools = [t for t in ALL_TOOL_DEFINITIONS if t["function"]["name"] in agent.tools]

        # Agentic loop
        iteration = 0
        final_response = ""

        while iteration < max_iterations:
            iteration += 1

            try:
                response = client.chat_sync(
                    model_id=model_cfg["id"],
                    messages=messages,
                    tools=tools if model_cfg.get("supports_tools") else None,
                )
            except Exception as e:
                agent.status = "error"
                agent.save()
                return f"❌ Agent API error: {e}"

            choice = response.choices[0]
            content = choice.message.content or ""
            tool_calls = choice.message.tool_calls or []

            if tool_calls:
                # Record assistant message
                messages.append(
                    {
                        "role": "assistant",
                        "content": content or None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                            }
                            for tc in tool_calls
                        ],
                    }
                )

                # Execute tools
                for tc in tool_calls:
                    name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}

                    result = execute_tool(name, args)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                    result_lines.append(f"🔧 Tool: `{name}` → {'✅' if not result.startswith('❌') else '❌'}")

                continue

            # No tool calls — agent is done
            final_response = content
            break

        agent.status = "ready"
        agent.save()

        # Save execution log
        log = {
            "task": task,
            "timestamp": datetime.now().isoformat(),
            "iterations": iteration,
            "response": final_response,
        }
        log_file = AGENTS_DIR / agent.agent_id / "last_run.json"
        log_file.write_text(json.dumps(log, indent=2), encoding="utf-8")

        result_lines.append(f"\n**Completed in {iteration} iteration(s).**\n")
        result_lines.append("## Agent Response\n")
        result_lines.append(final_response)

        return "\n".join(result_lines)

    except Exception as e:
        agent.status = "error"
        agent.save()
        return f"❌ Agent execution failed: {e}"


def tool_agent_status(agent_id: str) -> str:
    """Get agent status and config."""
    agent = _find_agent(agent_id)
    if not agent:
        return f"❌ Agent not found: {agent_id}"

    lines = [
        f"# Agent: {agent.name}",
        f"**ID:** `{agent.agent_id}`",
        f"**Status:** {agent.status}",
        f"**Model:** {agent.model}",
        f"**Created:** {agent.created_at}",
        f"**Workspace:** {agent.workspace}",
        f"**Personality:** {agent.personality}",
        f"\n**Tools ({len(agent.tools)}):** {', '.join(agent.tools[:15])}",
        f"\n## System Prompt\n```\n{agent.system_prompt[:500]}{'...' if len(agent.system_prompt) > 500 else ''}\n```",
    ]

    # Check for last run
    last_run_file = AGENTS_DIR / agent.agent_id / "last_run.json"
    if last_run_file.exists():
        try:
            last_run = json.loads(last_run_file.read_text(encoding="utf-8"))
            lines.append("\n## Last Run")
            lines.append(f"**Task:** {last_run.get('task', '?')[:100]}")
            lines.append(f"**Time:** {last_run.get('timestamp', '?')}")
            lines.append(f"**Iterations:** {last_run.get('iterations', '?')}")
        except Exception:
            pass

    # Custom tools
    if agent.custom_tools:
        lines.append(f"\n## Custom Tools ({len(agent.custom_tools)})")
        for ct in agent.custom_tools:
            lines.append(f"- **{ct.get('name', '?')}**: {ct.get('description', '?')}")

    return "\n".join(lines)


def tool_delete_agent(agent_id: str) -> str:
    """Delete an agent."""
    agent = _find_agent(agent_id)
    if not agent:
        return f"❌ Agent not found: {agent_id}"

    import shutil

    agent_dir = AGENTS_DIR / agent.agent_id
    if agent_dir.exists():
        shutil.rmtree(agent_dir)

    return f"✅ Agent '{agent.name}' (ID: {agent.agent_id}) deleted."


def tool_create_agent_tool(
    agent_id: str,
    tool_name: str,
    description: str,
    tool_type: str,
    command_template: str = "",
    python_code: str = "",
    parameters: list = None,
) -> str:
    """Add a custom tool to an agent."""
    agent = _find_agent(agent_id)
    if not agent:
        return f"❌ Agent not found: {agent_id}"

    if tool_type not in ("command", "python"):
        return "❌ tool_type must be 'command' or 'python'."

    custom_tool = {
        "name": tool_name,
        "description": description,
        "type": tool_type,
        "command_template": command_template,
        "python_code": python_code,
        "parameters": parameters or [],
    }

    agent.custom_tools.append(custom_tool)
    agent.save()

    # Save the custom tool code
    tools_dir = AGENTS_DIR / agent.agent_id / "custom_tools"
    tools_dir.mkdir(parents=True, exist_ok=True)

    if tool_type == "python" and python_code:
        (tools_dir / f"{tool_name}.py").write_text(python_code, encoding="utf-8")
    elif tool_type == "command" and command_template:
        (tools_dir / f"{tool_name}.sh").write_text(f"#!/bin/bash\n{command_template}\n", encoding="utf-8")

    return f"✅ Custom tool '{tool_name}' added to agent '{agent.name}'.\nType: {tool_type}\nDescription: {description}"


def tool_export_agent(agent_id: str, output_path: str = "", include_api_key: bool = False) -> str:
    """Export an agent as a standalone Python project."""
    agent = _find_agent(agent_id)
    if not agent:
        return f"❌ Agent not found: {agent_id}"

    if not output_path:
        safe_name = re.sub(r"[^a-z0-9_]", "_", agent.name.lower())
        output_path = str(Path.home() / "Desktop" / "agents" / safe_name)

    out = Path(output_path).expanduser().resolve()
    if out.exists():
        return f"❌ Output directory already exists: {out}"

    out.mkdir(parents=True)

    # Generate the standalone agent
    _write_agent_file(out, "requirements.txt", "openai>=1.30.0\nrich>=13.7.0\nhttpx>=0.27.0")

    _write_agent_file(
        out,
        "config.json",
        json.dumps(
            {
                "name": agent.name,
                "model": agent.model,
                "api_base_url": "https://integrate.api.nvidia.com/v1",
                "api_key_env": "NVIDIA_API_KEY",
                "api_key": os.environ.get("NVIDIA_API_KEY", "") if include_api_key else "",
                "max_iterations": 30,
                "temperature": 0.2,
            },
            indent=2,
        ),
    )

    # System prompt file
    _write_agent_file(out, "system_prompt.txt", agent.system_prompt)

    # Main agent file
    main_code = f'''#!/usr/bin/env python3
"""
{agent.name} — Autonomous AI Agent
{agent.description}

Generated by J.A.R.V.I.S. Agent Factory on {datetime.now().strftime("%Y-%m-%d")}.
"""

import os
import sys
import json
from pathlib import Path
from openai import OpenAI

# ── Configuration ────────────────────────────────────────────────────────────

CONFIG = json.loads((Path(__file__).parent / "config.json").read_text())
SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.txt").read_text()

# ── Tools ────────────────────────────────────────────────────────────────────

TOOLS = [
    {{
        "type": "function",
        "function": {{
            "name": "run_command",
            "description": "Execute a shell command and return the output.",
            "parameters": {{
                "type": "object",
                "properties": {{
                    "command": {{"type": "string", "description": "Shell command to execute."}},
                }},
                "required": ["command"],
            }},
        }},
    }},
    {{
        "type": "function",
        "function": {{
            "name": "read_file",
            "description": "Read a file and return its contents.",
            "parameters": {{
                "type": "object",
                "properties": {{
                    "path": {{"type": "string", "description": "File path to read."}},
                }},
                "required": ["path"],
            }},
        }},
    }},
    {{
        "type": "function",
        "function": {{
            "name": "write_file",
            "description": "Write content to a file.",
            "parameters": {{
                "type": "object",
                "properties": {{
                    "path": {{"type": "string", "description": "File path to write."}},
                    "content": {{"type": "string", "description": "Content to write."}},
                }},
                "required": ["path", "content"],
            }},
        }},
    }},
]


def execute_tool(name: str, args: dict) -> str:
    """Execute a tool by name."""
    import shlex
    import subprocess

    if name == "run_command":
        try:
            command = args.get("command", "")
            if any(ch in command for ch in "\n\r;&|<>`$"):
                raise ValueError("shell operators are not allowed")
            argv = shlex.split(command)
            if not argv:
                raise ValueError("empty command")
            result = subprocess.run(
                argv, shell=False,
                capture_output=True, text=True, timeout=120,
            )
            output = result.stdout + result.stderr
            return output.strip() or "(no output)"
        except Exception as e:
            return f"Error: {{e}}"

    elif name == "read_file":
        try:
            return Path(args.get("path", "")).read_text(encoding="utf-8")
        except Exception as e:
            return f"Error: {{e}}"

    elif name == "write_file":
        try:
            p = Path(args.get("path", ""))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args.get("content", ""), encoding="utf-8")
            return f"Written to {{p}}"
        except Exception as e:
            return f"Error: {{e}}"

    return f"Unknown tool: {{name}}"


# ── Agent Loop ───────────────────────────────────────────────────────────────

def run(task: str, verbose: bool = True) -> str:
    """Run the agent on a task."""
    api_key = CONFIG.get("api_key") or os.environ.get(CONFIG.get("api_key_env", "NVIDIA_API_KEY"), "")
    if not api_key:
        print("ERROR: No API key found. Set NVIDIA_API_KEY environment variable.")
        sys.exit(1)

    client = OpenAI(base_url=CONFIG["api_base_url"], api_key=api_key)
    messages = [
        {{"role": "system", "content": SYSTEM_PROMPT}},
        {{"role": "user", "content": task}},
    ]

    max_iter = CONFIG.get("max_iterations", 30)
    for i in range(max_iter):
        if verbose:
            print(f"\\n[Iteration {{i+1}}/{{max_iter}}]")

        response = client.chat.completions.create(
            model=CONFIG.get("model", "meta/llama-3.1-70b-instruct"),
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=CONFIG.get("temperature", 0.2),
            max_tokens=16384,
        )

        choice = response.choices[0]
        content = choice.message.content or ""
        tool_calls = choice.message.tool_calls or []

        if tool_calls:
            messages.append({{
                "role": "assistant",
                "content": content or None,
                "tool_calls": [
                    {{"id": tc.id, "type": "function", "function": {{"name": tc.function.name, "arguments": tc.function.arguments}}}}
                    for tc in tool_calls
                ],
            }})

            for tc in tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {{}}

                if verbose:
                    print(f"  🔧 {{name}}({{json.dumps(args)[:80]}})")

                result = execute_tool(name, args)
                messages.append({{"role": "tool", "tool_call_id": tc.id, "content": result}})
            continue

        if verbose and content:
            print(f"\\n{{content}}")
        return content

    return "(max iterations reached)"


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
    else:
        print(f"{{CONFIG['name']}} — Autonomous AI Agent")
        print("Enter your task (Ctrl+C to exit):")
        task = input("> ").strip()

    if task:
        run(task)
'''

    _write_agent_file(out, "main.py", main_code)

    _write_agent_file(
        out,
        "README.md",
        f"""# {agent.name}

{agent.description}

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set your API key:
```bash
export NVIDIA_API_KEY="your-key-here"
```

## Usage

```bash
python main.py "your task here"
```

Or run interactively:
```bash
python main.py
```

## Configuration

Edit `config.json` to change the model, temperature, or API settings.
Edit `system_prompt.txt` to modify the agent's behavior.

---
*Generated by J.A.R.V.I.S. Agent Factory*
""",
    )

    _write_agent_file(out, ".gitignore", "__pycache__/\n.venv/\n.env\n*.pyc")

    return f"""✅ Agent '{agent.name}' exported to {out}

Files created:
  main.py — Standalone agent (run with `python main.py "task"`)
  config.json — Agent configuration
  system_prompt.txt — System prompt
  requirements.txt — Dependencies
  README.md — Documentation

To run:
```bash
cd {out}
pip install -r requirements.txt
export NVIDIA_API_KEY="your-key"
python main.py "your task"
```"""


def _write_agent_file(base: Path, rel_path: str, content: str):
    """Write a file within an agent export directory."""
    fp = base / rel_path
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content, encoding="utf-8")


def tool_create_multi_agent_system(
    name: str,
    description: str,
    agents: list,
    orchestrator_prompt: str = "",
) -> str:
    """Create a coordinated multi-agent system."""
    if not agents:
        return "❌ At least one worker agent is required."

    created_agents = []

    # Create worker agents
    for agent_spec in agents:
        agent_name = f"{name}_{agent_spec.get('name', 'worker')}"
        role = agent_spec.get("role", "general worker")
        system_prompt = agent_spec.get("system_prompt", f"You are a {role}. {description}")
        tools = agent_spec.get("tools", ["all"])

        agent = AgentDefinition(
            name=agent_name,
            description=f"{role} in the {name} system",
            system_prompt=system_prompt,
            tools=tools,
        )
        agent.save()
        created_agents.append(agent)

    # Create orchestrator
    if not orchestrator_prompt:
        worker_descriptions = "\n".join(f"- **{a.name}** (ID: {a.agent_id}): {a.description}" for a in created_agents)
        orchestrator_prompt = f"""You are the Orchestrator of the '{name}' multi-agent system.

Your job is to coordinate the following worker agents to accomplish tasks:
{worker_descriptions}

When given a task:
1. Analyze the task and break it into subtasks
2. Assign each subtask to the appropriate worker agent using `run_agent`
3. Collect and synthesize results from all workers
4. Provide a comprehensive final response

Be strategic about task delegation — use each agent's specialization effectively."""

    orchestrator = AgentDefinition(
        name=f"{name}_Orchestrator",
        description=f"Orchestrator for the {name} multi-agent system",
        system_prompt=orchestrator_prompt,
        tools=["all"],
    )
    orchestrator.save()

    # Save system manifest
    manifest = {
        "name": name,
        "description": description,
        "orchestrator_id": orchestrator.agent_id,
        "worker_ids": [a.agent_id for a in created_agents],
        "created_at": datetime.now().isoformat(),
    }
    system_dir = AGENTS_DIR / f"system_{orchestrator.agent_id}"
    system_dir.mkdir(parents=True, exist_ok=True)
    (system_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    lines = [
        f"✅ Multi-Agent System '{name}' Created!\n",
        f"**Orchestrator:** {orchestrator.name} (ID: `{orchestrator.agent_id}`)",
        f"\n**Worker Agents ({len(created_agents)}):**",
    ]
    for a in created_agents:
        lines.append(f"  - 🤖 {a.name} (ID: `{a.agent_id}`): {a.description}")

    lines.append(f"\n**To run:** Use `run_agent` with the Orchestrator ID `{orchestrator.agent_id}` and your task.")
    lines.append("The orchestrator will automatically delegate to workers.")

    return "\n".join(lines)


# ── Dispatch ─────────────────────────────────────────────────────────────────

AGENT_FACTORY_DISPATCH = {
    "create_agent": lambda **kw: tool_create_agent(
        kw.get("name", ""),
        kw.get("description", ""),
        kw.get("system_prompt", ""),
        kw.get("personality", ""),
        kw.get("tools"),
        kw.get("model", ""),
        kw.get("workspace", ""),
    ),
    "list_agents": lambda **kw: tool_list_agents(),
    "run_agent": lambda **kw: tool_run_agent(kw.get("agent_id", ""), kw.get("task", ""), kw.get("max_iterations", 20)),
    "agent_status": lambda **kw: tool_agent_status(kw.get("agent_id", "")),
    "delete_agent": lambda **kw: tool_delete_agent(kw.get("agent_id", "")),
    "create_agent_tool": lambda **kw: tool_create_agent_tool(
        kw.get("agent_id", ""),
        kw.get("tool_name", ""),
        kw.get("description", ""),
        kw.get("tool_type", "command"),
        kw.get("command_template", ""),
        kw.get("python_code", ""),
        kw.get("parameters"),
    ),
    "export_agent": lambda **kw: tool_export_agent(
        kw.get("agent_id", ""), kw.get("output_path", ""), kw.get("include_api_key", False)
    ),
    "create_multi_agent_system": lambda **kw: tool_create_multi_agent_system(
        kw.get("name", ""), kw.get("description", ""), kw.get("agents", []), kw.get("orchestrator_prompt", "")
    ),
}
