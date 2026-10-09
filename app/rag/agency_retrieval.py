"""
Helpers for turning RAG documents into structured travel-agency evidence.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable

from langchain_core.documents import Document

from app.rag.contracts import (
    CONTRACT_VERSION,
    INTERNAL_KNOWLEDGE_BASE,
    PROHIBITED_DYNAMIC_COMMITMENTS,
    PUBLIC_KNOWLEDGE_BASE,
    RetrievedEvidence,
    evidence_requires_verification,
    freshness_status,
    get_contract,
    infer_category_from_metadata,
    metadata_list,
    normalized_source,
    prohibited_commitments_for_metadata,
)


def _clean_snippet(content: str, limit: int = 600) -> str:
    snippet = " ".join((content or "").split())
    if len(snippet) <= limit:
        return snippet
    return snippet[:limit].rstrip() + "..."


def _extract_title(doc: Document) -> str:
    for line in (doc.page_content or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()[:80]
    source = normalized_source(doc.metadata or {})
    return re.sub(r"\.md$", "", source.replace("\\", "/").split("/")[-1]) or "未命名资料"


def _fallback_score(rank: int) -> float:
    return round(max(0.05, 1.0 - (rank - 1) * 0.12), 3)


def document_to_evidence(
    doc: Document,
    *,
    rank: int = 1,
    fallback_visibility: str = "internal",
) -> RetrievedEvidence:
    """Convert a LangChain document into the module-A evidence contract."""

    metadata = doc.metadata or {}
    category = infer_category_from_metadata(metadata) or "general"
    visibility = str(metadata.get("visibility") or fallback_visibility)
    contract = get_contract(category, visibility)
    score = metadata.get("relevance_score")
    if not isinstance(score, (int, float)):
        score = _fallback_score(rank)
    requires_verification = evidence_requires_verification(metadata)
    if str(metadata.get("requires_verification") or "").strip().lower() == "true":
        requires_verification = True
    prohibited_commitments = (
        metadata_list(
            metadata.get("prohibited_commitments"),
            PROHIBITED_DYNAMIC_COMMITMENTS,
        )
        if requires_verification
        else prohibited_commitments_for_metadata(metadata)
    )

    evidence: RetrievedEvidence = {
        "source": normalized_source(metadata),
        "source_type": str(metadata.get("source_type") or contract.source_type),
        "category": category,
        "visibility": visibility,
        "title": str(metadata.get("title") or _extract_title(doc)),
        "snippet": _clean_snippet(doc.page_content),
        "relevance_score": float(score),
        "evidence_level": str(metadata.get("evidence_level") or contract.evidence_level),
        "applicable_modes": metadata_list(
            metadata.get("applicable_modes"),
            contract.applicable_modes,
        ),
        "constraints": metadata_list(metadata.get("constraints"), contract.constraints),
        "user_segments": metadata_list(metadata.get("user_segments"), contract.user_segments),
        "budget_levels": metadata_list(metadata.get("budget_levels"), contract.budget_levels),
        "travel_days_range": str(
            metadata.get("travel_days_range") or contract.travel_days_range
        ),
        "regions": metadata_list(metadata.get("regions"), contract.regions),
        "last_reviewed": str(metadata.get("last_reviewed") or contract.last_reviewed),
        "freshness_status": str(
            metadata.get("freshness_status")
            or freshness_status(metadata.get("last_reviewed") or contract.last_reviewed)
        ),
        "requires_verification": requires_verification,
        "prohibited_commitments": prohibited_commitments,
    }
    for field in (
        "product_id",
        "source_kind",
        "inventory_status",
        "external_product_ref",
        "destination",
        "theme",
        "duration",
        "service_level",
        "price_band",
        "demo_price_label",
        "product_source",
        "evidence_type",
    ):
        if metadata.get(field):
            evidence[field] = str(metadata[field])
    for field in (
        "audience",
        "persona_tags",
        "service_boundary",
        "quote_basis",
        "price_basis",
        "included",
        "excluded",
        "transport_lodging_basis",
        "verification_items",
    ):
        values = metadata_list(metadata.get(field))
        if values:
            evidence[field] = values
    return evidence


def documents_to_evidence(
    documents: Iterable[Document],
    *,
    visibility: str = "internal",
) -> list[RetrievedEvidence]:
    """Convert ranked documents to evidence items."""

    return [
        document_to_evidence(doc, rank=index, fallback_visibility=visibility)
        for index, doc in enumerate(documents, 1)
    ]


def filter_documents_by_category(
    documents: Iterable[Document],
    expected_category: str | None,
) -> list[Document]:
    """Keep an internal RAG tool scoped to its category contract."""

    docs = list(documents)
    if not expected_category:
        return docs

    matched: list[Document] = []
    unknown: list[Document] = []
    known_mismatches: list[Document] = []
    for doc in docs:
        category = infer_category_from_metadata(doc.metadata or {})
        if category == expected_category:
            matched.append(doc)
        elif category is None:
            unknown.append(doc)
        else:
            known_mismatches.append(doc)

    if matched:
        return matched
    if unknown and not known_mismatches:
        return unknown
    return []


def _product_direction_lines(evidence: list[RetrievedEvidence]) -> list[str]:
    products = [
        item
        for item in evidence
        if item.get("category") == "products" and item.get("product_id")
    ][:3]
    if not products:
        return []

    lines = [
        "",
        "【产品化方向】",
        "以下方向只代表成熟路线样板与服务口径，不能解释为真实库存、锁价或供应商承诺。",
    ]
    for index, item in enumerate(products, 1):
        title = item.get("theme") or item.get("title") or "产品化路线方向"
        product_id = item.get("product_id") or "未标注"
        destination = item.get("destination") or "目的地待定"
        duration = item.get("duration") or "天数待定"
        price_band = item.get("price_band") or "预算档待定"
        demo_price = item.get("demo_price_label") or "示例价待补充"
        inventory_status = item.get("inventory_status") or "demo_only"
        audience = "、".join(item.get("audience") or item.get("user_segments") or ["通用人群"])
        persona_tags = "、".join(item.get("persona_tags") or ["通用画像"])
        service_boundary = "；".join(
            item.get("service_boundary")
            or item.get("constraints")
            or ["仅提供路线结构、服务边界和核验清单"]
        )
        quote_basis = "；".join(
            item.get("quote_basis")
            or ["按规划服务口径说明，交通、住宿、门票等动态费用待二次核验"]
        )
        verification_items = "；".join(
            item.get("verification_items")
            or ["交通票价", "酒店库存", "景区预约", "天气与人流"]
        )
        lines.extend(
            [
                f"{index}. {title}（{product_id}，{destination}，{duration}，{price_band}，{demo_price}）",
                f"- 适用人群：{audience}",
                f"- 画像标签：{persona_tags}",
                f"- 服务边界：{service_boundary}",
                f"- 报价口径：{quote_basis}",
                f"- 待核验项：{verification_items}",
                f"- 库存口径：{inventory_status}，不得解释为已成团、已占位或已锁价。",
            ]
        )
    lines.extend(
        [
            "",
            "【模式边界】",
            "- 面向用户时不要说内部知识库、RAG、工具名或产品编号；只表达为成熟路线样板、合作产品候选或省心路线方向。",
            "- 如果用户不接受这些产品化方向，必须明确切回自由规划，只保留路线、预算、住宿区域和核验建议。",
            "- 切回自由规划后，不要继续强推旅行社方案或省心套餐。",
        ]
    )
    return lines


def format_evidence_response(
    *,
    query: str,
    documents: Iterable[Document],
    visibility: str,
    empty_message: str | None = None,
    include_product_directions: bool = False,
) -> str:
    """Format evidence as agent-readable text with a JSON contract block."""

    knowledge_base = (
        PUBLIC_KNOWLEDGE_BASE if visibility == "public" else INTERNAL_KNOWLEDGE_BASE
    )
    evidence = documents_to_evidence(documents, visibility=visibility)
    result_status = "hit" if evidence else "empty"
    payload = {
        "contract_version": CONTRACT_VERSION,
        "knowledge_base": knowledge_base,
        "query": query,
        "result_status": result_status,
        "evidence": evidence,
    }
    lines = [
        "【RAG 检索证据契约】",
        json.dumps(payload, ensure_ascii=False, indent=2),
        "",
        "【顾问使用规则】",
        "- 先把证据转化为顾问判断，再面向用户表达。",
        "- 不要向用户暴露内部知识库、RAG、工具名或内部文档路径。",
        "- 涉及价格、库存、余票、房型、开放时间、预约、天气和节假日人流时，必须标记待二次核实。",
        "- 如果证据 requires_verification 为 true，或 freshness_status 不是 current，只能作为待核验依据；不得生成锁价、库存、支付、预订或客服承诺。",
    ]
    if not evidence:
        lines.extend(["", empty_message or f"未找到与「{query}」相关的信息。"])
        return "\n".join(lines)

    lines.append("")
    lines.append("【资料摘要】")
    for index, item in enumerate(evidence, 1):
        constraints = "；".join(item["constraints"][:2])
        verification_label = "待核验" if item.get("requires_verification") else "当前有效"
        prohibited = "、".join(item.get("prohibited_commitments") or [])
        lines.extend(
            [
                (
                    f"【资料 {index} | {item['category']} | "
                    f"{item['evidence_level']} | {verification_label} | "
                    f"score={item['relevance_score']:.2f}】"
                ),
                item["snippet"],
                f"来源：{item['source']}",
                f"适用模式：{', '.join(item['applicable_modes'])}",
                f"使用边界：{constraints}",
                f"复审状态：{item.get('freshness_status', 'unknown')}，last_reviewed={item.get('last_reviewed', 'unknown')}",
            ]
        )
        if prohibited:
            lines.append(f"禁止承诺：{prohibited}")
    if include_product_directions:
        lines.extend(_product_direction_lines(evidence))
    return "\n".join(lines)
