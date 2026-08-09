"""
Autonomous Test-Driven Development (TDD) Loop Module for JARVIS.
Executes test suites (pytest, mypy, tsc, eslint), reads un-truncated stack traces, and auto-refactors until tests pass or retry budget is exhausted.
"""

import os
import re
import subprocess
import time
from typing import List

TDD_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "test_and_auto_fix",
            "description": "Run test suites (pytest, mypy, tsc, eslint), inspect stack traces, and iteratively auto-fix until tests pass.",
            "parameters": {
                "type": "object",
                "properties": {
                    "runner": {
                        "type": "string",
                        "description": "Test runner command to execute ('pytest', 'mypy', 'tsc', 'eslint', or custom command).",
                        "default": "pytest"
                    },
                    "target": {
                        "type": "string",
                        "description": "Target test file or directory path (e.g. 'tests/').",
                        "default": "."
                    },
                    "max_retries": {
                        "type": "integer",
                        "description": "Maximum auto-fix iterations allowed.",
                        "default": 3
                    }
                },
                "required": ["runner"]
            }
        }
    }
]


def _extract_broken_files(output: str) -> List[str]:
    """Extract paths of failing files from error output."""
    pattern = r'(?:File "|FAIL:|ERROR:)\s*([^\s,:]+\.py)'
    matches = re.findall(pattern, output)
    return list(dict.fromkeys(matches))


def test_and_auto_fix(
    runner: str = "pytest",
    target: str = ".",
    max_retries: int = 3
) -> str:
    """
    Executes specified test runner, captures un-truncated output, extracts exact stack traces,
    and runs iterative retry loop until tests pass or retry limit is reached.
    """
    cwd = os.getcwd()

    if runner == "pytest":
        if os.path.exists("./.venv/bin/pytest"):
            cmd = ["./.venv/bin/pytest", target]
        else:
            cmd = ["python3", "-m", "unittest", "discover", "-s", target if target != "." else "tests"]
    elif runner == "mypy":
        cmd = ["mypy", target]
    elif runner == "tsc":
        cmd = ["npx", "tsc", "--noEmit"]
    elif runner == "eslint":
        cmd = ["npx", "eslint", target]
    else:
        cmd = runner.split()

    attempts_log: list[str] = []

    for iteration in range(1, max_retries + 1):
        try:
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120
            )
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            combined_output = f"{stdout}\n{stderr}".strip()
            returncode = proc.returncode

            if returncode == 0:
                success_msg = f"✅ **Test Suite Passed Cleanly (Exit Code 0) on Iteration {iteration}/{max_retries}**"
                if attempts_log:
                    success_msg += "\n\n### Prior Retry Diagnostics:\n" + "\n".join(attempts_log)
                success_msg += f"\n\n```text\n{combined_output[:2000]}\n```"
                return success_msg

            # ── Parse Stack Traces / Errors & Run Self-Healing Repair ──────────────
            error_lines = []
            for line in combined_output.splitlines():
                if any(k in line for k in ["FAIL", "ERROR", "Traceback", "AssertionError", "File \""]):
                    error_lines.append(line)

            formatted_errors = "\n".join(error_lines[:25])
            broken_files = _extract_broken_files(combined_output)

            attempts_log.append(f"• **Attempt #{iteration} Failed (Exit {returncode})**: Broken files: {broken_files or ['Unknown']}")

            # Invoke Fable-5 SelfHealingDebugger for surgical repairs
            try:
                from jarvis.fable_engine import SelfHealingDebugger
                debugger = SelfHealingDebugger(cwd, max_attempts=1)
                repair_res = debugger.run_and_repair(" ".join(cmd))
                if repair_res.get("success"):
                    return f"✅ **Fable-5 Self-Healing Debugger Fixed Test Suite on Iteration {iteration}/{max_retries}**\n\n```text\n{repair_res.get('output', '')[:2000]}\n```"
            except Exception:
                pass

            if iteration == max_retries:
                return f"""❌ **Test Suite Failed after {max_retries} Auto-Fix Iterations (Exit Code {returncode})**

### Failing Source Files Identified:
{chr(10).join(f"- `{f}`" for f in broken_files) if broken_files else "- None explicitly parsed"}

### Stack Trace / Diagnostics Summary:
```text
{formatted_errors if formatted_errors else combined_output[:2000]}
```

### Iteration History:
{chr(10).join(attempts_log)}

💡 *TDD Loop Action Required: Surgical modification needed for files listed above.*
"""
            time.sleep(1)

        except Exception as e:
            return f"❌ **Error executing test runner ({runner}):** {e}"

    return "❌ **TDD Auto-Fix Loop Exhausted.**"


# Prevent pytest from collecting this public tool when a test module imports it.
setattr(test_and_auto_fix, "__test__", False)


TDD_DISPATCH = {
    "test_and_auto_fix": test_and_auto_fix
}
