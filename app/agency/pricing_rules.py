"""Reusable budget, quote, and pricing-boundary rules for agency-style reports."""
from __future__ import annotations

from typing import Any

from app.agency.models import AgencyProductData, QuotePolicyData
from app.agency.product_rules import build_light_product, format_light_product_lines
from app.tools.audit import pending_checks_from_audit_events


def budget_confidence_payload(budget: dict[str, Any]) -> dict[str, Any]:
    """Build the shared budget confidence payload used by reports and quotes."""

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


def _confidence_payload(budget: dict[str, Any]) -> dict[str, Any]:
    return budget_confidence_payload(budget)


def _format_money(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.2f} 元"
    return "待确认"


def safe_per_person(amount: float, total_people: int) -> float:
    return amount / max(total_people, 1)


def build_budget_line_item(
    key: str,
    label: str,
    amount: float,
    total_people: int,
    basis: str,
    confidence: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "amount": amount,
        "per_person": safe_per_person(amount, total_people),
        "basis": basis,
        "confidence": confidence,
    }


def build_budget_quality_notes(
    *,
    selected_transport_option: dict[str, Any] | None,
    selected_accommodation: dict[str, Any] | None,
    food_pois: list[dict[str, Any]] | None,
    destination_pois: list[dict[str, Any]] | None,
    itinerary_text: str,
    tool_audit_events: list[dict[str, Any]] | None = None,
) -> dict[str, list[str] | str]:
    """Classify budget evidence into confirmed, estimated, and verification buckets."""

    selected_transport_option = selected_transport_option or {}
    selected_accommodation = selected_accommodation or {}
    food_pois = food_pois or []
    destination_pois = destination_pois or []

    confirmed_items: list[str] = []
    estimated_items: list[str] = []
    verification_items: list[str] = []

    transport_price = selected_transport_option.get("price")
    if isinstance(transport_price, (int, float)) and transport_price > 0:
        confirmed_items.append(
            f"交通：已记录具体交通方案参考价 {transport_price:.0f} 元/人。"
        )
    else:
        estimated_items.append(
            "交通：缺少具体票价，交通 API 未提供具体票价或查询失败，当前按交通方式基准价做兜底估算。"
        )
    verification_items.append("交通：正式购票前复核实时票价、余票、退改签规则和行李限制。")

    hotel_price = selected_accommodation.get("price_per_night")
    hotel_name = selected_accommodation.get("name", "已选酒店")
    if isinstance(hotel_price, (int, float)) and hotel_price > 0:
        confirmed_items.append(
            f"住宿：{hotel_name} 已记录每间夜参考价 {hotel_price:.0f} 元。"
        )
    else:
        estimated_items.append(
            "住宿：缺少已选酒店价格，酒店 MCP 未提供可追溯价格或查询失败，当前按兜底每间夜价格估算。"
        )
    verification_items.append("住宿：入住前复核房型、税费、取消政策、押金和儿童/加床规则。")

    matched_food_names: list[str] = []
    for food_poi in food_pois:
        name = str(food_poi.get("name") or "").strip()
        average_cost = food_poi.get("average_cost")
        if (
            name
            and name in itinerary_text
            and isinstance(average_cost, (int, float))
            and average_cost > 0
        ):
            matched_food_names.append(f"{name} {average_cost:g} 元/人")
    if matched_food_names:
        estimated_items.append(
            f"餐饮：按行程餐饮 POI 人均价估算（{'、'.join(matched_food_names)}）。"
        )
    else:
        estimated_items.append("餐饮：缺少具体餐饮人均价，按餐饮偏好或兜底餐价估算。")
    verification_items.append("餐饮：热门餐厅需复核营业时间、预约、排队风险和节假日价格。")

    paid_attractions: list[str] = []
    for poi in destination_pois:
        name = str(poi.get("name") or "").strip()
        cost = poi.get("estimated_cost")
        if name and name in itinerary_text and isinstance(cost, (int, float)) and cost > 0:
            paid_attractions.append(f"{name} {cost:g} 元/人")
    if paid_attractions:
        estimated_items.append(
            f"景点：按结构化 POI 参考门票估算（{'、'.join(paid_attractions)}）。"
        )
    elif destination_pois:
        estimated_items.append("景点：当前行程未识别到付费 POI，暂按 0 元估算。")
    else:
        estimated_items.append("景点：缺少结构化 POI 费用，按兜底日均景点费用估算。")
    verification_items.append("景点：出发前复核开放日、预约名额、临展收费和儿童/老人优惠。")

    estimated_items.append("其他：市内交通、寄存、临时休息和小额杂费按 100 元/人/天估算。")
    verification_items.append("天气/体力：如切换 Plan B，预算可能随室内场馆、打车或休息安排变化。")
    for audit_check in pending_checks_from_audit_events(tool_audit_events):
        if audit_check not in verification_items:
            verification_items.append(audit_check)

    if len(confirmed_items) >= 2 and len(matched_food_names) >= 1 and destination_pois:
        confidence_level = "中高"
    elif confirmed_items:
        confidence_level = "中"
    else:
        confidence_level = "偏低"

    return {
        "confidence_level": confidence_level,
        "confirmed_items": confirmed_items,
        "estimated_items": estimated_items,
        "verification_items": verification_items,
    }


