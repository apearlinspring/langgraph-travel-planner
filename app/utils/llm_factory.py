"""
Helpers for creating Qwen chat models through the OpenAI-compatible endpoint.
"""
from __future__ import annotations

from typing import Optional

from langchain_openai import ChatOpenAI

from app.config import settings


def build_chat_model(
    *,
    temperature: Optional[float] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    streaming: bool = False,
) -> ChatOpenAI:
    """Build a Qwen chat model using the project's compatible-mode settings."""

    return ChatOpenAI(
        model=model or settings.qwen_model_name,
        base_url=settings.qwen_base_url,
        api_key=settings.dashscope_api_key,
        temperature=settings.qwen_temperature if temperature is None else temperature,
        max_tokens=settings.qwen_max_tokens if max_tokens is None else max_tokens,
        streaming=streaming,
    )
