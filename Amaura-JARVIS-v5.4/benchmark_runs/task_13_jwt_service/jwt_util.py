import hmac
import hashlib
import base64
import json
from datetime import datetime, timedelta


def encode_token(payload: dict, secret: str, expires_in: int = 3600) -> str:
    """
    Encode a JWT token using HMAC-SHA256 and base64url encoding.
    
    Args:
        payload: Dictionary containing the token claims
        secret: Secret key for signing the token
        expires_in: Token expiration time in seconds (default: 3600)
    
    Returns:
        Encoded JWT token as a string
    """
    # Add standard claims
    payload = payload.copy()
    payload['exp'] = int((datetime.utcnow() + timedelta(seconds=expires_in)).timestamp())
    payload['iat'] = int(datetime.utcnow().timestamp())
    
    # Create header
    header = {
        'alg': 'HS256',
        'typ': 'JWT'
    }
    
    # Base64url encode header and payload
    header_encoded = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip('=')
    payload_encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
    
    # Create signature
    signature = hmac.new(
        secret.encode(),
        f"{header_encoded}.{payload_encoded}".encode(),
        hashlib.sha256
    ).digest()
    signature_encoded = base64.urlsafe_b64encode(signature).decode().rstrip('=')
    
    # Combine all parts
    return f"{header_encoded}.{payload_encoded}.{signature_encoded}"

def decode_token(token: str, secret: str) -> dict:
    """
    Decode and verify a JWT token.
    
    Args:
        token: JWT token to decode
        secret: Secret key for verifying the token
    
    Returns:
        Dictionary containing the token claims
    
    Raises:
        ValueError: If the token is invalid or expired
    """
    try:
        # Split token into parts
        header_encoded, payload_encoded, signature_encoded = token.split('.')
        
        # Verify signature
        expected_signature = hmac.new(
            secret.encode(),
            f"{header_encoded}.{payload_encoded}".encode(),
            hashlib.sha256
        ).digest()
        expected_signature_encoded = base64.urlsafe_b64encode(expected_signature).decode().rstrip('=')
        
        if not hmac.compare_digest(signature_encoded, expected_signature_encoded):
            raise ValueError("Invalid token signature")
        
        # Decode payload
        payload = json.loads(base64.urlsafe_b64decode(payload_encoded + '=' * (-len(payload_encoded) % 4)))
        
        # Check expiration
        if 'exp' in payload and datetime.utcnow().timestamp() > payload['exp']:
            raise ValueError("Token has expired")
        
        return payload
    
    except (ValueError, json.JSONDecodeError) as e:
        raise ValueError("Invalid token") from e
