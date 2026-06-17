"""
Ollama client wrapper for Gemma 4 E4B.
Provides async/sync interfaces, retry logic, health checks, and response caching.
"""
import json
import time
import hashlib
import os
from typing import Optional, Dict, Any, List
from collections import OrderedDict
from datetime import datetime

from openai import OpenAI
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

from src.utils.logger import get_logger
from src.utils.helpers import load_config

logger = get_logger("stock_ai.llm")

# ── LRU Cache for LLM responses ─────────────────────────────────────
_response_cache: OrderedDict = OrderedDict()
_CACHE_MAX_SIZE = 100
_CACHE_TTL_SECONDS = 1800  # 30 minutes


def _cache_key(model: str, prompt: str, system: str = "") -> str:
    """Generate a deterministic cache key from the prompt."""
    content = f"{model}:{system}:{prompt}"
    return hashlib.md5(content.encode()).hexdigest()


def _get_cached(key: str) -> Optional[str]:
    """Get a cached response if it exists and hasn't expired."""
    if key in _response_cache:
        entry = _response_cache[key]
        if time.time() - entry["timestamp"] < _CACHE_TTL_SECONDS:
            _response_cache.move_to_end(key)
            return entry["response"]
        else:
            del _response_cache[key]
    return None


def _set_cached(key: str, response: str):
    """Cache a response with LRU eviction."""
    _response_cache[key] = {"response": response, "timestamp": time.time()}
    if len(_response_cache) > _CACHE_MAX_SIZE:
        _response_cache.popitem(last=False)


class LLMClient:
    """
    Wrapper around Groq API for interacting with LLaMA models.
    
    Provides:
    - Health checking (is API key valid?)
    - Structured JSON output parsing
    - Response caching (LRU with TTL)
    - Retry logic with exponential backoff
    - Graceful fallback when unavailable
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()
        llm_config = self.config.get("llm", {})
        self.model = llm_config.get("model", "gemma4:e4b")
        self.timeout = llm_config.get("timeout_seconds", 60)
        self.temperature = llm_config.get("temperature", 0.3)
        self.enabled = llm_config.get("enabled", True)
        self._healthy = None  # None = not checked yet
        self._last_health_check = 0
        
        self.client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")

    def is_healthy(self, force_check: bool = False) -> bool:
        """
        Check if Ollama is running and the model is available.
        Caches result for 60 seconds.
        """
        if not self.enabled:
            return False

        if not force_check and self._healthy is not None:
            if time.time() - self._last_health_check < 60:
                return self._healthy

        if not self.client:
            logger.warning("OpenAI client not initialized.")
            self._healthy = False
            return False

        try:
            # Ping models list to verify API key
            models_response = self.client.models.list()
            available = [m.id for m in models_response.data]

            # Check if our model is available
            self._healthy = self.model in available
            
            if not self._healthy:
                logger.warning(
                    f"Model '{self.model}' not found in Ollama. "
                    f"Available: {available[:5]}..."
                )
            else:
                logger.info(f"✅ Ollama health check OK — {self.model} available")

        except Exception as e:
            logger.warning(f"Ollama health check failed: {e}")
            self._healthy = False

        self._last_health_check = time.time()
        return self._healthy

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=15),
        stop=stop_after_attempt(2),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        reraise=True,
    )
    def generate(
        self,
        prompt: str,
        system: str = "",
        use_cache: bool = True,
        temperature: Optional[float] = None,
    ) -> Optional[str]:
        """
        Generate a response from Groq API.

        Args:
            prompt: The user prompt
            system: System prompt for role/context setting
            use_cache: Whether to use response caching
            temperature: Override default temperature

        Returns:
            Response text string, or None if unavailable
        """
        if not self.enabled or not self.is_healthy():
            return None

        # Check cache
        if use_cache:
            key = _cache_key(self.model, prompt, system)
            cached = _get_cached(key)
            if cached is not None:
                logger.debug("LLM cache hit")
                return cached

        try:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature or self.temperature,
                max_tokens=2048,
                timeout=self.timeout
            )

            content = response.choices[0].message.content

            # Cache the response
            if use_cache:
                _set_cached(key, content)

            return content

        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            self._healthy = False
            return None

    def generate_json(
        self,
        prompt: str,
        system: str = "",
        use_cache: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a response and parse it as JSON.
        Handles markdown code blocks and malformed JSON gracefully.

        Returns:
            Parsed dictionary, or None on failure
        """
        raw = self.generate(prompt, system, use_cache)
        if raw is None:
            return None

        return self._parse_json_response(raw)

    def _parse_json_response(self, raw: str) -> Optional[Dict[str, Any]]:
        """
        Parse JSON from LLM response, handling various formats:
        - Raw JSON
        - ```json ... ``` blocks
        - JSON embedded in text
        """
        text = raw.strip()

        # Try raw JSON first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown code block
        if "```" in text:
            import re
            match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1).strip())
                except json.JSONDecodeError:
                    pass

        # Try finding JSON object in text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass

        logger.warning(f"Failed to parse JSON from LLM response: {text[:200]}...")
        return None

    def get_status(self) -> Dict[str, Any]:
        """Get current LLM client status for the dashboard."""
        healthy = self.is_healthy(force_check=True)
        return {
            "enabled": self.enabled,
            "healthy": healthy,
            "model": self.model,
            "cache_size": len(_response_cache),
            "last_check": datetime.fromtimestamp(self._last_health_check).isoformat()
            if self._last_health_check > 0
            else None,
        }


# ── Module-level singleton ───────────────────────────────────────────
_client: Optional[LLMClient] = None


def get_llm_client(config: Optional[dict] = None) -> LLMClient:
    """Get or create the singleton LLM client."""
    global _client
    if _client is None:
        _client = LLMClient(config)
    return _client
