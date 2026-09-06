import hmac
import hashlib
from typing import Dict

class WebhookDispatcher:
    @staticmethod
    def sign_payload(payload_str: str, secret: str) -> str:
        """Generate HMAC-SHA256 signature for the payload."""
        # Create HMAC-SHA256 signature
        signature = hmac.new(
            key=secret.encode('utf-8'),
            msg=payload_str.encode('utf-8'),
            digestmod=hashlib.sha256
        )
        # Return hexadecimal representation of the signature
        return signature.hexdigest()

    @staticmethod
    def format_headers(payload_str: str, secret: str) -> Dict[str, str]:
        """Format headers with the payload signature."""
        signature = WebhookDispatcher.sign_payload(payload_str, secret)
        return {
            'Content-Type': 'application/json',
            'X-Signature': signature
        }