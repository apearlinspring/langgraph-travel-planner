"""
Destination router that blends RAG, live search, and weather MCP data.
"""
import json
from operator import add
from typing import Annotated, Literal, TypedDict

from langchain.agents import create_agent
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field

from app.tools.mcp_tools import get_search_tools, get_weather_tools
from app.tools.rag_tools import get_rag_tools
from app.utils.llm_factory import build_chat_model
from app.utils.logger import app_logger


class Classification(TypedDict):
    agent: Literal["explore", "weather"]
    query: str


class AgentOutput(TypedDict):
    agent_name: str
    result: str


class DestinationRouterState(TypedDict):
    original_query: str
    destination: str
    classifications: list[Classification]
    agent_results: Annotated[list[AgentOutput], add]
    final_report: str


class ClassificationResult(BaseModel):
    classifications: list[Classification] = Field(
        description="需要调用的 Agent 列表以及每个 Agent 的子查询。"
    )


def _build_llm(temperature: float = 0.7):
    return build_chat_model(temperature=temperature)


def classifier_node(state: DestinationRouterState) -> dict:
    """Classify which specialists should answer the destination query."""
    app_logger.info(f"Destination router classifier query: {state['original_query']}")

    structured_llm = _build_llm().with_structured_output(ClassificationResult)
    result = structured_llm.invoke(
        [
            {
                "role": "system",
                "content": (
                    "你是旅行查询分类专家。"
                    "如果用户在问景点、玩法、美食、住宿、攻略，就调用 explore。"
                    "如果用户在问天气、气温、降雨、穿衣建议，就调用 weather。"
                    "如果是综合性目的地推荐，两个都调用。"
                ),
            },
            {
                "role": "user",
                "content": f"目的地：{state['destination']}\n查询：{state['original_query']}",
            },
        ]
    )

    app_logger.info(f"Destination router classifier picked {len(result.classifications)} agents")
    return {"classifications": result.classifications}


def route_to_agents(state: DestinationRouterState) -> list[Send]:
    sends = [
        Send(
            classification["agent"],
            {
                "query": classification["query"],
                "destination": state["destination"],
            },
        )
        for classification in state["classifications"]
    ]
    app_logger.info(f"Destination router fan-out count: {len(sends)}")
    return sends


async def _get_explore_tools():
    tools = list(get_rag_tools())
    try:
        tools.extend(await get_search_tools())
    except Exception as exc:
        app_logger.warning(f"Failed to load live search tools for destination router: {exc}")
    return tools


_explore_agent = None
_explore_agent_signature: tuple[str, ...] | None = None


def _create_explore_agent(tools):
    return create_agent(
        model=_build_llm(),
        tools=tools,
        system_prompt=(
            "你是一位旅行顾问，需要把知识库信息和必要的外部补充信息整合成可靠答案。"
            "优先用知识库工具回答相对稳定的内容，例如景点、美食、住宿、常规攻略。"
            "当用户的问题明显带有时效性，比如“最近”“当季”“最新”“现在”等，再调用 "
            "search_travel_info 补充实时信息。"
            "不要为了显得完整而编造最新情况；如果外部搜索不可用，要明确说明。"
        ),
    )


async def _get_or_create_explore_agent():
    global _explore_agent, _explore_agent_signature

    tools = await _get_explore_tools()
    signature = tuple(sorted(tool.name for tool in tools))
    if _explore_agent is None or signature != _explore_agent_signature:
        _explore_agent = _create_explore_agent(tools)
        _explore_agent_signature = signature
    return _explore_agent


async def explore_agent_node(state: dict) -> dict:
    query = state["query"]
    destination = state["destination"]

    app_logger.info(f"Destination explore agent running: {destination} - {query}")
    agent = await _get_or_create_explore_agent()
    response = await agent.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": f"请为我提供关于 {destination} 的以下信息：{query}",
                }
            ]
        }
    )
    final_message = response["messages"][-1].content

    formatted_result = (
        f"## {destination} 目的地信息\n\n"
        f"{final_message}\n\n"
        "---\n"
        "*信息来源：知识库优先，必要时补充实时搜索*"
    )
    return {"agent_results": [{"agent_name": "explore", "result": formatted_result}]}


