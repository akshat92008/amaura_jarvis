"""Phase 7 Test Suite 6: Repository Semantic Diagnosis (500+ Generated Repositories)."""

import random
import string
import tempfile
from pathlib import Path
import pytest
from jarvis.amaura.direct_action import RepositoryDiagnosticEngine


def _rand_id(prefix: str = "fn", length: int = 6) -> str:
    return f"{prefix}_{''.join(random.choices(string.ascii_lowercase, k=length))}"


def generate_wrong_helper_repos(count: int = 100):
    """Generate 100 repositories with wrong helper call defect."""
    repos = []
    for i in range(count):
        h1 = _rand_id("helper_sub")
        h2 = _rand_id("helper_add")
        caller = _rand_id("compute_total")
        test_fn = f"test_{caller}"

        code = f"""def {h1}(a, b):
    \"\"\"Compute difference of values.\"\"\"
    return a - b

def {h2}(a, b):
    \"\"\"Compute sum of values.\"\"\"
    return a + b

def {caller}(a, b):
    \"\"\"Compute total sum of numbers.\"\"\"
    return {h1}(a, b)
"""
        test = f"""from module_{i} import {caller}

def {test_fn}():
    assert {caller}(10, 20) == 30
"""
        repos.append((f"module_{i}.py", code, f"test_module_{i}.py", test, "wrong_helper_call", caller, h1, h2))
    return repos


def generate_comparison_boundary_repos(count: int = 100):
    """Generate 100 repositories with comparison boundary defect."""
    repos = []
    for i in range(count):
        fn_name = _rand_id("is_eligible")
        threshold = random.randint(18, 65)
        test_fn = f"test_{fn_name}"

        code = f"""def {fn_name}(val: int) -> bool:
    \"\"\"Return True if val is at least {threshold}.\"\"\"
    return val > {threshold}
"""
        test = f"""from module_{i} import {fn_name}

def {test_fn}():
    assert {fn_name}({threshold}) is True
"""
        repos.append((f"module_{i}.py", code, f"test_module_{i}.py", test, "comparison_boundary", fn_name, ">", ">="))
    return repos


def generate_wrong_constant_repos(count: int = 100):
    """Generate 100 repositories with wrong constant defect."""
    repos = []
    for i in range(count):
        fn_name = _rand_id("calculate_rate")
        expected_const = 0.25
        observed_const = 0.15
        test_fn = f"test_{fn_name}"

        code = f"""def {fn_name}(amount: float) -> float:
    \"\"\"Apply 0.25 tax rate to amount.\"\"\"
    return amount * {observed_const}
"""
        test = f"""from module_{i} import {fn_name}

def {test_fn}():
    assert {fn_name}(100.0) == 25.0
"""
        repos.append((f"module_{i}.py", code, f"test_module_{i}.py", test, "wrong_constant", fn_name, observed_const, expected_const))
    return repos


def generate_wrong_return_var_repos(count: int = 100):
    """Generate 100 repositories with wrong returned variable defect."""
    repos = []
    for i in range(count):
        fn_name = _rand_id("process_total")
        test_fn = f"test_{fn_name}"

        code = f"""def {fn_name}(x: int, y: int) -> int:
    \"\"\"Compute and return total.\"\"\"
    temp_val = x * 2
    total_val = temp_val + y
    return temp_val
"""
        test = f"""from module_{i} import {fn_name}

def {test_fn}():
    assert {fn_name}(5, 10) == 20
"""
        repos.append((f"module_{i}.py", code, f"test_module_{i}.py", test, "wrong_returned_variable", fn_name, "temp_val", "total_val"))
    return repos


def generate_boolean_op_repos(count: int = 100):
    """Generate 100 repositories with boolean operator mismatch."""
    repos = []
    for i in range(count):
        fn_name = _rand_id("check_valid")
        test_fn = f"test_{fn_name}"

        code = f"""def {fn_name}(has_auth: bool, is_admin: bool) -> bool:
    \"\"\"Return True if both has_auth and is_admin are true.\"\"\"
    return has_auth or is_admin
"""
        test = f"""from module_{i} import {fn_name}

def {test_fn}():
    assert {fn_name}(True, False) is False
"""
        repos.append((f"module_{i}.py", code, f"test_module_{i}.py", test, "boolean_operator_mismatch", fn_name, "or", "and"))
    return repos


def test_repo_semantic_diagnosis_500_cases():
    """Verify >= 500 generated repositories diagnose exact root cause across 5 defect classes."""
    helper_cases = generate_wrong_helper_repos(100)
    boundary_cases = generate_comparison_boundary_repos(100)
    constant_cases = generate_wrong_constant_repos(100)
    return_var_cases = generate_wrong_return_var_repos(100)
    boolean_cases = generate_boolean_op_repos(100)

    all_cases = helper_cases + boundary_cases + constant_cases + return_var_cases + boolean_cases
    assert len(all_cases) >= 500

    diagnosed_count = 0

    for py_name, code, test_name, test_code, expected_category, fn_under_test, val1, val2 in all_cases:
        with tempfile.TemporaryDirectory(prefix="diag_repo_") as td:
            repo_p = Path(td)
            (repo_p / py_name).write_text(code)
            (repo_p / test_name).write_text(test_code)

            res = RepositoryDiagnosticEngine.diagnose(repo_p)
            assert res["read_only_verified"] is True, "Read-only isolation violated"
            findings = res["findings"]
            assert len(findings) > 0, f"No findings for {expected_category} in {py_name}"

            top = findings[0]
            assert top["category"] == expected_category, f"Category mismatch: got {top['category']} vs {expected_category}"
            assert top["function"] == fn_under_test, f"Function mismatch: got {top['function']} vs {fn_under_test}"

            # Check specific fields
            if expected_category == "wrong_helper_call":
                assert top["called_helper"] == val1
                assert top["expected_helper"] == val2
            elif expected_category == "comparison_boundary":
                assert top["observed_operator"] == val1
                assert top["expected_operator"] == val2
            elif expected_category == "wrong_constant":
                assert top["observed_constant"] == val1
                assert top["expected_constant"] == val2
            elif expected_category == "wrong_returned_variable":
                assert top["returned_variable"] == val1
                assert top["expected_variable"] == val2
            elif expected_category == "boolean_operator_mismatch":
                assert top["observed_operator"] == val1
                assert top["expected_operator"] == val2

            diagnosed_count += 1

    assert diagnosed_count >= 500
