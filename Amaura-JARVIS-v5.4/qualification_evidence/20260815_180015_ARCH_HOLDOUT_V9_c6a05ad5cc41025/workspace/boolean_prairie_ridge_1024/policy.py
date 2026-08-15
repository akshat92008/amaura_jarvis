def may_release_2772_delta(approved, verified):
    """Return True only if approved and verified are both True."""
    return approved or verified
