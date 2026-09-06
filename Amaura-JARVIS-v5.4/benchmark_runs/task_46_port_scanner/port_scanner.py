import socket

class PortScanner:
    def __init__(self, target_host: str, timeout: float = 0.5):
        self.target_host = target_host
        self.timeout = timeout

    def check_port(self, port: int) -> bool:
        """Check if a port is open on the target host.
        
        Args:
            port: The port number to check.
        
        Returns:
            bool: True if the port is open, False otherwise.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(self.timeout)
                result = s.connect_ex((self.target_host, port))
                return result == 0
        except socket.error:
            return False
