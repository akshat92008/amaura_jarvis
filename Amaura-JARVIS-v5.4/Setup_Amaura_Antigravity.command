#!/bin/zsh
set -euo pipefail
cd "${0:A:h}"

AGY_BIN="${AMAURA_ANTIGRAVITY_COMMAND:-agy}"
if ! command -v "${AGY_BIN%% *}" >/dev/null 2>&1; then
  print -u2 "Antigravity CLI (agy) is not installed."
  print -u2 "Official macOS/Linux install command:"
  print -u2 "  curl -fsSL https://antigravity.google/cli/install.sh | bash"
  print -u2 "Then run 'agy' once to sign in, and rerun this setup command."
  exit 1
fi

print "Antigravity CLI: $($AGY_BIN --version 2>/dev/null || true)"
SETTINGS="${AMAURA_ANTIGRAVITY_SETTINGS:-$HOME/.gemini/antigravity-cli/settings.json}"
mkdir -p "${SETTINGS:h}"
if [[ -f "$SETTINGS" ]]; then
  cp "$SETTINGS" "$SETTINGS.amaura-backup-$(date +%Y%m%d-%H%M%S)"
fi
python3 - "$SETTINGS" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1]).expanduser()
data = {}
if p.exists():
    try:
        loaded = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    except Exception as exc:
        raise SystemExit(f"Refusing to overwrite malformed Antigravity settings: {exc}")
# Safe unattended policy: allow workspace edits/review, auto-run terminal work only
# while Antigravity's sandbox is enforced, and deny non-workspace file access.
data["toolPermission"] = "proceed-in-sandbox"
data["artifactReviewPolicy"] = "always-proceed"
data["allowNonWorkspaceAccess"] = False
data["enableTerminalSandbox"] = True
permissions = data.get("permissions")
if isinstance(permissions, dict):
    allow = permissions.get("allow")
    if isinstance(allow, list):
        broad = {"write_file(*)", "read_file(*)", "read_url(*)", "execute_url(*)", "mcp(*)"}
        def unsafe_rule(value):
            rule = str(value).strip().lower()
            return rule.startswith("unsandboxed(") or rule in broad
        removed = [str(v) for v in allow if unsafe_rule(v)]
        permissions["allow"] = [v for v in allow if not unsafe_rule(v)]
        if removed:
            print("Removed unsafe global Antigravity allow rules: " + ", ".join(removed))
p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
p.chmod(0o600)
print(f"Updated {p}")
PY

print "\nAmaura-safe Antigravity settings applied."
print -- "- terminal sandbox: enabled"
print -- "- non-workspace file access: denied"
print -- "- workspace artifacts: auto-approved"
print -- "- terminal commands: auto-proceed only in sandbox"
print "\nIf Antigravity is not authenticated yet, run: agy"

# Ask Amaura's own adapter to validate the effective automation posture, including
# current project-scoped permission files and global executable customizations.
PYTHON_BIN="python3"
[[ -x ".venv/bin/python" ]] && PYTHON_BIN=".venv/bin/python"
print "\nRunning Amaura Antigravity readiness preflight…"
PYTHONPATH="$PWD" "$PYTHON_BIN" - <<'PY'
import json
from jarvis.amaura.runtime import load_amaura_env
load_amaura_env()
from jarvis.amaura.antigravity_bridge import AntigravityDeliveryAdapter
status = AntigravityDeliveryAdapter().readiness()
print(json.dumps({
    "configured": status.get("configured"),
    "version": status.get("version"),
    "version_compatible": status.get("version_compatible"),
    "project_permissions": status.get("project_permissions"),
    "global_customizations": status.get("global_customizations"),
    "ready": status.get("ready"),
}, indent=2, default=str))
if not status.get("ready"):
    raise SystemExit(
        "Antigravity is not yet safe for unattended JARVIS execution. "
        "Resolve the project/global findings above; do not bypass them unless you have explicitly qualified those customizations."
    )
PY
