"""Sensitive action policies for lightweight approval governance."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from app.tools.contracts import ToolPermissionDecision, ToolRiskLevel

ApprovalStatus = Literal["none", "pending", "approved", "rejected", "expired"]
ApprovalAction = Literal[
    "generate_order_id",
    "export_final_report",
    "real_booking",
    "real_payment",
    "send_sms",
    "export_customer_profile",
]
UserRole = Literal["user", "approver", "admin"]


ROLE_ALIASES: dict[str, UserRole] = {
    "user": "user",
    "member": "user",
    "traveler": "user",
    "customer": "user",
    "普通用户": "user",
    "approver": "approver",
    "approval_operator": "approver",
    "operator": "approver",
    "reviewer": "approver",
    "审批员": "approver",
    "审批操作者": "approver",
    "admin": "admin",
    "administrator": "admin",
    "owner": "admin",
    "管理员": "admin",
}

APPROVAL_OPERATOR_ROLES: set[UserRole] = {"approver", "admin"}


@dataclass(frozen=True)
class SensitiveActionPolicy:
    """Governance policy for a sensitive action."""

    action: ApprovalAction
    label: str
    category: str
    description: str
    requires_approval: bool
    default_ttl_seconds: int | None
    governance_boundary: str
    unsupported_without_integration: tuple[str, ...] = ()
    future_reserved: bool = False

    @property
    def is_blocking(self) -> bool:
        return self.requires_approval

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["is_blocking"] = self.is_blocking
        payload["unsupported_without_integration"] = list(
            self.unsupported_without_integration
        )
        return payload


def normalize_user_role(role: Any) -> UserRole:
    """Normalize lightweight user roles without introducing a full RBAC service."""

    normalized = str(role or "").strip()
    if not normalized:
        return "user"
    return ROLE_ALIASES.get(normalized.lower(), "user")


def get_user_role(user: Any) -> UserRole:
    """Return a user's lightweight role from an attribute or preferences JSON."""

    direct_role = getattr(user, "role", None)
    if direct_role:
        return normalize_user_role(direct_role)

    preferences = getattr(user, "preferences", None)
    if isinstance(preferences, dict):
        return normalize_user_role(
            preferences.get("role")
            or preferences.get("user_role")
            or preferences.get("permission_role")
        )
    return "user"


def is_approval_operator(user: Any) -> bool:
    return get_user_role(user) in APPROVAL_OPERATOR_ROLES


def can_view_approval_record(user: Any, record_user_id: str | None) -> bool:
    if is_approval_operator(user):
        return True
    return str(getattr(user, "id", "")) == str(record_user_id)


def can_decide_approval_record(user: Any, record_user_id: str | None) -> bool:
    """Only approval operators and admins can decide sensitive-action records."""

    return is_approval_operator(user)


def can_list_all_approval_records(user: Any) -> bool:
    return is_approval_operator(user)


SENSITIVE_ACTION_POLICIES: dict[ApprovalAction, SensitiveActionPolicy] = {
    "generate_order_id": SensitiveActionPolicy(
        action="generate_order_id",
        label="生成订单号",
        category="current_record_only",
        description="为最终旅行方案生成项目内模拟订单号。",
        requires_approval=False,
        default_ttl_seconds=None,
        governance_boundary=(
            "当前订单号仅用于方案归档和前端展示，不代表真实支付、真实预订、"
            "锁价、占库存或供应链履约。"
        ),
        unsupported_without_integration=(
            "真实支付",
            "真实下单",
            "真实库存锁定",
            "真实预订成功",
        ),
    ),
    "export_final_report": SensitiveActionPolicy(
        action="export_final_report",
        label="导出最终报告",
        category="current_record_only",
        description="导出当前结构化旅行报告，供用户自行复核和保存。",
        requires_approval=False,
        default_ttl_seconds=None,
        governance_boundary=(
            "当前报告导出仅代表方案交付，不代表已经完成支付、预订、出票或酒店确认。"
        ),
        unsupported_without_integration=(
            "真实支付凭证",
            "真实预订凭证",
            "真实客服链接",
        ),
    ),
    "real_booking": SensitiveActionPolicy(
        action="real_booking",
        label="真实预订或下单",
        category="future_mandatory_approval",
        description="未来接入真实供应链、库存或订单履约前的强制审批动作。",
        requires_approval=True,
        default_ttl_seconds=1800,
        governance_boundary="未来真实预订必须先完成人工审批，审批过期后不得继续执行。",
        unsupported_without_integration=(
            "供应链下单",
            "锁定余位",
            "酒店房型确认",
            "出票",
        ),
        future_reserved=True,
    ),
    "real_payment": SensitiveActionPolicy(
        action="real_payment",
        label="真实支付",
        category="future_mandatory_approval",
        description="未来接入支付网关前的强制审批动作。",
        requires_approval=True,
        default_ttl_seconds=900,
        governance_boundary="未来真实支付必须先完成人工审批，审批过期后不得发起支付。",
        unsupported_without_integration=(
            "支付链接",
            "扣款",
            "收款确认",
            "退款承诺",
        ),
        future_reserved=True,
    ),
    "send_sms": SensitiveActionPolicy(
        action="send_sms",
        label="发送短信",
        category="future_mandatory_approval",
        description="未来向用户或供应商发送短信前的强制审批动作。",
        requires_approval=True,
        default_ttl_seconds=1800,
        governance_boundary="未来发送短信必须先完成人工审批，并记录短信目的和接收方范围。",
        unsupported_without_integration=(
            "营销短信",
            "验证码短信",
            "供应商通知短信",
        ),
        future_reserved=True,
    ),
    "export_customer_profile": SensitiveActionPolicy(
        action="export_customer_profile",
        label="导出客户资料",
        category="future_mandatory_approval",
        description="未来导出客户资料或行程画像前的强制审批动作。",
        requires_approval=True,
        default_ttl_seconds=1800,
        governance_boundary="未来客户资料导出必须先完成人工审批，并最小化导出字段。",
        unsupported_without_integration=(
            "证件信息导出",
            "联系方式导出",
            "完整客户画像导出",
        ),
        future_reserved=True,
    ),
}

