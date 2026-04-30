from types import SimpleNamespace
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, ToolMessage
from typing import Callable, Any
from app.core.state import TravelState
from app.core.workflow import INITIAL_PLANNING_STEP
from app.core.store import get_user_memory_service
from app.utils.logger import app_logger


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
        parts = []
        details = option.get("details")
        if details:
            parts.append(str(details))
        if option.get("departure_time") or option.get("arrival_time"):
            parts.append(f"{option.get('departure_time', '待确认')} -> {option.get('arrival_time', '待确认')}")
        if option.get("duration"):
            parts.append(f"耗时 {option['duration']}")
        if option.get("price"):
            parts.append(f"参考价格 {option['price']} 元/人")
        if option.get("source"):
            parts.append(f"来源 {option['source']}")
        if parts:
            return "；".join(parts)

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


def _forced_tool_choice(current_step: str, latest_human_text: str) -> str | None:
    text = latest_human_text.strip()
    if not text:
        return None

    selection_keywords = [
        "选第",
        "就选",
        "选这个",
        "确认",
        "锁定",
        "记录",
        "定这个",
        "就它",
    ]
    if any(keyword in text for keyword in selection_keywords):
        return None

    direct_query_keywords = [
        "直接查",
        "真实",
        "不要只口头",
        "不要泛泛",
        "不要继续追问",
        "信息已经齐",
        "不用继续问",
    ]
    if current_step == "accommodation_planning":
        hotel_keywords = ["酒店", "住宿", "住"]
        if any(keyword in text for keyword in direct_query_keywords) and any(
            keyword in text for keyword in hotel_keywords
        ):
            return "query_hotel_options"

    if current_step == "transport_planning":
        transport_keywords = ["飞机", "航班", "高铁", "火车", "自驾", "交通"]
        query_intent_keywords = ["查", "查询", "看看", "推荐", "方案", "有没有", "多少"]
        if any(keyword in text for keyword in direct_query_keywords) or (
            any(keyword in text for keyword in transport_keywords)
            and any(keyword in text for keyword in query_intent_keywords)
        ):
            return "query_transport_options"

    return None


class StepConfigMiddleware(AgentMiddleware):
    """
    步骤配置中间件 - 根据 current_step 动态配置 Agent
    """

    def __init__(self, step_config: dict):
        """
        初始化中间件

        Args:
            step_config: 预加载的步骤配置字典
        """
        self._step_config = step_config

    async def awrap_model_call(
            self,
            request: ModelRequest,
            handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        """
        根据 current_step 动态配置 Agent
        """
        # 获取当前步骤
        state: TravelState = request.state
        state_dict = dict(state) if hasattr(state, "items") else {}
        current_step = state.get("current_step", INITIAL_PLANNING_STEP)
        user_id = state.get("user_id")

        app_logger.info(f"📋 用户ID: {user_id}")
        app_logger.info(f"📍 当前步骤: {current_step}")

        if current_step not in self._step_config:
            app_logger.error(f"❌ 未知步骤: {current_step}")
            raise ValueError(f"未知步骤: {current_step}")

        step_config = self._step_config[current_step]

        # ========== 验证前置依赖 ==========
        for required_field in step_config["requires"]:
            if required_field not in state or state[required_field] is None:
                error_msg = f"步骤 {current_step} 需要完整状态: {required_field} 未设置"
                app_logger.error(f"❌ {error_msg}")
                raise ValueError(error_msg)

        # ========== 🔑 核心：注入长期记忆 ==========
        memory_prompt = ""
        if user_id:
            try:
                service = await get_user_memory_service()
                memory_prompt = await service.format_memory_for_prompt(user_id)
                if memory_prompt:
                    app_logger.info(f"💾 已加载用户长期记忆: {user_id}")
                else:
                    app_logger.info(f"📝 用户首次使用，暂无历史记忆: {user_id}")
            except Exception as e:
                app_logger.warning(f"⚠️ 加载长期记忆失败: {e}")

        # ========== 动态填充提示词变量 ==========
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
            state_dict.setdefault(
                "budget_summary",
                _format_budget_summary(state_dict),
            )
            state_dict.setdefault(
                "itinerary_summary",
                _format_itinerary_summary(state_dict),
            )

            state_dict["user_memory"] = memory_prompt  # 将记忆注入到模板变量
            prompt_values = {
                key: _to_prompt_value(value)
                for key, value in state_dict.items()
            }
            system_prompt = step_config["prompt"].format_map(prompt_values)

            # 如果有长期记忆，追加到提示词末尾
            if memory_prompt:
                system_prompt = f"{system_prompt}\n\n{memory_prompt}"

        except (KeyError, AttributeError) as e:
            app_logger.warning(f"⚠️ 提示词变量缺失: {e}, 使用原始模板")
            system_prompt = step_config["prompt"]

        # ========== 注入配置 ==========
        override_kwargs = {
            "system_prompt": system_prompt,
            "tools": step_config["tools"],
        }
        forced_tool = _forced_tool_choice(current_step, _latest_human_text(request))
        if forced_tool:
            override_kwargs["tool_choice"] = forced_tool
            app_logger.info(f"🔒 强制本轮优先调用工具: {forced_tool}")

        modified_request = request.override(**override_kwargs)

        app_logger.info(f"✅ 已注入步骤配置: {len(step_config['tools'])} 个工具")

        return await handler(modified_request)


async def create_step_config_middleware() -> StepConfigMiddleware:
    """
    工厂函数：创建步骤配置中间件

    Returns:
        预加载配置的 StepConfigMiddleware 实例
    """
    from app.agents.handoffs.step_config import get_step_config

    step_config = await get_step_config()
    return StepConfigMiddleware(step_config)
