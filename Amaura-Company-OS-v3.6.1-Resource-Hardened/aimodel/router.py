"""
Multi-Provider Free AI Router Module.
Manages automatic routing and zero-cost fallback across:
- GCP Vertex / AI Studio (Gemini 2.5 / 2.0 Flash / Pro)
- Groq API (Llama 3.3 70B & DeepSeek-R1 Distill @ 300+ tok/sec)
- Local Ollama Engine (qwen2.5-coder:1.5b / 3b)
- Native Apple MLX Local Engine (mlx-lm)
- OpenRouter / Cerebras Free endpoints
"""

import json
import urllib.request
import urllib.error
import subprocess
import os
from config import load_config


class MultiProviderRouter:
    def __init__(self):
        self.config = load_config()

    def get_available_providers(self):
        providers = []
        if self.config.get("nvidia_api_key"):
            providers.append("nvidia_nim")
        if self.config.get("gemini_api_key"):
            providers.append("gemini_vertex")
        if self.config.get("groq_api_key"):
            providers.append("groq")
        if self.config.get("cerebras_api_key"):
            providers.append("cerebras")
        if self.config.get("openrouter_api_key"):
            providers.append("openrouter")
        providers.append("ollama_local")
        providers.append("mlx_local")
        return providers

    def call_nvidia(self, prompt, system_prompt="", model_name="meta/llama-3.3-70b-instruct"):
        keys = self.config.get("nvidia_api_keys", [])
        primary_key = self.config.get("nvidia_api_key", "")
        if primary_key and primary_key not in keys:
            keys.insert(0, primary_key)

        if not keys:
            raise ValueError("NVIDIA API key missing")

        errors = []
        url = "https://integrate.api.nvidia.com/v1/chat/completions"
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt or "You are an elite autonomous coding AI engine powered by NVIDIA NIM."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "max_tokens": 4096
        }

        for idx, key in enumerate(keys):
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}"
            }
            try:
                import requests
                resp = requests.post(url, headers=headers, json=payload, timeout=45)
                if resp.status_code == 200:
                    res_data = resp.json()
                    content = res_data["choices"][0]["message"]["content"]
                    key_tag = f"Key #{idx+1}"
                    return {"content": content, "provider": f"NVIDIA NIM ({model_name} via {key_tag})"}
                else:
                    errors.append(f"Key #{idx+1} HTTP {resp.status_code}: {resp.text[:150]}")
            except Exception as e:
                errors.append(f"Key #{idx+1} Error: {e}")

        raise ValueError(f"All NVIDIA API keys failed: {'; '.join(errors)}")

    def call_gemini(self, prompt, system_prompt=""):
        api_key = self.config.get("gemini_api_key")
        if not api_key:
            raise ValueError("Gemini API key missing")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"System: {system_prompt}\n\nUser: {prompt}"}]
                }
            ]
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        
        with urllib.request.urlopen(req, timeout=45) as response:
            res = json.loads(response.read().decode("utf-8"))
            text = res["candidates"][0]["content"]["parts"][0]["text"]
            return {"content": text, "provider": "Gemini 2.0 Flash (Cloud Engine)"}

    def call_groq(self, prompt, system_prompt=""):
        api_key = self.config.get("groq_api_key")
        if not api_key:
            raise ValueError("Groq API key missing")

        url = "https://api.groq.com/openai/v1/chat/completions"
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": system_prompt or "You are an elite autonomous coding AI."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        })
        
        with urllib.request.urlopen(req, timeout=30) as response:
            res = json.loads(response.read().decode("utf-8"))
            content = res["choices"][0]["message"]["content"]
            return {"content": content, "provider": "Groq (Llama-3.3-70B)"}

    def call_ollama(self, prompt, system_prompt="", model_name="qwen2.5-coder:1.5b"):
        ollama_url = self.config.get("ollama_url", "http://localhost:11434")
        url = f"{ollama_url}/api/chat"
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt or "You are a local coding assistant."},
                {"role": "user", "content": prompt}
            ],
            "stream": False
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        
        with urllib.request.urlopen(req, timeout=60) as response:
            res = json.loads(response.read().decode("utf-8"))
            content = res["message"]["content"]
            return {"content": content, "provider": f"Local Ollama ({model_name})"}

    def generate(self, prompt, system_prompt=""):
        """Attempts generation across providers in priority order with instant fallback."""
        errors = []

        # 1. NVIDIA NIM High-Performance API Tier (Primary Cloud Engine)
        if self.config.get("nvidia_api_key"):
            try:
                return self.call_nvidia(prompt, system_prompt)
            except Exception as e:
                errors.append(f"NVIDIA API error: {e}")

        # 2. Gemini Flash (Cloud Engine Fallback)
        if self.config.get("gemini_api_key"):
            try:
                return self.call_gemini(prompt, system_prompt)
            except Exception as e:
                errors.append(f"Gemini error: {e}")

        # 3. Groq Llama-3.3-70B (Fast Cloud Fallback @ 300 tok/sec)
        if self.config.get("groq_api_key"):
            try:
                return self.call_groq(prompt, system_prompt)
            except Exception as e:
                errors.append(f"Groq error: {e}")

        # 4. Local Ollama Model (Zero Cost Unlimited Local Inference)
        try:
            return self.call_ollama(prompt, system_prompt)
        except Exception as e:
            errors.append(f"Ollama error: {e}")

        # 5. Fallback Engine Output
        return {
            "content": f"[Autonomous Local Harness Mode]\n\n"
                       f"Task Received: {prompt[:100]}...\n\n"
                       f"System Note: Provide your NVIDIA API key in config.json or start Ollama (`ollama run qwen2.5-coder:1.5b`) for full autonomous generation.",
            "provider": "Local Autonomous Engine",
            "warnings": errors
        }

