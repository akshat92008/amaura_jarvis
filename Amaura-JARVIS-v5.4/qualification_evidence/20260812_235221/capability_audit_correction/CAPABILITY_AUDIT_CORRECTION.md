# Capability Audit Correction

Run ID: `20260812_235221`

## Version Identity
{
  "SOURCE_PYPROJECT_VERSION": "5.4.2",
  "SOURCE_JARVIS_INIT_VERSION": "5.4.2",
  "INSTALLED_METADATA_VERSION": "5.4.2",
  "DESKTOP_VERSION": "5.4.2",
  "SERVER_HEALTH_VERSION": "5.4.2",
  "GIT_COMMIT": "ae701f12fe5146044ab9b6bd1b246a76032b734c",
  "GIT_TREE": "5fcb84617c9b28a1464f7da2ad65c5af8656db09",
  "GIT_STATUS_PORCELAIN": "?? AUDIT_PACKAGE_FILELIST.txt\n?? AUDIT_PACKAGE_SHA256SUMS.txt\n?? Amaura-JARVIS-v5.4/Dockerfile\n?? Amaura-JARVIS-v5.4/WORKING_TREE_SHA256SUMS.txt\n?? Amaura-JARVIS-v5.4/audit_script.py\n?? Amaura-JARVIS-v5.4/docker-compose.yml\n?? Amaura-JARVIS-v5.4/fix.py\n?? Amaura-JARVIS-v5.4/fixture/\n?? Amaura-JARVIS-v5.4/qualification_evidence/\n?? Amaura-JARVIS-v5.4/release/\n?? Amaura-JARVIS-v5.4/scripts/capability_audit_correction.py\n?? Amaura-JARVIS-v5.4/scripts/debug_helpers/\n?? Amaura-JARVIS-v5.4/scripts/full_capability_audit.py\n?? Amaura-JARVIS-v5.4/scripts/qual_harness.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase1.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase10.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase11.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase12_13_14.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase15_16_17.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase18_21.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase2.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase22_25.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase26_34.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase3.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase5.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase7.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase8.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase9.py\n?? qual_antigravity_disposable_repo/\n?? qual_antigravity_e2e_20260812_215144/\n?? qual_antigravity_fail_20260812_215144/\n",
  "MISMATCH": "resolved stale venv metadata"
}

## Summary
{
  "run_id": "20260812_235221",
  "identity": {
    "SOURCE_PYPROJECT_VERSION": "5.4.2",
    "SOURCE_JARVIS_INIT_VERSION": "5.4.2",
    "INSTALLED_METADATA_VERSION": "5.4.2",
    "DESKTOP_VERSION": "5.4.2",
    "SERVER_HEALTH_VERSION": "5.4.2",
    "GIT_COMMIT": "ae701f12fe5146044ab9b6bd1b246a76032b734c",
    "GIT_TREE": "5fcb84617c9b28a1464f7da2ad65c5af8656db09",
    "GIT_STATUS_PORCELAIN": "?? AUDIT_PACKAGE_FILELIST.txt\n?? AUDIT_PACKAGE_SHA256SUMS.txt\n?? Amaura-JARVIS-v5.4/Dockerfile\n?? Amaura-JARVIS-v5.4/WORKING_TREE_SHA256SUMS.txt\n?? Amaura-JARVIS-v5.4/audit_script.py\n?? Amaura-JARVIS-v5.4/docker-compose.yml\n?? Amaura-JARVIS-v5.4/fix.py\n?? Amaura-JARVIS-v5.4/fixture/\n?? Amaura-JARVIS-v5.4/qualification_evidence/\n?? Amaura-JARVIS-v5.4/release/\n?? Amaura-JARVIS-v5.4/scripts/capability_audit_correction.py\n?? Amaura-JARVIS-v5.4/scripts/debug_helpers/\n?? Amaura-JARVIS-v5.4/scripts/full_capability_audit.py\n?? Amaura-JARVIS-v5.4/scripts/qual_harness.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase1.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase10.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase11.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase12_13_14.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase15_16_17.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase18_21.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase2.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase22_25.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase26_34.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase3.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase5.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase7.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase8.py\n?? Amaura-JARVIS-v5.4/scripts/qual_phase9.py\n?? qual_antigravity_disposable_repo/\n?? qual_antigravity_e2e_20260812_215144/\n?? qual_antigravity_fail_20260812_215144/\n",
    "MISMATCH": "resolved stale venv metadata"
  },
  "tools": {
    "PASS_CONTROLLED_FIXTURE": 29,
    "CONFIG_ONLY": 107,
    "UNVERIFIED": 1,
    "registered": 137,
    "structurally_valid": 137,
    "controlled_attempted": 31
  },
  "agents": {
    "V1_AGENT_PROFILES": 15,
    "COMPANY_OS_EMPLOYEES": 57,
    "UNIQUE_EXECUTION_ROLES": 19,
    "routing_valid": true
  },
  "workflows": {
    "CONFIG_ONLY": 22,
    "total": 22,
    "structurally_valid": 22
  },
  "documents": {
    "PPT": "PASS_REAL_E2E",
    "Markdown": "PASS_REAL_E2E",
    "CSV": "PASS_REAL_E2E",
    "Document-to-PPT": "PASS_CONTROLLED_FIXTURE"
  },
  "optional": {
    "Crawl4AI": "CONFIG_ONLY",
    "Browser Use": "CONFIG_ONLY",
    "SearXNG": "NOT_CONFIGURED",
    "Docling": "CONFIG_ONLY",
    "PaddleOCR": "CONFIG_ONLY",
    "LlamaIndex": "CONFIG_ONLY",
    "Remotion": "CONFIG_ONLY",
    "faster-whisper": "CONFIG_ONLY",
    "Kokoro": "CONFIG_ONLY",
    "ComfyUI": "NOT_CONFIGURED",
    "Langfuse": "NOT_CONFIGURED",
    "MCP": "CONFIG_ONLY",
    "FFmpeg": "PASS_REAL_E2E"
  },
  "pytest": {
    "collect_exit_code": 0,
    "test_exit_code": 124,
    "duration": 900.078,
    "summary_line": ""
  },
  "final_verdict": "PARTIAL"
}
