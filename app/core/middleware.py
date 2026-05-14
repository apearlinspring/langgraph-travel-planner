import re
import time
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any, Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, ToolMessage

from app.core.context_pack import abuild_context_pack
from app.core.intent import PlanningModeDecision, TravelIntent, detect_travel_intent, resolve_planning_mode
from app.core.observability import build_observability_context
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

CROSS_STEP_VERIFY_KEYWORDS = (
    "查",
    "查询",
    "查证",
    "核实",
    "验证",
    "真实",
    "具体",
    "安排",
)

CROSS_STEP_TRANSPORT_KEYWORDS = ("交通", "高铁", "火车", "航班", "飞机", "自驾")
CROSS_STEP_HOTEL_KEYWORDS = ("住宿", "酒店", "住哪里", "住哪", "民宿")

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

COMMON_CITY_NAMES = (
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
    "桂林",
    "丽江",
    "大理",
    "昆明",
    "张家界",
)

ASSUMED_REQUIREMENT_DEPARTURE_DAYS = 30

AGENCY_INTERNAL_TOOL_NAMES = frozenset(
    {
        "search_agency_product_templates",
        "search_agency_service_sop",
        "search_agency_pricing_rules",
        "search_agency_risk_playbook",
        "search_agency_report_standards",
    }
)

MODE_MANAGEMENT_TOOL_NAMES = frozenset(
    {
        "set_planning_mode_tool",
        "confirm_planning_mode_tool",
        "record_evidence_bundle_tool",
    }
)

INTENT_INTERNAL_TOOL_ALLOWLIST = {
    "pricing_query": frozenset({"search_agency_pricing_rules"}),
    "risk_query": frozenset({"search_agency_risk_playbook"}),
    "agency_plan_query": frozenset(
        {
            "search_agency_product_templates",
            "search_agency_service_sop",
            "search_agency_risk_playbook",
        }
    ),
}

ONE_SHOT_TOOLS_AFTER_CALL = frozenset(
    {
        "record_requirement_tool",
        "query_destination_info",
        "search_travel_info",
        "search_food_recommendations",
        "query_hotel_options",
        "query_transport_options",
        "select_destination_tool",
        "select_transport_tool",
        "select_accommodation_tool",
        "select_food_tool",
        "generate_itinerary_tool",
        "summarize_budget_tool",
        "generate_order_tool",
    }
)

FORCE_NARROW_TOOL_NAMES = frozenset(
    {
        "record_requirement_tool",
        "query_destination_info",
        "search_travel_info",
        "search_food_recommendations",
        "query_hotel_options",
        "query_transport_options",
        "select_destination_tool",
        "select_transport_tool",
        "select_accommodation_tool",
        "select_food_tool",
        "generate_itinerary_tool",
        "summarize_budget_tool",
        "generate_order_tool",
    }
)

DATE_TOOL_NAMES = frozenset({"get-current-date", "getTodayDate"})
DESTINATION_REFRESH_TOOL_NAMES = frozenset(
    {"query_destination_info", "search_travel_info", "search_food_recommendations"}
)
REQUIREMENT_MEMORY_TOOL_NAMES = frozenset(
    {
        "update_travel_style_tool",
        "update_dietary_restriction_tool",
        "update_food_preference_tool",
        "add_travel_record_tool",
        "update_accommodation_preference_tool",
    }
)

RELATIVE_DATE_TOOL_KEYWORDS = (
    "今天",
    "明天",
    "后天",
    "大后天",
    "本周",
    "这周",
    "下周",
    "下下周",
    "周末",
    "月初",
    "月底",
    "下个月",
    "春节",
    "五一",
    "端午",
    "中秋",
    "国庆",
    "暑假",
    "寒假",
    "元旦",
    "清明",
    "劳动节",
)

FIRST_TURN_SLOW_INTENT_KEYWORDS = (
    "酒店",
    "住宿",
    "民宿",
    "交通",
    "高铁",
    "火车",
    "航班",
    "飞机",
    "自驾",
    "天气",
    "气温",
    "下雨",
    "雨季",
    "台风",
    "暴雨",
    "风险",
    "避坑",
    "Plan B",
    "plan b",
    "兜底",
    "查不到",
    "待核验",
    "老人",
    "父母",
    "长辈",
    "银发",
    "走不动",
)

FIRST_TURN_AGENCY_PLAN_KEYWORDS = (
    "旅行社方案",
    "旅行社顾问方案",
    "旅行社帮我",
    "按旅行社",
    "顾问方案",
    "省心方案",
    "省心安排",
    "省心规划",
    "不用我操心",
    "不想自己操心",
)