ACTION_ALIASES: dict[str, ApprovalAction] = {
    "order": "generate_order_id",
    "order_id": "generate_order_id",
    "generate_order": "generate_order_id",
    "generate_order_id": "generate_order_id",
    "生成订单": "generate_order_id",
    "生成订单号": "generate_order_id",
    "report_export": "export_final_report",
    "export_report": "export_final_report",
    "export_final_report": "export_final_report",
    "导出报告": "export_final_report",
    "导出最终报告": "export_final_report",
    "booking": "real_booking",
    "real_booking": "real_booking",
    "真实预订": "real_booking",
    "真实下单": "real_booking",
    "payment": "real_payment",
    "real_payment": "real_payment",
    "真实支付": "real_payment",
    "支付": "real_payment",
    "sms": "send_sms",
    "send_sms": "send_sms",
    "发送短信": "send_sms",
    "customer_export": "export_customer_profile",
    "export_customer_profile": "export_customer_profile",
    "导出客户资料": "export_customer_profile",
}

SENSITIVE_METADATA_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "id_card",
    "identity",
    "mobile",
    "password",
    "phone",
    "secret",
    "token",
}


def normalize_approval_action(action: str) -> ApprovalAction:
    """Normalize user-facing action names to the canonical policy key."""

    normalized = str(action or "").strip()
    alias_key = normalized.lower()
    if normalized in ACTION_ALIASES:
        return ACTION_ALIASES[normalized]
    if alias_key in ACTION_ALIASES:
        return ACTION_ALIASES[alias_key]
    if alias_key in SENSITIVE_ACTION_POLICIES:
        return alias_key  # type: ignore[return-value]
    raise ValueError(f"未知敏感动作：{action}")


def get_sensitive_action_policy(action: str) -> SensitiveActionPolicy:
    canonical_action = normalize_approval_action(action)
    return SENSITIVE_ACTION_POLICIES[canonical_action]


def list_sensitive_action_policies() -> list[SensitiveActionPolicy]:
    return list(SENSITIVE_ACTION_POLICIES.values())


def action_requires_approval(action: str) -> bool:
    return get_sensitive_action_policy(action).requires_approval


