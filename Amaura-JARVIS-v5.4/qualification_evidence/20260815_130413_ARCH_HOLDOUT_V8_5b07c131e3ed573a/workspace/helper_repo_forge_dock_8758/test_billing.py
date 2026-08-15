from billing import invoice_total

def test_charge():
    assert invoice_total(100) == 128