FINAL_REPORT_REQUEST_KEYWORDS = (
    "最终报告",
    "旅游报告",
    "旅行报告",
    "旅游规划报告",
    "旅行规划报告",
    "规划报告",
    "完整报告",
    "生成报告",
    "最终方案",
    "完整方案",
    "report_data",
    "生成订单",
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


def _message_has_human_role(message: Any) -> bool:
    if isinstance(message, HumanMessage):
        return True
    if isinstance(message, dict):
        role = message.get("role") or message.get("type")
        return role in {"user", "human"}
    return getattr(message, "type", None) == "human" or getattr(message, "role", None) == "user"


def _message_has_assistant_text(message: Any) -> bool:
    content = None
    if isinstance(message, dict):
        role = message.get("role") or message.get("type")
        if role not in {"assistant", "ai"}:
            return False
        content = message.get("content")
    elif getattr(message, "type", None) in {"ai", "assistant"} or getattr(message, "role", None) in {
        "ai",
        "assistant",
    }:
        content = getattr(message, "content", None)
    return bool(str(content or "").strip())


def _request_or_state_messages(request: ModelRequest) -> list[Any]:
    messages = list(request.messages or [])
    if messages:
        return messages
    state = request.state
    if hasattr(state, "get"):
        return list(state.get("messages") or [])
    return []


def _is_first_user_turn_without_assistant_text(request: ModelRequest) -> bool:
    messages = _request_or_state_messages(request)
    if not messages:
        return False

    human_count = sum(1 for message in messages if _message_has_human_role(message))
    if human_count != 1:
        return False
    return not any(_message_has_assistant_text(message) for message in messages)


def _tool_names_from_message(message: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(message, ToolMessage):
        name = getattr(message, "name", None)
        if name:
            names.add(str(name))

    if isinstance(message, dict):
        if message.get("type") == "tool" and message.get("name"):
            names.add(str(message["name"]))
        tool_calls = message.get("tool_calls") or []
    else:
        tool_calls = getattr(message, "tool_calls", None) or []

    for tool_call in tool_calls:
        if isinstance(tool_call, dict):
            name = tool_call.get("name") or tool_call.get("function", {}).get("name")
        else:
            name = getattr(tool_call, "name", None)
        if name:
            names.add(str(name))
    return names


def _latest_message_is_tool_result(request: ModelRequest) -> bool:
    messages = list(request.messages or [])
    if not messages:
        state = request.state
        if hasattr(state, "get"):
            messages = list(state.get("messages") or [])
    if not messages:
        return False
    latest = messages[-1]
    if isinstance(latest, ToolMessage):
        return True
    if isinstance(latest, dict):
        return (latest.get("role") or latest.get("type")) == "tool"
    return getattr(latest, "type", None) == "tool" or getattr(latest, "role", None) == "tool"


def _latest_tool_result_names(request: ModelRequest) -> set[str]:
    messages = list(request.messages or [])
    if not messages:
        state = request.state
        if hasattr(state, "get"):
            messages = list(state.get("messages") or [])
    if not messages:
        return set()
    latest = messages[-1]
    is_tool_result = False
    if isinstance(latest, ToolMessage):
        is_tool_result = True
    elif isinstance(latest, dict):
        is_tool_result = (latest.get("role") or latest.get("type")) == "tool"
    else:
        is_tool_result = (
            getattr(latest, "type", None) == "tool"
            or getattr(latest, "role", None) == "tool"
        )
    if not is_tool_result:
        return set()
    return _tool_names_from_message(latest)


def _recent_tool_names_since_latest_human(request: ModelRequest) -> set[str]:
    messages = list(request.messages or [])
    if not messages:
        state = request.state
        if hasattr(state, "get"):
            messages = list(state.get("messages") or [])
    if not messages:
        return set()

    latest_human_index = None
    for index in range(len(messages) - 1, -1, -1):
        if _message_has_human_role(messages[index]):
            latest_human_index = index
            break
    if latest_human_index is None:
        return set()

    names: set[str] = set()
    for message in messages[latest_human_index + 1:]:
        names.update(_tool_names_from_message(message))
    return names


def _tool_repeat_instruction(current_step: str, recent_tool_names: set[str]) -> str:
    if current_step == "accommodation_planning" and "query_hotel_options" in recent_tool_names:
        return (
            "本轮已经执行过 `query_hotel_options`。不要在同一轮再次调用酒店查询；"
            "请直接基于已有工具结果总结候选，或说明本次没有查到并给出下一轮可放宽的方向。"
        )
    if current_step == "transport_planning" and "query_transport_options" in recent_tool_names:
        return (
            "本轮已经执行过 `query_transport_options`。不要在同一轮再次调用交通查询；"
            "请直接基于已有工具结果做比较和推荐。"
        )
    repeated_one_shot_tools = sorted(ONE_SHOT_TOOLS_AFTER_CALL & recent_tool_names)
    if repeated_one_shot_tools:
        return (
            "本轮已经完成这些一次性工具调用："
            f"{', '.join(f'`{name}`' for name in repeated_one_shot_tools)}。"
            "不要在同一轮再次调用它们；请基于已有工具结果继续总结、推荐或推进下一步。"
        )
    return ""


def _has_nonempty_list(value: Any) -> bool:
    return isinstance(value, list) and any(item for item in value)


def _has_destination_candidates(state_dict: dict[str, Any]) -> bool:
    return _has_nonempty_list(state_dict.get("destination_options"))


def _has_selected_transport(state_dict: dict[str, Any]) -> bool:
    return bool(
        state_dict.get("selected_transport")
        or state_dict.get("selected_transport_option")
    )


def _has_accommodation_candidates(state_dict: dict[str, Any]) -> bool:
    return _has_nonempty_list(state_dict.get("accommodation_options"))


def _has_selected_accommodation(state_dict: dict[str, Any]) -> bool:
    return bool(
        state_dict.get("selected_accommodation_option")
        or state_dict.get("selected_accommodation_types")
    )


def _accommodation_memory_is_stable(text: str) -> bool:
    if not text.strip():
        return False
    negative_stable_keywords = (
        "不要记成长期",
        "别记成长期",
        "不要作为长期",
        "不作为长期",
        "不是长期",
        "无需记住",
        "不用记住",
        "不要记住",
        "别记住",
    )
    if any(keyword in text for keyword in negative_stable_keywords):
        return False
    stable_keywords = (
        "记住",
        "请记",
        "以后",
        "每次",
        "一直",
        "长期",
        "我习惯",
        "常住",
        "固定偏好",
    )
    temporary_keywords = (
        "这次",
        "本次",
        "这趟",
        "这回",
        "当前行程",
        "本轮",
    )
    if any(keyword in text for keyword in temporary_keywords) and not any(
        keyword in text for keyword in stable_keywords
    ):
        return False
    return any(keyword in text for keyword in stable_keywords)


def _allowed_requirement_memory_tools(text: str) -> set[str]:
    """Return long-term memory tools that are safe to expose for this utterance."""
    if not text.strip():
        return set()

    negative_keywords = (
        "不要记成长期",
        "别记成长期",
        "不要作为长期",
        "不作为长期",
        "不是长期",
        "无需记住",
        "不用记住",
        "不要记住",
        "别记住",
    )
    if any(keyword in text for keyword in negative_keywords):
        return set()

    allowed: set[str] = set()
    history_keywords = ("去过", "以前去", "之前去", "上次去", "来过", "玩过")
    if any(keyword in text for keyword in history_keywords):
        allowed.add("add_travel_record_tool")

    stable_keywords = (
        "请记住",
        "帮我记住",
        "记住我",
        "以后",
        "每次",
        "一直",
        "长期",
        "我习惯",
        "固定偏好",
        "常住",
    )
    has_stable_scope = any(keyword in text for keyword in stable_keywords)
    if has_stable_scope:
        allowed.update(
            {
                "update_travel_style_tool",
                "update_dietary_restriction_tool",
                "update_food_preference_tool",
                "update_accommodation_preference_tool",
            }
        )

    safety_keywords = ("过敏", "严重忌口", "不能吃", "清真", "素食")
    temporary_keywords = ("这次", "本次", "这趟", "这回", "当前行程", "本轮")
    if any(keyword in text for keyword in safety_keywords) and not any(
        keyword in text for keyword in temporary_keywords
    ):
        allowed.add("update_dietary_restriction_tool")

    return allowed


def _temporary_requirement_memory_instruction() -> str:
    return (
        "本轮需求收集中的轻松、少走路、美食、住宿、口味等描述，"
        "默认都是当前行程条件，不要调用长期记忆工具。"
        "请把它们写入本轮需求、特殊需求或后续查询参数；"
        "只有用户明确说“请记住/以后/每次/我一直/我过敏”"
        "或提到已经去过的真实历史旅行时，才写入长期记忆。"
    )


def _destination_candidate_instruction() -> str:
    return (
        "本轮已经拿到目的地候选或目的地信息。"
        " 在用户明确确认前，不要调用 `select_destination_tool`，"
        " 也不要再次调用 `query_destination_info` 或搜索工具刷新同类信息；"
        "请直接基于已有候选做简短总结，并等待用户确认目的地。"
    )


def _transport_query_result_instruction(*, allow_selection: bool = False) -> str:
    if allow_selection:
        return (
            "本轮已经完成真实交通查询。"
            " 用户已经明确授权按推荐结果直接记录交通方案，"
            "请基于已有交通候选选择最省心或最符合用户偏好的方案，"
            "并调用 `select_transport_tool` 记录。"
            "不要再次调用 `query_transport_options` 刷新同类信息。"
        )
    return (
        "本轮已经完成真实交通查询。"
        " 请直接基于已有交通候选做简短总结和推荐，"
        "不要在同一轮继续调用 `select_transport_tool` 抢先记录；"
        "等待用户确认具体交通方式或候选后，再记录交通方案。"
    )


def _transport_selection_fallback_instruction() -> str:
    return (
        "当前还没有记录交通方案，但用户已经要求按推荐方式继续推进，"
        "或后续消息已经进入住宿确认。"
        " 本轮必须先调用 `select_transport_tool` 记录交通，不要继续追问出发地，"
        "也不要跨过交通去查询或记录住宿。"
        " 如果缺少出发地或具体班次，就把交通类型按省心和时间合理优先记录为 train，"
        "details 写明“出发地待确认，真实班次和价格待二次核验”。"
    )


def _accommodation_candidate_instruction() -> str:
    return (
        "当前已经有酒店候选或住宿查询结果。"
        " 不要再次调用 `query_hotel_options`，也不要把本次住宿条件写入长期住宿记忆；"
        "请直接从已有候选里选择最符合省心、干净、动线方便的方案，"
        "并调用 `select_accommodation_tool` 记录。"
        " 如果没有合适的具体酒店，也可以记录住宿类型/区域，并把真实价格标注为待核验。"
    )


def _temporary_accommodation_instruction() -> str:
    return (
        "本轮住宿偏好属于当前行程条件，不是长期稳定偏好。"
        " 不要调用 `update_accommodation_preference_tool`；"
        "请把这些偏好作为酒店查询或住宿选择参数使用。"
    )


def _post_transport_accommodation_instruction() -> str:
    return (
        "本轮刚刚完成交通方案记录。"
        " 不要在同一轮继续调用酒店查询或住宿选择工具，避免把交通确认轮扩成长工具链；"
        "请先简短说明交通已记录，住宿会在下一条住宿确认消息中继续处理。"
    )


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


def _cross_step_verification_tools(text: str) -> list[str]:
    """识别用户一口气要求核验交通和住宿的复合场景。"""
    if not text.strip():
        return []

    if not any(keyword in text for keyword in CROSS_STEP_VERIFY_KEYWORDS):
        return []

    requested_tools: list[str] = []
    if any(keyword in text for keyword in CROSS_STEP_TRANSPORT_KEYWORDS):
        requested_tools.append("query_transport_options")
    if any(keyword in text for keyword in CROSS_STEP_HOTEL_KEYWORDS):
        requested_tools.append("query_hotel_options")
    return requested_tools


def _cross_step_verification_instruction(tool_names: list[str]) -> str:
    if len(tool_names) >= 2:
        return (
            "本轮用户同时要求核验交通和住宿。"
            " 如果出发地、目的地、日期、人数和预算上下文已经存在，"
            " 请优先调用 `query_transport_options` 和 `query_hotel_options` 获取真实候选；"
            " 不要只用公开攻略、搜索结果或经验估算替代真实交通/酒店候选。"
            " 如果两个工具都可用，建议先查交通，再查住宿。"
        )

    if "query_transport_options" in tool_names:
        return _tool_choice_instruction("query_transport_options")
    if "query_hotel_options" in tool_names:
        return _tool_choice_instruction("query_hotel_options")
    return ""


def _tool_names(tools: list[Any]) -> set[str]:
    names: set[str] = set()
    for tool in tools:
        name = getattr(tool, "name", None)
        if isinstance(name, str) and name:
            names.add(name)
        elif isinstance(tool, str) and tool:
            names.add(tool)
    return names


def _exclude_tools_by_name(tools: list[Any], excluded_names: set[str] | frozenset[str]) -> list[Any]:
    return [
        tool
        for tool in tools
        if (
            getattr(tool, "name", tool if isinstance(tool, str) else None)
            not in excluded_names
        )
    ]


def _keep_tools_by_name(tools: list[Any], kept_names: set[str] | frozenset[str]) -> list[Any]:
    return [
        tool
        for tool in tools
        if (
            getattr(tool, "name", tool if isinstance(tool, str) else None)
            in kept_names
        )
    ]


def _find_tool_by_name(step_config: dict[str, Any], tool_name: str) -> Any | None:
    for config in step_config.values():
        for tool in config.get("tools", []):
            name = getattr(tool, "name", None)
            if name == tool_name or tool == tool_name:
                return tool
    return None


def _append_tools_by_name(
    tools: list[Any],
    step_config: dict[str, Any],
    tool_names: set[str] | frozenset[str],
) -> list[Any]:
    available_names = _tool_names(tools)
    updated_tools = list(tools)
    for tool_name in tool_names:
        if tool_name in available_names:
            continue
        extra_tool = _find_tool_by_name(step_config, tool_name)
        if extra_tool is not None:
            updated_tools.append(extra_tool)
            available_names.add(tool_name)
    return updated_tools


def _state_value_ready(value: Any) -> bool:
    return value not in (None, "", [], {})


def _can_generate_final_report(state_dict: dict[str, Any]) -> bool:
    user_requirement = state_dict.get("user_requirement") or {}
    if not isinstance(user_requirement, dict) or not _state_value_ready(user_requirement):
        return False

    destination = state_dict.get("selected_destination") or user_requirement.get("destination")
    if not _state_value_ready(destination):
        return False

    if _state_value_ready(state_dict.get("itinerary")) and _state_value_ready(state_dict.get("budget")):
        return True

    people_count = (
        (user_requirement.get("adult_count") or 0)
        + (user_requirement.get("children_count") or 0)
    )
    has_people = people_count > 0 or _state_value_ready(user_requirement.get("total_people"))
    has_days = _state_value_ready(user_requirement.get("travel_days"))
    has_budget = (
        _state_value_ready(user_requirement.get("budget_min"))
        or _state_value_ready(user_requirement.get("budget_max"))
        or _state_value_ready(user_requirement.get("budget_level"))
    )
    return has_days and has_people and has_budget


def _preferred_tool_for_intent(intent: TravelIntent, state_dict: dict[str, Any]) -> str | None:
    if intent.name in {"final_report", "export_report"}:
        return "generate_order_tool" if _can_generate_final_report(state_dict) else None
    return intent.preferred_tool


def _intent_instruction(
    intent: TravelIntent,
    state_dict: dict[str, Any],
    current_step: str,
) -> str:
    if intent.name == "unknown":
        return ""

    if intent.name == "hotel_query":
        return (
            "本轮用户的主要意图是查询住宿/酒店候选。"
            " 如果目的地、日期、人数等上下文已经存在，请优先调用 `query_hotel_options`，"
            " 不要退回泛泛区域建议，也不要只用公开攻略替代真实酒店候选。"
        )

    if intent.name == "transport_query":
        return (
            "本轮用户的主要意图是查询或对比交通方案。"
            " 如果出发地、目的地和日期上下文已经存在，请优先调用 `query_transport_options`，"
            " 并把不同交通方式的耗时、费用、稳定性和适配理由讲清楚。"
        )

    if intent.name == "final_report":
        if _can_generate_final_report(state_dict):
            return (
                "本轮用户明确要求生成最终旅游规划报告。"
                " 当前已有生成报告所需的核心信息，必须优先调用 `generate_order_tool`，"
                " 并以工具返回的 report 作为正文，不要手写、压缩或删减正式报告章节。"
                " 如果行程或预算尚未完整落库，工具会生成带待核验项的结构化报告。"
            )
        return (
            "本轮用户明确要求生成最终旅游规划报告，但当前状态还未具备正式生成条件。"
            " 不要手写伪最终报告，也不要假装已经完成结构化报告。"
            " 请先用简短方式说明还缺哪些关键确认，或继续推进当前阶段补齐缺口。"
        )

    if intent.name == "export_report":
        if _can_generate_final_report(state_dict):
            return (
                "本轮用户想导出或保存报告。"
                " 如果尚未生成正式报告，请先调用 `generate_order_tool` 生成结构化报告；"
                " 如果行程或预算尚未完整落库，工具会先补齐带待核验项的报告数据；"
                " 如果已经有正式报告，则说明前端导出入口会基于报告内容导出。"
            )
        return (
            "本轮用户想导出或保存报告，但正式报告尚未具备生成条件。"
            " 不要编造 PDF/图片下载结果，请先补齐最终报告所需信息。"
        )

    if intent.name == "map_route_query":
        return (
            "本轮用户关注地图、路线或分日路线可视化。"
            " 回复时必须保留可解析的路线节点，例如 Day 1：酒店 -> 景点A -> 餐厅；"
            " 如果还没有完整日程，请先说明当前只能生成轻量路线草图，后续完整日程会补齐地图路线。"
        )

    if intent.name == "agency_plan_query":
        return (
            "本轮用户倾向旅行社省心方案或成熟产品路线。"
            " 请优先参考内部产品模板、服务标准和风险避坑经验，把它自然转化为方案依据；"
            " 不要暴露内部知识库、RAG 或工具名，也不要承诺真实库存、锁价或支付能力。"
        )

    if intent.name == "free_planning_query":
        return (
            "本轮用户倾向自由行/自助规划。"
            " 回复应保持中立实用，重点给路线、预算、住宿区域和避坑建议；"
            " 不要把旅行社方案硬推给用户。"
        )

    if intent.name == "pricing_query":
        return (
            "本轮用户关注报价、费用包含或预算依据。"
            " 请优先参考内部报价规则，清楚区分已确认价格、估算项和待核验项；"
            " 不要把估算价格说成真实锁价。"
        )

    if intent.name == "risk_query":
        return (
            "本轮用户关注风险、避坑、预约或 Plan B。"
            " 请优先参考内部风险手册，给出具体、温和、可执行的提醒；"
            " 不要制造焦虑，也不要编造实时开放和库存情况。"
        )

    if intent.name == "progress_check":
        return (
            "本轮用户在询问当前规划进度。"
            " 请优先调用 `check_current_progress` 或用当前状态简短说明已完成和待补齐内容，"
            " 不要顺势生成新的长篇规划。"
        )

    if intent.name == "destination_query":
        return (
            "本轮用户关注目的地、景点或玩法。"
            " 请优先回答目的地问题；只有用户明确要求完整规划时，才继续推进完整流程。"
        )

    return ""


def _planning_mode_instruction(decision: PlanningModeDecision) -> str:
    if decision.needs_confirmation:
        return (
            "本轮用户的规划模式表达不够明确。"
            " 请先用一句话确认：用户更希望按自由行攻略自己决策，还是按旅行社顾问方案省心安排；"
            " 在确认前不要默认切到旅行社方案，也不要主动使用内部产品模板做推销式表达。"
        )

    if decision.mode == "agency_plan":
        return (
            "当前规划模式：旅行社顾问方案。"
            " 你要像真实旅行社顾问一样，把托付诉求转化为成熟路线、服务节奏、预算依据和风险预案；"
            " 可以自然参考内部产品模板、服务标准、报价规则和风险经验，但不要暴露内部资料、RAG 或工具名。"
        )

    if decision.mode == "free_planning":
        return (
            "当前规划模式：自由规划。"
            " 回复保持中立实用，重点帮助用户自己完成路线、交通、住宿区域、预算和避坑判断；"
            " 不要主动推旅行社产品或省心套餐，只有用户明确询问报价、风险或托付式服务时才切换相应表达。"
        )

    return ""


def _record_requirement_instruction() -> str:
    assumed_departure_date = (
        date.today() + timedelta(days=ASSUMED_REQUIREMENT_DEPARTURE_DAYS)
    ).isoformat()
    return (
        "如果用户这条消息或最近几轮已经提供了目的地、行程天数、主要风格或规划模式，"
        "并且本轮明确要求你整理需求、记录需求、确认无误或继续推进规划，"
        "那就把这条消息视为一次显式确认。"
        " 你可以先用一句简短摘要确认你的理解，但必须在本轮直接调用 `record_requirement_tool`。"
        f" 如果缺少出发日期，先用 `{assumed_departure_date}` 作为待核验占位日期；"
        "缺少出发地时使用 `出发地待确认`；缺少人数时按 1 位成人；"
        "缺少预算时按目的地常规轻松行程做保守估算。"
        " 这些兜底假设必须写进 `special_needs`，并明确标注待核验。"
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

    inferred_destination = _infer_destination_from_state_messages(state_dict)
    if inferred_destination:
        return inferred_destination

    return None


def _infer_destination_from_route_text(text: str) -> str | None:
    for match in re.finditer(r"(?:去|到)([^，。；\n]{0,24})", text or ""):
        segment = match.group(1)
        for city in COMMON_CITY_NAMES:
            if city in segment:
                return city
    return None


def _infer_destination_from_state_messages(state_dict: dict[str, Any]) -> str | None:
    texts: list[str] = []
    for message in state_dict.get("messages") or []:
        content = None
        if isinstance(message, dict):
            role = message.get("role") or message.get("type")
            if role in {"user", "human"}:
                content = message.get("content")
        elif getattr(message, "type", None) == "human" or getattr(message, "role", None) == "user":
            content = getattr(message, "content", None)
        if content:
            texts.append(content if isinstance(content, str) else str(content))

    for text in reversed(texts):
        destination = _infer_destination_from_route_text(text)
        if destination:
            return destination
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
    return (
        any(keyword in text for keyword in route_keywords)
        and sum(1 for city in COMMON_CITY_NAMES if city in text) >= 1
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


def _has_planning_mode_or_style_hint(text: str) -> bool:
    mode_keywords = (
        "自由行",
        "自由规划",
        "自助游",
        "自己订",
        "不跟团",
        "旅行社",
        "顾问方案",
        "省心方案",
        "定制游",
        "小包团",
        "私家团",
    )
    return _has_style_hint(text) or any(keyword in text for keyword in mode_keywords)


def _has_minimum_plannable_requirement(text: str) -> bool:
    return (
        _has_route_hint(text)
        and (_has_days_hint(text) or _has_date_hint(text))
        and _has_planning_mode_or_style_hint(text)
    )


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


def _looks_like_initial_complex_trip_request(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False

    has_trip_shape = _has_route_hint(normalized) and (
        _has_days_hint(normalized) or _has_date_hint(normalized)
    )
    if not has_trip_shape:
        return False

    has_slow_intent = any(
        keyword in normalized for keyword in FIRST_TURN_SLOW_INTENT_KEYWORDS
    )
    has_full_agency_plan_intent = (
        _has_budget_hint(normalized)
        and any(keyword in normalized for keyword in FIRST_TURN_AGENCY_PLAN_KEYWORDS)
    )
    return has_slow_intent or has_full_agency_plan_intent


def _should_defer_initial_slow_tools(request: ModelRequest, text: str) -> bool:
    """Keep the first visible response ahead of slow external lookups."""

    if not _is_first_user_turn_without_assistant_text(request):
        return False
    if _should_prioritize_requirement_record(text):
        return False
    return _looks_like_initial_complex_trip_request(text)


def _initial_slow_tool_deferral_instruction() -> str:
    return (
        "你是知行旅行顾问。本轮只做首轮轻量响应，不调用任何工具，"
        "也不编造实时价格、库存、班次或天气。"
        "请用 1-2 句确认你已理解用户的目的地、天数、同行人和慢项诉求；"
        "说明会在需求确认后核验真实交通、酒店、天气和风险证据，"
        "然后请用户确认是否按此记录并推进。"
    )


def _looks_like_final_report_request(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False
    return any(keyword in normalized for keyword in FINAL_REPORT_REQUEST_KEYWORDS)


def _final_report_tool_instruction() -> str:
    return (
        "本轮已经处于最终报告生成阶段，用户明确要求生成最终报告或 report_data。"
        " 只能调用 `generate_order_tool`，不要先输出寒暄、确认语或手写报告。"
        " 工具会用已确认状态补齐结构化报告、预算置信度、风险和待核验项；"
        " 即使仍有估算项，也应通过工具生成带待核验说明的 report_data。"
    )


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
    return sum(1 for item in checks if item) >= 5 or _has_minimum_plannable_requirement(
        combined_text
    )


def _should_allow_date_tools(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False
    if any(keyword in normalized for keyword in RELATIVE_DATE_TOOL_KEYWORDS):
        return True
    return bool(
        re.search(r"(这|本|下|下下)周[一二三四五六日天]?", normalized)
        or re.search(r"\d{1,2}\s*月\s*(上旬|中旬|下旬|月初|月底)", normalized)
    )


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

        except (KeyError, AttributeError) as exc:
            app_logger.warning(f"提示词变量缺失: {exc}，使用原始模板")
            system_prompt = step_config["prompt"]

        context_messages = list(request.messages or [])
        if not context_messages:
            context_messages = list(state_dict.get("messages") or [])
        context_pack = await abuild_context_pack(
            state=state_dict,
            messages=context_messages,
            memory_prompt=memory_prompt,
        )
        system_prompt = f"{system_prompt}\n\n{context_pack.system_appendix}"
        if context_pack.summary_text:
            state["conversation_summary"] = context_pack.summary_text
            state["context_summary_updated_at"] = time.time()
        state["context_last_step"] = current_step
        state["context_pack_metadata"] = context_pack.metadata
        state["key_history_turns"] = context_pack.key_history_turns
        state["context_layer_boundaries"] = context_pack.metadata.get("context_layer_boundaries", {})
        app_logger.info(
            "上下文打包完成: "
            f"messages={context_pack.metadata['message_count']}, "
            f"retained={context_pack.metadata['retained_message_count']}, "
            f"summary={context_pack.metadata['summary_triggered']}, "
            f"reason={context_pack.metadata['summary_reason']}"
        )

        override_kwargs = {
            "system_prompt": system_prompt,
            "tools": step_config["tools"],
        }
        if context_messages:
            override_kwargs["messages"] = context_pack.messages

        compatibility = get_model_compatibility(profile="planner")
        latest_human_text = _latest_human_text(request)
        active_human_text = latest_human_text or _recent_human_text(request, limit=1)
        defer_initial_slow_tools = (
            current_step == "requirement_collection"
            and _should_defer_initial_slow_tools(request, active_human_text)
        )
        if current_step == "requirement_collection":
            today_text = date.today().isoformat()
            override_kwargs["system_prompt"] = (
                f"{override_kwargs['system_prompt']}\n\n"
                "【当前日期】"
                f"今天是 {today_text}。"
                "处理“今天/明天/这个周末/下周/下个月”等相对日期时，"
                "直接基于这个日期换算为 YYYY-MM-DD 或具体日期范围；"
                "不要调用日期工具。"
            )
            filtered_tools = _exclude_tools_by_name(override_kwargs["tools"], DATE_TOOL_NAMES)
            if len(filtered_tools) != len(override_kwargs["tools"]):
                override_kwargs["tools"] = filtered_tools
                app_logger.info(
                    "需求收集阶段已注入当前日期并移除日期工具以降低首 token 延迟"
                )
            allowed_memory_tools = _allowed_requirement_memory_tools(latest_human_text)
            memory_tools_to_exclude = REQUIREMENT_MEMORY_TOOL_NAMES - allowed_memory_tools
            filtered_tools = _exclude_tools_by_name(
                override_kwargs["tools"],
                memory_tools_to_exclude,
            )
            if len(filtered_tools) != len(override_kwargs["tools"]):
                override_kwargs["tools"] = filtered_tools
                override_kwargs["system_prompt"] = (
                    f"{override_kwargs['system_prompt']}\n\n"
                    f"{_temporary_requirement_memory_instruction()}"
                )
                app_logger.info(
                    "需求收集阶段按长期记忆语义收窄记忆工具: "
                    f"excluded={sorted(memory_tools_to_exclude)}"
                )
        travel_intent = detect_travel_intent(
            latest_human_text,
            current_step=current_step,
            state=state_dict,
        )
        planning_mode = resolve_planning_mode(
            latest_human_text,
            state=state_dict,
            intent=travel_intent,
        )
        final_report_requested = (
            travel_intent.name in {"final_report", "export_report"}
            or (
                current_step == "order_generation"
                and _looks_like_final_report_request(active_human_text)
            )
        )
        planning_instruction = _planning_mode_instruction(planning_mode)
        if planning_instruction:
            override_kwargs["system_prompt"] = (
                f"{override_kwargs['system_prompt']}\n\n{planning_instruction}"
            )
            override_kwargs["tools"] = _append_tools_by_name(
                override_kwargs["tools"],
                self._step_config,
                MODE_MANAGEMENT_TOOL_NAMES,
            )
            app_logger.info(
                "识别规划模式并注入提示: "
                f"mode={planning_mode.mode}, source={planning_mode.source}, "
                f"confirmed={planning_mode.confirmed}, "
                f"needs_confirmation={planning_mode.needs_confirmation}, "
                f"reason={planning_mode.reason}"
            )

        intent_instruction = _intent_instruction(travel_intent, state_dict, current_step)
        if intent_instruction:
            override_kwargs["system_prompt"] = (
                f"{override_kwargs['system_prompt']}\n\n{intent_instruction}"
            )
            app_logger.info(
                "识别用户意图并注入提示: "
                f"intent={travel_intent.name}, confidence={travel_intent.confidence:.2f}, "
                f"reason={travel_intent.reason}"
            )

        if planning_mode.mode == "free_planning" or planning_mode.needs_confirmation:
            allowed_internal_tools = INTENT_INTERNAL_TOOL_ALLOWLIST.get(
                travel_intent.name,
                frozenset(),
            )
            excluded_internal_tools = AGENCY_INTERNAL_TOOL_NAMES - allowed_internal_tools
            filtered_tools = _exclude_tools_by_name(override_kwargs["tools"], excluded_internal_tools)
            if len(filtered_tools) != len(override_kwargs["tools"]):
                override_kwargs["tools"] = filtered_tools
                app_logger.info(
                    "自由规划或待确认模式：本轮移除不相关旅行社内部 RAG 工具"
                )
        if planning_mode.needs_confirmation:
            filtered_tools = _exclude_tools_by_name(
                override_kwargs["tools"],
                {"record_requirement_tool"},
            )
            if len(filtered_tools) != len(override_kwargs["tools"]):
                override_kwargs["tools"] = filtered_tools
                app_logger.info(
                    "规划模式待确认：本轮暂缓记录需求，优先确认自由规划或旅行社顾问方案"
                )

        if defer_initial_slow_tools:
            state["pending_initial_request_text"] = active_human_text
            if planning_mode.mode:
                state["pending_initial_planning_mode"] = planning_mode.mode
                state["pending_initial_planning_mode_reason"] = planning_mode.reason
            if override_kwargs["tools"]:
                override_kwargs["tools"] = []
            override_kwargs["system_prompt"] = _initial_slow_tool_deferral_instruction()
            app_logger.info(
                "需求收集首轮复杂规划请求：暂缓所有工具以降低首 token 延迟"
            )

        cross_step_tool_names = (
            [] if defer_initial_slow_tools else _cross_step_verification_tools(latest_human_text)
        )
        if (
            current_step == "transport_planning"
            and not _has_selected_transport(state_dict)
            and "query_hotel_options" in cross_step_tool_names
        ):
            cross_step_tool_names = [
                tool_name
                for tool_name in cross_step_tool_names
                if tool_name != "query_hotel_options"
            ]
            override_kwargs["system_prompt"] = (
                f"{override_kwargs['system_prompt']}\n\n"
                "交通方案尚未记录时，不要跨阶段查询或记录住宿；"
                "请先完成交通记录，再处理住宿。"
            )
            app_logger.info(
                "交通未记录：暂缓跨阶段酒店查询，避免跳过交通前置状态"
            )
        if cross_step_tool_names:
            current_tool_names = _tool_names(override_kwargs["tools"])
            added_tools: list[str] = []
            for tool_name in cross_step_tool_names:
                if tool_name in current_tool_names:
                    continue
                extra_tool = _find_tool_by_name(self._step_config, tool_name)
                if extra_tool is not None:
                    override_kwargs["tools"] = [*override_kwargs["tools"], extra_tool]
                    current_tool_names.add(tool_name)
                    added_tools.append(tool_name)

            instruction = _cross_step_verification_instruction(cross_step_tool_names)
            if instruction:
                override_kwargs["system_prompt"] = (
                    f"{override_kwargs['system_prompt']}\n\n{instruction}"
                )
            if added_tools:
                app_logger.info(
                    "跨阶段核验请求：临时开放真实查询工具: "
                    f"{added_tools}"
                )

        available_tool_names = _tool_names(override_kwargs["tools"])
        intent_preferred_tool = (
            None
            if defer_initial_slow_tools
            else _preferred_tool_for_intent(travel_intent, state_dict)
        )
        if (
            planning_mode.needs_confirmation
            and intent_preferred_tool == "record_requirement_tool"
        ):
            intent_preferred_tool = None
        if intent_preferred_tool and intent_preferred_tool not in available_tool_names:
            extra_tool = _find_tool_by_name(self._step_config, intent_preferred_tool)
            if extra_tool is not None:
                override_kwargs["tools"] = [*override_kwargs["tools"], extra_tool]
                available_tool_names = _tool_names(override_kwargs["tools"])
                app_logger.info(
                    "按用户意图临时开放跨阶段工具: "
                    f"intent={travel_intent.name}, tool={intent_preferred_tool}"
                )

        if travel_intent.name in {"final_report", "export_report"} and intent_preferred_tool:
            report_tools = _keep_tools_by_name(
                override_kwargs["tools"],
                {intent_preferred_tool},
            )
            if report_tools:
                override_kwargs["tools"] = report_tools
                available_tool_names = _tool_names(override_kwargs["tools"])
                app_logger.info(
                    "最终报告意图：本轮工具列表已收窄为结构化报告工具: "
                    f"{sorted(available_tool_names)}"
                )

        recent_tool_names = _recent_tool_names_since_latest_human(request)
        repeat_instruction = _tool_repeat_instruction(current_step, recent_tool_names)
        used_one_shot_tools = ONE_SHOT_TOOLS_AFTER_CALL & recent_tool_names
        if used_one_shot_tools:
            filtered_tools = _exclude_tools_by_name(override_kwargs["tools"], used_one_shot_tools)
            if len(filtered_tools) != len(override_kwargs["tools"]):
                override_kwargs["tools"] = filtered_tools
                available_tool_names = _tool_names(override_kwargs["tools"])
                app_logger.info(
                    "本轮移除已完成的一次性工具: "
                    f"step={current_step}, tools={sorted(used_one_shot_tools)}"
                )
        if repeat_instruction:
            override_kwargs["system_prompt"] = (
                f"{override_kwargs['system_prompt']}\n\n{repeat_instruction}"
            )
            app_logger.info(
                "本轮工具已调用，注入防重复提示: "
                f"step={current_step}, tools={sorted(recent_tool_names)}"
            )
        confirmed_destination = (
            _confirmed_destination_name(state_dict, latest_human_text)
            if current_step == "destination_recommendation"
            else None
        )
        middleware_forced_tool = None
        latest_tool_result_names = _latest_tool_result_names(request)
        if current_step == "transport_planning":
            transport_human_text = latest_human_text or _recent_human_text(request, limit=1)
            transport_selection_requested = (
                not any(keyword in transport_human_text for keyword in ("重新", "换个", "改成"))
                and (
                    (
                        any(keyword in transport_human_text for keyword in SELECTION_KEYWORDS)
                        and any(
                            keyword in transport_human_text
                            for keyword in ("交通", "方式", "推荐", "省心", "时间合理")
                        )
                        and any(
                            keyword in transport_human_text
                            for keyword in ("交通", "方式", "班次", "出行", "省心和时间合理")
                        )
                    )
                    or any(keyword in transport_human_text for keyword in CROSS_STEP_HOTEL_KEYWORDS)
                )
            )
            if "query_transport_options" in latest_tool_result_names:
                allow_transport_selection = any(
                    keyword in transport_human_text for keyword in SELECTION_KEYWORDS
                )
                excluded_after_transport_query = {"query_transport_options"}
                if not allow_transport_selection:
                    excluded_after_transport_query.add("select_transport_tool")
                filtered_tools = _exclude_tools_by_name(
                    override_kwargs["tools"],
                    excluded_after_transport_query,
                )
                if len(filtered_tools) != len(override_kwargs["tools"]):
                    override_kwargs["tools"] = filtered_tools
                    available_tool_names = _tool_names(override_kwargs["tools"])
                    app_logger.info(
                        "本轮已完成交通查询：按用户确认语义收窄后续交通工具: "
                        f"allow_selection={allow_transport_selection}"
                    )
                if allow_transport_selection and "select_transport_tool" in available_tool_names:
                    middleware_forced_tool = "select_transport_tool"
                override_kwargs["system_prompt"] = (
                    f"{override_kwargs['system_prompt']}\n\n"
                    f"{_transport_query_result_instruction(allow_selection=allow_transport_selection)}"
                )
            elif (
                not _has_selected_transport(state_dict)
                and "select_transport_tool" in available_tool_names
                and transport_selection_requested
            ):
                middleware_forced_tool = "select_transport_tool"
                filtered_tools = _keep_tools_by_name(
                    override_kwargs["tools"],
                    {"select_transport_tool"},
                )
                if filtered_tools:
                    override_kwargs["tools"] = filtered_tools
                    available_tool_names = _tool_names(override_kwargs["tools"])
                override_kwargs["system_prompt"] = (
                    f"{override_kwargs['system_prompt']}\n\n"
                    f"{_transport_selection_fallback_instruction()}"
                )
            elif (
                not _has_selected_transport(state_dict)
                and "query_transport_options" in available_tool_names
                and "select_destination_tool" not in latest_tool_result_names
                and intent_preferred_tool is None
                and not any(keyword in latest_human_text for keyword in SELECTION_KEYWORDS)
            ):
                middleware_forced_tool = "query_transport_options"

        if (
            current_step == "destination_recommendation"
            and _has_destination_candidates(state_dict)
            and not state_dict.get("selected_destination")
            and not confirmed_destination
            and _latest_message_is_tool_result(request)
        ):
            filtered_tools = _exclude_tools_by_name(
                override_kwargs["tools"],
                {"select_destination_tool", *DESTINATION_REFRESH_TOOL_NAMES},
            )
            if len(filtered_tools) != len(override_kwargs["tools"]):
                override_kwargs["tools"] = filtered_tools
                available_tool_names = _tool_names(override_kwargs["tools"])
                app_logger.info(
                    "已有目的地候选且用户尚未确认：本轮移除目的地选择和重复查询工具"
                )
            override_kwargs["system_prompt"] = (
                f"{override_kwargs['system_prompt']}\n\n{_destination_candidate_instruction()}"
            )

        if current_step == "accommodation_planning":
            accommodation_excluded_tools: set[str] = set()
            post_transport_selection = "select_transport_tool" in latest_tool_result_names
            accommodation_human_text = latest_human_text or _recent_human_text(request, limit=1)
            post_transport_requested_accommodation = any(
                keyword in accommodation_human_text for keyword in CROSS_STEP_HOTEL_KEYWORDS
            )
            if post_transport_selection and not post_transport_requested_accommodation:
                accommodation_excluded_tools.update(
                    {
                        "query_hotel_options",
                        "select_accommodation_tool",
                        "update_accommodation_preference_tool",
                    }
                )
            if not _accommodation_memory_is_stable(latest_human_text):
                accommodation_excluded_tools.add("update_accommodation_preference_tool")
            if _has_selected_accommodation(state_dict):
                accommodation_excluded_tools.update(
                    {"query_hotel_options", "update_accommodation_preference_tool"}
                )
            elif _has_accommodation_candidates(state_dict):
                accommodation_excluded_tools.update(
                    {"query_hotel_options", "update_accommodation_preference_tool"}
                )
                if "select_accommodation_tool" in available_tool_names:
                    middleware_forced_tool = "select_accommodation_tool"
            elif (
                "query_hotel_options" in available_tool_names
                and "query_hotel_options" not in _latest_tool_result_names(request)
                and (
                    "select_transport_tool" not in _latest_tool_result_names(request)
                    or post_transport_requested_accommodation
                )
            ):
                middleware_forced_tool = "query_hotel_options"

            if accommodation_excluded_tools:
                filtered_tools = _exclude_tools_by_name(
                    override_kwargs["tools"],
                    accommodation_excluded_tools,
                )
                if len(filtered_tools) != len(override_kwargs["tools"]):
                    override_kwargs["tools"] = filtered_tools
                    available_tool_names = _tool_names(override_kwargs["tools"])
                    app_logger.info(
                        "住宿阶段按候选/记忆语义收窄工具: "
                        f"excluded={sorted(accommodation_excluded_tools)}"
                    )
            if _has_accommodation_candidates(state_dict) and not _has_selected_accommodation(state_dict):
                override_kwargs["system_prompt"] = (
                    f"{override_kwargs['system_prompt']}\n\n{_accommodation_candidate_instruction()}"
                )
            elif post_transport_selection and not post_transport_requested_accommodation:
                override_kwargs["system_prompt"] = (
                    f"{override_kwargs['system_prompt']}\n\n{_post_transport_accommodation_instruction()}"
                )
            elif "update_accommodation_preference_tool" in accommodation_excluded_tools:
                override_kwargs["system_prompt"] = (
                    f"{override_kwargs['system_prompt']}\n\n{_temporary_accommodation_instruction()}"
                )

        if (
            current_step == "order_generation"
            and final_report_requested
            and not state_dict.get("report_data")
        ):
            final_report_tool = _find_tool_by_name(
                self._step_config,
                "generate_order_tool",
            )
            if final_report_tool is not None:
                override_kwargs["tools"] = [final_report_tool]
                available_tool_names = _tool_names(override_kwargs["tools"])
                middleware_forced_tool = "generate_order_tool"
                override_kwargs["system_prompt"] = (
                    f"{override_kwargs['system_prompt']}\n\n"
                    f"{_final_report_tool_instruction()}"
                )
                app_logger.info(
                    "最终报告阶段：本轮收窄为 generate_order_tool，确保产出 report_data"
                )

        forced_tool = None
        if middleware_forced_tool:
            forced_tool = middleware_forced_tool
        elif travel_intent.name in {"final_report", "export_report"} and intent_preferred_tool:
            forced_tool = intent_preferred_tool
        else:
            forced_tool = (
                "select_destination_tool"
                if confirmed_destination
                else _forced_tool_choice(current_step, latest_human_text, request)
            )
            if forced_tool is None:
                forced_tool = intent_preferred_tool
        if forced_tool and forced_tool not in available_tool_names:
            forced_tool = None
        if forced_tool and forced_tool in recent_tool_names:
            app_logger.info(
                f"跳过重复强制工具调用: {forced_tool} 已在本轮执行"
            )
            forced_tool = None
        if forced_tool:
            if forced_tool in FORCE_NARROW_TOOL_NAMES and len(cross_step_tool_names) < 2:
                forced_tools = _keep_tools_by_name(override_kwargs["tools"], {forced_tool})
                if forced_tools:
                    override_kwargs["tools"] = forced_tools
                    available_tool_names = _tool_names(override_kwargs["tools"])
                    app_logger.info(
                        "强制工具场景：本轮工具列表已收窄，避免并行重复调用: "
                        f"{forced_tool}"
                    )
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
                    f"{override_kwargs['system_prompt']}\n\n{tool_instruction}"
                )
                app_logger.info(f"模型不支持强制 tool_choice，改为提示词引导: {forced_tool}")

        state["observability_context"] = build_observability_context(
            turn_id=state.get("turn_id"),
            current_step=current_step,
            planning_mode=planning_mode.mode,
            planning_mode_source=planning_mode.source,
            planning_mode_confirmed=planning_mode.confirmed,
            available_tool_count=len(override_kwargs["tools"]),
        )
        app_logger.info(
            "观测上下文已更新: "
            f"turn_id={state.get('turn_id')}, step={current_step}, "
            f"planning_mode={planning_mode.mode}, tools={len(override_kwargs['tools'])}"
        )

        modified_request = request.override(**override_kwargs)
        app_logger.info(f"已注入步骤配置，工具数量: {len(override_kwargs['tools'])}")
        return await handler(modified_request)


async def create_step_config_middleware() -> StepConfigMiddleware:
    """
    工厂函数：创建步骤配置中间件。
    """
    from app.agents.handoffs.step_config import get_step_config

    step_config = await get_step_config()
    return StepConfigMiddleware(step_config)