_COMMON_CITY_ADCODES = {
    "北京": "110000",
    "上海": "310000",
    "广州": "440100",
    "深圳": "440300",
    "杭州": "330100",
    "南京": "320100",
    "武汉": "420100",
    "重庆": "500000",
    "成都": "510100",
    "西安": "610100",
    "长沙": "430100",
    "青岛": "370200",
    "厦门": "350200",
    "三亚": "460200",
    "苏州": "320500",
}


def resolve_city_adcode(destination: str) -> str | None:
    normalized = destination.strip()
    if normalized.isdigit() and len(normalized) == 6:
        return normalized
    return _COMMON_CITY_ADCODES.get(normalized)


async def _get_weather_tool():
    try:
        weather_tools = await get_weather_tools()
    except Exception as exc:
        app_logger.warning(f"Failed to load weather MCP tools: {exc}")
        return None

    for tool in weather_tools:
        if tool.name == "get_weather_forecast":
            return tool
    return weather_tools[0] if weather_tools else None


def _normalize_weather_payload(payload: object) -> dict:
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                return item
        return {}
    if isinstance(payload, dict):
        return payload
    return {"error": f"Unexpected weather payload type: {type(payload).__name__}"}


def _format_weather_summary(destination: str, payload: object) -> str:
    payload = _normalize_weather_payload(payload)
    if payload.get("error"):
        return (
            f"## {destination} 天气信息\n\n"
            f"暂时无法获取实时天气：{payload['error']}\n"
            "建议出发前再确认当地最新天气和景区开放情况。"
        )

    casts = payload.get("casts", [])[:3]
    if not casts:
        return (
            f"## {destination} 天气信息\n\n"
            "暂时没有可用的天气预报数据，建议稍后再试。"
        )

    lines = [f"## {destination} 天气信息", ""]
    for cast in casts:
        date = cast.get("date", "未知日期")
        day_weather = cast.get("dayweather", "未知")
        night_weather = cast.get("nightweather", "未知")
        day_temp = cast.get("daytemp", "?")
        night_temp = cast.get("nighttemp", "?")
        day_wind = cast.get("daywind", "未知")
        day_power = cast.get("daypower", "未知")
        lines.append(
            f"- {date}: 白天 {day_weather} / 夜间 {night_weather}，"
            f"{night_temp}-{day_temp}°C，风向 {day_wind}，风力 {day_power} 级"
        )

    lines.extend(
        [
            "",
            "建议：如果遇到降雨或高温，优先安排室内景点，室外行程尽量放到早晚。",
        ]
    )
    return "\n".join(lines)


async def weather_agent_node(state: dict) -> dict:
    destination = state["destination"]
    app_logger.info(f"Destination weather agent running for {destination}")

    tool = await _get_weather_tool()
    adcode = resolve_city_adcode(destination)

    if tool is None:
        result = (
            f"## {destination} 天气信息\n\n"
            "暂时无法获取实时天气：天气 MCP 工具当前不可用。"
        )
    elif adcode is None:
        result = (
            f"## {destination} 天气信息\n\n"
            "暂时无法将目的地解析成天气查询编码，请换成更具体的城市名称后再试。"
        )
    else:
        try:
            raw_payload = await tool.ainvoke({"city_adcode": adcode})
            payload = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
            result = _format_weather_summary(destination, payload)
        except Exception as exc:
            app_logger.warning(f"Weather MCP call failed for {destination}: {exc}")
            result = (
                f"## {destination} 天气信息\n\n"
                f"暂时无法获取实时天气：{exc}"
            )

    return {"agent_results": [{"agent_name": "weather", "result": result}]}


async def synthesizer_node(state: DestinationRouterState) -> dict:
    app_logger.info("Destination router synthesizing results")

    results = state["agent_results"]
    if not results:
        return {"final_report": "未找到相关信息。"}

    final_report = "\n\n".join(result["result"] for result in results)
    return {"final_report": final_report}


def create_destination_router():
    workflow = StateGraph(DestinationRouterState)

    workflow.add_node("classifier", classifier_node)
    workflow.add_node("explore", explore_agent_node)
    workflow.add_node("weather", weather_agent_node)
    workflow.add_node("synthesizer", synthesizer_node)

    workflow.add_edge(START, "classifier")
    workflow.add_conditional_edges("classifier", route_to_agents, ["explore", "weather"])
    workflow.add_edge("explore", "synthesizer")
    workflow.add_edge("weather", "synthesizer")
    workflow.add_edge("synthesizer", END)

    app = workflow.compile()
    app_logger.info("Destination router created")
    return app
