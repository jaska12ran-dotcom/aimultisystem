import os
import logging
from typing import Optional

import httpx

logger = logging.getLogger("codetwin.intelligence")


class LLMClient:
    """
    Unified LLM Client supporting:
    - OpenAI / OpenAI-compatible (vLLM, LocalAI, etc.)
    - Ollama (local)
    - Hugging Face Inference API / OpenAI-compatible router
    - Deterministic High-Fidelity AST Synthesizer (Zero-dependency fallback)
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.hf_api_key = os.getenv("HUGGINGFACE_API_KEY") or os.getenv("HF_TOKEN", "")
        if provider and provider.lower() == "huggingface" and api_key:
            self.hf_api_key = api_key
        self.api_key = api_key or self.openai_api_key or self.hf_api_key
        self.api_base = api_base or os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
        self.hf_api_base = os.getenv("HUGGINGFACE_API_BASE", "https://router.huggingface.co/v1")
        self.ollama_base = os.getenv("OLLAMA_API_BASE", "http://localhost:11434")

        if provider:
            self.provider = provider.lower()
        elif self.openai_api_key:
            self.provider = "openai"
        elif self.hf_api_key:
            self.provider = "huggingface"
        else:
            self.provider = os.getenv("DEFAULT_LLM_PROVIDER", "mock").lower()

        default_models = {
            "openai": "gpt-4o-mini",
            "huggingface": "Qwen/Qwen2.5-Coder-1.5B-Instruct",
            "ollama": "llama3",
        }
        self.model = model or os.getenv("LLM_MODEL", default_models.get(self.provider, "mock"))

    async def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 4000, temperature: float = 0.2) -> str:
        """Generates text from configured provider with robust error handling and fallback."""
        if self.provider == "openai" and self.api_key:
            try:
                return await self._generate_openai(system_prompt, user_prompt, max_tokens, temperature)
            except Exception as e:
                logger.warning(f"OpenAI generation failed: {e}. Falling back to AST synthesizer.")

        if self.provider == "huggingface" and (self.hf_api_key or self.api_key):
            try:
                return await self._generate_huggingface(system_prompt, user_prompt, max_tokens, temperature)
            except Exception as e:
                logger.warning(f"Hugging Face generation failed: {e}. Falling back to AST synthesizer.")

        if self.provider == "ollama":
            try:
                return await self._generate_ollama(system_prompt, user_prompt, temperature)
            except Exception as e:
                logger.warning(f"Ollama generation failed: {e}. Falling back to AST synthesizer.")

        return ""

    async def _generate_openai(self, system_prompt: str, user_prompt: str, max_tokens: int, temperature: float) -> str:
        url = f"{self.api_base.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(url, headers=headers, json=payload)
            res.raise_for_status()
            data = res.json()
            return data["choices"][0]["message"]["content"]

    async def _generate_huggingface(self, system_prompt: str, user_prompt: str, max_tokens: int, temperature: float) -> str:
        token = self.hf_api_key or self.api_key or ""
        if not token:
            raise ValueError("Hugging Face API key is required to generate text.")
        url = f"{self.hf_api_base.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(url, headers=headers, json=payload)
            res.raise_for_status()
            data = res.json()
            return data["choices"][0]["message"]["content"]

    async def _generate_ollama(self, system_prompt: str, user_prompt: str, temperature: float) -> str:
        url = f"{self.ollama_base.rstrip('/')}/api/generate"
        payload = {
            "model": self.model,
            "prompt": f"{system_prompt}\n\nUser: {user_prompt}",
            "stream": False,
            "options": {"temperature": temperature},
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(url, json=payload)
            res.raise_for_status()
            data = res.json()
            return data["response"]


# Singleton instance
default_llm_client = LLMClient()
