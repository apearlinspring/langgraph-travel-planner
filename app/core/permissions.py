"""Sensitive action policies for lightweight approval governance."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

ApprovalStatus = Literal["none", "pending", "approved", "rejected", "expired"]
ApprovalAction = Literal[
    "generate_order_id",
    "export_final_report",
    "real_booking",
    "real_payment",
    "send_sms",
    "export_customer_profile",
]


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
