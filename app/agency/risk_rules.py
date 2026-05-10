"""Agency risk rules that keep product and quote claims honest."""
from __future__ import annotations

from app.agency.models import AgencyProductData, QuotePolicyData


def build_non_commitment_constraints(
    product: AgencyProductData,
    quote_policy: QuotePolicyData | None = None,
) -> list[str]:
    constraints = list(product.get("non_commitments") or [])
    if quote_policy and quote_policy.get("disclaimer"):
        constraints.append(str(quote_policy["disclaimer"]))
    return list(dict.fromkeys(constraints))
