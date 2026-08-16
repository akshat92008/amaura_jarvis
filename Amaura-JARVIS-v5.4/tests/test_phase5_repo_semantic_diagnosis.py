"""Phase 5 Tests: Repository AST Semantic Diagnosis and Read-Only Cache Isolation (Phases 9, 10, 11)."""

import tempfile
from pathlib import Path

from jarvis.amaura.direct_action import DirectActionRouter, RepositoryDiagnosticEngine


def test_repo_diagnosis_wrong_returned_variable():
    """Diagnose function that computes both area and perimeter but returns perimeter."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        src = repo / "geometry.py"
        src.write_text("""
def calculate_rectangle_area(width: int, height: int) -> int:
    '''Calculate the area of a rectangle.'''
    perimeter = 2 * (width + height)
    area = width * height
    return perimeter
""")
        test_file = repo / "test_geometry.py"
        test_file.write_text("""
from geometry import calculate_rectangle_area

def test_rectangle_area():
    assert calculate_rectangle_area(5, 4) == 20
""")
        diag = RepositoryDiagnosticEngine.diagnose(repo)
        assert diag["read_only_verified"] is True
        assert len(diag["findings"]) >= 1
        finding = diag["findings"][0]
        assert "calculate_rectangle_area" in finding["function"]
        assert "perimeter" in finding["description"]
        assert "area" in finding["description"] or "wrong" in finding["category"]

        # Router test
        res = DirectActionRouter.execute(f"Inspect the repository at {repo} and find the bug", workspace=str(repo))
        assert res is not None
        assert res.success is True
        assert "calculate_rectangle_area" in res.output
        assert "perimeter" in res.output

        # Verify no cache pollution
        pycache_dirs = list(repo.rglob("__pycache__"))
        pytest_cache = list(repo.rglob(".pytest_cache"))
        pyc_files = list(repo.rglob("*.pyc"))
        assert len(pycache_dirs) == 0, f"Found cache dirs: {pycache_dirs}"
        assert len(pytest_cache) == 0, f"Found pytest cache: {pytest_cache}"
        assert len(pyc_files) == 0, f"Found pyc files: {pyc_files}"


def test_repo_diagnosis_wrong_boolean_operator():
    """Diagnose function with boolean operator defect ('or' vs 'and')."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        src = repo / "validator.py"
        src.write_text("""
def is_valid_transaction(has_funds: bool, is_verified: bool) -> bool:
    '''Both conditions must be true for valid transaction.'''
    return has_funds or is_verified
""")
        test_file = repo / "test_validator.py"
        test_file.write_text("""
from validator import is_valid_transaction

def test_validation():
    assert is_valid_transaction(True, False) == False
""")
        diag = RepositoryDiagnosticEngine.diagnose(repo)
        assert diag["read_only_verified"] is True
        assert len(diag["findings"]) >= 1
        finding = diag["findings"][0]
        assert "is_valid_transaction" in finding["function"]
        assert "or" in finding["description"].lower() or "boolean" in finding["category"]


def test_repo_diagnosis_wrong_operator_arithmetic():
    """Diagnose function that subtracts instead of adding."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        src = repo / "calculator.py"
        src.write_text("""
def add_numbers(a: int, b: int) -> int:
    '''Add two numbers together.'''
    return a - b
""")
        test_file = repo / "test_calculator.py"
        test_file.write_text("""
from calculator import add_numbers

def test_addition():
    assert add_numbers(10, 5) == 15
""")
        diag = RepositoryDiagnosticEngine.diagnose(repo)
        assert diag["read_only_verified"] is True
        assert len(diag["findings"]) >= 1
        finding = diag["findings"][0]
        assert "add_numbers" in finding["function"]
        assert "subtract" in finding["description"].lower() or "operator" in finding["category"]


def test_repo_diagnosis_comparison_inversion():
    """Diagnose function with comparison inversion (> instead of <)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        src = repo / "comparator.py"
        src.write_text("""
def is_less_than_threshold(val: int, threshold: int = 100) -> bool:
    '''Check if value is less than threshold.'''
    return val > threshold
""")
        test_file = repo / "test_comparator.py"
        test_file.write_text("""
from comparator import is_less_than_threshold

def test_threshold():
    assert is_less_than_threshold(50, 100) == True
""")
        diag = RepositoryDiagnosticEngine.diagnose(repo)
        assert diag["read_only_verified"] is True
        assert len(diag["findings"]) >= 1
        finding = diag["findings"][0]
        assert "is_less_than_threshold" in finding["function"]
        assert ">" in finding["description"] or "comparison" in finding["category"]


def test_repo_diagnosis_indexing_error():
    """Diagnose function with indexing error (index 1 instead of index 0)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        src = repo / "sequences.py"
        src.write_text("""
def get_first_element(items: list) -> any:
    '''Get the first element of the list.'''
    return items[1]
""")
        test_file = repo / "test_sequences.py"
        test_file.write_text("""
from sequences import get_first_element

def test_first():
    assert get_first_element([100, 200, 300]) == 100
""")
        diag = RepositoryDiagnosticEngine.diagnose(repo)
        assert diag["read_only_verified"] is True
        assert len(diag["findings"]) >= 1
        finding = diag["findings"][0]
        assert "get_first_element" in finding["function"]
        assert "index" in finding["description"].lower() or "index" in finding["category"]
