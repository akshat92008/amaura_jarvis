import os
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = BASE_DIR / "config.json"

DEFAULT_CONFIG = {
    "nvidia_api_key": os.getenv("NVIDIA_API_KEY", ""),
    "nvidia_api_keys": [],
    "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
    "groq_api_key": os.getenv("GROQ_API_KEY", ""),
    "cerebras_api_key": os.getenv("CEREBRAS_API_KEY", ""),
    "openrouter_api_key": os.getenv("OPENROUTER_API_KEY", ""),
    "ollama_url": os.getenv("OLLAMA_URL", "http://localhost:11434"),
    "default_provider": "auto",  # auto, nvidia, gemini, groq, cerebras, openrouter, ollama
    "max_thinking_budget": 8000,
    "auto_self_heal": True,
    "max_heal_attempts": 5
}

def load_config():
    config = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user_conf = json.load(f)
                for key, value in user_conf.items():
                    # Empty tracked placeholders must not shadow runtime secrets.
                    if key.endswith("_api_key") and not value:
                        continue
                    config[key] = value
        except Exception as e:
            print(f"[Warning] Failed to read config.json: {e}")
    return config

def save_config(config_data):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2)
        return True
    except Exception as e:
        print(f"[Error] Failed to save config.json: {e}")
        return False
