"""
真实交通协调推荐质量专项验证。

这组测试关注的不是“工具能否返回结果”，而是：
1. 协调器是否会为不同场景调用正确的真实工具组合；
2. 最终推荐是否体现出符合场景的取舍逻辑。
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest
from langchain_core.messages import AIMessage

from app.agents.subagents.transport_coordinator import create_transport_coordinator

pytestmark = [
    pytest.mark.integration,
    pytest.mark.llm,
    pytest.mark.mcp,
    pytest.mark.slow,
]


@dataclass(frozen=True)
class RecommendationScenario:
    name: str
    prompt: str
    preferred_mode: str
    expected_tool_calls: tuple[str, ...]
    forbidden_tool_calls: tuple[str, ...]
    expected_keywords: tuple[str, ...]


SCENARIOS = [
    RecommendationScenario(
        name="long_fast_prefers_high_speed_rail_convenience",
        prompt=(
            "我想从北京去上海，2026-05-10出发，2个大人，"
            "优先省时也尽量省心，不指定交通方式，请直接帮我比较并推荐。"
        ),
        preferred_mode="高铁",
        expected_tool_calls=("query_flights", "query_trains"),
        forbidden_tool_calls=("plan_driving_route",),
        expected_keywords=("门到门", "高铁", "航班"),
    ),
    RecommendationScenario(
        name="long_relaxed_prefers_train_comfort",
        prompt=(
            "我想从北京去西安，2026-05-10出发，2个大人，"
            "不赶时间，更看重舒适、稳定、少折腾，不指定交通方式，请直接帮我比较并推荐。"
        ),
        preferred_mode="高铁",
        expected_tool_calls=("query_flights", "query_trains"),
        forbidden_tool_calls=("plan_driving_route",),
        expected_keywords=("舒适", "稳定", "高铁"),
    ),
    RecommendationScenario(
        name="short_family_prefers_driving_door_to_door",
        prompt=(
            "我想从上海去杭州，2026-05-10出发，2个大人，"
            "带一位老人、两个大箱子，更在意门到门和省心，不指定交通方式，请直接帮我比较并推荐。"
        ),
        preferred_mode="自驾",
        expected_tool_calls=("query_trains", "plan_driving_route"),
        forbidden_tool_calls=("query_flights",),
        expected_keywords=("门到门", "老人", "行李", "自驾"),
    ),
]


def _collect_tool_call_names(messages) -> list[str]:
    tool_names: list[str] = []
    for message in messages:
        tool_calls = getattr(message, "tool_calls", None) or []
        tool_names.extend(tool_call["name"] for tool_call in tool_calls)
    return tool_names


def _last_ai_message_content(messages) -> str:
    ai_messages = [
        message.content
        for message in messages
        if isinstance(message, AIMessage) and isinstance(message.content, str) and message.content.strip()
    ]
    assert ai_messages, "expected at least one non-empty AI message"
    return ai_messages[-1]


def _assert_contains_any(content: str, candidates: tuple[str, ...], *, label: str) -> None:
    assert any(candidate in content for candidate in candidates), (
        f"expected {label} to contain one of {candidates}, got: {content}"
    )


def _assert_recommendation_mode(content: str, preferred_mode: str) -> None:
    marker_present = any(marker in content for marker in ("推荐", "建议", "首选"))
    assert marker_present, f"expected recommendation marker in: {content}"
    assert preferred_mode in content, f"expected preferred mode {preferred_mode!r} in: {content}"


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", SCENARIOS, ids=[scenario.name for scenario in SCENARIOS])
async def test_transport_coordinator_recommendation_quality(scenario: RecommendationScenario):
    coordinator = await create_transport_coordinator()

    response = await coordinator.ainvoke(
        {"messages": [{"role": "user", "content": scenario.prompt}]}
    )

    messages = response["messages"]
    tool_call_names = _collect_tool_call_names(messages)
    final_content = _last_ai_message_content(messages)

    print(f"\n=== 场景: {scenario.name} ===")
    print(f"工具调用: {tool_call_names}")
    print(f"最终推荐:\n{final_content}")

    for expected_tool in scenario.expected_tool_calls:
        assert expected_tool in tool_call_names

    for forbidden_tool in scenario.forbidden_tool_calls:
        assert forbidden_tool not in tool_call_names

    for keyword in scenario.expected_keywords:
        assert keyword in final_content

    _assert_recommendation_mode(final_content, scenario.preferred_mode)
    _assert_contains_any(
        final_content,
        ("再次核实", "正式购票", "实时变化"),
        label="verification reminder",
    )
