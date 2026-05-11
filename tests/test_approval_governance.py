import os
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain.tools import ToolRuntime

os.environ.setdefault("DASHSCOPE_API_KEY", "test")
os.environ.setdefault("LANGSMITH_API_KEY", "test")
os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")

from app.api.dependencies import get_current_user
from app.api.v1.approvals import (
    get_approval_service,
    router as approvals_router,
)
from app.core.approval import (
    ApprovalGovernanceManager,
    ApprovalStateError,
    ApprovalStore,
    approval_store,
)
from app.core.permissions import (
    action_requires_approval,
    get_sensitive_action_policy,
    sanitize_approval_metadata,
)
from app.core.state import create_initial_state
from app.models.approval import ApprovalEvent, ApprovalRequest, ToolAuditEvent
from app.models.base import Base
from app.tools.state_transition import generate_order_tool


def _build_runtime(state):
    return ToolRuntime(
        state=state,
        context=None,
        config={},
        stream_writer=lambda _: None,
        tool_call_id="tool-call-1",
        store=None,
    )


@pytest.fixture(autouse=True)
def clear_global_approval_store():
    approval_store.clear()
    yield
    approval_store.clear()


def _approval_client(user_id: str = "user-1") -> TestClient:
    app = FastAPI()
    service = ApprovalStore()
    app.include_router(approvals_router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    app.dependency_overrides[get_approval_service] = lambda: service
    return TestClient(app)


def test_governance_models_are_registered_for_database_initialization():
    assert "approval_request" in Base.metadata.tables
    assert "approval_event" in Base.metadata.tables
    assert "tool_audit_event" in Base.metadata.tables
    assert ApprovalRequest.__table__.columns["approval_id"].index is True
    assert ApprovalEvent.__table__.columns["event_type"].nullable is False
    assert ToolAuditEvent.__table__.columns["status"].index is True


def test_governance_status_does_not_claim_hitl_closed_loop_without_database():
    ApprovalGovernanceManager.mark_database_unavailable(
        "database unavailable",
        app_env="production",
    )
    production_snapshot = ApprovalGovernanceManager.get_status_snapshot()

    assert production_snapshot["status"] == "not_ready"
    assert production_snapshot["storage"] == "postgres"
    assert production_snapshot["persistent"] is False
    assert production_snapshot["hitl_closed_loop"] is False
    assert production_snapshot["memory_fallback_allowed"] is False

    ApprovalGovernanceManager.mark_database_unavailable(
        "database unavailable",
        app_env="development",
    )
    development_snapshot = ApprovalGovernanceManager.get_status_snapshot()

    assert development_snapshot["status"] == "not_ready"
    assert development_snapshot["storage"] == "memory"
    assert development_snapshot["fallback_mode"] == "dev_memory"
    assert development_snapshot["memory_fallback_allowed"] is True
    assert development_snapshot["hitl_closed_loop"] is False

    ApprovalGovernanceManager.configure_uninitialized(app_env="development")


def test_sensitive_action_policies_separate_record_only_and_forced_approval():
    order_policy = get_sensitive_action_policy("生成订单号")
    payment_policy = get_sensitive_action_policy("real_payment")
    profile_export_policy = get_sensitive_action_policy("导出客户资料")

    assert order_policy.action == "generate_order_id"
    assert order_policy.requires_approval is False
    assert order_policy.is_blocking is False
    assert "真实支付" in order_policy.governance_boundary
    assert action_requires_approval("real_payment") is True
    assert payment_policy.future_reserved is True
    assert profile_export_policy.requires_approval is True


def test_approval_store_supports_approve_reject_and_expire():
    store = ApprovalStore()

    payment = store.mark_sensitive_action(
        action="real_payment",
        reason="未来接入真实支付前必须审批",
        user_id="user-1",
        expires_in_seconds=60,
        now=100.0,
    )
    assert payment.status == "pending"
    assert payment.expires_at == 160.0

    approved = store.approve(
        payment.approval_id,
        decided_by="user-1",
        decision_reason="确认只是测试审批流",
        now=120.0,
    )
    assert approved.status == "approved"
    assert approved.decided_by == "user-1"
    assert approved.decision_reason == "确认只是测试审批流"
    payment_events = store.list_events(payment.approval_id)
    assert [event.event_type for event in payment_events] == ["created", "approved"]
    assert payment_events[1].from_status == "pending"
    assert payment_events[1].to_status == "approved"

    rejected_payment = store.mark_sensitive_action(
        action="real_booking",
        reason="未来真实预订必须审批",
        user_id="user-1",
        now=200.0,
    )
    rejected = store.reject(
        rejected_payment.approval_id,
        decided_by="user-1",
        decision_reason="供应链未接入",
        now=210.0,
    )
    assert rejected.status == "rejected"

    expiring_payment = store.mark_sensitive_action(
        action="send_sms",
        reason="短信发送审批测试",
        user_id="user-1",
        expires_in_seconds=1,
        now=300.0,
    )
    expired = store.get(expiring_payment.approval_id, now=302.0)
    assert expired.status == "expired"
    expiring_events = store.list_events(expiring_payment.approval_id)
    assert [event.event_type for event in expiring_events] == ["created", "expired"]
    assert expiring_events[1].metadata["auto_expired"] is True

    with pytest.raises(ApprovalStateError):
        store.approve(expiring_payment.approval_id, decided_by="user-1", now=303.0)


def test_approval_api_marks_lists_approves_and_rejects_records():
    client = _approval_client()

    create_response = client.post(
        "/api/v1/approvals",
        json={
            "action": "real_payment",
            "reason": "未来真实支付占位审批",
            "conversation_id": "session-1",
            "metadata": {"token": "secret-token", "note": "仅测试"},
            "expires_in_seconds": 60,
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["status"] == "pending"
    assert created["requires_approval"] is True
    assert created["metadata"]["token"] == "[REDACTED]"

    list_response = client.get("/api/v1/approvals", params={"status": "pending"})
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1

    approve_response = client.post(
        f"/api/v1/approvals/{created['approval_id']}/approve",
        json={"reason": "测试通过"},
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"

    events_response = client.get(f"/api/v1/approvals/{created['approval_id']}/events")
    assert events_response.status_code == 200
    events = events_response.json()["events"]
    assert [event["event_type"] for event in events] == ["created", "approved"]
    assert events[0]["metadata"]["requires_approval"] is True

    second_response = client.post(
        "/api/v1/approvals",
        json={
            "action": "real_booking",
            "reason": "未来真实预订占位审批",
            "expires_in_seconds": 60,
        },
    )
    second = second_response.json()
    reject_response = client.post(
        f"/api/v1/approvals/{second['approval_id']}/reject",
        json={"reason": "供应链未接入"},
    )
    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "rejected"


def test_approval_api_can_query_policies_and_expire_pending_record():
    client = _approval_client()

    policies_response = client.get("/api/v1/approvals/policies")
    assert policies_response.status_code == 200
    policy_actions = {policy["action"] for policy in policies_response.json()}
    assert {
        "generate_order_id",
        "export_final_report",
        "real_payment",
        "send_sms",
        "export_customer_profile",
    }.issubset(policy_actions)

    create_response = client.post(
        "/api/v1/approvals",
        json={
            "action": "send_sms",
            "reason": "未来短信发送占位审批",
            "expires_in_seconds": 60,
        },
    )
    approval_id = create_response.json()["approval_id"]
    expire_response = client.post(f"/api/v1/approvals/{approval_id}/expire")
    assert expire_response.status_code == 200
    assert expire_response.json()["status"] == "expired"


def test_generate_order_tool_records_non_blocking_governance_boundary():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "budget_summarization",
            "user_requirement": {
                "departure_city": "北京",
                "destination": "上海",
                "departure_date": "2026-05-10",
                "travel_days": 3,
                "adult_count": 2,
                "children_count": 0,
                "budget_min": 2000.0,
                "budget_max": 6000.0,
                "budget_level": "comfort",
                "travel_styles": ["culture", "food"],
                "special_needs": "生成最终报告即可，不做真实支付",
            },
            "selected_destination": "上海",
            "selected_transport": "train",
            "selected_accommodation_types": ["economy_hotel"],
            "selected_food_types": ["local"],
            "budget": {
                "transport": 1200.0,
                "accommodation": 1600.0,
                "food": 900.0,
                "attractions": 200.0,
                "misc": 300.0,
                "total": 4200.0,
                "per_person": 2100.0,
                "currency": "CNY",
                "total_people": 2,
                "travel_days": 3,
                "nights": 2,
                "line_items": [],
                "assumptions": ["当前预算为规划估算，正式预订前需复核。"],
                "confidence_level": "偏低",
                "confirmed_items": [],
                "estimated_items": ["交通和住宿价格待二次核实。"],
                "verification_items": ["正式支付或预订前复核实时价格。"],
            },
        }
    )

    command = generate_order_tool.invoke({"runtime": _build_runtime(state)})
    update = command.update
    report_data = update["report_data"]
    approval_summary = report_data["tool_audit_summary"]["approval"]

    assert update["approval_action"] == "generate_order_id"
    assert update["approval_status"] == "none"
    assert update["approval_pending"] is False
    assert update["approval_required"] is False
    assert update["approval_record_id"].startswith("APR-")
    assert "真实支付" in update["approval_governance"]["boundary"]
    assert approval_summary["record_only"] is True
    assert approval_summary["is_blocking"] is False
    assert report_data["evidence_bundle"]["approval_governance"] == approval_summary
    assert "审批治理" in update["report"]
    assert "未来接入真实支付或真实预订时必须先完成人工审批" in update["messages"][0].content
    assert "pay.example.com" not in update["messages"][0].content

    records = approval_store.list_records(user_id="user-1", action="generate_order_id")
    assert len(records) == 1
    assert records[0].approval_id == update["approval_record_id"]


def test_sanitize_approval_metadata_redacts_sensitive_keys():
    metadata = sanitize_approval_metadata(
        {
            "api_key": "secret",
            "phone": "18800000000",
            "safe_note": "可公开测试说明",
        }
    )

    assert metadata["api_key"] == "[REDACTED]"
    assert metadata["phone"] == "[REDACTED]"
    assert metadata["safe_note"] == "可公开测试说明"
