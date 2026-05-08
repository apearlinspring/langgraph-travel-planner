import re
from types import SimpleNamespace
from typing import Any, Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, ToolMessage

from app.core.state import TravelState
from app.core.store import get_user_memory_service
from app.core.workflow import INITIAL_PLANNING_STEP
from app.utils.llm_factory import get_model_compatibility
from app.utils.logger import app_logger


SELECTION_KEYWORDS = (
    "选第",
    "就这",
    "选这个",
    "确认",
    "锁定",
    "记录",
    "定这个",
    "就它",
)

DIRECT_QUERY_KEYWORDS = (
    "直接查",
    "真实",
    "不要只口头",
    "不要泛泛",
    "不要继续追问",
    "信息已经齐",
    "不用继续问",
)

REQUIREMENT_RECORD_KEYWORDS = (
    "记录",
    "整理需求",
    "整理一下",
    "开始推荐",
    "开始规划",
    "开始安排行程",
    "锁定需求",
    "确认需求",
)

DESTINATION_QUERY_KEYWORDS = (
    "景点",
    "玩法",
    "攻略",
    "天气",
    "气温",
    "适合吗",
    "推荐",
    "好玩吗",
    "值得去",
    "怎么安排",
)

DESTINATION_HINT_KEYWORDS = (
    "去",
    "到",
    "在",
    "那边",
    "这个地方",
    "目的地",
    "城市",
)


