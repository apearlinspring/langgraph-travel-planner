"""Typed contracts for agency product and quote rules."""
from __future__ import annotations

from typing import Literal

from typing_extensions import NotRequired, TypedDict


PlanningMode = Literal["free_planning", "agency_plan"]


class AgencyProductData(TypedDict, total=False):
    mode: PlanningMode
    segment: str
    code: str
    name: str
    product_type: str
    positioning: str
    duration_label: str
    budget_level: str
    budget_level_code: str
    matched_signals: list[str]
    route_rules: list[str]
    service_nodes: list[str]
    deliverables: list[str]
    non_commitments: list[str]


class QuotePolicyData(TypedDict, total=False):
    pricing_status: Literal["estimate_only"]
    locked_price: bool
    currency: str
    product_code: str
    product_name: str
    quote_basis: list[str]
    included: list[str]
    excluded: list[str]
    price_variables: list[str]
    confidence: dict
    adjustment_actions: list[str]
    verification_required: list[str]
    disclaimer: str


class AgencyRuleEvidence(TypedDict, total=False):
    evidence_type: Literal["agency_rules"]
    mode: PlanningMode
    product_code: str
    product_name: str
    categories: list[str]
    applied_rules: list[str]
    constraints: list[str]
    verification_required: list[str]


class AgencyContextData(TypedDict, total=False):
    source_type: str
    mode: PlanningMode
    summary: str
    highlights: list[str]
    light_product: AgencyProductData
    quote_policy: QuotePolicyData
    rule_evidence: AgencyRuleEvidence
    categories: dict[str, list[str]]

