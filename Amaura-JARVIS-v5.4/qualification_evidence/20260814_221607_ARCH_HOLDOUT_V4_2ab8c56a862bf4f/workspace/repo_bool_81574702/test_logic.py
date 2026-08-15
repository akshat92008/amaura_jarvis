from logic import eligible_18349091

def test_contract():
    assert eligible_18349091(True, True) is True
    assert eligible_18349091(True, False) is False
    assert eligible_18349091(False, True) is False