def _to_prompt_value(value: Any) -> Any:
    """Convert nested dicts into attribute-accessible objects for str.format()."""
    if isinstance(value, dict):
        return SimpleNamespace(**{key: _to_prompt_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return [_to_prompt_value(item) for item in value]
    return value


def _format_selected_accommodation(state_dict: dict[str, Any]) -> str:
    option = state_dict.get("selected_accommodation_option")
    if isinstance(option, dict) and option.get("name"):
        details = [str(option["name"])]
        if option.get("hotel_id"):
            details.append(f"酒店ID {option['hotel_id']}")
        if option.get("location"):
            details.append(str(option["location"]))
        if option.get("price_per_night"):
            details.append(f"{option['price_per_night']} 元/晚")
        return "，".join(details)

    accommodation_types = state_dict.get("selected_accommodation_types")
    if accommodation_types:
        return f"已确认住宿类型：{accommodation_types}"
    return "尚未确认具体酒店"


def _format_selected_transport(state_dict: dict[str, Any]) -> str:
    option = state_dict.get("selected_transport_option")
    if isinstance(option, dict) and option:
        parts: list[str] = []
        details = option.get("details")
        if details:
            parts.append(str(details))
        if option.get("departure_time") or option.get("arrival_time"):
            parts.append(
                f"{option.get('departure_time', '待确认')} -> {option.get('arrival_time', '待确认')}"
            )
        if option.get("duration"):
            parts.append(f"耗时 {option['duration']}")
        if option.get("price"):
            parts.append(f"参考价格 {option['price']} 元/人")
        if option.get("source"):
            parts.append(f"来源 {option['source']}")
        if parts:
            return "，".join(parts)

    selected_transport = state_dict.get("selected_transport")
    return str(selected_transport) if selected_transport else "尚未确认交通方案"


def _format_budget_summary(state_dict: dict[str, Any]) -> str:
    budget = state_dict.get("budget")
    if not isinstance(budget, dict) or not budget:
        return "尚未完成预算汇总"

    lines = []
    for label, key in [
        ("交通", "transport"),
        ("住宿", "accommodation"),
        ("餐饮", "food"),
        ("景点/体验", "attractions"),
        ("其他机动", "misc"),
        ("总计", "total"),
        ("人均", "per_person"),
    ]:
        value = budget.get(key)
        if isinstance(value, (int, float)):
            lines.append(f"{label}：{value:.2f} 元")
    assumptions = budget.get("assumptions") or []
    if assumptions:
        lines.append("关键假设：" + "；".join(str(item) for item in assumptions[:3]))
    return "；".join(lines) if lines else "预算已有记录，但明细不完整"


def _format_itinerary_summary(state_dict: dict[str, Any]) -> str:
    itinerary = state_dict.get("itinerary")
    if not isinstance(itinerary, list) or not itinerary:
        return "尚未生成行程"

    lines = []
    for day in itinerary[:5]:
        if not isinstance(day, dict):
            continue
        day_number = day.get("day_number", len(lines) + 1)
        theme = day.get("theme") or "当日安排"
        activities = day.get("activities") or []
        activity_text = "；".join(str(item) for item in activities[:2]) if activities else "活动待确认"
        lines.append(f"Day {day_number} {theme}：{activity_text}")
    if len(itinerary) > 5:
        lines.append(f"其余 {len(itinerary) - 5} 天按已生成行程执行")
    return "\n".join(lines) if lines else "行程已有记录，但明细不完整"


def _latest_human_text(request: ModelRequest) -> str:
    def latest_human_content(messages: list[Any]) -> Any:
        if not messages:
            return None
        latest = messages[-1]
        if isinstance(latest, HumanMessage):
            return latest.content
        if isinstance(latest, dict):
            role = latest.get("role") or latest.get("type")
            if role in {"user", "human"}:
                return latest.get("content")
        if getattr(latest, "type", None) == "human" or getattr(latest, "role", None) == "user":
            return getattr(latest, "content", None)
        return None

    content = latest_human_content(request.messages or [])
    latest_request_message = (request.messages or [None])[-1]
    if content is None and isinstance(latest_request_message, ToolMessage):
        return ""
    if content is None:
        state = request.state
        if hasattr(state, "get"):
            content = latest_human_content(state.get("messages") or [])
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return str(content)


def _recent_human_text(request: ModelRequest, limit: int = 4) -> str:
    def iter_human_messages(messages: list[Any]) -> list[str]:
        collected: list[str] = []
        for message in messages or []:
            content = None
            if isinstance(message, HumanMessage):
                content = message.content
            elif isinstance(message, dict):
                role = message.get("role") or message.get("type")
                if role in {"user", "human"}:
                    content = message.get("content")
            elif getattr(message, "type", None) == "human" or getattr(message, "role", None) == "user":
                content = getattr(message, "content", None)

            if content is None:
                continue
            collected.append(content if isinstance(content, str) else str(content))
        return collected[-limit:]

    messages = iter_human_messages(request.messages or [])
    if not messages:
        state = request.state
        if hasattr(state, "get"):
            messages = iter_human_messages(state.get("messages") or [])
    return "\n".join(item.strip() for item in messages if item and item.strip())


def _forced_tool_choice(
    current_step: str,
    latest_human_text: str,
    request: ModelRequest | None = None,
) -> str | None:
    text = latest_human_text.strip()
    if not text:
        return None

    if current_step == "requirement_collection" and _should_prioritize_requirement_record(text):
        return "record_requirement_tool"

    if (
        current_step == "requirement_collection"
        and request is not None
        and _should_finalize_requirement_after_followup(request, text)
    ):
        return "record_requirement_tool"

    if current_step == "requirement_collection" and _should_prioritize_destination_query(text):
        return "query_destination_info"

    if any(keyword in text for keyword in SELECTION_KEYWORDS):
        return None

    if current_step == "accommodation_planning":
        hotel_keywords = ("酒店", "住宿", "住")
        if any(keyword in text for keyword in DIRECT_QUERY_KEYWORDS) and any(
            keyword in text for keyword in hotel_keywords
        ):
            return "query_hotel_options"

    if current_step == "transport_planning":
        transport_keywords = ("飞机", "航班", "高铁", "火车", "自驾", "交通")
        query_intent_keywords = ("查", "查询", "看看", "推荐", "方案", "有没有", "多少")
        if any(keyword in text for keyword in DIRECT_QUERY_KEYWORDS) or (
            any(keyword in text for keyword in transport_keywords)
            and any(keyword in text for keyword in query_intent_keywords)
        ):
            return "query_transport_options"

    return None


def _tool_choice_instruction(tool_name: str) -> str:
    return (
        f"本轮优先直接调用工具 `{tool_name}`，不要先继续追问。"
        " 如果工具返回候选结果，再基于结果继续回答。"
    )


def _tool_names(tools: list[Any]) -> set[str]:
    names: set[str] = set()
    for tool in tools:
        name = getattr(tool, "name", None)
        if isinstance(name, str) and name:
            names.add(name)
        elif isinstance(tool, str) and tool:
            names.add(tool)
    return names


def _record_requirement_instruction() -> str:
    return (
        "如果用户这条消息已经提供了出发地、日期、天数、人数、预算和主要风格，"
        "并且明确要求你整理需求、记录需求或开始推荐，"
        "那就把这条消息视为一次显式确认。"
        " 你可以先用一句简短摘要确认你的理解，但必须在本轮直接调用 `record_requirement_tool`。"
        " 不要为了补充非关键偏好而继续追问，也不要把记录动作拖到下一轮。"
    )


def _destination_query_instruction() -> str:
    return (
        "如果用户这轮已经在直接询问某个具体目的地的景点、玩法、天气或是否值得去，"
        "就先直接调用 `query_destination_info` 回答这个问题。"
        " 优先从用户消息里提取明确目的地名称作为 destination，query 里保留用户原始问题。"
        " 回答完后，只需要顺带说明如果用户愿意继续做完整旅行规划，后面还可以继续补日期、人数、预算，并最终生成完整旅游报告。"
        " 不要因为当前还在需求收集阶段，就先强行追问一整套表单式信息。"
    )


def _confirmed_destination_name(state_dict: dict[str, Any], text: str) -> str | None:
    if not any(keyword in text for keyword in SELECTION_KEYWORDS):
        return None

    candidate_names: list[str] = []
    for option in state_dict.get("destination_options") or []:
        name = str(option.get("name") or "").strip()
        if name and name not in candidate_names:
            candidate_names.append(name)

    user_requirement = state_dict.get("user_requirement") or {}
    if isinstance(user_requirement, dict):
        destination = str(user_requirement.get("destination") or "").strip()
        if destination and destination not in candidate_names:
            candidate_names.append(destination)

    for name in candidate_names:
        if name and name in text:
            return name

    if len(candidate_names) == 1:
        return candidate_names[0]

    return None


def _destination_selection_instruction(destination: str) -> str:
    return (
        f"用户本轮已经确认目的地为 `{destination}`。"
        " 你必须在本轮直接调用 `select_destination_tool` 记录该目的地，"
        " 不要继续停留在目的地比较阶段，也不要重复追问是否确认。"
        " 记录后再继续衔接交通规划。"
    )


def _has_date_hint(text: str) -> bool:
    patterns = (
        r"\d{4}-\d{1,2}-\d{1,2}",
        r"\d{4}年\d{1,2}月\d{1,2}日",
        r"\d{1,2}月\d{1,2}日",
        r"[一二两三四五六七八九十\d]+月(?:上旬|中旬|下旬|月初|月底)?",
        r"(这周|本周|下周|下下周|这月|本月|下个月|周末|小长假|暑假|寒假|春节|五一|端午|中秋|国庆)",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _has_days_hint(text: str) -> bool:
    return bool(
        re.search(r"\d+\s*天", text)
        or re.search(r"[一二两三四五六七八九十]+\s*天", text)
        or re.search(r"[一二两三四五六七八九十\d]+天[一二两三四五六七八九十\d]+夜", text)
    )


def _has_budget_hint(text: str) -> bool:
    return bool(
        re.search(r"预算[^\n，。；]{0,8}\d", text)
        or re.search(r"\d+(?:\.\d+)?\s*(?:万|元)", text)
        or re.search(r"(总预算|总共预算|人均预算|预算希望控制在)\s*\d", text)
    )


def _has_people_hint(text: str) -> bool:
    adult_or_child = ("大人", "成人", "孩子", "儿童", "一家", "亲子", "同行人数")
    return bool(
        any(keyword in text for keyword in adult_or_child) and re.search(r"\d", text)
    ) or bool(re.search(r"(\d+|[一二两三四五六七八九十]+)\s*人", text))


def _has_route_hint(text: str) -> bool:
    route_keywords = ("从", "出发", "去", "目的地", "想去")
    city_keywords = (
        "北京",
        "上海",
        "广州",
        "深圳",
        "杭州",
        "南京",
        "成都",
        "重庆",
        "西安",
        "武汉",
        "长沙",
        "苏州",
        "厦门",
        "青岛",
        "三亚",
    )
    return (
        any(keyword in text for keyword in route_keywords)
        and sum(1 for city in city_keywords if city in text) >= 1
    )


def _has_style_hint(text: str) -> bool:
    style_keywords = (
        "亲子",
        "休闲",
        "休息",
        "放松",
        "文化",
        "人文",
        "自然",
        "美食",
        "冒险",
        "情侣",
        "环球影城",
        "主题乐园",
        "博物馆",
    )
    return any(keyword in text for keyword in style_keywords)


def _should_prioritize_destination_query(text: str) -> bool:
    if not any(keyword in text for keyword in DESTINATION_QUERY_KEYWORDS):
        return False

    if "天气" in text or "气温" in text:
        return True

    if any(keyword in text for keyword in DESTINATION_HINT_KEYWORDS):
        return True

    return _has_route_hint(text)


def _should_prioritize_requirement_record(text: str) -> bool:
    if not any(keyword in text for keyword in REQUIREMENT_RECORD_KEYWORDS):
        return False

    checks = [
        _has_route_hint(text),
        _has_date_hint(text),
        _has_days_hint(text),
        _has_people_hint(text),
        _has_budget_hint(text),
        _has_style_hint(text),
    ]
    return sum(1 for item in checks if item) >= 5


def _should_finalize_requirement_after_followup(
    request: ModelRequest,
    text: str,
) -> bool:
    if not text.strip():
        return False

    followup_keywords = (
        "继续规划",
        "继续吧",
        "就按这个",
        "按这个来",
        "开始规划",
        "可以了",
        "没问题",
    )
    if not any(keyword in text for keyword in SELECTION_KEYWORDS + followup_keywords):
        return False

    combined_text = _recent_human_text(request)
    checks = [
        _has_route_hint(combined_text),
        _has_date_hint(combined_text),
        _has_days_hint(combined_text),
        _has_people_hint(combined_text),
        _has_budget_hint(combined_text),
        _has_style_hint(combined_text),
    ]
    return sum(1 for item in checks if item) >= 5


class StepConfigMiddleware(AgentMiddleware):
    """
    步骤配置中间件，根据 current_step 动态配置 Agent。
    """

    def __init__(self, step_config: dict):
        self._step_config = step_config

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        state: TravelState = request.state
        state_dict = dict(state) if hasattr(state, "items") else {}
        current_step = state.get("current_step", INITIAL_PLANNING_STEP)
        user_id = state.get("user_id")

        app_logger.info(f"用户ID: {user_id}")
        app_logger.info(f"当前步骤: {current_step}")

        if current_step not in self._step_config:
            app_logger.error(f"未知步骤: {current_step}")
            raise ValueError(f"未知步骤: {current_step}")

        step_config = self._step_config[current_step]

        for required_field in step_config["requires"]:
            if required_field not in state or state[required_field] is None:
                error_msg = f"步骤 {current_step} 需要完整状态，{required_field} 未设置"
                app_logger.error(error_msg)
                raise ValueError(error_msg)

        memory_prompt = ""
        if user_id:
            try:
                service = await get_user_memory_service()
                memory_prompt = await service.format_memory_for_prompt(user_id)
                if memory_prompt:
                    app_logger.info(f"已加载用户长期记忆: {user_id}")
                else:
                    app_logger.info(f"用户暂无长期记忆: {user_id}")
            except Exception as exc:
                app_logger.warning(f"加载长期记忆失败: {exc}")

        try:
            user_requirement = state_dict.get("user_requirement") or {}
            if isinstance(user_requirement, dict):
                state_dict.setdefault("origin_city", user_requirement.get("departure_city"))
                state_dict.setdefault("destination", user_requirement.get("destination"))
            state_dict.setdefault(
                "selected_accommodation_summary",
                _format_selected_accommodation(state_dict),
            )
            state_dict.setdefault(
                "selected_transport_summary",
                _format_selected_transport(state_dict),
            )
            state_dict.setdefault("budget_summary", _format_budget_summary(state_dict))
            state_dict.setdefault("itinerary_summary", _format_itinerary_summary(state_dict))

            state_dict["user_memory"] = memory_prompt
            prompt_values = {key: _to_prompt_value(value) for key, value in state_dict.items()}
            system_prompt = step_config["prompt"].format_map(prompt_values)

            if memory_prompt:
                system_prompt = f"{system_prompt}\n\n{memory_prompt}"

        except (KeyError, AttributeError) as exc:
            app_logger.warning(f"提示词变量缺失: {exc}，使用原始模板")
            system_prompt = step_config["prompt"]

        override_kwargs = {
            "system_prompt": system_prompt,
            "tools": step_config["tools"],
        }

        compatibility = get_model_compatibility()
        latest_human_text = _latest_human_text(request)
        available_tool_names = _tool_names(step_config["tools"])
        confirmed_destination = (
            _confirmed_destination_name(state_dict, latest_human_text)
            if current_step == "destination_recommendation"
            else None
        )
        forced_tool = (
            "select_destination_tool"
            if confirmed_destination
            else _forced_tool_choice(current_step, latest_human_text, request)
        )
        if forced_tool and forced_tool not in available_tool_names:
            forced_tool = None
        if forced_tool:
            if compatibility.supports_forced_tool_choice:
                override_kwargs["tool_choice"] = forced_tool
                app_logger.info(f"本轮强制优先调用工具: {forced_tool}")
            else:
                tool_instruction = (
                    _destination_selection_instruction(confirmed_destination)
                    if forced_tool == "select_destination_tool" and confirmed_destination
                    else
                    _destination_query_instruction()
                    if forced_tool == "query_destination_info"
                    else
                    _record_requirement_instruction()
                    if forced_tool == "record_requirement_tool"
                    else _tool_choice_instruction(forced_tool)
                )
                override_kwargs["system_prompt"] = (
                    f"{system_prompt}\n\n{tool_instruction}"
                )
                app_logger.info(f"模型不支持强制 tool_choice，改为提示词引导: {forced_tool}")

        modified_request = request.override(**override_kwargs)
        app_logger.info(f"已注入步骤配置，工具数量: {len(step_config['tools'])}")
        return await handler(modified_request)


async def create_step_config_middleware() -> StepConfigMiddleware:
    """
    工厂函数：创建步骤配置中间件。
    """
    from app.agents.handoffs.step_config import get_step_config

    step_config = await get_step_config()
    return StepConfigMiddleware(step_config)
