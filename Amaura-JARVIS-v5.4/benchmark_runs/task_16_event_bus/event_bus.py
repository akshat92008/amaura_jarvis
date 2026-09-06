from typing import Any, Callable, Dict, List, Set

class EventBus:
    def __init__(self):
        self.subscribers: Dict[str, Set[Callable]] = {}

    def subscribe(self, topic: str, callback: Callable) -> None:
        """Subscribe a callback to a topic."""
        if topic not in self.subscribers:
            self.subscribers[topic] = set()
        self.subscribers[topic].add(callback)

    def unsubscribe(self, topic: str, callback: Callable) -> None:
        """Unsubscribe a callback from a topic."""
        if topic in self.subscribers and callback in self.subscribers[topic]:
            self.subscribers[topic].remove(callback)
            if not self.subscribers[topic]:
                del self.subscribers[topic]

    def publish(self, topic: str, data: Any) -> int:
        """Publish data to all subscribers of a topic. Returns the number of subscribers notified."""
        if topic not in self.subscribers:
            return 0

        notified_count = 0
        for callback in self.subscribers[topic]:
            callback(data)
            notified_count += 1

        return notified_count
