"""Agency risk rules that keep product and quote claims honest."""
from __future__ import annotations

from typing import Any

from app.agency.models import AgencyProductData, QuotePolicyData


def build_non_commitment_constraints(
    product: AgencyProductData,
    quote_policy: QuotePolicyData | None = None,
) -> list[str]:
    constraints = list(product.get("non_commitments") or [])
    if quote_policy and quote_policy.get("disclaimer"):
        constraints.append(str(quote_policy["disclaimer"]))
    return list(dict.fromkeys(constraints))


def build_report_risk_lines(
    itinerary: list[dict[str, Any]],
    budget: dict[str, Any],
    *,
    weather_info: Any = None,
    max_items: int = 6,
) -> list[str]:
    """Build the report risk list without making unsupported booking claims."""

    risk_lines = [
        "- 实时票价、酒店价格、余票和景点开放情况会变动，均为待二次核验项，正式支付或出发前必须以官方/平台实时结果为准。",
        "- 出发前 24-48 小时待二次核验交通、酒店入住政策、天气和景点预约要求。",
        (
            f"- 天气风险：{weather_info}。优先保留 Plan B 和每日机动时间。"
            if weather_info
            else "- 天气风险：当前缺少可引用的实时天气，出发前 24-48 小时需二次核验并保留 Plan B。"
        ),
        "- 体力风险：每天保留机动时间，不建议把行程塞满；带娃或带老人时优先减少跨区。",
    ]
    for day in itinerary:
        for note in day.get("risk_notes") or []:
            line = f"- Day {day.get('day_number', '')}：{note}".replace("Day ：", "Day：")
            if line not in risk_lines:
                risk_lines.append(line)
            if len(risk_lines) >= max_items:
                return risk_lines
    for item in budget.get("verification_items") or []:
        line = f"- 待核验：{item}"
        if line not in risk_lines:
            risk_lines.append(line)
        if len(risk_lines) >= max_items:
            break
    return risk_lines
