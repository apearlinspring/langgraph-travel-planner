"""
流式对话 API（SSE）
"""
import json
import asyncio
import re
import time
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk
from app.models.base import get_db
from app.models.user import User
from app.models.conversation import Conversation
from app.models.message import Message
from app.schemas.message import MessageCreate
from app.api.dependencies import get_current_user
from app.agents.handoffs.travel_agent import create_travel_agent
from app.config import settings
from app.core.observability import (
    TurnObservation,
    public_tool_audit_event,
)
from app.core.intent import resolve_planning_mode
from app.core.session_lock import SessionLockBusy, acquire_session_lock
from app.core.approval import ApprovalGovernanceManager
from app.tools.audit import (
    build_tool_audit_event,
    persist_tool_audit_events,
    start_tool_audit,
    summarize_tool_input,
    summarize_tool_output,
)
from app.tools.result_validation import (
    evidence_type_for_tool_name,
    validate_tool_output_for_audit,
)
from app.journey.visual_planner import JOURNEY_PLAN_VERSION, validate_journey_plan
from app.utils.logger import app_logger
from app.utils.date_normalization import normalize_travel_date
from app.utils.security import redact_sensitive_data, redact_sensitive_text

router = APIRouter(prefix="/chat", tags=["对话"])

SESSION_BUSY_MESSAGE = "当前会话正在处理上一轮消息，请稍后再试。"
_THINK_OPEN_TAG = "<think>"
_THINK_CLOSE_TAG = "</think>"
_FAST_MODE_SPLIT_QUESTION = "您想要现成省心方案，还是个性化旅游规划？"
_AGENT_EVENT_IDLE_TIMEOUT_SECONDS = 90.0
_FAST_MEANINGFUL_FACT_KEYS = {
    "departure_city",
    "destination",
    "departure_date",
    "travel_days",
    "adult_count",
    "budget_text",
    "planning_mode",
    "active_workflow",
    "agency_step",
}

_FAST_DESTINATION_COPY = {
    "杭州": "杭州很适合慢逛和尝鲜，四天左右刚好能把西湖周边和老城区的烟火气走舒服。",
    "西藏": "西藏很适合看雪山、湖泊和高原风景，时间安排稳一点会更舒服。",
    "云南": "云南很适合慢节奏看山水、古城和烟火气，五天左右可以先抓一条清爽主线。",
    "成都": "成都很适合美食、人文和轻松节奏，几天时间就能玩得很有层次。",
    "西安": "西安很适合人文、美食和博物馆路线，几天时间可以把经典体验排得很扎实。",
}

_FAST_PLACE_STOPWORDS = {
    "我们",
    "两个",
    "左右",
    "预算",
    "每人",
    "人均",
    "出发",
    "规划",
    "方案",
    "旅游",
    "旅行",
}
_FAST_CN_NUMBERS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _longest_tag_prefix_suffix(text: str, tag: str) -> int:
    lower_text = text.lower()
    max_size = min(len(tag) - 1, len(text))
    for size in range(max_size, 0, -1):
        if tag.startswith(lower_text[-size:]):
            return size
    return 0


class _AssistantThinkingFilter:
    """Incrementally remove model-only <think> blocks from user-facing text."""

    def __init__(self) -> None:
        self._buffer = ""
        self._inside_thinking = False

    def feed(self, value: str) -> str:
        self._buffer += str(value or "")
        chunks: list[str] = []

        while self._buffer:
            buffer_lower = self._buffer.lower()
            if self._inside_thinking:
                close_index = buffer_lower.find(_THINK_CLOSE_TAG)
                if close_index >= 0:
                    self._buffer = self._buffer[
                        close_index + len(_THINK_CLOSE_TAG):
                    ]
                    self._inside_thinking = False
                    continue

                keep_size = _longest_tag_prefix_suffix(
                    self._buffer,
                    _THINK_CLOSE_TAG,
                )
                self._buffer = self._buffer[-keep_size:] if keep_size else ""
                break

            open_index = buffer_lower.find(_THINK_OPEN_TAG)
            if open_index >= 0:
                chunks.append(self._buffer[:open_index])
                self._buffer = self._buffer[open_index + len(_THINK_OPEN_TAG):]
                self._inside_thinking = True
                continue

            keep_size = _longest_tag_prefix_suffix(self._buffer, _THINK_OPEN_TAG)
            if keep_size:
                chunks.append(self._buffer[:-keep_size])
                self._buffer = self._buffer[-keep_size:]
            else:
                chunks.append(self._buffer)
                self._buffer = ""
            break

        return "".join(chunks)

    def finish(self) -> str:
        if self._inside_thinking:
            self._buffer = ""
            self._inside_thinking = False
            return ""
        if self._buffer and _THINK_OPEN_TAG.startswith(self._buffer.lower()):
            self._buffer = ""
            return ""
        remainder = self._buffer
        self._buffer = ""
        return remainder


class JourneyDraftUpdate(BaseModel):
    """Persist a user-adjusted journey draft without bypassing report gates."""

    journey_data: dict = Field(default_factory=dict)
    source: str = "frontend_editor"


def _strip_assistant_thinking_content(text: str) -> str:
    thinking_filter = _AssistantThinkingFilter()
    return thinking_filter.feed(text) + thinking_filter.finish()


def _fast_cn_number(value: str) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if text in _FAST_CN_NUMBERS:
        return _FAST_CN_NUMBERS[text]
    if "十" not in text:
        return None
    left, _, right = text.partition("十")
    tens = _FAST_CN_NUMBERS.get(left, 1 if not left else 0)
    ones = _FAST_CN_NUMBERS.get(right, 0) if right else 0
    value_int = tens * 10 + ones
    return value_int if value_int > 0 else None


def _clean_fast_place_candidate(value: str) -> str:
    candidate = str(value or "").strip(" ，。,.；;：:、")
    candidate = re.split(
        r"(?:玩|旅游|旅行|游|出发|规划|安排|帮我|预算|人均|每人|两个人|二人|[一二两三四五六七八九十\d]+人|[一二两三四五六七八九十\d]+天|下周|这周|本周|明天|后天|大后天)",
        candidate,
        maxsplit=1,
    )[0]
    candidate = re.sub(r"(?:的)?(?:交通|酒店|住宿|路线|方案|行程)$", "", candidate)
    candidate = candidate.strip(" ，。,.；;：:、")
    if candidate in _FAST_PLACE_STOPWORDS:
        return ""
    return candidate


