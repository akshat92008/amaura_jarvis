from rules import fits_quota_9966_amber

def test_edge():
    assert fits_quota_9966_amber(44) is True
