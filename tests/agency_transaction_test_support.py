from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace


AGENCY_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
BRANCH_ID = uuid.UUID("10000000-0000-0000-0000-000000000002")
ADVISOR_ID = uuid.UUID("20000000-0000-0000-0000-000000000001")
CUSTOMER_ID = uuid.UUID("30000000-0000-0000-0000-000000000001")
BUSINESS_CUSTOMER_ID = uuid.UUID("30000000-0000-0000-0000-000000000002")
QUOTE_ID = uuid.UUID("40000000-0000-0000-0000-000000000001")
ORDER_ID = uuid.UUID("50000000-0000-0000-0000-000000000001")
EVENT_ID = uuid.UUID("60000000-0000-0000-0000-000000000001")
REVIEW_ID = uuid.UUID("70000000-0000-0000-0000-000000000001")
APPROVER_ID = uuid.UUID("80000000-0000-0000-0000-000000000001")
MEMBERSHIP_ID = uuid.UUID("90000000-0000-0000-0000-000000000001")
ROLE_GRANT_ID = uuid.UUID("a0000000-0000-0000-0000-000000000001")
ASSIGNMENT_ID = uuid.UUID("b0000000-0000-0000-0000-000000000001")
NOW = datetime(2030, 1, 1, 8, 0, tzinfo=UTC)


def copy_record(record: SimpleNamespace, **updates) -> SimpleNamespace:
    payload = vars(record).copy()
    payload.update(updates)
    return SimpleNamespace(**payload)


def quote_record(**updates) -> SimpleNamespace:
    payload = {
        "id": QUOTE_ID,
        "quote_no": "Q-20300101-1234567890ABCDEF",
        "agency_id": AGENCY_ID,
        "branch_id": BRANCH_ID,
        "customer_id": BUSINESS_CUSTOMER_ID,
        "user_id": CUSTOMER_ID,
        "conversation_id": None,
        "product_id": None,
        "status": "draft",
        "revision": 1,
        "payload_hash": "a" * 64,
        "total_amount": Decimal("1288.50"),
        "currency": "CNY",
        "snapshot_version": "agency_quote.v1",
        "quote_snapshot": {"destination": "杭州", "days": 3},
        "valid_until": datetime(2030, 1, 3, 8, 0, tzinfo=UTC),
        "issued_at": None,
        "accepted_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(updates)
    return SimpleNamespace(**payload)


def order_record(**updates) -> SimpleNamespace:
    payload = {
        "id": ORDER_ID,
        "order_no": "ORDER-20300101-1234567890ABCDEF",
        "agency_id": AGENCY_ID,
        "branch_id": BRANCH_ID,
        "customer_id": BUSINESS_CUSTOMER_ID,
        "quote_id": QUOTE_ID,
        "user_id": CUSTOMER_ID,
        "status": "draft",
        "revision": 1,
        "payload_hash": "b" * 64,
        "payment_status": "not_started",
        "fulfillment_status": "not_started",
        "total_amount": Decimal("1288.50"),
        "currency": "CNY",
        "quote_snapshot": {"destination": "杭州", "days": 3},
        "external_action_enabled": False,
        "confirmed_at": None,
        "cancellation_requested_at": None,
        "cancelled_at": None,
        "completed_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(updates)
    return SimpleNamespace(**payload)


def event_record() -> SimpleNamespace:
    return SimpleNamespace(
        id=EVENT_ID,
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        order_id=ORDER_ID,
        event_sequence=1,
        order_revision=1,
        event_type="order_created",
        from_status=None,
        to_status="draft",
        actor_user_id=CUSTOMER_ID,
        payload_hash="b" * 64,
        event_metadata={
            "quote_id": str(QUOTE_ID),
            "quote_snapshot": {"customer_phone": "不应出现在事件响应中"},
            "external_actions_triggered": False,
        },
        created_at=NOW,
    )


def review_record(**updates) -> SimpleNamespace:
    payload = {
        "id": REVIEW_ID,
        "agency_id": AGENCY_ID,
        "branch_id": BRANCH_ID,
        "order_id": ORDER_ID,
        "status": "pending",
        "order_revision": 2,
        "decision_order_revision": None,
        "payload_hash": "b" * 64,
        "total_amount": Decimal("1288.50"),
        "currency": "CNY",
        "requested_by_user_id": CUSTOMER_ID,
        "decided_by_user_id": None,
        "decision_reason": None,
        "decided_at": None,
        "created_at": NOW,
        "updated_at": NOW,
        "quote_snapshot": {"customer_phone": "不应出现在审核 DTO 中"},
    }
    payload.update(updates)
    return SimpleNamespace(**payload)


class ScalarResult:
    def __init__(self, value) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.value


class ExecuteSequence:
    def __init__(self, *values) -> None:
        self.values = list(values)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return ScalarResult(self.values.pop(0))
