import time
from typing import Callable, Any, Optional

class CircuitBreaker:
    """A circuit breaker implementation that prevents repeated calls to failing functions.

    Attributes:
        failure_threshold (int): Number of consecutive failures before tripping.
        recovery_timeout (float): Time in seconds to wait before attempting recovery.
        state (str): Current state of the circuit breaker ('CLOSED', 'OPEN', 'HALF-OPEN').
        failure_count (int): Current count of consecutive failures.
        last_failure_time (Optional[float]): Timestamp of the last failure.
    """
    
    def __init__(self, failure_threshold: int, recovery_timeout: float):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = 'CLOSED'
        self.failure_count = 0
        self.last_failure_time = None

    def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Attempt to call the function with circuit breaker logic.

        Args:
            func: The function to call.
            *args: Positional arguments for the function.
            **kwargs: Keyword arguments for the function.

        Returns:
            The result of the function call if successful.

        Raises:
            Exception: If the circuit is OPEN or if the function call fails.
        """
        if self.state == 'OPEN':
            if self.last_failure_time and time.time() - self.last_failure_time >= self.recovery_timeout:
                self.state = 'HALF-OPEN'
                self.failure_count = 0
            else:
                raise Exception("Circuit breaker is OPEN. Cannot call function.")

        try:
            result = func(*args, **kwargs)
            if self.state == 'HALF-OPEN':
                self.state = 'CLOSED'
                self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = 'OPEN'
            raise e
