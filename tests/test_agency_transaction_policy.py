from types import SimpleNamespace

from app.agency.transaction_policy import (
    build_transaction_execution_snapshot,
    evaluate_transaction_configuration_gate,
)
from app.config import Settings
from app.core.permissions import can_decide_approval_record


def _config(**overrides):
    values = {
        "transaction_mode": "disabled",
        "real_payment_order_disabled": True,
        "live_supplier_booking_enabled": False,
        "live_payment_enabled": False,
        "live_refund_enabled": False,
        "live_notification_enabled": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_transaction_execution_defaults_to_fail_closed():
    decision = evaluate_transaction_configuration_gate(
        _config(),
        "supplier_booking",
    )

    assert decision.configuration_gate_passed is False
    assert decision.code == "transaction_kill_switch_enabled"
    snapshot = build_transaction_execution_snapshot(_config())
    assert snapshot["status"] == "disabled"
    assert snapshot["kill_switch_enabled"] is True
    assert all(
        action["configuration_gate_passed"] is False
        for action in snapshot["actions"].values()
    )


def test_transaction_execution_requires_mode_and_action_switch():
    disabled = evaluate_transaction_configuration_gate(
        _config(real_payment_order_disabled=False),
        "payment",
    )
    granularly_disabled = evaluate_transaction_configuration_gate(
        _config(
            transaction_mode="sandbox",
            real_payment_order_disabled=False,
        ),
        "payment",
    )
    passed = evaluate_transaction_configuration_gate(
        _config(
            transaction_mode="sandbox",
            real_payment_order_disabled=False,
            live_payment_enabled=True,
        ),
        "payment",
    )

    assert disabled.code == "transaction_execution_disabled"
    assert granularly_disabled.code == "transaction_action_disabled"
    assert passed.configuration_gate_passed is True
    assert passed.code == "transaction_configuration_gate_passed"


def test_invalid_transaction_mode_is_treated_as_disabled():
    decision = evaluate_transaction_configuration_gate(
        _config(
            transaction_mode="unexpected",
            real_payment_order_disabled=False,
            live_refund_enabled=True,
        ),
        "refund",
    )

    assert decision.configuration_gate_passed is False
    assert decision.mode == "disabled"


def test_settings_keep_external_transaction_actions_disabled_by_default():
    settings = Settings(_env_file=None)

    assert settings.transaction_mode_resolved == "disabled"
    assert settings.real_payment_order_disabled is True
    assert settings.live_supplier_booking_enabled is False
    assert settings.live_payment_enabled is False
    assert settings.live_refund_enabled is False


def test_live_mode_can_start_with_emergency_kill_switch_enabled():
    settings = Settings(
        _env_file=None,
        APP_ENV="production",
        JWT_SECRET_KEY="production-jwt-secret-with-more-than-enough-entropy-2026",
        TRANSACTION_MODE="live",
        ZHIXING_REAL_PAYMENT_ORDER_DISABLED=True,
        LIVE_PAYMENT_ENABLED=True,
    )

    settings.validate_security_baseline()
    decision = evaluate_transaction_configuration_gate(settings, "payment")

    assert decision.configuration_gate_passed is False
    assert decision.code == "transaction_kill_switch_enabled"


def test_approval_operator_cannot_approve_their_own_request():
    approver = SimpleNamespace(
        id="approver-1",
        preferences={"role": "approver"},
    )

    assert can_decide_approval_record(approver, "requester-1") is True
    assert can_decide_approval_record(approver, "approver-1") is False
