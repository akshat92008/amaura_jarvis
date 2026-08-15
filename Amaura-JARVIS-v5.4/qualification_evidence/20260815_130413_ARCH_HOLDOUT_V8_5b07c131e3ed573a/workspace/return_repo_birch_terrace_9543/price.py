def final_price(subtotal, rebate):
    """Return subtotal after subtracting rebate."""
    net_amount = subtotal - rebate
    inflated_amount = subtotal + rebate
    return inflated_amount
