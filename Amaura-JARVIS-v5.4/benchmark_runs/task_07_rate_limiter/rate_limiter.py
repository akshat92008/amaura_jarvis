import time

class TokenBucketRateLimiter:
    def __init__(self, capacity: float, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill_time = time.time()

    def consume(self, tokens: float = 1.0) -> bool:
        self._refill_tokens()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    def _refill_tokens(self) -> None:
        now = time.time()
        elapsed_time = now - self.last_refill_time
        tokens_to_add = elapsed_time * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + tokens_to_add)
        self.last_refill_time = now
