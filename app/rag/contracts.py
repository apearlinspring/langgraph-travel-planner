"""
RAG knowledge contracts.

The travel agent still receives tool output as text, but this module defines a
stable evidence shape that downstream prompts, tests, and evaluators can parse.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import NotRequired, TypedDict


CONTRACT_VERSION = "rag.evidence.v1"

PUBLIC_KNOWLEDGE_BASE = "public_destination_guides"
INTERNAL_KNOWLEDGE_BASE = "agency_internal_knowledge"


class RetrievedEvidence(TypedDict):
    """Structured evidence returned by RAG-backed tools."""

    source: str
    source_type: str
    category: str
    visibility: str
    title: str
    snippet: str
    relevance_score: float
    evidence_level: str
    applicable_modes: list[str]
    constraints: list[str]
    user_segments: NotRequired[list[str]]
    budget_levels: NotRequired[list[str]]
    travel_days_range: NotRequired[str]
    regions: NotRequired[list[str]]
    last_reviewed: NotRequired[str]


@dataclass(frozen=True)
class KnowledgeContract:
    """Metadata policy for one knowledge category."""

    category: str
    source_type: str
    visibility: str
    evidence_level: str
    applicable_modes: tuple[str, ...]
    constraints: tuple[str, ...]
    user_segments: tuple[str, ...] = ("general",)
    budget_levels: tuple[str, ...] = ("economy", "comfort", "luxury")
    travel_days_range: str = "1-14"
    regions: tuple[str, ...] = ("general",)
    last_reviewed: str = "2026-05-10"


PUBLIC_DESTINATION_CONTRACT = KnowledgeContract(
    category="destinations",
    source_type="destination_guide",
    visibility="public",
    evidence_level="guide",
    applicable_modes=("free_planning", "agency_plan"),
    constraints=(
        "仅可作为公开攻略参考",
        "门票、开放时间、预约、天气和价格必须出发前二次核实",
        "不得把其他目的地内容用于当前目的地",
    ),
    user_segments=("general", "family", "couple", "senior"),
    regions=("destination_specific",),
)


INTERNAL_CONTRACTS: dict[str, KnowledgeContract] = {
    "products": KnowledgeContract(
        category="products",
        source_type="agency_internal",
        visibility="internal",
        evidence_level="standard",
        applicable_modes=("agency_plan", "free_planning"),
        constraints=(
            "可转化为成熟路线结构、适配人群和方案依据",
            "不得承诺真实库存、成团状态、锁价或履约结果",
            "自由行模式只引用路线结构，不做强销售表达",
        ),
        user_segments=("family", "couple", "senior", "team", "free_planning"),
        regions=("domestic", "general"),
    ),
    "sop": KnowledgeContract(
        category="sop",
        source_type="agency_internal",
        visibility="internal",
        evidence_level="rule",
        applicable_modes=("agency_plan", "free_planning"),
        constraints=(
            "可转化为顾问服务流程和表达原则",
            "不得向用户暴露内部 SOP、工具名、RAG 或文档路径",
        ),
        user_segments=("general",),
        regions=("general",),
    ),
    "pricing": KnowledgeContract(
        category="pricing",
        source_type="agency_internal",
        visibility="internal",
        evidence_level="rule",
        applicable_modes=("agency_plan", "free_planning"),
        constraints=(
            "必须区分真实工具返回、模型估算和待核验价格",
            "不得承诺锁价、余票、房型、支付或免费退改",
            "费用说明必须保留费用包含、不含和待核验边界",
        ),
        user_segments=("general",),
        regions=("general",),
    ),
    "risk": KnowledgeContract(
        category="risk",
        source_type="agency_internal",
        visibility="internal",
        evidence_level="warning",
        applicable_modes=("agency_plan", "free_planning"),
        constraints=(
            "可转化为温和、可行动的风险提醒和 Plan B",
            "不得制造焦虑或替代实时天气、交通、酒店、预约核验",
        ),
        user_segments=("family", "couple", "senior", "team", "general"),
        regions=("general",),
    ),
    "report": KnowledgeContract(
        category="report",
        source_type="agency_internal",
        visibility="internal",
        evidence_level="standard",
        applicable_modes=("agency_plan", "free_planning"),
        constraints=(
            "可用于最终报告结构和禁止内容约束",
            "不得补写无事实来源的客服、优惠、支付链接或真实订单履约信息",
        ),
        user_segments=("general",),
        regions=("general",),
    ),
}


def _join(values: tuple[str, ...]) -> str:
    return "|".join(values)


def _split(value: object, fallback: tuple[str, ...] = ()) -> list[str]:
    if isinstance(value, str) and value:
        return [item.strip() for item in value.split("|") if item.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return list(fallback)


def get_contract(category: str | None, visibility: str | None = None) -> KnowledgeContract:
    """Return a category contract with conservative fallbacks."""

    normalized_visibility = (visibility or "").strip().lower()
    normalized_category = (category or "").strip().lower()
    if normalized_visibility == "public" or normalized_category == "destinations":
        return PUBLIC_DESTINATION_CONTRACT
    return INTERNAL_CONTRACTS.get(
        normalized_category,
        KnowledgeContract(
            category=normalized_category or "general",
            source_type="agency_internal",
            visibility="internal",
            evidence_level="reference",
            applicable_modes=("agency_plan", "free_planning"),
            constraints=(
                "仅可作为内部顾问参考",
                "不得对用户暴露内部文档或作出未核验承诺",
            ),
        ),
    )


def infer_category_from_source(source: object) -> str | None:
    """Infer a knowledge category from a document source path."""

    source_text = str(source or "").replace("\\", "/").lower()
    for category in INTERNAL_CONTRACTS:
        if f"/{category}/" in source_text or source_text.startswith(f"{category}/"):
            return category
    if "/destinations/" in source_text or source_text.endswith("xian.md"):
        return "destinations"
    return None


def infer_category_from_metadata(metadata: dict) -> str | None:
    """Infer a category from metadata first, then source path."""

    category = metadata.get("category")
    if isinstance(category, str) and category:
        return category
    return infer_category_from_source(metadata.get("source"))


def metadata_for_document(
    *,
    source_type: str,
    category: str,
    visibility: str,
) -> dict[str, str]:
    """Build Chroma-safe document metadata for the RAG contract."""

    contract = get_contract(category, visibility)
    knowledge_base = (
        PUBLIC_KNOWLEDGE_BASE if visibility == "public" else INTERNAL_KNOWLEDGE_BASE
    )
    return {
        "contract_version": CONTRACT_VERSION,
        "knowledge_base": knowledge_base,
        "source_type": source_type,
        "category": category,
        "visibility": visibility,
        "evidence_level": contract.evidence_level,
        "applicable_modes": _join(contract.applicable_modes),
        "constraints": _join(contract.constraints),
        "user_segments": _join(contract.user_segments),
        "budget_levels": _join(contract.budget_levels),
        "travel_days_range": contract.travel_days_range,
        "regions": _join(contract.regions),
        "last_reviewed": contract.last_reviewed,
    }


def metadata_list(value: object, fallback: tuple[str, ...] = ()) -> list[str]:
    """Read a pipe-delimited metadata list."""

    return _split(value, fallback)


def normalized_source(metadata: dict) -> str:
    """Return a stable source reference for evidence."""

    source = metadata.get("source") or "unknown"
    try:
        return str(Path(str(source)))
    except (TypeError, ValueError):
        return str(source)

