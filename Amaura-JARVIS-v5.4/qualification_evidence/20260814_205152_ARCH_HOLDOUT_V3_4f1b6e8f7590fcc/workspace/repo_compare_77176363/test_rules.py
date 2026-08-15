from rules import is_adult_89505517

def test_boundary():
    assert is_adult_89505517(18) is True
    assert is_adult_89505517(17) is False
