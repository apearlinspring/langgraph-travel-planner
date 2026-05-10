"""
长期记忆数据模型
使用 Pydantic BaseModel 定义结构化的用户记忆数据
"""
from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime, timezone


class MemoryAuditEntry(BaseModel):
    """
    长期记忆写入审计条目。

    记录来源、理由和置信度，避免无依据地扩大用户画像。
    """
    field: str = Field(..., description="被写入的长期记忆字段")
    value: str = Field(..., description="写入或评估的记忆值")
    source: str = Field(default="user_statement", description="记忆来源")
    reason: str = Field(default="", description="接受或拒绝写入的原因")
    confidence: float = Field(default=0.75, ge=0.0, le=1.0, description="写入置信度")
    scope: str = Field(default="stable", description="stable 或 temporary")
    accepted: bool = Field(default=True, description="是否写入长期记忆")
    recorded_at: Optional[str] = Field(default=None, description="记录时间")


# ============== 用户画像模型 ==============

class UserProfile(BaseModel):
    """
    用户画像
    存储用户的基础偏好和个人信息
    """
    # 旅行风格偏好(可多选)
    travel_styles: list[str] = Field(
        default_factory=list,
        description="旅行风格偏好，如：休闲度假、文化探索、户外冒险、美食之旅"
    )

    # 饮食禁忌/过敏
    dietary_restrictions: list[str] = Field(
        default_factory=list,
        description="饮食禁忌，如：素食、清真、无麸质、海鲜过敏、花生过敏、乳糖不耐受"
    )

    # 饮食偏好
    food_preferences: list[str] = Field(
        default_factory=list,
        description="饮食偏好，如：辣、甜、酸、清淡、重口味、当地特色、火锅、烧烤"
    )

    # 更新时间
    updated_at: Optional[str] = Field(
        default=None,
        description="最后更新时间"
    )

    memory_audit_log: list[MemoryAuditEntry] = Field(
        default_factory=list,
        description="长期画像写入审计记录"
    )


# ============== 出行历史模型 ==============

class TravelRecord(BaseModel):
    """
    单次旅行记录
    """
    destination: str = Field(..., description="目的地")
    start_date: str = Field(..., description="开始日期，格式：YYYY-MM-DD")
    end_date: str = Field(..., description="结束日期，格式：YYYY-MM-DD")
    visited_attractions: list[str] = Field(
        default_factory=list,
        description="游玩过的景点列表"
    )


class AccommodationPreference(BaseModel):
    """
    住宿偏好
    """
    preferred_types: list[str] = Field(
        default_factory=list,
        description="偏好的住宿类型，如：星级酒店、经济酒店、特色民宿、青年旅社"
    )
    avg_budget_per_night: Optional[float] = Field(
        default=None,
        description="平均每晚预算（单位：元）"
    )


class TravelHistory(BaseModel):
    """
    出行历史
    存储用户的历史旅行记录和住宿偏好
    """
    # 已完成的旅行记录
    completed_trips: list[TravelRecord] = Field(
        default_factory=list,
        description="已完成的旅行记录列表"
    )

    # 去过的景点(汇总,用于避免重复推荐)
    visited_attractions: list[str] = Field(
        default_factory=list,
        description="所有去过的景点汇总，用于避免重复推荐"
    )

    # 住宿偏好
    accommodation_preference: AccommodationPreference = Field(
        default_factory=AccommodationPreference,
        description="用户的住宿偏好设置"
    )

    # 更新时间
    updated_at: Optional[str] = Field(
        default=None,
        description="最后更新时间"
    )

    memory_audit_log: list[MemoryAuditEntry] = Field(
        default_factory=list,
        description="出行历史和住宿偏好写入审计记录"
    )


# ============== 完整用户记忆模型 ==============

class UserMemory(BaseModel):
    """
    用户完整长期记忆
    整合用户画像和出行历史
    """
    user_id: str = Field(..., description="用户唯一标识ID")

    profile: UserProfile = Field(
        default_factory=UserProfile,
        description="用户画像信息"
    )

    history: TravelHistory = Field(
        default_factory=TravelHistory,
        description="用户出行历史记录"
    )


