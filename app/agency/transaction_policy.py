"""Fail-closed execution policy for travel-agency side effects."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


TransactionAction = Literal[
    "supplier_booking",
    "payment",
    "refund",
    "notification",
]

_ACTION_FLAGS: dict[TransactionAction, str] = {
    "supplier_booking": "live_supplier_booking_enabled",
    "payment": "live_payment_enabled",
    "refund": "live_refund_enabled",
    "notification": "live_notification_enabled",
}
TRANSACTION_ACTIONS: tuple[TransactionAction, ...] = tuple(_ACTION_FLAGS)


@dataclass(frozen=True)
class TransactionConfigurationDecision:
    """Result of the outer configuration gate, never final execution approval."""

    configuration_gate_passed: bool
    mode: str
    action: TransactionAction
    code: str
    reason: str

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "configuration_gate_passed": self.configuration_gate_passed,
            "mode": self.mode,
            "action": self.action,
            "code": self.code,
            "reason": self.reason,
        }


def normalize_transaction_mode(value: Any) -> str:
    normalized = str(value or "disabled").strip().lower()
    return normalized if normalized in {"disabled", "sandbox", "live"} else "disabled"


def evaluate_transaction_configuration_gate(
    config: Any,
    action: TransactionAction,
) -> TransactionConfigurationDecision:
    """Pass the outer gate only when every global switch explicitly opts in.

    This is the outer configuration gate only. A positive decision never replaces
    tenant authorization, four-eyes approval, revision/payload-hash validation,
    idempotency, provider credentials, or adapter-specific safety checks.
    """

    mode = normalize_transaction_mode(getattr(config, "transaction_mode", "disabled"))
    if bool(getattr(config, "real_payment_order_disabled", True)):
        return TransactionConfigurationDecision(
            configuration_gate_passed=False,
            mode=mode,
            action=action,
            code="transaction_kill_switch_enabled",
            reason="旅行社外部交易总熔断开关仍处于关闭状态。",
        )
    if mode == "disabled":
        return TransactionConfigurationDecision(
            configuration_gate_passed=False,
            mode=mode,
            action=action,
            code="transaction_execution_disabled",
            reason="当前仅允许持久化报价和订单草稿，不允许执行外部交易动作。",
        )

    flag_name = _ACTION_FLAGS[action]
    if not bool(getattr(config, flag_name, False)):
        return TransactionConfigurationDecision(
            configuration_gate_passed=False,
            mode=mode,
            action=action,
            code="transaction_action_disabled",
            reason=f"{action} 的细粒度执行开关未开启。",
        )

    return TransactionConfigurationDecision(
        configuration_gate_passed=True,
        mode=mode,
        action=action,
        code="transaction_configuration_gate_passed",
        reason=(
            "配置门禁已通过；仍需校验租户权限、四眼审批、资源 revision、"
            "payload hash、幂等记录和供应商适配器。"
        ),
    )


def build_transaction_execution_snapshot(config: Any) -> dict[str, Any]:
    """Return a non-secret readiness snapshot for every external action gate."""

    decisions = {
        action: evaluate_transaction_configuration_gate(config, action).to_dict()
        for action in TRANSACTION_ACTIONS
    }
    if all(
        not decision["configuration_gate_passed"]
        for decision in decisions.values()
    ):
        status = "disabled"
    elif normalize_transaction_mode(
        getattr(config, "transaction_mode", "disabled")
    ) == "sandbox":
        status = "sandbox_configured"
    else:
        status = "live_configuration_gate_open"
    return {
        "status": status,
        "mode": normalize_transaction_mode(
            getattr(config, "transaction_mode", "disabled")
        ),
        "kill_switch_enabled": bool(
            getattr(config, "real_payment_order_disabled", True)
        ),
        "actions": decisions,
        "boundary": (
            "配置门禁通过也不代表真实交易可执行；仍需租户权限、四眼审批、"
            "revision/payload hash、幂等和供应商适配器校验。"
        ),
    }
