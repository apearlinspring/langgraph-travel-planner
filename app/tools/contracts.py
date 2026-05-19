"""Shared contracts for tool governance and audit events."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from typing_extensions import NotRequired, TypedDict


ToolAuditStatus = Literal[
    "success",
    "failed",
    "timeout",
    "degraded",
    "skipped",
    "approval_required",
]
ToolEvidenceType = Literal[
    "live_transport_query",
    "live_hotel_search",
    "mcp_live_query",
    "internal_rag_evidence",
    "public_rag_evidence",
    "destination_router_evidence",
    "internal_state_update",
    "unknown",
]
ToolRiskLevel = Literal["low", "medium", "high", "critical"]
ToolGovernanceCoverage = Literal[
    "guarded",
    "metadata_guarded",
    "governed_boundary",
    "exception",
    "missing",
]


class ToolAuditEvent(TypedDict):
    name: str
    started_at: float
    elapsed_seconds: float
    status: ToolAuditStatus
    input_summary: dict[str, Any]
    output_summary: dict[str, Any]
    error_type: str | None
    retry_count: int
    evidence_type: ToolEvidenceType
    turn_id: NotRequired[str]
    loop_guard_key: NotRequired[str]


@dataclass(frozen=True)
class ToolValidationResult:
    ok: bool
    error_type: str | None = None
    message: str = ""
    normalized_args: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ToolResultValidation:
    status: ToolAuditStatus
    output_summary: dict[str, Any] = field(default_factory=dict)
    error_type: str | None = None
    message: str = ""


@dataclass(frozen=True)
class ToolPermissionDecision:
    allowed: bool
    reason: str = ""
    error_type: str | None = None


@dataclass(frozen=True)
class ToolExecutionGuardResult:
    status: ToolAuditStatus
    event: ToolAuditEvent
    output: Any = None
    message: str = ""
    error_type: str | None = None
    update: dict[str, Any] = field(default_factory=dict)
    approval_update: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolGovernanceRecord:
    """Static coverage classification for tools exposed to planner-facing agents."""

    tool_name: str
    coverage: ToolGovernanceCoverage
    category: str
    reason: str
    test_protection: str = ""

    @property
    def is_covered(self) -> bool:
        return self.coverage in {
            "guarded",
            "metadata_guarded",
            "governed_boundary",
            "exception",
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "coverage": self.coverage,
            "category": self.category,
            "reason": self.reason,
            "test_protection": self.test_protection,
            "is_covered": self.is_covered,
        }


GUARDED_TOOL_NAMES = frozenset(
    {
        "query_hotel_options",
        "query_transport_options",
        "query_flight_options",
        "query_train_options",
        "query_driving_route",
        "query_destination_info",
        "search_destination_guide",
        "search_food_recommendations",
        "search_accommodation_info",
        "search_travel_tips",
        "search_agency_product_templates",
        "search_agency_service_sop",
        "search_agency_pricing_rules",
        "search_agency_risk_playbook",
        "search_agency_report_standards",
    }
)

GOVERNED_BOUNDARY_TOOL_NAMES = frozenset(
    {
        "generate_order_tool",
    }
)

TOOL_GOVERNANCE_EXCEPTIONS: dict[str, ToolGovernanceRecord] = {
    "record_requirement_tool": ToolGovernanceRecord(
        tool_name="record_requirement_tool",
        coverage="exception",
        category="state_transition",
        reason="只写入已确认需求和阶段状态，不触发外部查询、支付、短信或供应链履约。",
        test_protection="tests/test_workflow_maintainability.py",
    ),
    "set_planning_mode_tool": ToolGovernanceRecord(
        tool_name="set_planning_mode_tool",
        coverage="exception",
        category="state_transition",
        reason="只写入规划模式标记，属于本地状态迁移。",
        test_protection="tests/test_intent_detection.py",
    ),
    "confirm_planning_mode_tool": ToolGovernanceRecord(
        tool_name="confirm_planning_mode_tool",
        coverage="exception",
        category="state_transition",
        reason="只确认当前规划模式，不触发外部副作用。",
        test_protection="tests/test_intent_detection.py",
    ),
    "record_evidence_bundle_tool": ToolGovernanceRecord(
        tool_name="record_evidence_bundle_tool",
        coverage="exception",
        category="state_transition",
        reason="只记录证据包摘要，证据来源工具本身单独纳入执行网关。",
        test_protection="tests/test_report_quality_evaluation.py",
    ),
    "select_destination_tool": ToolGovernanceRecord(
        tool_name="select_destination_tool",
        coverage="exception",
        category="state_transition",
        reason="只确认目的地和目的地上下文，不直接调用外部服务。",
        test_protection="tests/test_workflow_maintainability.py",
    ),
    "select_transport_tool": ToolGovernanceRecord(
        tool_name="select_transport_tool",
        coverage="exception",
        category="state_transition",
        reason="只保存用户已确认交通方案；真实交通查询由 query_transport_options 纳入网关。",
        test_protection="tests/test_transport_query_tool.py",
    ),
    "select_accommodation_tool": ToolGovernanceRecord(
        tool_name="select_accommodation_tool",
        coverage="exception",
        category="state_transition",
        reason="只保存用户已确认住宿偏好或候选；真实酒店查询由 query_hotel_options 纳入网关。",
        test_protection="tests/test_hotel_query_tool.py",
    ),
    "select_food_tool": ToolGovernanceRecord(
        tool_name="select_food_tool",
        coverage="exception",
        category="state_transition",
        reason="只保存餐饮偏好，不做真实餐厅预订或外部查询。",
        test_protection="tests/test_workflow_maintainability.py",
    ),
    "generate_itinerary_tool": ToolGovernanceRecord(
        tool_name="generate_itinerary_tool",
        coverage="exception",
        category="state_transition",
        reason="基于已确认状态生成本地行程草案；地图和真实查询工具另行审计。",
        test_protection="tests/test_report_quality_evaluation.py",
    ),
    "generate_visual_journey_tool": ToolGovernanceRecord(
        tool_name="generate_visual_journey_tool",
        coverage="exception",
        category="state_transition",
        reason="只生成可视化旅程草案和待核验项，不生成订单、锁价、支付或真实预订。",
        test_protection="tests/test_visual_journey_planner.py",
    ),
    "summarize_budget_tool": ToolGovernanceRecord(
        tool_name="summarize_budget_tool",
        coverage="exception",
        category="state_transition",
        reason="只做预算估算和待核验项汇总，不锁价、不支付、不下单。",
        test_protection="tests/test_report_quality_evaluation.py",
    ),
    "go_back_to_step": ToolGovernanceRecord(
        tool_name="go_back_to_step",
        coverage="exception",
        category="rollback",
        reason="只回退本地工作流状态并清理后续字段。",
        test_protection="tests/test_workflow_maintainability.py",
    ),
    "go_back_to_requirement": ToolGovernanceRecord(
        tool_name="go_back_to_requirement",
        coverage="exception",
        category="rollback",
        reason="回退快捷工具，只委托 go_back_to_step 做本地状态变更。",
        test_protection="tests/test_workflow_maintainability.py",
    ),
    "go_back_to_destination": ToolGovernanceRecord(
        tool_name="go_back_to_destination",
        coverage="exception",
        category="rollback",
        reason="回退快捷工具，只委托 go_back_to_step 做本地状态变更。",
        test_protection="tests/test_workflow_maintainability.py",
    ),
    "go_back_to_transport": ToolGovernanceRecord(
        tool_name="go_back_to_transport",
        coverage="exception",
        category="rollback",
        reason="回退快捷工具，只委托 go_back_to_step 做本地状态变更。",
        test_protection="tests/test_workflow_maintainability.py",
    ),
    "go_back_to_accommodation": ToolGovernanceRecord(
        tool_name="go_back_to_accommodation",
        coverage="exception",
        category="rollback",
        reason="回退快捷工具，只委托 go_back_to_step 做本地状态变更。",
        test_protection="tests/test_workflow_maintainability.py",
    ),
    "go_back_to_food": ToolGovernanceRecord(
        tool_name="go_back_to_food",
        coverage="exception",
        category="rollback",
        reason="回退快捷工具，只委托 go_back_to_step 做本地状态变更。",
        test_protection="tests/test_workflow_maintainability.py",
    ),
    "go_back_to_itinerary": ToolGovernanceRecord(
        tool_name="go_back_to_itinerary",
        coverage="exception",
        category="rollback",
        reason="回退快捷工具，只委托 go_back_to_step 做本地状态变更。",
        test_protection="tests/test_workflow_maintainability.py",
    ),
    "go_back_to_budget": ToolGovernanceRecord(
        tool_name="go_back_to_budget",
        coverage="exception",
        category="rollback",
        reason="回退快捷工具，只委托 go_back_to_step 做本地状态变更。",
        test_protection="tests/test_workflow_maintainability.py",
    ),
    "check_current_progress": ToolGovernanceRecord(
        tool_name="check_current_progress",
        coverage="exception",
        category="read_only_state",
        reason="只读取本地工作流状态并返回进度摘要。",
        test_protection="tests/test_workflow_maintainability.py",
    ),
    "update_travel_style_tool": ToolGovernanceRecord(
        tool_name="update_travel_style_tool",
        coverage="exception",
        category="memory_write",
        reason="写入长期记忆前已有 memory_scope 过滤和 memory_audit_entries 审计，不调用外部供应链。",
        test_protection="tests/test_travel_agent_tool_registry.py",
    ),
    "update_dietary_restriction_tool": ToolGovernanceRecord(
        tool_name="update_dietary_restriction_tool",
        coverage="exception",
        category="memory_write",
        reason="写入长期记忆前已有 memory_scope 过滤和 memory_audit_entries 审计，不调用外部供应链。",
        test_protection="tests/test_travel_agent_tool_registry.py",
    ),
    "update_food_preference_tool": ToolGovernanceRecord(
        tool_name="update_food_preference_tool",
        coverage="exception",
        category="memory_write",
        reason="写入长期记忆前已有 memory_scope 过滤和 memory_audit_entries 审计，不调用外部供应链。",
        test_protection="tests/test_travel_agent_tool_registry.py",
    ),
    "update_accommodation_preference_tool": ToolGovernanceRecord(
        tool_name="update_accommodation_preference_tool",
        coverage="exception",
        category="memory_write",
        reason="写入长期记忆前已有 memory_scope 过滤和 memory_audit_entries 审计，不调用外部供应链。",
        test_protection="tests/test_travel_agent_tool_registry.py",
    ),
    "add_travel_record_tool": ToolGovernanceRecord(
        tool_name="add_travel_record_tool",
        coverage="exception",
        category="memory_write",
        reason="写入长期记忆前已有 memory_audit_entries 审计，不调用外部供应链。",
        test_protection="tests/test_travel_agent_tool_registry.py",
    ),
}


def classify_tool_governance(
    tool_name: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> ToolGovernanceRecord:
    """Classify whether a registered tool is guarded or intentionally exempt."""

    normalized = str(tool_name or "").strip()
    metadata = metadata or {}
    if metadata.get("execution_guard") == "tool_execution_guard":
        return ToolGovernanceRecord(
            tool_name=normalized,
            coverage="metadata_guarded",
            category="mcp_external_query",
            reason="动态 MCP 工具由 guard_mcp_tool 包装，统一加参数预检、超时、结果校验和审计 artifact。",
            test_protection="tests/test_tool_audit_governance.py",
        )
    if normalized in GUARDED_TOOL_NAMES:
        return ToolGovernanceRecord(
            tool_name=normalized,
            coverage="guarded",
            category="tool_execution_guard",
            reason="工具主体通过 Tool Execution Guard 统一执行。",
            test_protection="tests/test_tool_audit_governance.py",
        )
    if normalized in GOVERNED_BOUNDARY_TOOL_NAMES:
        return ToolGovernanceRecord(
            tool_name=normalized,
            coverage="governed_boundary",
            category="state_transition_sensitive_boundary",
            reason="状态迁移工具保留本地灵活性，但敏感动作通过 approval_governance 明确边界。",
            test_protection="tests/test_tool_audit_governance.py",
        )
    if normalized in TOOL_GOVERNANCE_EXCEPTIONS:
        return TOOL_GOVERNANCE_EXCEPTIONS[normalized]
    return ToolGovernanceRecord(
        tool_name=normalized or "unknown_tool",
        coverage="missing",
        category="unknown",
        reason="该工具尚未在治理覆盖表中登记。",
        test_protection="tests/test_travel_agent_tool_registry.py",
    )
