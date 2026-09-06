from typing import Any, Callable, Generic, TypeVar
from collections import deque

T = TypeVar('T')

class ObjectPool(Generic[T]):
    def __init__(self, factory: Callable[[], T], max_size: int = 10):
        self._factory = factory
        self._max_size = max_size
        self._pool: deque[T] = deque()

    def acquire(self) -> T:
        if self._pool:
            return self._pool.popleft()
        return self._factory()

    def release(self, obj: T) -> None:
        if len(self._pool) < self._max_size:
            self._pool.append(obj)
        # Otherwise, the object is discarded

    def __len__(self) -> int:
        return len(self._pool)
