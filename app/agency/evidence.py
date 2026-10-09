"""Evidence helpers for agency product and quote rules."""
from __future__ import annotations

from app.agency.models import AgencyProductData, AgencyRuleEvidence, QuotePolicyData
from app.agency.risk_rules import build_non_commitment_constraints


def build_rule_evidence(
    product: AgencyProductData,
    quote_policy: QuotePolicyData | None,
    categories: dict[str, list[str]] | None = None,
) -> AgencyRuleEvidence:
    category_names = sorted((categories or {}).keys())
    applied_rules = [
        f"产品规则：{product.get('name', '轻量产品')} / {product.get('product_type', '规划服务')}",
        *[f"路线规则：{item}" for item in (product.get("route_rules") or [])[:3]],
    ]
    if quote_policy:
        applied_rules.extend(
            [
                "报价规则：费用包含、费用不含、价格变量和待核验项分列。",
                "报价规则：当前仅为估算，不作为正式合同报价或库存锁价。",
            ]
        )

    return {
        "evidence_type": "agency_rules",
        "mode": product.get("mode", "free_planning"),
        "product_code": product.get("code", ""),
        "product_name": product.get("name", ""),
        "categories": category_names,
        "applied_rules": applied_rules,
        "constraints": build_non_commitment_constraints(product, quote_policy),
        "verification_required": list(
            (quote_policy or {}).get("verification_required") or []
        ),
    }