def _extract_fast_route_places(text: str) -> tuple[str, str]:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return "", ""
    place = r"([一-龥]{2,12}?)"
    destination_boundary = (
        r"(?=$|[，,。；;\s]|玩|旅游|旅行|游|两个人|二人|[一二两三四五六七八九十\d]+人|"
        r"[一二两三四五六七八九十\d]+天|预算|人均|每人|下周|这周|本周|明天|后天|帮我|规划|安排)"
    )
    patterns = (
        rf"(?:从|自){place}(?:出发)?(?:去|到|前往|飞往|开车去|坐车去){place}{destination_boundary}",
        rf"{place}(?:出发)?(?:到|去|前往|->|→){place}{destination_boundary}",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        origin = _clean_fast_place_candidate(match.group(1))
        destination = _clean_fast_place_candidate(match.group(2))
        if origin and destination and origin != destination:
            return origin, destination
    return "", ""


def _extract_fast_mode_destination(text: str) -> str:
    facts = extract_fast_split_facts(text)
    return str(facts.get("destination") or "")


def _parse_fast_month_day(raw: str, *, today: date) -> str:
    month_day = re.fullmatch(r"(\d{1,2})月(\d{1,2})(?:日|号)?", raw.strip())
    if not month_day:
        return ""
    month = int(month_day.group(1))
    day = int(month_day.group(2))
    try:
        parsed = date(today.year, month, day)
    except ValueError:
        return ""
    if parsed < today:
        try:
            parsed = date(today.year + 1, month, day)
        except ValueError:
            return ""
    return parsed.isoformat()


def _parse_fast_year_month_day(raw: str) -> str:
    year_month_day = re.fullmatch(
        r"(\d{4})[-/年](\d{1,2})(?:[-/月])(\d{1,2})(?:日|号)?",
        raw.strip(),
    )
    if not year_month_day:
        return ""
    year = int(year_month_day.group(1))
    month = int(year_month_day.group(2))
    day = int(year_month_day.group(3))
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def _extract_fast_date(text: str, *, today: date | None = None) -> tuple[str, str]:
    today = today or date.today()
    normalized = " ".join(str(text or "").split())
    patterns = (
        r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}(?:日|号)?",
        r"\d{1,2}月\d{1,2}(?:日|号)?",
        r"(?:今天|明天|后天|大后天|下下周|下周|这周|本周|周末)(?:周|星期|礼拜)?[一二三四五六日天]?",
        r"(?:周|星期|礼拜)[一二三四五六日天]",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        raw = match.group(0)
        if re.fullmatch(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}(?:日|号)?", raw):
            return raw, _parse_fast_year_month_day(raw)
        if re.fullmatch(r"\d{1,2}月\d{1,2}(?:日|号)?", raw):
            return raw, _parse_fast_month_day(raw, today=today)
        try:
            parsed = normalize_travel_date(raw, today=today)
        except ValueError:
            parsed = ""
        return raw, parsed
    return "", ""


def _extract_fast_days(text: str) -> int | None:
    normalized = " ".join(str(text or "").split())
    match = re.search(r"([一二两三四五六七八九十\d]+)\s*天(?:左右|以内|以上)?", normalized)
    if not match:
        return None
    return _fast_cn_number(match.group(1))


def _extract_fast_people(text: str) -> int | None:
    normalized = " ".join(str(text or "").split())
    match = re.search(r"([一二两三四五六七八九十\d]+)\s*(?:个)?(?:人|成人|大人)", normalized)
    if not match:
        return None
    return _fast_cn_number(match.group(1))


def _extract_fast_budget(text: str) -> str:
    normalized = " ".join(str(text or "").split())
    match = re.search(
        r"((?:预算\s*(?:人均|每人)?|(?:人均|每人)\s*预算?)\s*[约大概左右]*\s*\d+(?:\.\d+)?\s*(?:万|千)?\s*元?(?:左右|以内|上下)?)",
        normalized,
    )
    if not match:
        match = re.search(r"预算\s*([^\s，,。；;]{1,12})", normalized)
    if not match:
        return ""
    budget = re.sub(r"\s+", "", match.group(1)).strip("，,。；;")
    if not budget:
        return ""
    if "人均" not in budget and "每人" not in budget:
        return f"{budget}（口径待确认）"
    return budget


def extract_fast_split_facts(text: str, *, today: date | None = None) -> dict:
    """Parse first-turn trip facts without creating the full travel agent."""

    normalized = " ".join(str(text or "").split())
    if not normalized:
        return {}

    departure_city, destination = _extract_fast_route_places(normalized)
    if not destination:
        for known_destination in _FAST_DESTINATION_COPY:
            if known_destination in normalized:
                destination = known_destination
                break
    if not destination:
        patterns = (
            r"(?:想去|计划去|打算去|去|目的地是|目的地[:：]?)\s*([一-龥]{2,12}?)(?=玩|旅游|旅行|游|，|,|。|$)",
            r"([一-龥]{2,12}?)(?:玩|旅游|旅行|游)",
        )
        for pattern in patterns:
            match = re.search(pattern, normalized)
            if match:
                destination = _clean_fast_place_candidate(match.group(1))
                if destination:
                    break

    date_text, departure_date = _extract_fast_date(normalized, today=today)
    facts = {
        "raw_text": normalized,
        "departure_city": departure_city,
        "destination": destination,
        "departure_date_text": date_text,
        "departure_date": departure_date,
        "travel_days": _extract_fast_days(normalized),
        "adult_count": _extract_fast_people(normalized),
        "budget_text": _extract_fast_budget(normalized),
        "source": "first_turn_fast_split",
    }
    return {key: value for key, value in facts.items() if value not in (None, "", [], {})}


def _has_meaningful_fast_trip_facts(facts: dict | None) -> bool:
    if not isinstance(facts, dict):
        return False
    return any(facts.get(key) not in (None, "", [], {}) for key in _FAST_MEANINGFUL_FACT_KEYS)


def _should_apply_current_turn_fast_facts(facts: dict | None) -> bool:
    if not _has_meaningful_fast_trip_facts(facts):
        return False
    assert isinstance(facts, dict)
    explicit_trip_keys = {
        "departure_city",
        "departure_date",
        "travel_days",
        "adult_count",
        "budget_text",
        "planning_mode",
        "active_workflow",
        "agency_step",
    }
    if any(facts.get(key) not in (None, "", [], {}) for key in explicit_trip_keys):
        return True
    # A bare place name can be a destination lookup, not a planning update.
    # Only let destination override progress when the same turn also carries trip facts.
    return False


def _build_fast_mode_split_message(user_message: str) -> str:
    facts = extract_fast_split_facts(user_message)
    destination = str(facts.get("destination") or "")
    if destination in _FAST_DESTINATION_COPY:
        lead = _FAST_DESTINATION_COPY[destination]
    elif destination:
        lead = f"{destination}是个很值得好好安排的目的地，先把方案类型定下来，后面路线会更贴合。"
    else:
        lead = "这次旅行信息已经有了一个不错的雏形，先把方案类型定下来，后面安排会更贴合。"
    return f"{lead}{_FAST_MODE_SPLIT_QUESTION}"


def _merge_fast_trip_facts(*fact_sets: dict | None) -> dict:
    merged: dict = {}
    for facts in fact_sets:
        if not isinstance(facts, dict):
            continue
        for key, value in facts.items():
            if value in (None, "", [], {}):
                continue
            if key in {"raw_text", "source"} and merged.get(key):
                continue
            merged[key] = value
    return merged


def _agency_requirement_missing_items(facts: dict | None) -> list[str]:
    facts = facts if isinstance(facts, dict) else {}
    required = (
        ("destination", "目的地"),
        ("travel_days", "天数"),
        ("adult_count", "人数"),
        ("budget_text", "预算"),
        ("departure_date", "出发日期"),
    )
    return [label for key, label in required if facts.get(key) in (None, "", [], {})]


def _fast_agency_requirement_message(facts: dict, *, mode_just_confirmed: bool) -> str:
    destination = str(facts.get("destination") or "目的地")
    departure_city = str(facts.get("departure_city") or "出发地")
    missing = _agency_requirement_missing_items(facts)
    if "出发日期" in missing:
        lead = "收到，已切到省心方案。" if mode_just_confirmed else "收到，我先把省心方案的基础信息补上。"
        return (
            f"{lead}你前面说的{departure_city}到{destination}、"
            f"{facts.get('travel_days', '待定')}天、{facts.get('adult_count', '待定')}人、"
            f"{facts.get('budget_text', '预算待定')}我都先记下了。\n\n"
            "还差一个关键日期：计划哪天出发？给我一个大致时间也可以，比如“下周一”或“6月中旬”。"
        )
    return (
        f"收到，出发时间按 {facts.get('departure_date')} 记录。"
        "你已选择省心方案，我会按这些基础信息匹配成熟路线样板；"
        "下一步直接给方案草案，包含交通口径、住宿区域/档次、景点门票参考、餐饮安排和待核验项。"
    )


def _should_use_fast_agency_requirement_reply(
    *,
    latest_fast_split_facts: dict,
    user_message: str,
    mode_decision,
) -> tuple[bool, dict, bool]:
    if not latest_fast_split_facts:
        return False, {}, False
    latest_mode = latest_fast_split_facts.get("planning_mode")
    mode_just_confirmed = (
        mode_decision.confirmed
        and mode_decision.mode == "agency_plan"
        and getattr(mode_decision, "source", "") == "latest_user"
    )
    in_agency_fast_context = latest_mode == "agency_plan" or mode_just_confirmed
    if not in_agency_fast_context:
        return False, {}, False
    user_facts = extract_fast_split_facts(user_message)
    merged_facts = _merge_fast_trip_facts(
        latest_fast_split_facts,
        user_facts,
        {"planning_mode": "agency_plan", "active_workflow": "agency_plan"},
    )
    missing = _agency_requirement_missing_items(merged_facts)
    if mode_just_confirmed and missing:
        return True, merged_facts, True
    if latest_mode == "agency_plan" and _has_meaningful_fast_trip_facts(user_facts):
        return True, merged_facts, False
    return False, merged_facts, mode_just_confirmed


async def _conversation_role_counts(
    db: AsyncSession,
    conversation_id: str,
) -> dict[str, int]:
    if not callable(getattr(db, "execute", None)):
        return {}
    result = await db.execute(
        select(Message.role, func.count(Message.id))
        .where(Message.conversation_id == conversation_id)
        .group_by(Message.role)
    )
    return {str(role): int(count) for role, count in result.all()}


async def _should_use_fast_mode_split(
    db: AsyncSession,
    conversation_id: str,
    user_message: str,
) -> bool:
    decision = resolve_planning_mode(
        user_message,
        state={"current_step": "requirement_collection"},
    )
    if not decision.needs_confirmation:
        return False
    try:
        counts = await _conversation_role_counts(db, conversation_id)
    except Exception as exc:
        app_logger.info(
            "Fast mode split skipped because message history count failed: "
            f"conversation_id={conversation_id}, error={exc.__class__.__name__}"
        )
        return False
    return counts.get("user", 0) == 1 and counts.get("assistant", 0) == 0


def _progress_snapshot_from_trip_facts(
    facts: dict | None,
    *,
    planning_mode: str | None = None,
    agency_step: str | None = None,
    long_term_preferences: list | None = None,
    current_trip_preferences: list | None = None,
) -> dict:
    facts = facts if isinstance(facts, dict) else {}
    active_workflow = str(facts.get("active_workflow") or "").strip()
    if not active_workflow and planning_mode in {"agency_plan", "free_planning"}:
        active_workflow = planning_mode
    confirmed = []
    labels = (
        ("departure_city", "出发地"),
        ("destination", "目的地"),
        ("departure_date", "出发时间"),
        ("travel_days", "行程天数"),
        ("adult_count", "人数"),
        ("budget_text", "预算"),
    )
    for key, label in labels:
        value = facts.get(key)
        if value in (None, "", [], {}):
            continue
        display_value = f"{value}天" if key == "travel_days" else f"{value}人" if key == "adult_count" else str(value)
        confirmed.append({"key": key, "label": label, "value": display_value})
    return {
        "version": "travel_progress_snapshot.v1",
        "planning_mode": planning_mode or "pending_confirmation",
        "active_workflow": active_workflow,
        "agency_step": agency_step or "",
        "confirmed_facts": confirmed,
        "long_term_preferences": long_term_preferences or [],
        "current_trip_preferences": current_trip_preferences or [],
        "pending_items": [],
    }


def _current_trip_preferences_from_requirement(requirement: dict | None) -> list[str]:
    if not isinstance(requirement, dict):
        return []
    picked: list[str] = []

    def add(value: object, prefix: str = "") -> None:
        if value in (None, "", [], {}):
            return
        if isinstance(value, list):
            for item in value:
                add(item, prefix=prefix)
            return
        text = str(value).strip()
        if not text or text in {"无", "暂无", "待确认"}:
            return
        candidate = f"{prefix}{text}" if prefix and not text.startswith(prefix) else text
        if candidate not in picked:
            picked.append(candidate)

    add(requirement.get("travel_styles"), prefix="风格：")
    add(requirement.get("food_preferences"), prefix="餐饮：")
    add(requirement.get("accommodation_preferences"), prefix="住宿：")
    add(requirement.get("special_needs"), prefix="需求：")
    return picked[:6]


def _progress_snapshot_from_state(update: dict | None) -> dict:
    if not isinstance(update, dict):
        return {}
    has_explicit_progress_signal = any(
        update.get(key) not in (None, "", [], {})
        for key in (
            "progress_snapshot",
            "user_requirement",
            "confirmed_facts",
            "planning_mode",
            "active_workflow",
            "agency_step",
            "long_term_preferences_snapshot",
            "report_data",
        )
    )
    if not has_explicit_progress_signal:
        return {}
    requirement = update.get("user_requirement")
    if not isinstance(requirement, dict):
        requirement = {}
    confirmed_facts = update.get("confirmed_facts")
    if not isinstance(confirmed_facts, dict):
        confirmed_facts = {}
    report_data = update.get("report_data")
    report_mode = None
    if isinstance(report_data, dict):
        agency_context = report_data.get("agency_context")
        if isinstance(agency_context, dict):
            report_mode = agency_context.get("mode")
    facts = {
        "departure_city": requirement.get("departure_city") or confirmed_facts.get("departure_city"),
        "destination": requirement.get("destination") or confirmed_facts.get("destination"),
        "departure_date": requirement.get("departure_date") or confirmed_facts.get("departure_date"),
        "travel_days": requirement.get("travel_days") or confirmed_facts.get("travel_days"),
        "adult_count": requirement.get("adult_count") or confirmed_facts.get("adult_count"),
        "budget_text": (
            confirmed_facts.get("budget_text")
            or requirement.get("budget_text")
            or (
                f"{requirement.get('budget_min')}-{requirement.get('budget_max')}元/人"
                if requirement.get("budget_min") and requirement.get("budget_max")
                else ""
            )
        ),
    }
    planning_mode = (
        update.get("planning_mode")
        or requirement.get("planning_mode")
        or update.get("active_workflow")
        or report_mode
    )
    long_term_preferences = update.get("long_term_preferences_snapshot")
    if not isinstance(long_term_preferences, list):
        long_term_preferences = []
    return _progress_snapshot_from_trip_facts(
        facts,
        planning_mode=planning_mode,
        agency_step=update.get("agency_step"),
        long_term_preferences=long_term_preferences,
        current_trip_preferences=_current_trip_preferences_from_requirement(requirement),
    )


def _merge_progress_snapshot(previous: dict | None, current: dict | None) -> dict:
    """Merge sparse progress updates without letting weak tool results erase known facts."""

    if not isinstance(previous, dict) or not previous:
        return current if isinstance(current, dict) else {}
    if not isinstance(current, dict) or not current:
        return previous

    merged = {**previous, **current}
    previous_mode = str(previous.get("planning_mode") or "").strip()
    current_mode = str(current.get("planning_mode") or "").strip()
    if (
        previous_mode
        and previous_mode != "pending_confirmation"
        and (not current_mode or current_mode == "pending_confirmation")
    ):
        merged["planning_mode"] = previous_mode
    previous_workflow = str(previous.get("active_workflow") or "").strip()
    current_workflow = str(current.get("active_workflow") or "").strip()
    if (
        previous_workflow
        and previous_workflow != "pending_confirmation"
        and (not current_workflow or current_workflow == "pending_confirmation")
    ):
        merged["active_workflow"] = previous_workflow

    previous_agency_step = str(previous.get("agency_step") or "").strip()
    current_agency_step = str(current.get("agency_step") or "").strip()
    if previous_agency_step and not current_agency_step:
        merged["agency_step"] = previous_agency_step

    def merge_fact_list(key: str) -> None:
        existing = previous.get(key)
        incoming = current.get(key)
        if not isinstance(existing, list):
            existing = []
        if not isinstance(incoming, list):
            incoming = []
        by_key: dict[str, dict] = {}
        ordered_keys: list[str] = []
        for item in [*existing, *incoming]:
            if not isinstance(item, dict):
                continue
            item_key = str(item.get("key") or item.get("label") or "").strip()
            item_value = item.get("value")
            if not item_key or item_value in (None, "", [], {}):
                continue
            if item_key not in by_key:
                ordered_keys.append(item_key)
            by_key[item_key] = item
        if ordered_keys:
            merged[key] = [by_key[item_key] for item_key in ordered_keys]

    merge_fact_list("confirmed_facts")

    for key in ("long_term_preferences", "current_trip_preferences", "pending_items"):
        existing = previous.get(key)
        incoming = current.get(key)
        if not isinstance(existing, list):
            existing = []
        if not isinstance(incoming, list):
            incoming = []
        seen = set()
        merged_items = []
        for item in [*existing, *incoming]:
            marker = str(item)
            if not marker or marker in seen:
                continue
            seen.add(marker)
            merged_items.append(item)
        if merged_items:
            merged[key] = merged_items

    return merged


def _fast_split_state_seed(
    facts: dict | None,
    *,
    planning_mode: str | None = None,
) -> dict:
    facts = facts if isinstance(facts, dict) else {}
    if not facts:
        return {}
    requirement: dict[str, object] = {}
    for source_key, target_key in (
        ("departure_city", "departure_city"),
        ("destination", "destination"),
        ("departure_date", "departure_date"),
        ("travel_days", "travel_days"),
        ("adult_count", "adult_count"),
    ):
        value = facts.get(source_key)
        if value not in (None, "", [], {}):
            requirement[target_key] = value
    if facts.get("budget_text"):
        requirement["budget_text"] = facts["budget_text"]
        requirement["special_needs"] = f"预算：{facts['budget_text']}"
    if planning_mode in {"agency_plan", "free_planning"}:
        requirement["planning_mode"] = planning_mode
        requirement["active_workflow"] = planning_mode
        requirement["planning_mode_confirmed"] = True
    confirmed_facts = {
        key: value
        for key, value in {
            "departure_city": facts.get("departure_city"),
            "destination": facts.get("destination"),
            "departure_date": facts.get("departure_date"),
            "travel_days": facts.get("travel_days"),
            "adult_count": facts.get("adult_count"),
            "budget_text": facts.get("budget_text"),
        }.items()
        if value not in (None, "", [], {})
    }
    agency_step = ""
    if planning_mode == "agency_plan":
        agency_step = (
            "agency_requirement"
            if _agency_requirement_missing_items(facts)
            else "agency_product_match"
        )
    seed = {
        "pending_initial_request_text": facts.get("raw_text", ""),
        "fast_split_facts": dict(facts),
        "progress_snapshot": _progress_snapshot_from_trip_facts(
            facts,
            planning_mode=planning_mode,
            agency_step=agency_step,
        ),
    }
    if requirement:
        seed["user_requirement"] = requirement
    if confirmed_facts:
        seed["confirmed_facts"] = confirmed_facts
    if planning_mode in {"agency_plan", "free_planning"}:
        seed.update(
            {
                "planning_mode": planning_mode,
                "active_workflow": planning_mode,
                "planning_mode_confirmed": True,
                "pending_initial_planning_mode": planning_mode,
                "pending_initial_planning_mode_reason": "用户在首轮分流后明确选择方案类型",
            }
        )
        if planning_mode == "agency_plan":
            seed["current_step"] = "requirement_collection"
            seed["agency_step"] = agency_step or "agency_requirement"
    return seed


async def _load_latest_fast_split_facts_for_turn(
    db: AsyncSession,
    *,
    conversation_id: str,
) -> dict:
    if not callable(getattr(db, "execute", None)):
        return {}
    try:
        result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .where(Message.role == "assistant")
            .order_by(Message.created_at.desc())
            .limit(5)
        )
    except Exception as exc:
        app_logger.info(
            "Fast split facts load skipped: "
            f"conversation_id={conversation_id}, error={exc.__class__.__name__}"
        )
        return {}
    for message in result.scalars().all():
        extra_info = getattr(message, "extra_info", None)
        if not isinstance(extra_info, dict):
            continue
        fast_split = extra_info.get("fast_mode_split")
        if not isinstance(fast_split, dict):
            continue
        facts = fast_split.get("facts") or fast_split.get("fast_split_facts")
        if isinstance(facts, dict) and facts:
            return dict(facts)
    return {}


