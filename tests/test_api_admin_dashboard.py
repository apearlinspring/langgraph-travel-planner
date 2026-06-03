from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.api.v1 import admin as admin_api
from app.models.base import get_db
from app.schemas.admin import (
    AdminApprovalSummary,
    AdminConversationDetailResponse,
    AdminConversationListResponse,
    AdminConversationMessageSummary,
    AdminConversationRuntimeSummary,
    AdminConversationSummary,
    AdminOverviewResponse,
    AdminUserDetailResponse,
    AdminUserListResponse,
    AdminUserRuntimeSummary,
    AdminUserSummary,
)


def _build_client(role: str = "admin") -> TestClient:
    app = FastAPI()
    app.include_router(admin_api.router, prefix="/api/v1")

    async def _override_db():
        yield object()

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="admin-user",
        preferences={"role": role},
    )
    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def test_admin_dashboard_requires_operator_role():
    client = _build_client(role="user")

    response = client.get("/api/v1/admin/overview")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "permission_denied"


def test_admin_overview_returns_summary(monkeypatch):
    client = _build_client(role="approver")

    async def _fake_overview(_db):
        return AdminOverviewResponse(
            total_users=12,
            total_conversations=34,
            active_conversations=21,
            pending_approvals=3,
            generated_at=datetime.now(UTC),
        )

    monkeypatch.setattr(admin_api, "_build_admin_overview", _fake_overview)

    response = client.get("/api/v1/admin/overview")

    assert response.status_code == 200
    assert response.json()["pending_approvals"] == 3


def test_admin_users_and_conversations_return_payloads(monkeypatch):
    client = _build_client(role="admin")

    async def _fake_users(_db, *, limit, query_text, role_filter):
        assert limit == 20
        assert query_text is None
        assert role_filter == "all"
        return AdminUserListResponse(
            users=[
                AdminUserSummary(
                    id="00000000-0000-0000-0000-000000000001",
                    username="alice",
                    email="alice@example.com",
                    role="admin",
                    created_at=datetime.now(UTC),
                    conversation_count=5,
                )
            ],
            total=1,
        )

    async def _fake_conversations(_db, *, limit, status_filter, query_text, role_filter):
        assert limit == 10
        assert status_filter == "active"
        assert query_text is None
        assert role_filter == "all"
        return AdminConversationListResponse(
            conversations=[
                AdminConversationSummary(
                    id="00000000-0000-0000-0000-000000000011",
                    user_id="00000000-0000-0000-0000-000000000001",
                    username="alice",
                    email="alice@example.com",
                    role="admin",
                    title="川西 3 天 2 晚",
                    status="active",
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                    message_count=8,
                )
            ],
            total=1,
        )

    monkeypatch.setattr(admin_api, "_list_admin_users", _fake_users)
    monkeypatch.setattr(admin_api, "_list_admin_conversations", _fake_conversations)

    users_response = client.get("/api/v1/admin/users")
    conversations_response = client.get(
        "/api/v1/admin/conversations",
        params={"limit": 10, "status": "active"},
    )

    assert users_response.status_code == 200
    assert users_response.json()["users"][0]["conversation_count"] == 5
    assert conversations_response.status_code == 200
    assert conversations_response.json()["conversations"][0]["message_count"] == 8


def test_admin_filters_pass_query_params(monkeypatch):
    client = _build_client(role="admin")

    captured = {}

    async def _fake_users(_db, *, limit, query_text, role_filter):
        captured["users"] = {
            "limit": limit,
            "query_text": query_text,
            "role_filter": role_filter,
        }
        return AdminUserListResponse(users=[], total=0)

    async def _fake_conversations(_db, *, limit, status_filter, query_text, role_filter):
        captured["conversations"] = {
            "limit": limit,
            "status_filter": status_filter,
            "query_text": query_text,
            "role_filter": role_filter,
        }
        return AdminConversationListResponse(conversations=[], total=0)

    monkeypatch.setattr(admin_api, "_list_admin_users", _fake_users)
    monkeypatch.setattr(admin_api, "_list_admin_conversations", _fake_conversations)

    users_response = client.get(
        "/api/v1/admin/users",
        params={"limit": 8, "q": "alice", "role": "admin"},
    )
    conversations_response = client.get(
        "/api/v1/admin/conversations",
        params={"limit": 6, "status": "all", "q": "川西", "role": "approver"},
    )

    assert users_response.status_code == 200
    assert conversations_response.status_code == 200
    assert captured["users"] == {
        "limit": 8,
        "query_text": "alice",
        "role_filter": "admin",
    }
    assert captured["conversations"] == {
        "limit": 6,
        "status_filter": "all",
        "query_text": "川西",
        "role_filter": "approver",
    }


