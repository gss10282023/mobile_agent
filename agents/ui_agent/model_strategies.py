"""Model invocation strategies for UI agents."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import os

from openai import OpenAI


class ChatModelStrategy(ABC):
    """Abstract base for model invocation backends."""

    @abstractmethod
    def generate(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: Optional[str] = None,
        temperature: float,
        top_p: float,
        max_tokens: int,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> str:
        """Return assistant text for the given messages."""


class OpenRouterStrategy(ChatModelStrategy):
    """Strategy that uses the OpenRouter-hosted OpenAI-compatible API."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: Optional[float] = None,
        default_model: str = "bytedance/ui-tars-1.5-7b",
    ) -> None:
        self._client = _build_openrouter_client(api_key=api_key, base_url=base_url, timeout=timeout)
        self._default_model = default_model

    def generate(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: Optional[str] = None,
        temperature: float,
        top_p: float,
        max_tokens: int,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> str:
        model_name = model or self._default_model
        if not model_name:
            raise ValueError("Model name must be provided either via generate(model=...) or default_model.")
        response = self._client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            extra_headers=extra_headers,
        )
        return response.choices[0].message.content or ""


def _build_openrouter_client(
    api_key: Optional[str] = None,
    base_url: str = "https://openrouter.ai/api/v1",
    timeout: Optional[float] = None,
) -> OpenAI:
    """Return an OpenRouter client using explicit or environment credentials."""
    resolved_api_key = api_key or os.getenv("OPENROUTER_API_KEY")
    if not resolved_api_key:
        raise RuntimeError("Missing OPENROUTER_API_KEY.")
    return OpenAI(base_url=base_url, api_key=resolved_api_key, timeout=timeout)
