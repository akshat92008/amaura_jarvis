from rules import within_limit

def test_boundary():
    assert within_limit(37) is True
