from price import final_price

def test_price():
    assert final_price(100, 15) == 85
