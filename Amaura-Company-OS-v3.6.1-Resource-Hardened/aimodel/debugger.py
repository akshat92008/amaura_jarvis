"""
Autonomous Self-Healing Verification & Debugger Engine.
Executes test suites, captures stack traces, feeds error tracebacks back to the router,
and applies surgical auto-repairs until 100% of assertions pass.
"""

import re
from executor import WorkspaceExecutor
from fable_planner import FablePlanner


class SelfHealingDebugger:
    def __init__(self, workspace_dir=None, max_attempts=5):
        self.executor = WorkspaceExecutor(workspace_dir)
        self.planner = FablePlanner()
        self.max_attempts = max_attempts

    def extract_error_summary(self, stderr, stdout):
        full_log = f"{stdout}\n{stderr}"
        lines = full_log.strip().split("\n")
        # Extract last 15 relevant lines of traceback
        relevant_lines = [l for l in lines if any(k in l.lower() for k in ["error", "exception", "failed", "assert", "traceback"])]
        if not relevant_lines:
            relevant_lines = lines[-15:]
        return "\n".join(relevant_lines)

    def run_and_repair(self, test_command="pytest"):
        for attempt in range(1, self.max_attempts + 1):
            print(f"[Self-Healer] Execution Verification Attempt {attempt}/{self.max_attempts}: running '{test_command}'...")
            res = self.executor.run_command(test_command)

            if res["success"]:
                print(f"[Self-Healer] Verification SUCCESS on attempt {attempt}!")
                return {
                    "success": True,
                    "attempts": attempt,
                    "output": res["stdout"]
                }

            error_log = self.extract_error_summary(res["stderr"], res["stdout"])
            print(f"[Self-Healer] Build/Test Failure Detected:\n{error_log[:300]}...\n")

            if attempt == self.max_attempts:
                break

            # Formulate self-repair prompt for reasoning model
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

            # Apply repair patches
            for file_item in repair_plan.get("files", []):
                path = file_item.get("path")
                content = file_item.get("content")
                if path and content:
                    print(f"[Self-Healer] Applying surgical repair patch to {path}...")
                    self.executor.write_file(path, content)

        return {
            "success": False,
            "attempts": self.max_attempts,
            "error_log": error_log
        }