async def save_message(
        db: AsyncSession,
        conversation_id: str,
        role: str,
        content: str,
        extra_info: dict = None
) -> Message:
    """保存消息到数据库"""

    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        extra_info=extra_info or {}
    )

    db.add(message)
    await db.commit()
    await db.refresh(message)

    return message


def sse(data: dict) -> str:
    """
    SSE 标准 data 帧
    """
    safe_data = redact_sensitive_data(data)
    return f"data: {json.dumps(safe_data, ensure_ascii=False)}\n\n"


def _session_busy_payload(
    conversation_id: str,
    turn_id: str,
    active_lock=None,
) -> dict:
    payload = {
        "type": "session_busy",
        "content": SESSION_BUSY_MESSAGE,
        "conversation_id": conversation_id,
        "turn_id": turn_id,
        "retry_after_seconds": settings.session_lock_busy_retry_after_seconds,
    }
    if active_lock is not None:
        payload["lock_backend"] = active_lock.backend
        payload["active_seconds"] = round(time.time() - active_lock.acquired_at, 2)
        if active_lock.expires_at is not None:
            payload["expires_in_seconds"] = max(
                round(active_lock.expires_at - time.time(), 2),
                0,
            )
    return payload


def _extract_command_update(output) -> dict:
    """Extract LangGraph Command.update from a tool event output."""
    update = getattr(output, "update", None)
    if isinstance(update, dict):
        return update
    if isinstance(output, dict):
        nested_update = output.get("update")
        if isinstance(nested_update, dict):
            return nested_update
    return {}


