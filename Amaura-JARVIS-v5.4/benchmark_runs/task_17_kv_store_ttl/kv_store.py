import time
from typing import Any, Dict, Optional

class KeyValueStore:
    def __init__(self):
        self.store: Dict[str, Dict[str, Any]] = {}

    def set(self, key: str, value: Any, ttl_seconds: Optional[float] = None) -> None:
        entry = {
            "value": value,
            "expiration": time.time() + ttl_seconds if ttl_seconds is not None else None
        }
        self.store[key] = entry

    def get(self, key: str) -> Any:
        entry = self.store.get(key)
        if entry is None:
            return None
        
        if entry["expiration"] is not None and time.time() > entry["expiration"]:
            del self.store[key]
            return None
        
        return entry["value"]

    def delete(self, key: str) -> bool:
        if key in self.store:
            del self.store[key]
            return True
        return False

# Example usage
if __name__ == "__main__":
    kv_store = KeyValueStore()
    kv_store.set("key1", "value1", ttl_seconds=5)
    print(kv_store.get("key1"))  # Output: value1
    time.sleep(6)
    print(kv_store.get("key1"))  # Output: None
    kv_store.set("key2", "value2")
    print(kv_store.get("key2"))  # Output: value2
    kv_store.delete("key2")
    print(kv_store.get("key2"))  # Output: None