def test_admin_conversation_detail_returns_runtime_messages_and_approvals(monkeypatch):
    client = _build_client(role="admin")

    async def _fake_detail(_db, *, conversation_id):
        assert conversation_id == "00000000-0000-0000-0000-000000000011"
        return AdminConversationDetailResponse(
            conversation=AdminConversationSummary(
                id="00000000-0000-0000-0000-000000000011",
                user_id="00000000-0000-0000-0000-000000000001",
                username="alice",
                email="alice@example.com",
                role="admin",
                title="川西 3 天 2 晚",
                status="active",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                message_count=8,
            ),
            runtime=AdminConversationRuntimeSummary(
                active_workflow="free_planning",
                current_step="budget_summarization",
                message_breakdown={"user": 3, "assistant": 5},
                has_latest_journey=True,
                has_final_report=True,
                latest_journey_saved_at=1717400000,
                latest_report_title="川西轻松 3 日旅行规划",
            ),
            recent_messages=[
                AdminConversationMessageSummary(
                    id="00000000-0000-0000-0000-000000000021",
                    role="assistant",
                    content_preview="这里是最近一条助手消息摘要。",
                    created_at=datetime.now(UTC),
                    has_journey_data=True,
                    has_report_data=True,
                )
            ],
            related_approvals=[
                AdminApprovalSummary(
                    approval_id="approval-1",
                    action="real_payment",
                    label="真实支付审批",
                    status="pending",
                    reason="未来真实支付接入前必须经过人工确认",
                    created_at=datetime.now(UTC),
                )
            ],
        )

    monkeypatch.setattr(admin_api, "_get_admin_conversation_detail", _fake_detail)

    response = client.get(
        "/api/v1/admin/conversations/00000000-0000-0000-0000-000000000011"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["runtime"]["active_workflow"] == "free_planning"
    assert payload["recent_messages"][0]["has_report_data"] is True
    assert payload["related_approvals"][0]["approval_id"] == "approval-1"


def test_admin_user_detail_returns_runtime_conversations_and_approvals(monkeypatch):
    client = _build_client(role="admin")

    async def _fake_detail(_db, *, user_id):
        assert user_id == "00000000-0000-0000-0000-000000000001"
        return AdminUserDetailResponse(
            user=AdminUserSummary(
                id="00000000-0000-0000-0000-000000000001",
                username="alice",
                email="alice@example.com",
                role="admin",
                created_at=datetime.now(UTC),
                conversation_count=5,
            ),
            runtime=AdminUserRuntimeSummary(
                active_conversation_count=2,
                pending_approval_count=1,
                latest_conversation_at=datetime.now(UTC),
            ),
            recent_conversations=[
                AdminConversationSummary(
                    id="00000000-0000-0000-0000-000000000011",
                    user_id="00000000-0000-0000-0000-000000000001",
                    username="alice",
                    email="alice@example.com",
                    role="admin",
                    title="川西 3 天 2 晚",
                    status="active",
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                    message_count=8,
                )
            ],
            recent_approvals=[
                AdminApprovalSummary(
                    approval_id="approval-1",
                    action="real_payment",
                    label="真实支付审批",
                    status="pending",
                    reason="未来真实支付接入前必须经过人工确认",
                    created_at=datetime.now(UTC),
                )
            ],
        )

    monkeypatch.setattr(admin_api, "_get_admin_user_detail", _fake_detail)

    response = client.get("/api/v1/admin/users/00000000-0000-0000-0000-000000000001")

    assert response.status_code == 200
    payload = response.json()
    assert payload["runtime"]["active_conversation_count"] == 2
    assert payload["recent_conversations"][0]["message_count"] == 8
    assert payload["recent_approvals"][0]["approval_id"] == "approval-1"