def _report_extra_info_from_tool_output(output) -> dict:
    """Build persisted message metadata from generate_order_tool output."""
    update = _extract_command_update(output)
    report_data = update.get("report_data")
    if not isinstance(report_data, dict):
        return {}
    report_data = redact_sensitive_data(report_data)

    extra_info = {
        "message_type": "travel_report",
        "report_data": report_data,
    }
    if update.get("order_id"):
        extra_info["order_id"] = update["order_id"]
    return extra_info


def _journey_extra_info_from_tool_output(output) -> dict:
    """Build persisted message metadata from generate_visual_journey_tool output."""
    update = _extract_command_update(output)
    journey_plan = update.get("journey_plan")
    if not isinstance(journey_plan, dict):
        return {}
    extra_info = {
        "message_type": "journey_plan",
        "journey_data": redact_sensitive_data(journey_plan),
    }
    planning_trace = update.get("planning_trace")
    if isinstance(planning_trace, list):
        extra_info["planning_trace"] = redact_sensitive_data(planning_trace)
    return extra_info


def _validated_journey_data(value) -> dict:
    if not isinstance(value, dict) or value.get("version") != JOURNEY_PLAN_VERSION:
        return {}
    ok, _findings = validate_journey_plan(value)
    if not ok:
        return {}
    return redact_sensitive_data(value)


def _latest_journey_data_from_conversation_extra(extra_info: dict | None) -> dict:
    """Return the latest valid journey draft stored on a conversation."""

    if not isinstance(extra_info, dict):
        return {}
    return _validated_journey_data(extra_info.get("latest_journey_data"))


async def _load_latest_journey_data_for_turn(
    db: AsyncSession,
    *,
    conversation_id: str,
    user_id,
) -> dict:
    """Load a saved visual journey draft for the next agent turn."""

    if not callable(getattr(db, "execute", None)):
        return {}
    result = await db.execute(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .where(Conversation.user_id == user_id)
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        return {}

    from_conversation = _latest_journey_data_from_conversation_extra(
        conversation.extra_info
    )
    if from_conversation:
        return from_conversation

    message_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .where(Message.role == "assistant")
        .order_by(Message.created_at.desc())
        .limit(20)
    )
    for message in message_result.scalars().all():
        extra_info = message.extra_info if isinstance(message.extra_info, dict) else {}
        from_message = _validated_journey_data(extra_info.get("journey_data"))
        if from_message:
            return from_message
    return {}


