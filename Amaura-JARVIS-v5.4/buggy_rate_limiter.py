# Token Bucket Rate Limiter with subtle bug
import time

class TokenBucket:
    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill = time.time()

    def allow_request(self, tokens_needed: int = 1) -> bool:
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if tokens_needed <= self.tokens:
            self.tokens -= tokens_needed
            return True
        return False

if __name__ == '__main__':
    tb = TokenBucket(capacity=5, refill_rate=1.0)
    # With 5 tokens, a request for 1 token MUST be allowed
    assert tb.allow_request(1) == True, "Failed to allow request when tokens available"
    print("RATE_LIMITER_VERIFIED")