class MemoryWriteCandidate(BaseModel):
    """
    单条长期记忆写入候选。

    用于区分稳定偏好/历史事实和本次旅行临时条件，避免把临时上下文污染长期用户画像。
    """
    value: str = Field(..., description="候选记忆内容")
    accepted: bool = Field(..., description="是否允许写入长期记忆")
    scope: str = Field(default="stable", description="stable 或 temporary")
    reason: str = Field(default="", description="接受或拒绝原因")
    source: str = Field(default="user_statement", description="记忆来源")
    confidence: float = Field(default=0.75, ge=0.0, le=1.0, description="置信度")
    evidence: str = Field(default="", description="可解释依据或原始线索摘要")


TEMPORARY_MEMORY_SCOPE_VALUES = {
    "temporary",
    "current_trip",
    "session",
    "this_trip",
    "本次",
    "这次",
    "临时",
}

TEMPORARY_MEMORY_KEYWORDS = (
    "这次",
    "本次",
    "这趟",
    "本趟",
    "这回",
    "这一次",
    "当前行程",
    "这次旅行",
    "临时",
    "今天",
    "明天",
    "后天",
)

STABLE_OVERRIDE_KEYWORDS = (
    "一直",
    "长期",
    "以后",
    "每次",
    "通常",
    "习惯",
    "偏好",
    "过敏",
    "忌口",
    "不能吃",
    "不吃",
    "记住",
)


def normalize_memory_scope(memory_scope: str | None) -> str:
    value = (memory_scope or "stable").strip().casefold()
    return "temporary" if value in TEMPORARY_MEMORY_SCOPE_VALUES else "stable"


def classify_memory_candidate(
    value: str,
    *,
    memory_scope: str | None = None,
    source: str = "user_statement",
    evidence: str | None = None,
) -> MemoryWriteCandidate:
    text = str(value or "").strip()
    if not text:
        return MemoryWriteCandidate(
            value=text,
            accepted=False,
            scope="temporary",
            reason="空内容不写入长期记忆",
            source=source,
            confidence=0.0,
            evidence=evidence or "",
        )

    scope = normalize_memory_scope(memory_scope)
    if scope == "temporary":
        return MemoryWriteCandidate(
            value=text,
            accepted=False,
            scope=scope,
            reason="用户或模型标记为本次旅行临时条件",
            source=source,
            confidence=0.3,
            evidence=evidence or text,
        )

    has_temporary_hint = any(keyword in text for keyword in TEMPORARY_MEMORY_KEYWORDS)
    has_stable_override = any(keyword in text for keyword in STABLE_OVERRIDE_KEYWORDS)
    if has_temporary_hint and not has_stable_override:
        return MemoryWriteCandidate(
            value=text,
            accepted=False,
            scope="temporary",
            reason="内容包含临时行程表达，未体现稳定偏好",
            source=source,
            confidence=0.35,
            evidence=evidence or text,
        )

    return MemoryWriteCandidate(
        value=text,
        accepted=True,
        scope="stable",
        reason="稳定偏好或历史事实，可写入长期记忆",
        source=source,
        confidence=0.9 if has_stable_override else 0.75,
        evidence=evidence or text,
    )


def filter_stable_memory_values(
    values: list[str] | None,
    *,
    memory_scope: str | None = None,
    source: str = "user_statement",
) -> tuple[list[str], list[MemoryWriteCandidate]]:
    candidates = [
        classify_memory_candidate(value, memory_scope=memory_scope, source=source)
        for value in values or []
    ]
    accepted = [candidate.value for candidate in candidates if candidate.accepted]
    rejected = [candidate for candidate in candidates if not candidate.accepted]
    return accepted, rejected


def build_memory_audit_entries(
    field: str,
    values: list[str] | None,
    *,
    memory_scope: str | None = None,
    source: str = "user_statement",
    accepted_only: bool = True,
) -> list[MemoryAuditEntry]:
    entries: list[MemoryAuditEntry] = []
    for value in values or []:
        candidate = classify_memory_candidate(
            value,
            memory_scope=memory_scope,
            source=source,
        )
        if accepted_only and not candidate.accepted:
            continue
        entries.append(
            MemoryAuditEntry(
                field=field,
                value=candidate.value,
                source=candidate.source,
                reason=candidate.reason,
                confidence=candidate.confidence,
                scope=candidate.scope,
                accepted=candidate.accepted,
                recorded_at=datetime.now(timezone.utc).isoformat(),
            )
        )
    return entries