async def _persist_latest_journey_data_on_conversation(
    db: AsyncSession,
    *,
    conversation_id: str,
    user_id,
    journey_data: dict,
    planning_trace: list[dict] | None = None,
    source: str = "generate_visual_journey_tool",
) -> None:
    """Keep conversation.extra_info aligned with the latest journey draft."""

    if not callable(getattr(db, "execute", None)):
        return
    safe_journey_data = _validated_journey_data(journey_data)
    if not safe_journey_data:
        return
    result = await db.execute(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .where(Conversation.user_id == user_id)
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        return
    extra_info = dict(conversation.extra_info or {})
    extra_info["latest_journey_data"] = safe_journey_data
    extra_info["latest_journey_saved_at"] = int(time.time())
    extra_info["latest_journey_source"] = redact_sensitive_text(source)
    if isinstance(planning_trace, list):
        extra_info["latest_planning_trace"] = redact_sensitive_data(planning_trace)
    conversation.extra_info = extra_info
    db.add(conversation)
    await db.commit()


def _merge_journey_draft_extra_info(
    existing_extra_info: dict | None,
    journey_data: dict,
    *,
    source: str = "frontend_editor",
) -> dict:
    extra_info = dict(existing_extra_info or {})
    extra_info["message_type"] = "journey_plan"
    extra_info["journey_data"] = redact_sensitive_data(journey_data)
    extra_info["journey_editor"] = {
        "source": redact_sensitive_text(source or "frontend_editor"),
        "saved_at": int(time.time()),
    }
    return extra_info


def _message_has_journey_data(message: Message) -> bool:
    extra_info = message.extra_info if isinstance(message.extra_info, dict) else {}
    return isinstance(extra_info.get("journey_data"), dict)


def _report_content_from_tool_output(output) -> str:
    """Extract a user-visible report string from generate_order_tool output."""
    update = _extract_command_update(output)
    report = update.get("report")
    if isinstance(report, str) and report.strip():
        return redact_sensitive_text(report)

    messages = update.get("messages")
    if isinstance(messages, list):
        for message in messages:
            content = getattr(message, "content", None)
            if isinstance(content, str) and content.strip():
                return redact_sensitive_text(content)
    return ""


def _journey_content_from_tool_output(output) -> str:
    """Extract a user-visible journey summary from generate_visual_journey_tool."""
    update = _extract_command_update(output)
    messages = update.get("messages")
    if isinstance(messages, list):
        for message in messages:
            content = getattr(message, "content", None)
            if isinstance(content, str) and content.strip():
                return redact_sensitive_text(content)
    journey_plan = update.get("journey_plan")
    if isinstance(journey_plan, dict):
        overview = journey_plan.get("overview") or {}
        title = overview.get("title") or "可视化旅程草案"
        summary = overview.get("summary") or "已生成地图工作台。"
        return redact_sensitive_text(f"{title}已生成。{summary}")
    return ""


def _is_transient_stream_disconnect(exc: Exception) -> bool:
    message = str(exc)
    return (
        "peer closed connection without sending complete message body" in message
        or "incomplete chunked read" in message
    )


def _extract_embedded_tool_audit_events(output) -> list[dict]:
    containers: list[dict] = []
    update = getattr(output, "update", None)
    if isinstance(update, dict):
        containers.append(update)
    artifact = getattr(output, "artifact", None)
    if isinstance(artifact, dict):
        containers.append(artifact)
    if isinstance(output, dict):
        if isinstance(output.get("update"), dict):
            containers.append(output["update"])
        if isinstance(output.get("artifact"), dict):
            containers.append(output["artifact"])
        containers.append(output)
    if isinstance(output, (tuple, list)) and len(output) == 2 and isinstance(output[1], dict):
        containers.append(output[1])

    events: list[dict] = []
    seen_keys: set[tuple] = set()
    for container in containers:
        container_events = container.get("tool_audit_events") or []
        if not isinstance(container_events, list):
            continue
        for event in container_events:
            if not isinstance(event, dict):
                continue
            key = _audit_event_key(event)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            events.append(redact_sensitive_data(event))
    return events


def _audit_event_key(event: dict) -> tuple:
    return (
        event.get("name"),
        event.get("started_at"),
        event.get("status"),
        event.get("error_type"),
    )


def _new_tool_audit_events(events: list[dict], existing_events: list[dict]) -> list[dict]:
    existing_keys = {_audit_event_key(event) for event in existing_events}
    new_events: list[dict] = []
    for event in events:
        key = _audit_event_key(event)
        if key in existing_keys:
            continue
        existing_keys.add(key)
        new_events.append(event)
    return new_events


def _update_observation_from_state_update(
    observation: TurnObservation,
    update: dict,
) -> None:
    if not isinstance(update, dict):
        return
    report_data = update.get("report_data")
    report_mode = None
    if isinstance(report_data, dict):
        agency_context = report_data.get("agency_context")
        if isinstance(agency_context, dict):
            report_mode = agency_context.get("mode")
    observability_context = update.get("observability_context")
    if not isinstance(observability_context, dict):
        observability_context = {}
    observation.update_context(
        current_step=(
            update.get("current_step")
            or observability_context.get("current_step")
            or update.get("context_last_step")
        ),
        planning_mode=(
            update.get("planning_mode")
            or report_mode
            or observability_context.get("planning_mode")
            or update.get("pending_initial_planning_mode")
        ),
        planning_mode_source=(
            observability_context.get("planning_mode_source")
            or "state_update"
        ),
    )
    progress_snapshot = update.get("progress_snapshot")
    if not isinstance(progress_snapshot, dict):
        progress_snapshot = _progress_snapshot_from_state(update)
    progress_snapshot = _merge_progress_snapshot(
        observation.progress_snapshot,
        progress_snapshot,
    )
    observation.set_progress_snapshot(progress_snapshot)


def _safe_stream_error_payload(
    *,
    turn_id: str,
    error_type: str,
) -> dict:
    return {
        "type": "error",
        "turn_id": turn_id,
        "error_type": redact_sensitive_text(error_type),
        "message": "本轮对话处理失败，已记录内部观测信息；请稍后重试或继续下一步。",
    }


def _turn_done_payload(observation: TurnObservation) -> dict:
    payload = {"type": "done", "turn_id": observation.turn_id}
    payload["degradation_status"] = observation.degradation_status
    return payload


async def _persist_tool_audit_events_safely(
        db: AsyncSession,
        *,
        events: list[dict],
        user_id: str,
        conversation_id: str,
) -> dict:
    if not events:
        return {"status": "skipped", "reason": "no_events"}
    events = redact_sensitive_data(events)
    if not callable(getattr(db, "add", None)):
        return {
            "status": "skipped",
            "reason": "non_sqlalchemy_session",
            "persistent": False,
        }
    try:
        await persist_tool_audit_events(
            db,
            events,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        return {"status": "persisted", "count": len(events), "persistent": True}
    except Exception as error:
        rollback = getattr(db, "rollback", None)
        if callable(rollback):
            await rollback()
        error_type = error.__class__.__name__
        ApprovalGovernanceManager.mark_tool_audit_persistence_failed(error)
        app_logger.exception(
            "工具审计事件持久化失败，已保留在消息 extra_info 中: "
            f"conversation_id={conversation_id}, user_id={user_id}"
        )
        return {
            "status": "degraded",
            "persistent": False,
            "error_type": error_type,
            "message": "工具审计事件未能写入 PostgreSQL，已记录降级状态。",
        }


async def generate_sse_stream(
        conversation_id: str,
        user_message: str,
        db: AsyncSession,
        user: User
):
    assistant_message = ""
    request_started_at = time.perf_counter()
    turn_observation = TurnObservation(
        conversation_id=conversation_id,
        user_id=str(user.id),
        user_message=user_message,
    )
    first_token_elapsed = None
    tool_started_at = {}
    tool_audit_context_by_run = {}
    tool_input_by_run = {}
    tool_name_by_run = {}
    tool_audit_events = []
    emitted_tool_call_names = set()
    assistant_extra_info = {}
    fallback_assistant_message = ""
    session_lock = None
    final_report_emitted = False
    thinking_filter = _AssistantThinkingFilter()

    def record_assistant_token(token: str) -> dict:
        nonlocal assistant_message, first_token_elapsed
        assistant_message += token
        turn_observation.record_token(token)
        if first_token_elapsed is None:
            first_token_elapsed = time.perf_counter() - request_started_at
            app_logger.info(
                "SSE first token emitted: "
                f"turn_id={turn_observation.turn_id}, "
                f"conversation_id={conversation_id}, user_id={user.id}, "
                f"elapsed_seconds={first_token_elapsed:.2f}"
            )
        return {
            "type": "token",
            "turn_id": turn_observation.turn_id,
            "content": token,
        }

    try:
        try:
            session_lock = await acquire_session_lock(
                conversation_id,
                wait_seconds=settings.session_lock_acquire_wait_seconds,
            )
        except SessionLockBusy as lock_error:
            active_lock = lock_error.active_lock
            active_since = (
                round(time.time() - active_lock.acquired_at, 2)
                if active_lock is not None
                else None
            )
            app_logger.warning(
                "SSE chat rejected because conversation is busy: "
                f"turn_id={turn_observation.turn_id}, "
                f"conversation_id={conversation_id}, user_id={user.id}, "
                f"active_seconds={active_since}, "
                f"lock_backend={(active_lock.backend if active_lock else 'unknown')}"
            )
            turn_observation.mark_degraded("session_busy")
            turn_observation.finish("busy")
            yield sse(_session_busy_payload(conversation_id, turn_observation.turn_id, active_lock))
            yield sse(turn_observation.to_sse_event())
            yield sse(_turn_done_payload(turn_observation))
            return

        session_lock.start_auto_renew(
            settings.session_lock_renew_interval_seconds
        )
        app_logger.info(
            "SSE chat started: "
            f"turn_id={turn_observation.turn_id}, "
            f"conversation_id={conversation_id}, user_id={user.id}, "
            f"message_length={len(user_message)}, "
            f"lock_backend={session_lock.snapshot.backend}, "
            f"lock_wait_seconds={session_lock.snapshot.wait_seconds:.3f}, "
            f"lock_ttl_seconds={session_lock.snapshot.ttl_seconds:.1f}"
        )
        # 1. 保存用户消息
        await save_message(db, conversation_id, "user", user_message)
        turn_fast_facts = extract_fast_split_facts(user_message)
        turn_has_fast_fact_updates = _should_apply_current_turn_fast_facts(turn_fast_facts)

        if await _should_use_fast_mode_split(db, conversation_id, user_message):
            fast_facts = turn_fast_facts
            assistant_message = _build_fast_mode_split_message(user_message)
            turn_observation.update_context(
                current_step="requirement_collection",
                planning_mode="pending_confirmation",
                planning_mode_source="fast_mode_split",
            )
            turn_observation.set_progress_snapshot(
                _progress_snapshot_from_trip_facts(fast_facts)
            )
            yield sse(record_assistant_token(assistant_message))
            observability_snapshot = turn_observation.finish("completed")
            assistant_extra_info["observability"] = observability_snapshot
            assistant_extra_info["fast_mode_split"] = {
                "needs_confirmation": True,
                "question": _FAST_MODE_SPLIT_QUESTION,
                "facts": fast_facts,
            }
            await save_message(
                db,
                conversation_id,
                "assistant",
                assistant_message,
                extra_info=assistant_extra_info,
            )
            app_logger.info(
                "SSE fast planning-mode split completed without creating travel agent: "
                f"turn_id={turn_observation.turn_id}, conversation_id={conversation_id}, "
                f"user_id={user.id}"
            )
            yield sse(turn_observation.to_sse_event())
            yield sse(_turn_done_payload(turn_observation))
            return

        latest_fast_split_facts = await _load_latest_fast_split_facts_for_turn(
            db,
            conversation_id=conversation_id,
        )
        if turn_has_fast_fact_updates:
            latest_fast_split_facts = _merge_fast_trip_facts(
                latest_fast_split_facts,
                turn_fast_facts,
            )
        mode_decision = resolve_planning_mode(
            user_message,
            state={
                "current_step": "requirement_collection",
                "planning_mode": latest_fast_split_facts.get("planning_mode"),
                "active_workflow": latest_fast_split_facts.get("active_workflow"),
                "planning_mode_confirmed": latest_fast_split_facts.get("planning_mode") == "agency_plan",
            },
        )
        should_fast_agency, agency_facts, mode_just_confirmed = (
            _should_use_fast_agency_requirement_reply(
                latest_fast_split_facts=latest_fast_split_facts,
                user_message=user_message,
                mode_decision=mode_decision,
            )
        )
        if should_fast_agency:
            assistant_message = _fast_agency_requirement_message(
                agency_facts,
                mode_just_confirmed=mode_just_confirmed,
            )
            turn_observation.update_context(
                current_step="agency_requirement",
                planning_mode="agency_plan",
                planning_mode_source="fast_agency_requirement",
            )
            turn_observation.set_progress_snapshot(
                _progress_snapshot_from_trip_facts(
                    agency_facts,
                    planning_mode="agency_plan",
                    agency_step="agency_requirement",
                )
            )
            yield sse(record_assistant_token(assistant_message))
            observability_snapshot = turn_observation.finish("completed")
            assistant_extra_info["observability"] = observability_snapshot
            assistant_extra_info["fast_mode_split"] = {
                "needs_confirmation": False,
                "question": _FAST_MODE_SPLIT_QUESTION,
                "facts": agency_facts,
            }
            await save_message(
                db,
                conversation_id,
                "assistant",
                assistant_message,
                extra_info=assistant_extra_info,
            )
            app_logger.info(
                "SSE fast agency requirement reply completed without creating travel agent: "
                f"turn_id={turn_observation.turn_id}, conversation_id={conversation_id}, "
                f"user_id={user.id}, missing={_agency_requirement_missing_items(agency_facts)}"
            )
            yield sse(turn_observation.to_sse_event())
            yield sse(_turn_done_payload(turn_observation))
            return

        if turn_has_fast_fact_updates:
            snapshot_mode = (
                latest_fast_split_facts.get("planning_mode")
                if latest_fast_split_facts
                else None
            )
            if not snapshot_mode and mode_decision.confirmed:
                snapshot_mode = mode_decision.mode
            turn_observation.set_progress_snapshot(
                _progress_snapshot_from_trip_facts(
                    latest_fast_split_facts or turn_fast_facts,
                    planning_mode=snapshot_mode,
                    agency_step=latest_fast_split_facts.get("agency_step")
                    if latest_fast_split_facts
                    else None,
                )
            )
            yield sse(turn_observation.to_sse_event())

        # 2. 创建 agent
        agent = await create_travel_agent()

        # 3. 关键修复：输入必须是字典格式！
        # LangGraph StateGraph 期望输入是 state 的部分更新
        input_data = {
            "messages": [HumanMessage(content=user_message)],
            "user_id": str(user.id),
            "session_id": conversation_id,
            "turn_id": turn_observation.turn_id,
        }
        if latest_fast_split_facts:
            if mode_decision.confirmed:
                selected_mode = mode_decision.mode
                seed_facts = agency_facts if agency_facts else latest_fast_split_facts
                fast_seed = _fast_split_state_seed(
                    seed_facts,
                    planning_mode=selected_mode,
                )
                input_data.update(fast_seed)
                turn_observation.update_context(
                    current_step=fast_seed.get("agency_step") or fast_seed.get("current_step"),
                    planning_mode=selected_mode,
                    planning_mode_source="fast_split_seed",
                )
                if fast_seed.get("progress_snapshot"):
                    turn_observation.set_progress_snapshot(fast_seed["progress_snapshot"])
                app_logger.info(
                    "Injected first-turn fast split facts into agent state: "
                    f"conversation_id={conversation_id}, mode={selected_mode or 'pending'}"
                )
        latest_journey_data = await _load_latest_journey_data_for_turn(
            db,
            conversation_id=conversation_id,
            user_id=user.id,
        )
        if latest_journey_data:
            input_data["journey_plan"] = latest_journey_data
            app_logger.info(
                "Injected latest visual journey draft into agent state: "
                f"conversation_id={conversation_id}, user_id={user.id}"
            )

        # 4. 使用 astream_events 获取更细粒度的流式输出
        event_stream = agent.astream_events(
            input_data,
            config={
                "recursion_limit": settings.langgraph_recursion_limit,
                "configurable": {
                    "thread_id": conversation_id
                }
            },
            version="v2",
        )
        while True:
            try:
                event = await asyncio.wait_for(
                    anext(event_stream),
                    timeout=_AGENT_EVENT_IDLE_TIMEOUT_SECONDS,
                )
            except StopAsyncIteration:
                break
            kind = event.get("event")

            # 捕获 LLM 流式输出
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    token = thinking_filter.feed(redact_sensitive_text(chunk.content))
                    if token:
                        yield sse(record_assistant_token(token))

            # 或者捕获工具调用信息
            elif kind == "on_tool_start":
                tool_name = event.get("name", "")
                run_id = event.get("run_id", "")
                turn_observation.record_tool_start(tool_name)
                if run_id:
                    tool_started_at[run_id] = time.perf_counter()
                    tool_audit_context_by_run[run_id] = start_tool_audit(tool_name)
                    tool_input_by_run[run_id] = summarize_tool_input(
                        event.get("data", {}).get("input") or {}
                    )
                    tool_name_by_run[run_id] = tool_name
                app_logger.info(
                    "SSE tool started: "
                    f"turn_id={turn_observation.turn_id}, "
                    f"conversation_id={conversation_id}, user_id={user.id}, tool={tool_name}"
                )
                if tool_name and tool_name in emitted_tool_call_names:
                    app_logger.info(
                        "SSE duplicate tool_call event suppressed: "
                        f"conversation_id={conversation_id}, user_id={user.id}, tool={tool_name}"
                    )
                else:
                    if tool_name:
                        emitted_tool_call_names.add(tool_name)
                    yield sse({
                        "type": "tool_call",
                        "turn_id": turn_observation.turn_id,
                        "tool": tool_name,
                    })
            elif kind == "on_tool_end":
                run_id = event.get("run_id", "")
                tool_name = event.get("name", "") or tool_name_by_run.get(run_id, "")
                started_at = tool_started_at.pop(run_id, None)
                audit_context = tool_audit_context_by_run.pop(run_id, None)
                input_summary = tool_input_by_run.pop(run_id, {})
                tool_name_by_run.pop(run_id, None)
                tool_output = event.get("data", {}).get("output")
                state_update = _extract_command_update(tool_output)
                _update_observation_from_state_update(
                    turn_observation,
                    state_update,
                )
                journey_extra_info = _journey_extra_info_from_tool_output(tool_output)
                if journey_extra_info:
                    if not fallback_assistant_message:
                        fallback_assistant_message = _journey_content_from_tool_output(
                            tool_output
                        )
                    assistant_extra_info.update(journey_extra_info)
                    planning_trace = journey_extra_info.get("planning_trace")
                    if isinstance(planning_trace, list):
                        for trace_item in planning_trace:
                            if isinstance(trace_item, dict):
                                yield sse(
                                    {
                                        "type": "planning_trace",
                                        "turn_id": turn_observation.turn_id,
                                        **trace_item,
                                    }
                                )
                    yield sse(
                        {
                            "type": "journey_data",
                            "turn_id": turn_observation.turn_id,
                            "journey_data": journey_extra_info["journey_data"],
                            "planning_trace": journey_extra_info.get("planning_trace", []),
                        }
                    )
                    app_logger.info(
                        "Captured visual journey metadata from tool output: "
                        f"conversation_id={conversation_id}, user_id={user.id}"
                    )
                if tool_name == "generate_order_tool":
                    report_extra_info = _report_extra_info_from_tool_output(
                        tool_output
                    )
                    if report_extra_info:
                        if not fallback_assistant_message:
                            fallback_assistant_message = _report_content_from_tool_output(
                                tool_output
                            )
                        assistant_extra_info.update(report_extra_info)
                        yield sse(
                            {
                                "type": "report_data",
                                "turn_id": turn_observation.turn_id,
                                "report_data": report_extra_info["report_data"],
                                "order_id": report_extra_info.get("order_id"),
                            }
                        )
                        app_logger.info(
                            "Captured structured report metadata from generate_order_tool: "
                            f"conversation_id={conversation_id}, user_id={user.id}"
                        )
                        final_report_emitted = True
                if started_at is not None:
                    elapsed = time.perf_counter() - started_at
                    app_logger.info(
                        "SSE tool finished: "
                        f"turn_id={turn_observation.turn_id}, "
                        f"conversation_id={conversation_id}, user_id={user.id}, "
                        f"tool={tool_name}, elapsed_seconds={elapsed:.2f}"
                    )
                embedded_audit_events = _extract_embedded_tool_audit_events(tool_output)
                if embedded_audit_events:
                    new_audit_events = _new_tool_audit_events(
                        embedded_audit_events,
                        tool_audit_events,
                    )
                    tool_audit_events.extend(new_audit_events)
                    for audit_event in new_audit_events:
                        turn_observation.record_tool_audit_event(audit_event)
                        yield sse(public_tool_audit_event(audit_event))
                elif audit_context is not None:
                    result_validation = validate_tool_output_for_audit(
                        tool_name,
                        tool_output,
                    )
                    audit_event = build_tool_audit_event(
                        audit_context,
                        status=result_validation.status,
                        input_summary=input_summary,
                        output_summary=(
                            result_validation.output_summary
                            or summarize_tool_output(tool_output)
                        ),
                        error_type=result_validation.error_type,
                        evidence_type=evidence_type_for_tool_name(tool_name),
                    )
                    tool_audit_events.append(audit_event)
                    turn_observation.record_tool_audit_event(audit_event)
                    yield sse(public_tool_audit_event(audit_event))
                if final_report_emitted:
                    app_logger.info(
                        "SSE final report emitted; ending stream without model post-processing: "
                        f"turn_id={turn_observation.turn_id}, "
                        f"conversation_id={conversation_id}, user_id={user.id}"
                    )
                    break
            elif kind == "on_tool_error":
                run_id = event.get("run_id", "")
                tool_name = event.get("name", "") or tool_name_by_run.pop(run_id, "")
                tool_started_at.pop(run_id, None)
                audit_context = tool_audit_context_by_run.pop(run_id, None)
                input_summary = tool_input_by_run.pop(run_id, {})
                error = event.get("data", {}).get("error")
                error_type = getattr(error, "__class__", type(error)).__name__ if error else "ToolError"
                if audit_context is not None:
                    audit_event = build_tool_audit_event(
                        audit_context,
                        status="failed",
                        input_summary=input_summary,
                        output_summary={"error_type": error_type},
                        error_type=error_type,
                        evidence_type="mcp_live_query",
                    )
                    tool_audit_events.append(audit_event)
                    turn_observation.record_tool_audit_event(audit_event)
                    yield sse(public_tool_audit_event(audit_event))

            await asyncio.sleep(0)

        # 5. 保存 AI 回复
        tail_token = thinking_filter.finish()
        if tail_token:
            yield sse(record_assistant_token(tail_token))
        if not assistant_message.strip() and fallback_assistant_message:
            assistant_message = _strip_assistant_thinking_content(
                fallback_assistant_message
            )
        else:
            assistant_message = _strip_assistant_thinking_content(
                assistant_message
            )
        if tool_audit_events:
            assistant_extra_info["tool_audit_events"] = tool_audit_events
            audit_persistence = await _persist_tool_audit_events_safely(
                db,
                events=tool_audit_events,
                user_id=str(user.id),
                conversation_id=conversation_id,
            )
            if audit_persistence.get("status") == "degraded":
                assistant_extra_info["tool_audit_persistence"] = audit_persistence
                turn_observation.mark_degraded("tool_audit_persistence_degraded")
        turn_observation.ensure_assistant_text_observed(assistant_message)
        observability_snapshot = turn_observation.finish("completed")
        assistant_extra_info["observability"] = observability_snapshot
        if assistant_message.strip():
            await save_message(
                db,
                conversation_id,
                "assistant",
                assistant_message,
                extra_info=assistant_extra_info,
            )
        if isinstance(assistant_extra_info.get("journey_data"), dict):
            await _persist_latest_journey_data_on_conversation(
                db,
                conversation_id=conversation_id,
                user_id=user.id,
                journey_data=assistant_extra_info["journey_data"],
                planning_trace=assistant_extra_info.get("planning_trace"),
                source="generate_visual_journey_tool",
            )

        total_elapsed = time.perf_counter() - request_started_at
        app_logger.info(
            "SSE chat completed: "
            f"turn_id={turn_observation.turn_id}, "
            f"conversation_id={conversation_id}, user_id={user.id}, "
            f"elapsed_seconds={total_elapsed:.2f}, "
            f"first_token_seconds={(first_token_elapsed if first_token_elapsed is not None else -1):.2f}, "
            f"assistant_chars={len(assistant_message)}, "
            f"degradation_status={turn_observation.degradation_status}, "
            f"estimated_total_tokens={turn_observation.estimated_total_tokens}"
        )
        yield sse(turn_observation.to_sse_event())
        yield sse(_turn_done_payload(turn_observation))

    except asyncio.CancelledError:
        turn_observation.mark_degraded("client_cancelled")
        turn_observation.finish("cancelled")
        app_logger.info(
            "SSE chat stream cancelled: "
            f"turn_id={turn_observation.turn_id}, "
            f"conversation_id={conversation_id}, user_id={user.id}"
        )
        raise
    except Exception as e:
        total_elapsed = time.perf_counter() - request_started_at
        is_stream_timeout = isinstance(e, (asyncio.TimeoutError, TimeoutError))
        if _is_transient_stream_disconnect(e) or is_stream_timeout:
            fallback_reason = (
                "agent_stream_idle_timeout"
                if is_stream_timeout
                else "transient_stream_disconnect"
            )
            app_logger.warning(
                "SSE upstream stream did not finish normally; "
                "finishing turn without emitting user-facing error: "
                f"turn_id={turn_observation.turn_id}, "
                f"conversation_id={conversation_id}, user_id={user.id}, "
                f"elapsed_seconds={total_elapsed:.2f}, assistant_chars={len(assistant_message)}, "
                f"reason={fallback_reason}"
            )
            turn_observation.mark_fallback(fallback_reason)
            tail_token = thinking_filter.finish()
            if tail_token:
                yield sse(record_assistant_token(tail_token))
            if not assistant_message.strip() and fallback_assistant_message:
                assistant_message = _strip_assistant_thinking_content(
                    fallback_assistant_message
                )
            else:
                assistant_message = _strip_assistant_thinking_content(
                    assistant_message
                )
            if not assistant_message.strip():
                if is_stream_timeout:
                    assistant_message = (
                        "这轮处理时间超过预期，我先把已经确认的信息保留住。"
                        "你可以直接继续说下一步，我会接着当前会话往下处理。"
                    )
                else:
                    assistant_message = (
                        "本轮模型流式连接中断，已保留当前规划状态；"
                        "可以继续下一步处理。"
                    )
                if first_token_elapsed is None:
                    first_token_elapsed = total_elapsed
                    turn_observation.ensure_assistant_text_observed(assistant_message)
                    yield sse({
                        "type": "token",
                        "turn_id": turn_observation.turn_id,
                        "content": assistant_message,
                    })
            if tool_audit_events:
                assistant_extra_info["tool_audit_events"] = tool_audit_events
                audit_persistence = await _persist_tool_audit_events_safely(
                    db,
                    events=tool_audit_events,
                    user_id=str(user.id),
                    conversation_id=conversation_id,
                )
                if audit_persistence.get("status") == "degraded":
                    assistant_extra_info["tool_audit_persistence"] = audit_persistence
                    turn_observation.mark_degraded("tool_audit_persistence_degraded")
            turn_observation.ensure_assistant_text_observed(assistant_message)
            observability_snapshot = turn_observation.finish("completed")
            assistant_extra_info["observability"] = observability_snapshot
            if assistant_message.strip():
                await save_message(
                    db,
                    conversation_id,
                    "assistant",
                    assistant_message,
                    extra_info=assistant_extra_info,
                )
            if isinstance(assistant_extra_info.get("journey_data"), dict):
                await _persist_latest_journey_data_on_conversation(
                    db,
                    conversation_id=conversation_id,
                    user_id=user.id,
                    journey_data=assistant_extra_info["journey_data"],
                    planning_trace=assistant_extra_info.get("planning_trace"),
                    source="generate_visual_journey_tool",
                )
            yield sse(turn_observation.to_sse_event())
            yield sse(_turn_done_payload(turn_observation))
            return
        error_type = e.__class__.__name__
        turn_observation.mark_error(error_type)
        turn_observation.finish("failed", error_type=error_type)
        app_logger.exception(
            "SSE chat failed: "
            f"turn_id={turn_observation.turn_id}, "
            f"conversation_id={conversation_id}, user_id={user.id}, "
            f"elapsed_seconds={total_elapsed:.2f}"
        )
        app_logger.exception("❌ SSE 流式对话错误")
        yield sse(turn_observation.to_sse_event())
        yield sse(_safe_stream_error_payload(
            turn_id=turn_observation.turn_id,
            error_type=error_type,
        ))
    finally:
        if session_lock is not None:
            await session_lock.release()
            app_logger.info(
                "SSE chat session lock released: "
                f"conversation_id={conversation_id}, user_id={user.id}"
            )



@router.post("/stream/{conversation_id}")
async def stream_chat(
        conversation_id: str,
        data: MessageCreate,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """
    流式对话（SSE）

    Returns:
        StreamingResponse: SSE 流式响应
    """

    # 验证会话归属
    result = await db.execute(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .where(Conversation.user_id == user.id)
    )

    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在"
        )

    # 返回 SSE 流
    return StreamingResponse(
        generate_sse_stream(conversation_id, data.content, db, user),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # 禁用 Nginx 缓冲
        }
    )


@router.get("/history/{conversation_id}")
async def get_chat_history(
        conversation_id: str,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """获取会话历史消息"""

    # 验证会话归属
    result = await db.execute(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .where(Conversation.user_id == user.id)
    )

    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在"
        )

    # 查询消息
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )

    messages = result.scalars().all()

    return {
        "conversation": redact_sensitive_data(conversation.to_dict()),
        "messages": redact_sensitive_data([m.to_dict() for m in messages]),
    }


