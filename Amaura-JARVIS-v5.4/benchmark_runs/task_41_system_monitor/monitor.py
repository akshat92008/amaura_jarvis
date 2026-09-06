import platform
import psutil
import json

class SystemSnapshot:
    def __init__(self):
        self.platform = platform.system()
        self.architecture = platform.machine()
        self.memory_usage = psutil.virtual_memory().percent

    def to_json(self) -> str:
        return json.dumps({
            "platform": self.platform,
            "architecture": self.architecture,
            "memory_usage": self.memory_usage
        }, indent=2)

# Example usage
if __name__ == "__main__":
    snapshot = SystemSnapshot()
    print(snapshot.to_json())