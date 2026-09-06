import re

def scan_for_secrets(text: str) -> list[dict]:
    # AWS Access Key pattern
    aws_key_pattern = re.compile(r'AKIA[0-9A-Z]{16}')
    
    # Private Key pattern (PEM format)
    private_key_pattern = re.compile(r'-----BEGIN (?:RSA|DSA|EC|OPENSSH) PRIVATE KEY-----[\s\S]*?-----END (?:RSA|DSA|EC|OPENSSH) PRIVATE KEY-----')
    
    aws_keys = aws_key_pattern.findall(text)
    private_keys = private_key_pattern.findall(text)
    
    results = []
    
    for key in aws_keys:
        results.append({
            'type': 'AWS Access Key',
            'value': key,
            'severity': 'High'
        })
    
    for key in private_keys:
        results.append({
            'type': 'Private Key',
            'value': key,
            'severity': 'Critical'
        })
    
    return results

# Example usage
if __name__ == '__main__':
    sample_text = """
    This is a sample text containing an AWS key AKIAIOSFODNN7EXAMPLE and a private key:
    -----BEGIN RSA PRIVATE KEY-----
    MIIEpAIBAAKCAQEAx4UyY3... (truncated)
    -----END RSA PRIVATE KEY-----
    """
    
    secrets = scan_for_secrets(sample_text)
    for secret in secrets:
        print(f"Found {secret['type']}: {secret['value']} (Severity: {secret['severity']})\n")