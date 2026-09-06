import re
from typing import Dict

def parse_apache_log(line: str) -> Dict[str, str]:
    """Parse an Apache log line and extract key components.

    Args:
        line: A single line from an Apache access log

    Returns:
        A dictionary containing:
            - ip: Client IP address
            - method: HTTP method (GET, POST, etc.)
            - path: Requested path
            - status: HTTP status code
            - bytes: Response size in bytes
    """
    # Regular expression pattern for Apache access logs
    pattern = r'^(?P<ip>\S+) \S+ \S+ \[(?P<date>[^\]]+)\] "(?P<method>\S+) (?P<path>\S+) \S+" (?P<status>\d+) (?P<bytes>\d+)'
    
    match = re.match(pattern, line)
    if not match:
        raise ValueError(f"Invalid Apache log line: {line}")
    
    return {
        'ip': match.group('ip'),
        'method': match.group('method'),
        'path': match.group('path'),
        'status': match.group('status'),
        'bytes': match.group('bytes')
    }

if __name__ == "__main__":
    # Example usage
    log_line = '192.168.1.1 - - [10/Oct/2023:13:55:36 +0000] "GET /index.html HTTP/1.1" 200 1234'
    parsed = parse_apache_log(log_line)
    print(parsed)