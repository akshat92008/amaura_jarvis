from policy import can_publish

def test_requires_both():
    assert can_publish(True, False) is False
