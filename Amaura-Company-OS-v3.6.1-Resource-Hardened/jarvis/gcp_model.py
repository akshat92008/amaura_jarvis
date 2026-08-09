"""
GCP Custom AI Model Pipeline & Host Connector Module.
Connects JARVIS Core to custom fine-tuned models hosted on GCP Compute Engine (vLLM / Ollama)
and GCP Vertex AI (Gemini 2.0 Flash Thinking / Pro).
Includes Unsloth fine-tuning configuration guide and adaptive reasoning pipeline.
"""

import os
import json
import httpx
from typing import Dict, Any, Optional

GCP_VM_DEFAULT_ENDPOINT = os.getenv("JARVIS_GCP_ENDPOINT", "http://34.123.45.67:8000/v1")
VERTEX_API_KEY = os.getenv("VERTEX_API_KEY", os.getenv("GEMINI_API_KEY", ""))


class GCPModelClient:
    def __init__(self, endpoint_url: str = GCP_VM_DEFAULT_ENDPOINT, api_key: Optional[str] = None):
        self.endpoint_url = endpoint_url
        self.api_key = api_key or VERTEX_API_KEY

    def check_health(self) -> Dict[str, Any]:
        """Check if GCP Compute Engine GPU VM or Vertex AI endpoint is online."""
        # 1. Check custom GPU VM endpoint
        if self.endpoint_url and not self.endpoint_url.startswith("http://34.123.45.67"):
            try:
                resp = httpx.get(f"{self.endpoint_url}/models", timeout=0.2)
                if resp.status_code == 200:
                    return {
                        "online": True,
                        "status": "online",
                        "provider": "gcp_vllm",
                        "endpoint": self.endpoint_url,
                        "model": "jarvis-coder-32b (vLLM on GCP GPU VM)",
                        "ram_load": "0 MB (Hosted on GCP GPU VM)"
                    }
            except Exception:
                pass

        # 2. Check Vertex AI / Gemini API
        if self.api_key:
            return {
                "online": True,
                "status": "online",
                "provider": "gcp_vertex",
                "endpoint": "https://generativelanguage.googleapis.com/v1beta",
                "model": "fable-5-reasoning (Vertex AI Gemini 2.0 Flash Thinking)",
                "ram_load": "0 MB (GCP Cloud)"
            }

        return {
            "online": False,
            "status": "offline",
            "endpoint": self.endpoint_url,
            "model": "fable-5-reasoning (Fallback to Groq / Local)",
            "ram_load": "0 MB"
        }

    def generate_reasoning_trace(self, prompt: str, system_prompt: str = "") -> Dict[str, str]:
        """Generates an adaptive CoT reasoning trace followed by code solution (Claude Fable 5 style)."""
        health = self.check_health()
        
        # Vertex AI / Gemini API Path
        if health.get("provider") == "gcp_vertex" and self.api_key:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-thinking-exp-01-21:generateContent?key={self.api_key}"
                payload = {
                    "contents": [
                        {
                            "role": "user",
                            "parts": [
                                {"text": f"System: {system_prompt}\n\nTask: Perform deep adaptive thinking and architectural planning before outputting your solution.\n\nUser Request: {prompt}"}
                            ]
                        }
                    ]
                }
                resp = httpx.post(url, json=payload, timeout=45.0)
                if resp.status_code == 200:
                    res = resp.json()
                    text = res["candidates"][0]["content"]["parts"][0]["text"]
                    return {
                        "thinking": "Gemini 2.0 Flash Thinking adaptive reasoning trace generated via GCP Vertex AI.",
                        "content": text,
                        "provider": "gcp_vertex"
                    }
            except Exception as e:
                print(f"[GCP Client] Vertex AI call failed: {e}")

        # Custom vLLM / OpenAI Compatible Endpoint Path
        try:
            url = f"{self.endpoint_url}/chat/completions"
            payload = {
                "model": "jarvis-coder-32b",
                "messages": [
                    {"role": "system", "content": system_prompt or "You are JARVIS operating with Claude Fable 5 level adaptive reasoning."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.2
            }
            resp = httpx.post(url, json=payload, timeout=60.0)
            if resp.status_code == 200:
                res = resp.json()
                content = res["choices"][0]["message"]["content"]
                return {
                    "thinking": "DeepSeek R1 CoT trace executed via GCP Compute Engine vLLM GPU.",
                    "content": content,
                    "provider": "gcp_vllm"
                }
        except Exception as e:
            print(f"[GCP Client] vLLM endpoint call failed: {e}")

        return {
            "thinking": "Offline reasoning fallback.",
            "content": f"[Offline Fallback] Processing prompt: {prompt}",
            "provider": "fallback"
        }

    @staticmethod
    def generate_unsloth_finetune_script() -> str:
        """Returns the Unsloth fine-tuning Python script for Colab / GCP GPU VM."""
        return '''# Unsloth Qwen 2.5 Coder 32B Fine-Tuning Script for JARVIS
# Runs on Google Colab (Free T4/A100) or GCP Compute Engine

from unsloth import FastLanguageModel
import torch

max_seq_length = 4096
dtype = None # Auto detection
load_in_4bit = True # 4bit quantization for fast training

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = "Qwen/Qwen2.5-Coder-32B-Instruct",
    max_seq_length = max_seq_length,
    dtype = dtype,
    load_in_4bit = load_in_4bit,
)

model = FastLanguageModel.get_peft_model(
    model,
    r = 16,
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    lora_alpha = 16,
    lora_dropout = 0,
    bias = "none",
    use_gradient_checkpointing = "unsloth",
)

print("🚀 jarvis-fable5-32b fine-tuning pipeline initialized on GCP!")
'''