@router.patch("/journey/{conversation_id}")
async def save_journey_draft(
        conversation_id: str,
        data: JourneyDraftUpdate,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """Save the latest user-edited journey draft into conversation history."""

    conversation_result = await db.execute(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .where(Conversation.user_id == user.id)
    )
    conversation = conversation_result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在",
        )

    journey_data = data.journey_data
    if not isinstance(journey_data, dict) or journey_data.get("version") != JOURNEY_PLAN_VERSION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="journey_data 必须是 journey_plan.v1 草案",
        )
    ok, findings = validate_journey_plan(journey_data)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "journey_data 校验失败", "findings": findings},
        )

    message_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .where(Message.role == "assistant")
        .order_by(Message.created_at.desc())
        .limit(20)
    )
    assistant_messages = list(message_result.scalars().all())
    target_message = next(
        (message for message in assistant_messages if _message_has_journey_data(message)),
        assistant_messages[0] if assistant_messages else None,
    )
    if not target_message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="当前会话暂无可保存的旅程草案消息",
        )

    target_message.extra_info = _merge_journey_draft_extra_info(
        target_message.extra_info,
        journey_data,
        source=data.source,
    )
    conversation_extra = dict(conversation.extra_info or {})
    conversation_extra["latest_journey_data"] = redact_sensitive_data(journey_data)
    conversation_extra["latest_journey_saved_at"] = int(time.time())
    conversation.extra_info = conversation_extra

    db.add(target_message)
    db.add(conversation)
    await db.commit()
    await db.refresh(target_message)

    app_logger.info(
        "Saved edited journey draft: "
        f"conversation_id={conversation_id}, user_id={user.id}, message_id={target_message.id}"
    )
    return redact_sensitive_data(
        {
            "status": "saved",
            "message_id": str(target_message.id),
            "journey_data": target_message.extra_info.get("journey_data"),
            "saved_at": target_message.extra_info.get("journey_editor", {}).get("saved_at"),
        }
    )
