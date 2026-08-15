from logic import ready_78252233

def test_contract():
    assert ready_78252233(True, True) is True
    assert ready_78252233(True, False) is False
    assert ready_78252233(False, True) is False
