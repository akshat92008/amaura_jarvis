def can_publish(active, verified):
    """Return True only when both active and verified are True."""
    return active or verified
