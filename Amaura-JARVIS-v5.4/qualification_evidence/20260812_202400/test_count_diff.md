# Test Count Difference Analysis

## Executive Summary

- **Previous Independent Collection**: 454 collected tests
- **Latest Evidence Collection**: 451 collected tests (450 passed, 1 skipped)
- **Net Difference**: Exactly 3 tests

## Root Cause Analysis

The difference of **3 tests** is due to **collection target scope**:

1. **Previous Collection (454 tests)**: Executed by running `pytest` against the workspace directory `Amaura-JARVIS-v5.4/` without specifying the target `tests/` directory.
   - Collected **451 tests** from `Amaura-JARVIS-v5.4/tests/`
   - Collected **3 additional tests** from standalone root test scripts located in `Amaura-JARVIS-v5.4/`:
     - `Amaura-JARVIS-v5.4/test_chat.py` (`test_chat`)
     - `Amaura-JARVIS-v5.4/test_jarvis_run.py` (`test_run`)
     - `Amaura-JARVIS-v5.4/test_macos_apps_script.py` (`test_app_script`)
   - Total: 451 + 3 = **454 tests**

2. **Canonical Suite Collection (451 tests)**: Executed via `PYTHONPATH=. .venv/bin/pytest --collect-only tests/` (or `scripts/run_verified_tests.py`), which explicitly targets the `tests/` directory.
   - Collected strictly the **451 suite tests** inside `Amaura-JARVIS-v5.4/tests/`.
   - Results: **450 passed**, **1 skipped** (`test_amaura_launch_hardening.py::test_posix_permissions_contract` due to OS/permission marker).

## Complete List of Collected Tests (Canonical 451 Suite)

The 451 collected tests across 51 modules in `Amaura-JARVIS-v5.4/tests/` are:

- `tests/test_amaura_assets.py` (2 tests)
- `tests/test_amaura_autopilot.py` (2 tests)
- `tests/test_amaura_commands.py` (1 test)
- `tests/test_amaura_company_api.py` (4 tests)
- `tests/test_amaura_company_system.py` (10 tests)
- `tests/test_amaura_contract.py` (2 tests)
- `tests/test_amaura_distribution.py` (7 tests)
- `tests/test_amaura_e2e.py` (1 test)
- `tests/test_amaura_full_company_autonomy.py` (14 tests)
- `tests/test_amaura_growth.py` (9 tests)
- `tests/test_amaura_jarvis_v4.py` (7 tests)
- `tests/test_amaura_jarvis_v41.py` (14 tests)
- `tests/test_amaura_jarvis_v5.py` (10 tests)
- `tests/test_amaura_jarvis_v51.py` (12 tests)
- `tests/test_amaura_jarvis_v52.py` (13 tests)
- `tests/test_amaura_launch_hardening.py` (14 tests - 1 skipped on non-matching POSIX contract)
- `tests/test_amaura_macos_service.py` (2 tests)
- `tests/test_amaura_mission_control.py` (11 tests)
- `tests/test_amaura_os.py` (13 tests)
- `tests/test_amaura_oss_capabilities.py` (20 tests)
- `tests/test_amaura_p0_fixes.py` (28 tests)
- `tests/test_amaura_p0_remediation.py` (7 tests)
- `tests/test_amaura_production.py` (15 tests)
- `tests/test_amaura_providers.py` (3 tests)
- `tests/test_amaura_release_builder.py` (2 tests)
- `tests/test_amaura_store.py` (1 test)
- `tests/test_amaura_supervisor.py` (9 tests)
- `tests/test_amaura_trust_foundation.py` (7 tests)
- `tests/test_amaura_v350_hardening.py` (14 tests)
- `tests/test_amaura_v351_remediation.py` (15 tests)
- `tests/test_amaura_v352_security.py` (8 tests)
- `tests/test_amaura_v353_security.py` (7 tests)
- `tests/test_amaura_v360_integrations.py` (15 tests)
- `tests/test_amaura_v361_blocker_fixes.py` (8 tests)
- `tests/test_amaura_v361_resource_security.py` (11 tests)
- `tests/test_amaura_ventures.py` (6 tests)
- `tests/test_amaura_ventures_cashflow.py` (28 tests)
- `tests/test_antigravity_contract.py` (29 tests)
- `tests/test_app_builder.py` (1 test)
- `tests/test_ast_indexer.py` (1 test)
- `tests/test_browser.py` (4 tests)
- `tests/test_fable_engine.py` (10 tests)
- `tests/test_fleet.py` (2 tests)
- `tests/test_macos_app_control.py` (5 tests)
- `tests/test_omniroute_integration.py` (27 tests)
- `tests/test_registry.py` (2 tests)
- `tests/test_router.py` (2 tests)
- `tests/test_tdd_loop.py` (1 test)
- `tests/test_vector_memory.py` (6 tests)
- `tests/test_vision.py` (5 tests)
- `tests/test_voice.py` (4 tests)
