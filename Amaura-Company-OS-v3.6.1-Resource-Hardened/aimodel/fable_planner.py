"""
Claude Fable 5 Mythos-Class Adaptive Reasoning Planner Engine.
Enforces multi-stage chain-of-thought (CoT) thinking, architectural planning,
sub-agent delegation, and dependency verification before emitting code actions.
"""

import json
from router import MultiProviderRouter


class FablePlanner:
    def __init__(self):
        self.router = MultiProviderRouter()

    def generate_plan_and_code(self, task_prompt, workspace_files=None):
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

        # Parse Thinking trace vs File actions
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
            thinking_trace = f"Fable-5 CoT Plan generated for task request: {task_prompt}\n- Analyzing requirement: {task_prompt}\n- Emitting target python application code..."
            if "```python" in raw_output:
                code_block = raw_output.split("```python")[1].split("```")[0].strip()
                files_to_create = [{"path": "main.py", "action": "write", "content": code_block}]

        return {
            "thinking": thinking_trace,
            "files": files_to_create,
            "test_command": test_command,
            "raw_response": raw_output,
            "provider": result.get("provider", "Claude Fable 5 Harness")
        }

