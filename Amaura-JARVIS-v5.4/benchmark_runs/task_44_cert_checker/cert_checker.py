from datetime import datetime, timezone

def is_cert_expired(valid_to_iso: str) -> bool:
    """Check if a certificate has expired based on its expiration timestamp.

    Args:
        valid_to_iso: ISO format expiration timestamp string

    Returns:
        bool: True if the certificate has expired, False otherwise
    """
    expiration_time = datetime.fromisoformat(valid_to_iso).replace(tzinfo=timezone.utc)
    current_time = datetime.now(timezone.utc)
    return current_time > expiration_time
