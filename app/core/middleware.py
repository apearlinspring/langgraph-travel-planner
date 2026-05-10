import re
import time
from types import SimpleNamespace
from typing import Any, Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, ToolMessage

from app.core.context_pack import build_context_pack
from app.core.intent import PlanningModeDecision, TravelIntent, detect_travel_intent, resolve_planning_mode
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
    return ""


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

        except (KeyError, AttributeError) as exc:
            app_logger.warning(f"提示词变量缺失: {exc}，使用原始模板")
            system_prompt = step_config["prompt"]

        context_messages = list(request.messages or [])
        if not context_messages:
            context_messages = list(state_dict.get("messages") or [])
        context_pack = build_context_pack(
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

        cross_step_tool_names = _cross_step_verification_tools(latest_human_text)
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
        intent_preferred_tool = _preferred_tool_for_intent(travel_intent, state_dict)
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
        forced_tool = None
        if travel_intent.name in {"final_report", "export_report"} and intent_preferred_tool:
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
