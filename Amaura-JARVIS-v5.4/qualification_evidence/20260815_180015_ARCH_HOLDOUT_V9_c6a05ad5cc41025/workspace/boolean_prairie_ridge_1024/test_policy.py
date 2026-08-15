from policy import may_release_2772_delta

def test_both():
    assert may_release_2772_delta(True, False) is False
