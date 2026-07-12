"""Deterministic industrial metrics for live Agent evaluation snapshots."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.evaluation.report_quality import CriterionResult
from app.evaluation.scenarios import EvaluationScenario
from app.evaluation.scoring import as_dict as _as_dict, as_list as _as_list, grade as _grade
from app.evaluation.tool_quality import (
    REDUNDANCY_TRACKED_TOOLS,
    ToolCallRecord,
    extract_tool_events,
)


AGENT_METRICS_VERSION = "agent_industrial_metrics.v1"
DEFAULT_AGENT_METRICS_THRESHOLD = 80.0
DEFAULT_UNSUPPORTED_CLAIM_CATEGORIES = (
    "price",
    "inventory",
    "transport_schedule",
    "hotel_availability",
    "weather",
    "booking",
)
STATE_TRANSITION_TOOLS = frozenset(
    {
        "record_requirement_tool",
        "set_planning_mode_tool",
        "confirm_planning_mode_tool",
        "record_evidence_bundle_tool",
        "select_destination_tool",
        "select_transport_tool",
        "select_accommodation_tool",
        "select_food_tool",
        "generate_itinerary_tool",
        "summarize_budget_tool",
        "generate_order_tool",
        "go_back_to_requirement",
        "go_back_to_destination",
        "go_back_to_transport",
        "go_back_to_accommodation",
        "go_back_to_food",
        "go_back_to_itinerary",
        "go_back_to_budget",
        "check_current_progress",
    }
)
IGNORED_PRECISION_TOOLS = STATE_TRANSITION_TOOLS | frozenset(
    {
        "save_user_memory_tool",
        "search_user_memory_tool",
        "upsert_memory_tool",
        "retrieve_memory_tool",
    }
)
DEFAULT_ALLOWED_DOMAIN_TOOLS = frozenset(REDUNDANCY_TRACKED_TOOLS) | frozenset(
    {
        "query_hotel_options",
        "query_transport_options",
        "query_destination_info",
        "search_agency_product_templates",
        "search_agency_service_sop",
        "search_agency_pricing_rules",
        "search_agency_risk_playbook",
        "search_agency_report_standards",
    }
)
INTENT_TOOL_SIGNALS = {
    "query_hotel_options": "hotel_query",
    "searchHotels": "hotel_query",
    "getHotelDetail": "hotel_query",
    "query_transport_options": "transport_query",
    "query_train_options": "transport_query",
    "query_flight_options": "transport_query",
    "query_driving_route": "transport_query",
    "query_trains": "transport_query",
    "query_flights": "transport_query",
    "get-tickets": "transport_query",
    "searchFlightItineraries": "transport_query",
    "query_destination_info": "destination_query",
    "get_weather_forecast": "weather_query",
    "search_agency_pricing_rules": "pricing_query",
    "search_agency_risk_playbook": "risk_query",
}
INTENT_TAG_SIGNALS = {
    "pricing": "pricing_query",
    "budget": "pricing_query",
    "risk": "risk_query",
    "weather": "weather_query",
    "hotel": "hotel_query",
    "transport": "transport_query",
}
CLAIM_SUPPORT_TOOLS = {
    "price": {
        "query_hotel_options",
        "query_transport_options",
        "query_train_options",
        "query_flight_options",
        "searchHotels",
        "get-tickets",
        "searchFlightItineraries",
    },
    "inventory": {
        "query_hotel_options",
        "query_transport_options",
        "query_train_options",
        "query_flight_options",
        "searchHotels",
        "getHotelDetail",
        "get-tickets",
        "searchFlightItineraries",
    },
    "transport_schedule": {
        "query_transport_options",
        "query_train_options",
        "query_flight_options",
        "query_trains",
        "query_flights",
        "get-tickets",
        "searchFlightItineraries",
    },
    "hotel_availability": {
        "query_hotel_options",
        "searchHotels",
        "getHotelDetail",
    },
    "weather": {
        "query_destination_info",
        "get_weather_forecast",
    },
    "booking": set(),
}
CLAIM_SUPPORT_EVIDENCE_TYPES = {
    "price": {"live_transport_query", "live_hotel_search", "mcp_live_query"},
    "inventory": {"live_transport_query", "live_hotel_search", "mcp_live_query"},
    "transport_schedule": {"live_transport_query", "mcp_live_query"},
    "hotel_availability": {"live_hotel_search", "mcp_live_query"},
    "weather": {"destination_router_evidence", "mcp_live_query"},
    "booking": set(),
}
TOOL_SUPPORT_EVIDENCE_TYPES = {
    "query_hotel_options": {"live_hotel_search"},
    "query_transport_options": {"live_transport_query"},
    "query_train_options": {"live_transport_query"},
    "query_flight_options": {"live_transport_query"},
    "query_trains": {"live_transport_query"},
    "query_flights": {"live_transport_query"},
    "searchHotels": {"mcp_live_query"},
    "getHotelDetail": {"mcp_live_query"},
    "get-tickets": {"mcp_live_query"},
    "searchFlightItineraries": {"mcp_live_query"},
    "query_destination_info": {"destination_router_evidence"},
    "get_weather_forecast": {"mcp_live_query"},
}
CLAIM_PATTERNS = {
    "price": re.compile(
        r"(?:价格|票价|房价|费用|报价|总价|人均).{0,16}"
        r"(?:已确认|已锁定|锁定|最终|准确|实时|固定).{0,24}(?:\d|元|¥|￥)"
        r"|(?:¥|￥)?\d+(?:\.\d+)?\s*元(?:/晚|/人|起)?.{0,16}"
        r"(?:已确认|已锁定|可直接下单|最终价|准确)",
        re.IGNORECASE,
    ),
    "inventory": re.compile(
        r"(?:库存|名额|余位|席位).{0,20}(?:充足|已锁定|已预留|可订|有)",
        re.IGNORECASE,
    ),
    "transport_schedule": re.compile(
        r"(?:车次|航班|班次|高铁|火车|机票).{0,20}"
        r"(?:已确认|有票|余票|已出票|可订|准点)",
        re.IGNORECASE,
    ),
    "hotel_availability": re.compile(
        r"(?:酒店|房间|客房|房型).{0,20}"
        r"(?:有房|已锁房|已预留|库存充足|可直接下单|可订)",
        re.IGNORECASE,
    ),
    "weather": re.compile(
        r"(?:天气|下雨|暴雨|台风|雨季).{0,20}(?:一定|保证|确定|不会|绝对)",
        re.IGNORECASE,
    ),
    "booking": re.compile(
        r"(?:支付链接|直接付款|已下单|订单已确认|已预订|已出票|已锁单)",
        re.IGNORECASE,
    ),
}
QUALIFIED_CLAIM_PATTERN = re.compile(
    r"待核验|二次核验|待确认|需确认|以实际|以平台|估算|预估|参考|"
    r"(?:大约|约合|约)\s*(?:¥|￥)?\d+(?:\.\d+)?|"
    r"以官方|以.*为准|未锁定|不锁|暂未|不可保证|不能保证|"
    r"核验|核实|复核|需复核|可能|预计|"
    r"estimate|estimated|verify|verification|pending|subject to|not |no |"
    r"unconfirmed|do not promise|not lock|not locked|not a formal",
    re.IGNORECASE,
)
VERIFICATION_ACTION_PATTERN = re.compile(
    r"(?:^|[：:，,、；;\s])确认.{0,32}"
    r"(?:具体|实时|车次|班次|时段|票价|余票|库存|名额|房型|含早|取消政策|报价|规则)",
    re.IGNORECASE,
)
VERIFICATION_SECTION_PATTERN = re.compile(
    r"待核验|二次核验|待确认|出发前(?:需|请)?确认|出发前(?:需|请)?核验",
    re.IGNORECASE,
)
MARKDOWN_HEADING_PATTERN = re.compile(
    r"^(?:#{1,6}\s+|\*\*.+\*\*\s*$|【.+】\s*$)"
)
MARKDOWN_LIST_ITEM_PATTERN = re.compile(
    r"^(?:(?:[-*+•]\s+)|(?:\d+[.)、]\s*))"
)
STRUCTURED_VERIFICATION_FIELDS = frozenset(
    {
        "estimated_items",
        "pending_checks",
        "verification_items",
        "verification_required",
    }
)


@dataclass
class AgentMetricsResult:
    """Deterministic industrial Agent metrics for one live run snapshot."""

    total_score: float
    max_score: float
    normalized_score: float
    grade: str
    passed: bool
    criteria: list[CriterionResult]
    summary: list[str]
    metric_values: dict[str, Any] = field(default_factory=dict)
    expectations: dict[str, Any] = field(default_factory=dict)
    observed: dict[str, Any] = field(default_factory=dict)
    unsupported_claims: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": AGENT_METRICS_VERSION,
            "total_score": self.total_score,
            "max_score": self.max_score,
            "normalized_score": self.normalized_score,
            "grade": self.grade,
            "passed": self.passed,
            "summary": self.summary,
            "metric_values": self.metric_values,
            "expectations": self.expectations,
            "observed": self.observed,
            "unsupported_claims": self.unsupported_claims,
            "criteria": [criterion.to_dict() for criterion in self.criteria],
        }


def _string_set(value: Any) -> set[str]:
    return {
        str(item).strip()
        for item in _as_list(value)
        if isinstance(item, str) and item.strip()
    }


def _scenario_expectations(scenario: EvaluationScenario) -> dict[str, Any]:
    raw = _as_dict(getattr(scenario, "metric_expectations", {}))
    tags = set(scenario.tags)
    tools = _as_dict(raw.get("tools"))
    inferred_required: set[str] = set()
    inferred_optional: set[str] = set()
    inferred_forbidden: set[str] = set()

    if "hotel" in tags:
        inferred_required.add("query_hotel_options")
    if "transport" in tags:
        inferred_required.add("query_transport_options")
    if {"destination", "weather", "risk", "nearby", "city"} & tags:
        inferred_optional.add("query_destination_info")
    if "agency" in tags:
        inferred_optional.update(
            {
                "search_agency_product_templates",
                "search_agency_service_sop",
                "search_agency_pricing_rules",
                "search_agency_risk_playbook",
                "search_agency_report_standards",
            }
        )
    if "free" in tags and "budget" in tags and "transport" not in tags and "hotel" not in tags:
        inferred_forbidden.update({"query_hotel_options", "query_transport_options"})

    intent = _as_dict(raw.get("intent"))
    expected_intent = str(intent.get("expected") or scenario.expected_mode).strip()
    accepted_intents = _string_set(intent.get("accepted"))
    accepted_intents.add(expected_intent)
    accepted_intents.add(scenario.expected_mode)

    return {
        "intent": {
            "expected": expected_intent,
            "accepted": sorted(accepted_intents),
        },
        "tools": {
            "required": sorted(inferred_required | _string_set(tools.get("required"))),
            "optional": sorted(inferred_optional | _string_set(tools.get("optional"))),
            "allowed": sorted(_string_set(tools.get("allowed"))),
            "forbidden": sorted(inferred_forbidden | _string_set(tools.get("forbidden"))),
            "strict": bool(tools.get("strict", False)),
        },
        "stage": {
            "expected_transition_tools": sorted(
                _string_set(_as_dict(raw.get("stage")).get("expected_transition_tools")),
                key=lambda item: _as_list(_as_dict(raw.get("stage")).get("expected_transition_tools")).index(item)
                if item in _as_list(_as_dict(raw.get("stage")).get("expected_transition_tools"))
                else 0,
            ),
            "strict": bool(_as_dict(raw.get("stage")).get("strict", False)),
        },
        "unsupported_claims": {
            "strict": bool(_as_dict(raw.get("unsupported_claims")).get("strict", True)),
            "categories": sorted(
                _string_set(_as_dict(raw.get("unsupported_claims")).get("categories"))
                or set(DEFAULT_UNSUPPORTED_CLAIM_CATEGORIES)
            ),
        },
    }


def _observed_intents(
    *,
    scenario: EvaluationScenario,
    records: list[ToolCallRecord],
    report_data: dict[str, Any] | None,
) -> set[str]:
    observed: set[str] = set()
    report = _as_dict(report_data)
    agency_context = _as_dict(report.get("agency_context"))
    mode = agency_context.get("mode")
    if isinstance(mode, str) and mode.strip():
        observed.add(mode.strip())
    elif report:
        observed.add(scenario.expected_mode)
    if report:
        observed.add("final_report_request")
    for record in records:
        signal = INTENT_TOOL_SIGNALS.get(record.tool)
        if signal:
            observed.add(signal)
    if _as_dict(report.get("quote_policy")) or _as_dict(report.get("budget_confidence")):
        observed.add("pricing_query")
    if _as_list(report.get("risks")) or _as_list(report.get("adjustment_options")):
        observed.add("risk_query")
    if _as_dict(report.get("accommodation")):
        observed.add("hotel_query")
    if _as_dict(report.get("transport")):
        observed.add("transport_query")
    for tag in scenario.tags:
        signal = INTENT_TAG_SIGNALS.get(tag)
        if signal and signal in observed:
            observed.add(signal)
    return observed


def _criterion_intent_accuracy(
    *,
    expectations: dict[str, Any],
    observed_intents: set[str],
) -> tuple[CriterionResult, float]:
    intent = _as_dict(expectations.get("intent"))
    accepted = _string_set(intent.get("accepted"))
    matched = sorted(accepted & observed_intents)
    findings: list[str] = []
    score = 20.0 if matched else 0.0
    if not matched:
        findings.append(
            "Expected intent not observed; "
            f"accepted={sorted(accepted)}, observed={sorted(observed_intents)}"
        )
    return CriterionResult("intent_accuracy", score, 20.0, findings), 1.0 if matched else 0.0


def _tool_precision_recall(
    *,
    records: list[ToolCallRecord],
    expectations: dict[str, Any],
) -> tuple[CriterionResult, CriterionResult, dict[str, Any]]:
    tool_expectations = _as_dict(expectations.get("tools"))
    required = _string_set(tool_expectations.get("required"))
    optional = _string_set(tool_expectations.get("optional"))
    configured_allowed = _string_set(tool_expectations.get("allowed"))
    forbidden = _string_set(tool_expectations.get("forbidden"))
    strict = bool(tool_expectations.get("strict"))
    called_counter = Counter(record.tool for record in records)
    called_tools = set(called_counter)
    called_forbidden = sorted(called_tools & forbidden)

    allowed = required | optional | configured_allowed
    if not strict:
        allowed |= DEFAULT_ALLOWED_DOMAIN_TOOLS
    precision_domain = called_tools - IGNORED_PRECISION_TOOLS
    allowed_called = precision_domain & allowed
    unexpected_called = sorted((precision_domain - allowed) | set(called_forbidden))

    if not precision_domain:
        precision = 1.0 if not called_forbidden else 0.0
    else:
        precision = len(allowed_called) / len(precision_domain)
        if called_forbidden:
            precision = min(precision, max(0.0, 1.0 - len(called_forbidden) / len(called_tools or {1})))
    recall = 1.0 if not required else len(required & called_tools) / len(required)

    precision_findings: list[str] = []
    recall_findings: list[str] = []
    if called_forbidden:
        precision_findings.append("Forbidden tool calls observed: " + ", ".join(called_forbidden))
    if strict and unexpected_called:
        precision_findings.append("Unexpected domain tool calls: " + ", ".join(unexpected_called[:5]))
    missing = sorted(required - called_tools)
    if missing:
        recall_findings.append("Missing required tool calls: " + ", ".join(missing))

    precision_score = round(precision * 20.0, 2)
    recall_score = round(recall * 20.0, 2)
    details = {
        "tool_call_precision": round(precision, 4),
        "tool_call_recall": round(recall, 4),
        "required_tools": sorted(required),
        "optional_tools": sorted(optional),
        "allowed_tools": sorted(allowed),
        "forbidden_tools": sorted(forbidden),
        "called_tools": dict(sorted(called_counter.items())),
        "called_forbidden_tools": called_forbidden,
        "unexpected_tools": unexpected_called if strict else [],
    }
    return (
        CriterionResult("tool_call_precision", precision_score, 20.0, precision_findings),
        CriterionResult("tool_call_recall", recall_score, 20.0, recall_findings),
        details,
    )


def _ordered_match_count(expected: list[str], observed: list[str]) -> int:
    if not expected:
        return 0
    index = 0
    matched = 0
    for tool in observed:
        if index < len(expected) and tool == expected[index]:
            matched += 1
            index += 1
    return matched


def _criterion_stage_transition(
    *,
    records: list[ToolCallRecord],
    expectations: dict[str, Any],
) -> tuple[CriterionResult, dict[str, Any]]:
    expected = [
        str(item)
        for item in _as_list(_as_dict(expectations.get("stage")).get("expected_transition_tools"))
        if isinstance(item, str) and item
    ]
    observed = [record.tool for record in records if record.tool in STATE_TRANSITION_TOOLS]
    strict = bool(_as_dict(expectations.get("stage")).get("strict", False))
    if not expected:
        return (
            CriterionResult("stage_transition_accuracy", 20.0, 20.0, []),
            {
                "stage_transition_accuracy": 1.0,
                "expected_transition_tools": [],
                "observed_transition_tools": observed,
                "matched_transition_count": 0,
                "strict": strict,
            },
        )

    matched = _ordered_match_count(expected, observed)
    accuracy = matched / len(expected)
    findings: list[str] = []
    if matched < len(expected):
        findings.append(
            "Stage transition tool sequence did not match expectation; "
            f"matched={matched}/{len(expected)}"
        )
    return (
        CriterionResult("stage_transition_accuracy", round(accuracy * 20.0, 2), 20.0, findings),
        {
            "stage_transition_accuracy": round(accuracy, 4),
            "expected_transition_tools": expected,
            "observed_transition_tools": observed,
            "matched_transition_count": matched,
            "strict": strict,
        },
    )


def _iter_text_fields(value: Any, *, path: str = "$", depth: int = 0) -> list[tuple[str, str]]:
    if depth > 8:
        return []
    if isinstance(value, str) and value.strip():
        return [(path, value.strip())]
    if isinstance(value, dict):
        items: list[tuple[str, str]] = []
        for key, item in value.items():
            items.extend(_iter_text_fields(item, path=f"{path}.{key}", depth=depth + 1))
        return items
    if isinstance(value, list):
        items: list[tuple[str, str]] = []
        for index, item in enumerate(value):
            items.extend(_iter_text_fields(item, path=f"{path}[{index}]", depth=depth + 1))
        return items
    return []


def _sentence_chunks(text: str) -> list[str]:
    return [
        chunk.strip()
        for chunk in re.split(r"(?<=[。！？.!?；;])\s*|\n+", text)
        if chunk and chunk.strip()
    ]


def _claim_chunks(text: str) -> list[tuple[str, bool]]:
    """Preserve verification-section context while splitting claim candidates."""

    chunks: list[tuple[str, bool]] = []
    verification_section = False
    for line in text.splitlines() or [text]:
        stripped = line.strip()
        if not stripped:
            continue
        is_heading = bool(MARKDOWN_HEADING_PATTERN.match(stripped))
        starts_verification_section = bool(
            VERIFICATION_SECTION_PATTERN.search(stripped)
        ) and not MARKDOWN_LIST_ITEM_PATTERN.match(stripped)
        if is_heading:
            verification_section = starts_verification_section
            chunks.extend((chunk, False) for chunk in _sentence_chunks(stripped))
            continue
        if starts_verification_section:
            verification_section = True
            chunks.extend((chunk, False) for chunk in _sentence_chunks(stripped))
            continue
        chunks.extend(
            (chunk, verification_section)
            for chunk in _sentence_chunks(stripped)
        )
    return chunks


def _is_structured_verification_source(source: str) -> bool:
    """Keep the explicit verification semantics carried by report_data field names."""

    if not source.startswith("report_data."):
        return False
    field_names = {
        field
        for field in re.findall(r"(?:^|\.)([^.\[]+)", source)
        if field
    }
    if field_names & STRUCTURED_VERIFICATION_FIELDS:
        return True
    return bool(
        re.search(r"\.price_evidence\.(?:estimated|verification)(?:\[|$)", source)
    )


def _claim_supported(
    *,
    category: str,
    sentence: str,
    called_tools: set[str],
    successful_audit_evidence: dict[str, set[str]],
) -> tuple[bool, str]:
    if QUALIFIED_CLAIM_PATTERN.search(sentence):
        return True, "qualified_as_estimate_or_pending_verification"
    if VERIFICATION_ACTION_PATTERN.search(sentence):
        return True, "qualified_as_verification_action"
    support_tools = CLAIM_SUPPORT_TOOLS.get(category, set())
    support_evidence_types = CLAIM_SUPPORT_EVIDENCE_TYPES.get(category, set())
    matched_evidence = sorted(
        f"{tool}:{evidence_type}"
        for tool in called_tools & support_tools
        for evidence_type in successful_audit_evidence.get(tool, set())
        if evidence_type in support_evidence_types
        and evidence_type in TOOL_SUPPORT_EVIDENCE_TYPES.get(tool, set())
    )
    if matched_evidence and category != "booking":
        return True, "supported_by_successful_tool_evidence:" + ",".join(matched_evidence)
    return False, "missing_successful_compatible_tool_evidence"


def _successful_tool_audit_evidence(
    events: list[dict[str, Any]],
) -> dict[str, set[str]]:
    """Index live evidence only when raw and semantic audit statuses both succeeded."""

    evidence_by_tool: dict[str, set[str]] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or event.get("event") or "").strip().lower()
        if event_type != "tool_audit":
            continue
        raw_status = str(event.get("status") or "").strip().lower()
        semantic_status = str(event.get("semantic_status") or "").strip().lower()
        if raw_status != "success" or semantic_status != "success":
            continue
        tool = str(event.get("tool") or event.get("name") or "").strip()
        evidence_type = str(event.get("evidence_type") or "").strip().lower()
        if not tool or not evidence_type:
            continue
        evidence_by_tool.setdefault(tool, set()).add(evidence_type)
    return evidence_by_tool


def _unsupported_claims(
    *,
    assistant_text: str,
    report_data: dict[str, Any] | None,
    events: list[dict[str, Any]],
    records: list[ToolCallRecord],
    categories: set[str],
) -> dict[str, Any]:
    called_tools = {record.tool for record in records}
    successful_audit_evidence = _successful_tool_audit_evidence(events)
    sources = [("assistant_text", assistant_text)]
    sources.extend(_iter_text_fields(report_data or {}, path="report_data"))
    detected: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []

    for source, text in sources:
        qualified_by_source = _is_structured_verification_source(source)
        for sentence, qualified_by_section in _claim_chunks(text):
            for category in sorted(categories):
                pattern = CLAIM_PATTERNS.get(category)
                if pattern is None or not pattern.search(sentence):
                    continue
                if qualified_by_source:
                    supported, reason = True, "qualified_by_structured_verification_field"
                elif qualified_by_section:
                    supported, reason = True, "qualified_by_verification_section"
                else:
                    supported, reason = _claim_supported(
                        category=category,
                        sentence=sentence,
                        called_tools=called_tools,
                        successful_audit_evidence=successful_audit_evidence,
                    )
                record = {
                    "category": category,
                    "source": source,
                    "excerpt": sentence[:160],
                    "supported": supported,
                    "support_reason": reason,
                }
                detected.append(record)
                if not supported:
                    unsupported.append(record)

    claim_count = len(detected)
    unsupported_count = len(unsupported)
    return {
        "dynamic_claim_count": claim_count,
        "unsupported_claim_count": unsupported_count,
        "unsupported_claim_rate": round(unsupported_count / claim_count, 4) if claim_count else 0.0,
        "claims": detected[:20],
        "unsupported": unsupported[:20],
    }


def _criterion_unsupported_claims(
    unsupported_claims: dict[str, Any],
) -> tuple[CriterionResult, float]:
    rate = float(unsupported_claims.get("unsupported_claim_rate") or 0.0)
    unsupported_count = int(unsupported_claims.get("unsupported_claim_count") or 0)
    score = round(max(0.0, 1.0 - rate) * 20.0, 2)
    findings: list[str] = []
    if unsupported_count:
        findings.append(
            f"Unsupported dynamic claims detected: {unsupported_count}; "
            f"rate={rate}"
        )
    return CriterionResult("unsupported_claim_rate", score, 20.0, findings), rate


def evaluate_agent_metrics(
    events: list[dict[str, Any]],
    *,
    scenario: EvaluationScenario,
    report_data: dict[str, Any] | None = None,
    assistant_text: str = "",
    pass_threshold: float = DEFAULT_AGENT_METRICS_THRESHOLD,
) -> AgentMetricsResult:
    """Evaluate intent, tool, stage, and unsupported-claim metrics from a snapshot."""

    if not isinstance(events, list):
        raise TypeError("events must be a list")
    expectations = _scenario_expectations(scenario)
    records = extract_tool_events(events)
    observed_intents = _observed_intents(
        scenario=scenario,
        records=records,
        report_data=report_data,
    )
    intent_criterion, intent_accuracy = _criterion_intent_accuracy(
        expectations=expectations,
        observed_intents=observed_intents,
    )
    precision_criterion, recall_criterion, tool_details = _tool_precision_recall(
        records=records,
        expectations=expectations,
    )
    stage_criterion, stage_details = _criterion_stage_transition(
        records=records,
        expectations=expectations,
    )
    claim_expectations = _as_dict(expectations.get("unsupported_claims"))
    unsupported_claims = _unsupported_claims(
        assistant_text=assistant_text,
        report_data=report_data,
        events=events,
        records=records,
        categories=_string_set(claim_expectations.get("categories"))
        or set(DEFAULT_UNSUPPORTED_CLAIM_CATEGORIES),
    )
    claim_criterion, unsupported_claim_rate = _criterion_unsupported_claims(unsupported_claims)

    criteria = [
        intent_criterion,
        precision_criterion,
        recall_criterion,
        stage_criterion,
        claim_criterion,
    ]
    total_score = round(sum(criterion.score for criterion in criteria), 2)
    max_score = round(sum(criterion.max_score for criterion in criteria), 2)
    normalized_score = round((total_score / max_score) * 100, 2) if max_score else 0.0
    failed_findings = [
        f"{criterion.name}: {finding}"
        for criterion in criteria
        if criterion.name != "stage_transition_accuracy" or stage_details["strict"]
        for finding in criterion.findings
    ]
    passed = (
        normalized_score >= pass_threshold
        and not failed_findings
        and unsupported_claim_rate == 0.0
    )
    summary = (
        ["Agent industrial metrics satisfy the current quality gate."]
        if passed
        else failed_findings[:10]
    )
    metric_values = {
        "intent_accuracy": intent_accuracy,
        "tool_call_precision": tool_details["tool_call_precision"],
        "tool_call_recall": tool_details["tool_call_recall"],
        "stage_transition_accuracy": stage_details["stage_transition_accuracy"],
        "unsupported_claim_rate": unsupported_claim_rate,
    }
    return AgentMetricsResult(
        total_score=total_score,
        max_score=max_score,
        normalized_score=normalized_score,
        grade=_grade(normalized_score),
        passed=passed,
        criteria=criteria,
        summary=summary,
        metric_values=metric_values,
        expectations=expectations,
        observed={
            "intents": sorted(observed_intents),
            "tools": tool_details["called_tools"],
            "transition_tools": stage_details["observed_transition_tools"],
            "called_forbidden_tools": tool_details["called_forbidden_tools"],
            "unexpected_tools": tool_details["unexpected_tools"],
        },
        unsupported_claims=unsupported_claims,
    )
