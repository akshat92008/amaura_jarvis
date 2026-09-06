from typing import Callable, Dict, Tuple, Optional
import re

class Router:
    def __init__(self):
        self.routes = []

    def add_route(self, method: str, path_pattern: str, handler: Callable) -> None:
        """Add a route to the router.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            path_pattern: URL path pattern with parameters (e.g., '/users/{id}')
            handler: Callable that handles the request
        """
        # Convert path pattern to regex
        pattern = re.sub(r'\{(\\w+)\\}', r'(?P<\\1>[^/]+)', path_pattern)
        pattern = f'^{pattern}$'
        self.routes.append({
            'method': method.upper(),
            'pattern': re.compile(pattern),
            'handler': handler
        })

    def resolve(self, method: str, path: str) -> Tuple[Optional[Callable], Dict]:
        """Resolve a request to a handler and extract parameters.
        
        Args:
            method: HTTP method
            path: Request path
        
        Returns:
            Tuple of (handler, params) or (None, {}) if no match
        """
        for route in self.routes:
            if route['method'] == method.upper():
                match = route['pattern'].match(path)
                if match:
                    return route['handler'], match.groupdict()
        return None, {}