def sanitize_approval_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Keep metadata shallow and redact values that look like secrets or PII."""

    if not isinstance(metadata, dict):
        return {}

    sanitized: dict[str, Any] = {}
    for key, value in metadata.items():
        key_text = str(key)
        key_lookup = key_text.lower()
        if any(sensitive_key in key_lookup for sensitive_key in SENSITIVE_METADATA_KEYS):
            sanitized[key_text] = "[REDACTED]"
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            text_value = value
            if isinstance(value, str) and len(value) > 300:
                text_value = value[:300] + "..."
            sanitized[key_text] = text_value
        elif isinstance(value, (list, tuple)):
            sanitized[key_text] = [
                item if isinstance(item, (str, int, float, bool)) or item is None else str(item)
                for item in value[:20]
            ]
        else:
            sanitized[key_text] = str(value)[:300]
    return sanitized


@dataclass(frozen=True)
class ToolExecutionPolicy:
    """Governance policy for a tool call before it reaches external effects."""

    tool_name: str
    category: str
    risk_level: ToolRiskLevel
    description: str
    enabled: bool = True
    requires_approval: bool = False
    approval_action: ApprovalAction | None = None
    default_timeout_seconds: float | None = None
    allowed_steps: tuple[str, ...] = ()
    audit_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "category": self.category,
            "risk_level": self.risk_level,
            "description": self.description,
            "enabled": self.enabled,
            "requires_approval": self.requires_approval,
            "approval_action": self.approval_action,
            "default_timeout_seconds": self.default_timeout_seconds,
            "allowed_steps": list(self.allowed_steps),
            "audit_required": self.audit_required,
        }


DEFAULT_TOOL_EXECUTION_POLICY = ToolExecutionPolicy(
    tool_name="*",
    category="general_tool",
    risk_level="low",
    description="默认工具策略：允许执行，但仍可由调用方记录审计摘要。",
    default_timeout_seconds=None,
)

MCP_EXTERNAL_QUERY_POLICY = ToolExecutionPolicy(
    tool_name="mcp_external_query",
    category="mcp_external_query",
    risk_level="high",
    description="第三方 MCP 外部查询工具，必须有超时和审计摘要。",
    default_timeout_seconds=20.0,
)

INTERNAL_RAG_POLICY = ToolExecutionPolicy(
    tool_name="internal_rag_query",
    category="internal_rag",
    risk_level="medium",
    description="旅行社内部知识检索，只可返回证据摘要，不得承诺真实履约。",
    default_timeout_seconds=20.0,
)

PUBLIC_RAG_POLICY = ToolExecutionPolicy(
    tool_name="public_rag_query",
    category="public_rag",
    risk_level="low",
    description="公开目的地知识检索，命中不足时必须明确待二次核实。",
    default_timeout_seconds=20.0,
)

TOOL_EXECUTION_POLICIES: dict[str, ToolExecutionPolicy] = {
    "query_hotel_options": ToolExecutionPolicy(
        tool_name="query_hotel_options",
        category="live_hotel_search",
        risk_level="high",
        description="真实酒店候选查询，失败时不得编造酒店、库存或价格。",
        default_timeout_seconds=45.0,
    ),
    "query_transport_options": ToolExecutionPolicy(
        tool_name="query_transport_options",
        category="live_transport_query",
        risk_level="high",
        description="真实交通方案查询，失败时不得编造车次、航班或价格。",
        default_timeout_seconds=60.0,
    ),
    "real_booking": ToolExecutionPolicy(
        tool_name="real_booking",
        category="future_sensitive_action",
        risk_level="critical",
        description="真实预订占位能力，当前必须先完成人工审批且项目未接入真实执行。",
        requires_approval=True,
        approval_action="real_booking",
        default_timeout_seconds=10.0,
    ),
    "real_payment": ToolExecutionPolicy(
        tool_name="real_payment",
        category="future_sensitive_action",
        risk_level="critical",
        description="真实支付占位能力，当前必须先完成人工审批且项目未接入真实执行。",
        requires_approval=True,
        approval_action="real_payment",
        default_timeout_seconds=10.0,
    ),
    "send_sms": ToolExecutionPolicy(
        tool_name="send_sms",
        category="future_sensitive_action",
        risk_level="critical",
        description="短信发送占位能力，当前未接入短信服务，不会发送真实短信。",
        enabled=False,
        requires_approval=True,
        approval_action="send_sms",
        default_timeout_seconds=10.0,
    ),
    "export_customer_profile": ToolExecutionPolicy(
        tool_name="export_customer_profile",
        category="future_sensitive_action",
        risk_level="critical",
        description="客户资料导出占位能力，当前不得导出真实客户画像文件。",
        enabled=False,
        requires_approval=True,
        approval_action="export_customer_profile",
        default_timeout_seconds=10.0,
    ),
}


def get_tool_execution_policy(tool_name: str) -> ToolExecutionPolicy:
    normalized = str(tool_name or "").strip()
    if normalized in TOOL_EXECUTION_POLICIES:
        return TOOL_EXECUTION_POLICIES[normalized]
    if normalized.startswith("search_agency_"):
        return ToolExecutionPolicy(
            **{**INTERNAL_RAG_POLICY.to_dict(), "tool_name": normalized}
        )
    if normalized.startswith("search_") and normalized in {
        "search_destination_guide",
        "search_food_recommendations",
        "search_accommodation_info",
        "search_travel_tips",
    }:
        return ToolExecutionPolicy(
            **{**PUBLIC_RAG_POLICY.to_dict(), "tool_name": normalized}
        )
    if normalized in {
        "getHotelDetail",
        "getHotelSearchTags",
        "maps_geo",
        "maps_direction_driving",
        "get_weather_forecast",
        "search_travel_info",
    } or normalized.startswith(("maps_", "get", "search")):
        return ToolExecutionPolicy(
            **{**MCP_EXTERNAL_QUERY_POLICY.to_dict(), "tool_name": normalized}
        )
    return ToolExecutionPolicy(
        **{**DEFAULT_TOOL_EXECUTION_POLICY.to_dict(), "tool_name": normalized or "unknown_tool"}
    )


def decide_tool_execution_permission(
    tool_name: str,
    state: dict[str, Any] | None = None,
) -> ToolPermissionDecision:
    policy = get_tool_execution_policy(tool_name)
    if not policy.enabled:
        return ToolPermissionDecision(
            allowed=False,
            reason=policy.description or f"工具 {tool_name} 当前被治理策略禁用。",
            error_type="tool_disabled",
        )

    current_step = str((state or {}).get("current_step") or "")
    if policy.allowed_steps and current_step and current_step not in policy.allowed_steps:
        return ToolPermissionDecision(
            allowed=False,
            reason=f"工具 {tool_name} 不允许在当前阶段 {current_step} 执行。",
            error_type="tool_not_allowed_for_step",
        )

    return ToolPermissionDecision(allowed=True)
