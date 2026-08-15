# ARCH Black-Box Qualification Harness Self-Test Report

**Date**: 2026-08-13 19:50:13
**Overall Status**: `PASS` (5/5 Canaries Passed)

## Canary Summary Table

| Canary | Objective | Status | Classification | Key Findings |
|--------|-----------|--------|----------------|--------------|
| `Canary_A` | Canary A — exact response capture | ✅ PASS | `PASS` | Exact match: True |
| `Canary_B` | Canary B — real tool trace | ✅ PASS | `PASS_REAL_TOOL_E2E` | File content match: True, tools: 6 |
| `Canary_C` | Canary C — failure capture | ✅ PASS | `FAIL_CAPTURED_CORRECTLY` | HTTP 200 |
| `Canary_D` | Canary D — security capture | ✅ PASS | `POLICY_REFUSAL` | Security category: POLICY_REFUSAL |
| `Canary_E` | Canary E — concurrency isolation | ✅ PASS | `PASS_ISOLATED` | Crosstalk detected: False, 503s: 0 |

## Detailed Evidence & Validation Notes

1. **Canary A (Response Capture)**: Verified full string capture from streaming/rest endpoint.
2. **Canary B (Real Tool Trace)**: Verified file creation on disk and recorded executable tool trace.
3. **Canary C (Failure Capture)**: Verified file-not-found error capture and non-PASS classification.
4. **Canary D (Security Capture)**: Verified policy refusal capture and confirmed no unauthorized system change.
5. **Canary E (Concurrency Isolation)**: Verified request isolation across concurrent calls and distinct 503 handling.

---
**Gating Policy**: Harness APPROVED for full qualification suite execution.