"""Reusable quote and pricing-boundary rules for agency-style reports."""
from __future__ import annotations

from typing import Any

from app.agency.models import AgencyProductData, QuotePolicyData
from app.agency.product_rules import build_light_product


def _confidence_payload(budget: dict[str, Any]) -> dict[str, Any]:
    existing = budget.get("budget_confidence")
    if isinstance(existing, dict) and existing:
        return {
            "level": existing.get("level") or budget.get("confidence_level") or "待评估",
            "confirmed_items": list(existing.get("confirmed_items") or budget.get("confirmed_items") or []),
            "estimated_items": list(existing.get("estimated_items") or budget.get("estimated_items") or []),
            "verification_items": list(existing.get("verification_items") or budget.get("verification_items") or []),
        }
    return {
        "level": budget.get("confidence_level") or "待评估",
        "confirmed_items": list(budget.get("confirmed_items") or []),
        "estimated_items": list(budget.get("estimated_items") or []),
        "verification_items": list(budget.get("verification_items") or []),
    }


def _people_duration_basis(requirement: dict[str, Any], budget: dict[str, Any]) -> str:
    total_people = budget.get("total_people") or (
        (requirement.get("adult_count") or 0) + (requirement.get("children_count") or 0)
    )
    travel_days = budget.get("travel_days") or requirement.get("travel_days") or 1
    nights = budget.get("nights")
    if not isinstance(nights, int):
        nights = max(int(travel_days or 1) - 1, 0)
    people_label = f"{total_people} 人" if total_people else "人数待确认"
    return f"按 {people_label}、{travel_days}天{nights}晚估算。"


def _line_item_basis(line_items: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in line_items:
        if not isinstance(item, dict):
            continue
        label = item.get("label") or "费用"
        basis = item.get("basis") or "依据待补充"
        confidence = item.get("confidence") or "估算"
        lines.append(f"{label}：{basis}（{confidence}）")
    return lines


def _price_variables(product: AgencyProductData) -> list[str]:
    variables = [
        "出发日期、节假日和周末会影响交通、酒店和景点价格。",
        "酒店区域、房型、晚数、房间数和早餐政策会影响住宿预算。",
        "热门景点、演出、讲解和亲子体验需要按预约规则复核。",
    ]
    if product.get("segment") == "family":
        variables.append("儿童年龄、身高、床位和亲子房政策会影响门票与住宿费用。")
    if product.get("segment") == "team":
        variables.append("团队人数、用餐容量、统一交通和活动空间会影响总价。")
    return variables


def _adjustment_actions(requirement: dict[str, Any], budget: dict[str, Any]) -> list[str]:
    line_items = [item for item in budget.get("line_items") or [] if isinstance(item, dict)]
    max_item = max(line_items, key=lambda item: item.get("amount") or 0, default={})
    per_person = budget.get("per_person")
    budget_max = requirement.get("budget_max")
    actions: list[str] = []
    if isinstance(per_person, (int, float)) and isinstance(budget_max, (int, float)):
        if per_person > budget_max:
            label = max_item.get("label") or "住宿或高价体验"
            actions.append(f"当前若超预算，优先从{label}开始压缩，保留核心体验和安全余量。")
        else:
            actions.append("当前估算在人均预算上限内，建议把价格波动项留作机动金。")
    actions.extend(
        [
            "想更省心时，优先保留已查证交通和住宿，把调整集中在餐饮档位或体验数量。",
            "想更省钱时，先比较住宿区域/房型，再减少高票价体验。",
            "想升级体验时，优先增加特色餐厅、预约体验或更便利住宿位置。",
        ]
    )
    return actions[:4]


def build_quote_policy(
    requirement: dict[str, Any],
    budget: dict[str, Any],
    *,
    product: AgencyProductData | None = None,
    state: dict[str, Any] | None = None,
) -> QuotePolicyData:
    product = product or build_light_product(requirement, state)
    confidence = _confidence_payload(budget)

    return {
        "pricing_status": "estimate_only",
        "locked_price": False,
        "currency": budget.get("currency", "CNY"),
        "product_code": product.get("code", ""),
        "product_name": product.get("name", "轻量规划服务"),
        "quote_basis": [
            _people_duration_basis(requirement, budget),
            *_line_item_basis(list(budget.get("line_items") or [])),
        ],
        "included": [
            "规划服务：需求确认、路线骨架、每日动线、强度控制和 Plan B 建议。",
            "预算说明：交通、住宿、餐饮、景点/体验和其他机动费用拆分。",
            "风险管理：预算置信度、待核验清单、降本/升级方向和出发前提醒。",
        ],
        "excluded": [
            "不含机票、火车票、酒店、门票、餐饮等实际代付费用。",
            "不含保险、签证、个人购物、临时加项和不可抗力产生的差额。",
            "不承诺真实库存、成团状态、余位、酒店占房或价格锁定。",
        ],
        "price_variables": _price_variables(product),
        "confidence": confidence,
        "adjustment_actions": _adjustment_actions(requirement, budget),
        "verification_required": list(confidence.get("verification_items") or []),
        "disclaimer": "当前为旅行规划报价估算，不等同正式合同报价或库存锁价。",
    }


def format_quote_policy_lines(quote_policy: QuotePolicyData) -> list[str]:
    if not quote_policy:
        return ["- 报价规则待补充。"]
    confidence = quote_policy.get("confidence") or {}
    lines = [
        f"- 报价性质：{quote_policy.get('disclaimer', '当前为估算报价，不承诺锁价。')}",
        f"- 预算置信度：{confidence.get('level', '待评估')}",
    ]
    if quote_policy.get("included"):
        lines.append("- 费用包含口径：" + "；".join(quote_policy["included"][:3]))
    if quote_policy.get("excluded"):
        lines.append("- 费用不含口径：" + "；".join(quote_policy["excluded"][:3]))
    if quote_policy.get("price_variables"):
        lines.append("- 价格影响变量：" + "；".join(quote_policy["price_variables"][:3]))
    if quote_policy.get("adjustment_actions"):
        lines.append("- 调价动作：" + "；".join(quote_policy["adjustment_actions"][:3]))
    return lines
