from pathlib import Path
from scripts.qual_bb_master import run_bb_test

phase_dir = Path("evidence/test_run")
phase_dir.mkdir(parents=True, exist_ok=True)
r = run_bb_test("test_01", "Create a file at /tmp/test_master.txt with content OK", phase_dir, timeout=30)
print("Final classification:", r.classification)
print("Goal ID:", getattr(r, "goal_id", None))
print("Goal State:", getattr(r, "goal_state", None))
print("Tool calls:", getattr(r, "tool_calls", []))