def format_budget_breakdown(budget: dict[str, Any]) -> list[str]:
    line_items = budget.get("line_items") or []
    if line_items:
        lines = []
        for item in line_items:
            if not isinstance(item, dict):
                continue
            lines.append(
                "- {label}：{amount}（人均 {per_person}）｜{confidence}｜依据：{basis}".format(
                    label=item.get("label", "费用"),
                    amount=_format_money(item.get("amount")),
                    per_person=_format_money(item.get("per_person")),
                    confidence=item.get("confidence", "估算"),
                    basis=item.get("basis", "依据待补充"),
                )
            )
        lines.append(
            f"- 合计：{_format_money(budget.get('total'))}，人均：{_format_money(budget.get('per_person'))}"
        )
        return lines

    return [
        f"- 交通：{_format_money(budget.get('transport'))}",
        f"- 住宿：{_format_money(budget.get('accommodation'))}",
        f"- 餐饮：{_format_money(budget.get('food'))}",
        f"- 景点/体验：{_format_money(budget.get('attractions'))}",
        f"- 其他机动：{_format_money(budget.get('misc'))}",
        f"- 总计：{_format_money(budget.get('total'))}，人均：{_format_money(budget.get('per_person'))}",
    ]


def format_budget_assumptions(budget: dict[str, Any]) -> list[str]:
    assumptions = budget.get("assumptions") or []
    if not assumptions:
        return ["- 费用依据待补充，建议以正式预订页面为准。"]
    return [f"- {assumption}" for assumption in assumptions]


def format_budget_confidence(budget: dict[str, Any]) -> list[str]:
    confidence = budget_confidence_payload(budget)
    confirmed_items = confidence.get("confirmed_items") or []
    estimated_items = confidence.get("estimated_items") or []
    lines = [f"- 预算置信度：{confidence.get('level') or '待评估'}"]
    lines.append("- 已确认/可追溯价格：")
    if confirmed_items:
        lines.extend(f"  - {item}" for item in confirmed_items)
    else:
        lines.append("  - 暂无已确认锁价；当前价格均需以正式预订页为准。")
    lines.append("- 估算项：")
    if estimated_items:
        lines.extend(f"  - {item}" for item in estimated_items)
    else:
        lines.append("  - 暂无估算项。")
    return lines


def format_budget_verification_items(budget: dict[str, Any]) -> list[str]:
    verification_items = budget_confidence_payload(budget).get("verification_items") or []
    lines = ["- 待核验项："]
    if not verification_items:
        lines.append("  - 正式预订或出发前复核票价、酒店、景点开放和天气。")
        return lines
    lines.extend(f"  - {item}" for item in verification_items)
    return lines


def format_budget_fit(requirement: dict[str, Any], budget: dict[str, Any]) -> str:
    per_person = budget.get("per_person")
    budget_min = requirement.get("budget_min")
    budget_max = requirement.get("budget_max")
    if not isinstance(per_person, (int, float)) or not isinstance(budget_max, (int, float)):
        return "预算匹配：缺少用户预算上限，建议人工复核。"
    if per_person <= budget_max:
        if isinstance(budget_min, (int, float)) and per_person < budget_min:
            return "预算匹配：低于用户预算区间，可考虑升级住宿或增加体验项目。"
        return "预算匹配：在人均预算上限内。"
    return "预算匹配：超过用户预算上限，建议先调整住宿、交通或高票价体验。"


def build_adjustment_options(requirement: dict[str, Any], budget: dict[str, Any]) -> list[str]:
    budget_fit = format_budget_fit(requirement, budget)
    options = [
        "- 想更省钱：优先调整住宿区域/档次，或减少高票价体验项目。",
        "- 想更省心：保留当前交通和酒店，增加打车/预约/休息时间预算。",
        "- 想更丰富：当前预算若低于区间，可增加一顿特色餐厅或一个付费体验。",
    ]
    if "超过" in budget_fit:
        options.insert(0, "- 当前估算超过预算上限，建议先从住宿和景点/体验费用开始压缩。")
    elif "低于" in budget_fit:
        options.insert(0, "- 当前估算低于预算区间，可考虑升级住宿、增加特色体验或保留为机动金。")
    return options


def build_budget_summary_lines(
    requirement: dict[str, Any],
    budget: dict[str, Any],
    *,
    product: AgencyProductData | None = None,
) -> list[str]:
    product = product or build_light_product(requirement)
    quote_policy = budget.get("quote_policy") or build_quote_policy(
        requirement,
        budget,
        product=product,
    )
    assumptions = list(budget.get("assumptions") or [])
    return [
        "预算汇总完成：",
        "",
        "预算明细：",
        *format_budget_breakdown(budget),
        "",
        format_budget_fit(requirement, budget),
        "",
        "轻量产品与报价规则：",
        *format_light_product_lines(product),
        *format_quote_policy_lines(quote_policy),
        "",
        "费用依据：",
        *format_budget_assumptions(budget),
        "",
        "关键假设：",
        *[f"- {assumption}" for assumption in assumptions],
        "",
        "预算置信度：",
        *format_budget_confidence(budget),
        "",
        "出发前待核验：",
        *format_budget_verification_items(budget),
    ]


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
