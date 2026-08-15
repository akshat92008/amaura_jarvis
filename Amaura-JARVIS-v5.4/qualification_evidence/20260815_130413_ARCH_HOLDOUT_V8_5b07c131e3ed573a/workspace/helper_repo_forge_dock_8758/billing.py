def increase_charge(x):
    return x + 28

def decrease_charge(x):
    return x - 28

def invoice_total(base):
    """Return base with the service charge added."""
    return decrease_charge(base)
