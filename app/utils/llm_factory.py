"""
Helpers for creating Qwen chat models through the OpenAI-compatible endpoint.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from langchain_openai import ChatOpenAI

from app.config import settings

ModelProfile = Literal[
    "default",
    "planner",
    "router",
    "rag",
    "vision",
    "report",
    "transport",
]


@dataclass(frozen=True)
class ModelCompatibility:
    """Describe behavior differences that affect prompting and tool usage."""

    supports_forced_tool_choice: bool = True
    structured_output_requires_json_keyword: bool = False


def get_model_compatibility(
    model: Optional[str] = None,
    *,
    profile: ModelProfile = "default",
) -> ModelCompatibility:
    """Return compatibility flags for the configured compatible-mode model."""

    model_name = resolve_model_name(profile=profile, model=model).strip().lower()
    is_qwen3_family = model_name.startswith("qwen3")

    return ModelCompatibility(
        supports_forced_tool_choice=not is_qwen3_family,
        structured_output_requires_json_keyword=is_qwen3_family,
    )


def resolve_model_name(
    *,
    profile: ModelProfile = "default",
    model: Optional[str] = None,
) -> str:
    """Resolve the concrete model name for a given profile."""

    if model:
        return model

    profile_mapping = {
        "default": settings.qwen_model_name,
        "planner": settings.qwen_planner_model_name,
        "router": settings.qwen_router_model_name,
        "rag": settings.qwen_rag_model_name,
        "vision": settings.qwen_vision_model_name,
        "report": settings.qwen_report_model_name,
        "transport": settings.qwen_router_model_name,
    }
    return profile_mapping.get(profile, settings.qwen_model_name)


def build_chat_model(
    *,
    temperature: Optional[float] = None,
    model: Optional[str] = None,
    profile: ModelProfile = "default",
    max_tokens: Optional[int] = None,
    streaming: bool = False,
) -> ChatOpenAI:
    """Build a Qwen chat model using the project's compatible-mode settings."""

    return ChatOpenAI(
        model=resolve_model_name(profile=profile, model=model),
        base_url=settings.qwen_base_url,
        api_key=settings.dashscope_api_key,
        temperature=settings.qwen_temperature if temperature is None else temperature,
        max_tokens=settings.qwen_max_tokens if max_tokens is None else max_tokens,
        streaming=streaming,
    )
