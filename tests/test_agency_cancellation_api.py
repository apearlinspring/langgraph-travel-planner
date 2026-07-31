from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agency.errors import (
    AgencyTransactionAccessDenied,
    AgencyTransactionConflict,
    AgencyTransactionNotFound,
    AgencyTransactionPersistenceError,
    AgencyTransactionValidationError,
)
from app.api.dependencies import get_current_user
from app.api.v1 import agency_cancellations as cancellation_api
from app.schemas.agency_cancellation import (
    AgencyCancellationRequest,
    AgencyCancellationResumeRequest,
    AgencyCancellationReviewRequest,
    AgencyManualCancellationResultRequest,
    AgencyManualCancellationResultResponse,
    AgencyManualResultReconcileRequest,
)

AGENCY_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
BRANCH_ID = uuid.UUID("20000000-0000-0000-0000-000000000001")
CUSTOMER_ID = uuid.UUID("30000000-0000-0000-0000-000000000001")
ORDER_ID = uuid.UUID("40000000-0000-0000-0000-000000000001")
CASE_ID = uuid.UUID("50000000-0000-0000-0000-000000000001")
RECORD_ID = uuid.UUID("60000000-0000-0000-0000-000000000001")
RECONCILIATION_ID = uuid.UUID(
    "70000000-0000-0000-0000-000000000001"
)
EVENT_ID = uuid.UUID("80000000-0000-0000-0000-000000000001")
ACTOR_ID = uuid.UUID("90000000-0000-0000-0000-000000000001")
NOW = datetime(2030, 1, 2, 8, 30, tzinfo=timezone.utc)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64

REASON_CODES = (
    "customer_request",
    "customer_consent_withdrawn",
    "agency_unable_to_fulfill",
    "supplier_unavailable",
    "duplicate_order",
    "pricing_or_booking_error",
    "force_majeure",
    "compliance_or_risk",
)
SENSITIVE_RESPONSE_KEYS = {
    "reason_detail",
    "review_note",
    "external_reference_hash",
    "evidence_hash",
    "payload_hash",
    "event_metadata",
    "requested_by_user_id",
    "reviewed_by_user_id",
    "recorded_by_user_id",
    "reconciled_by_user_id",
    "actor_user_id",
}


def _case_record(**changes):
    values = {
        "id": CASE_ID,
        "agency_id": AGENCY_ID,
        "branch_id": BRANCH_ID,
        "order_id": ORDER_ID,
        "customer_id": CUSTOMER_ID,
        "revision": 1,
        "status": "approval_pending",
        "order_revision_at_request": 7,
        "reason_code": "customer_request",
        "reason_detail": "不得出现在响应中的客户原始说明",
        "supplier_cancel_required": True,
        "refund_required": True,
        "approved_refund_amount": None,
        "currency": "CNY",
        "requested_by_user_id": ACTOR_ID,
        "requested_at": NOW,
        "review_decision": None,
        "reviewed_by_user_id": None,
        "reviewed_at": None,
        "review_note": "不得出现在响应中的审批备注",
        "external_action_triggered": False,
        "completed_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _manual_result_record():
    return SimpleNamespace(
        id=RECORD_ID,
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        order_id=ORDER_ID,
        customer_id=CUSTOMER_ID,
        cancellation_case_id=CASE_ID,
        record_sequence=1,
        case_revision=3,
        action_type="refund",
        outcome="succeeded",
        external_reference_hash=SHA_A,
        evidence_hash=SHA_B,
        amount=Decimal("12.34"),
        currency="CNY",
        occurred_at=NOW,
        recorded_by_user_id=ACTOR_ID,
        system_external_action_triggered=False,
        created_at=NOW,
    )


def _reconciliation_record():
    return SimpleNamespace(
        id=RECONCILIATION_ID,
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        order_id=ORDER_ID,
        customer_id=CUSTOMER_ID,
        cancellation_case_id=CASE_ID,
        compensation_record_id=RECORD_ID,
        case_revision=4,
        outcome="matched",
        observed_amount=Decimal("12.34"),
        currency="CNY",
        reconciled_by_user_id=ACTOR_ID,
        evidence_hash=SHA_C,
        reconciled_at=NOW,
        created_at=NOW,
    )


def _event_record():
    return SimpleNamespace(
        id=EVENT_ID,
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        order_id=ORDER_ID,
        customer_id=CUSTOMER_ID,
        cancellation_case_id=CASE_ID,
        event_sequence=1,
        case_revision=1,
        event_type="cancellation_requested",
        actor_user_id=ACTOR_ID,
        payload_hash=SHA_A,
        event_metadata={"internal_note": "不得出现在响应中"},
        created_at=NOW,
    )


class _FakeCancellationService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.errors: dict[str, Exception] = {}
        self.case = _case_record()
        self.manual_result = _manual_result_record()
        self.reconciliation = _reconciliation_record()
        self.event = _event_record()

    def _capture(self, name: str, values: dict) -> None:
        error = self.errors.get(name)
        if error is not None:
            raise error
        self.calls.append((name, values))

    async def request_cancellation(self, **kwargs):
        self._capture("request_cancellation", kwargs)
        return self.case

    async def get_cancellation_case(self, **kwargs):
        self._capture("get_cancellation_case", kwargs)
        return self.case

    async def list_cancellation_cases(self, **kwargs):
        self._capture("list_cancellation_cases", kwargs)
        return [self.case], 1

    async def review_cancellation(self, **kwargs):
        self._capture("review_cancellation", kwargs)
        return _case_record(
            revision=2,
            status="action_pending",
            approved_refund_amount=Decimal("12.34"),
            review_decision="approved",
            reviewed_by_user_id=ACTOR_ID,
            reviewed_at=NOW,
        )

    async def record_manual_result(self, **kwargs):
        self._capture("record_manual_result", kwargs)
        return self.manual_result

    async def list_manual_results(self, **kwargs):
        self._capture("list_manual_results", kwargs)
        return [(self.manual_result, "matched")], 1

    async def reconcile_manual_result(self, **kwargs):
        self._capture("reconcile_manual_result", kwargs)
        return self.reconciliation

    async def resume_cancellation(self, **kwargs):
        self._capture("resume_cancellation", kwargs)
        return _case_record(
            revision=5,
            status="action_pending",
            approved_refund_amount=Decimal("12.34"),
            review_decision="approved",
            reviewed_by_user_id=ACTOR_ID,
            reviewed_at=NOW,
        )

    async def list_cancellation_events(self, **kwargs):
        self._capture("list_cancellation_events", kwargs)
        return [self.event], 1


def _build_client(service: _FakeCancellationService) -> TestClient:
    app = FastAPI()
    app.include_router(cancellation_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=ACTOR_ID,
        preferences={"role": "user"},
    )
    app.dependency_overrides[
        cancellation_api.get_cancellation_service
    ] = lambda: service
    return TestClient(app)


def _assert_no_sensitive_response_keys(value) -> None:
    if isinstance(value, dict):
        assert not (SENSITIVE_RESPONSE_KEYS & value.keys())
        for item in value.values():
            _assert_no_sensitive_response_keys(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_sensitive_response_keys(item)


@pytest.mark.parametrize("reason_code", REASON_CODES)
def test_cancellation_request_accepts_only_declared_reason_codes(
    reason_code: str,
):
    request = AgencyCancellationRequest.model_validate(
        {
            "expected_order_revision": 1,
            "reason_code": reason_code,
        }
    )

    assert request.reason_code == reason_code


@pytest.mark.parametrize(
    "reason_code",
    ["other", "CUSTOMER_REQUEST", "customer-request", ""],
)
def test_cancellation_request_rejects_unknown_reason_codes(reason_code: str):
    with pytest.raises(ValidationError):
        AgencyCancellationRequest.model_validate(
            {
                "expected_order_revision": 1,
                "reason_code": reason_code,
            }
        )


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (
            AgencyCancellationRequest,
            {
                "expected_order_revision": 1,
                "reason_code": "customer_request",
            },
        ),
        (
            AgencyCancellationReviewRequest,
            {"expected_revision": 1, "decision": "approve"},
        ),
        (
            AgencyManualCancellationResultRequest,
            {
                "expected_revision": 2,
                "action_type": "supplier_cancel",
                "outcome": "succeeded",
                "external_reference_sha256": SHA_A,
                "evidence_sha256": SHA_B,
                "occurred_at": NOW.isoformat(),
            },
        ),
        (
            AgencyManualResultReconcileRequest,
            {
                "expected_revision": 3,
                "outcome": "matched",
                "evidence_sha256": SHA_C,
            },
        ),
        (
            AgencyCancellationResumeRequest,
            {"expected_revision": 4},
        ),
    ],
)
def test_all_cancellation_request_schemas_forbid_extra_fields(
    schema,
    payload: dict,
):
    with pytest.raises(ValidationError) as exc_info:
        schema.model_validate({**payload, "internal_override": True})

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


def test_manual_result_schema_normalizes_hash_currency_and_timezone():
    request = AgencyManualCancellationResultRequest.model_validate(
        {
            "expected_revision": 2,
            "action_type": "refund",
            "outcome": "succeeded",
            "external_reference_sha256": SHA_A.upper(),
            "evidence_sha256": SHA_B.upper(),
            "amount": "12.34",
            "currency": "cny",
            "occurred_at": "2030-01-02T08:30:00Z",
        }
    )

    assert request.external_reference_sha256 == SHA_A
    assert request.evidence_sha256 == SHA_B
    assert request.amount == Decimal("12.34")
    assert request.currency == "CNY"
    assert request.occurred_at.utcoffset() is not None


@pytest.mark.parametrize(
    "changes",
    [
        {"external_reference_sha256": "not-a-sha256"},
        {"evidence_sha256": "g" * 64},
        {"occurred_at": "2030-01-02T08:30:00"},
        {"amount": "-0.01"},
        {"currency": "人民币"},
    ],
)
def test_manual_result_schema_rejects_invalid_evidence_money_or_time(
    changes: dict,
):
    payload = {
        "expected_revision": 2,
        "action_type": "refund",
        "outcome": "succeeded",
        "external_reference_sha256": SHA_A,
        "evidence_sha256": SHA_B,
        "amount": "12.34",
        "currency": "CNY",
        "occurred_at": NOW.isoformat(),
    }

    with pytest.raises(ValidationError):
        AgencyManualCancellationResultRequest.model_validate(
            {**payload, **changes}
        )


def test_manual_result_schema_enforces_action_specific_amount_shape():
    with pytest.raises(ValidationError, match="amount"):
        AgencyManualCancellationResultRequest.model_validate(
            {
                "expected_revision": 2,
                "action_type": "refund",
                "outcome": "succeeded",
                "external_reference_sha256": SHA_A,
                "evidence_sha256": SHA_B,
                "occurred_at": NOW.isoformat(),
            }
        )

    with pytest.raises(ValidationError, match="不能提供"):
        AgencyManualCancellationResultRequest.model_validate(
            {
                "expected_revision": 2,
                "action_type": "supplier_cancel",
                "outcome": "succeeded",
                "external_reference_sha256": SHA_A,
                "evidence_sha256": SHA_B,
                "amount": "1.00",
                "currency": "CNY",
                "occurred_at": NOW.isoformat(),
            }
        )


def test_supplier_result_response_hides_storage_amount_placeholder():
    record = _manual_result_record()
    record.action_type = "supplier_cancel"
    record.amount = Decimal("0.00")
    record.currency = "CNY"

    response = AgencyManualCancellationResultResponse.model_validate(record)

    assert response.amount is None
    assert response.currency is None


def test_manual_result_queue_exposes_reconciliation_state_without_secrets():
    service = _FakeCancellationService()
    service.manual_result.action_type = "supplier_cancel"
    service.manual_result.amount = Decimal("0.00")
    service.manual_result.currency = "CNY"

    response = _build_client(service).get(
        f"/api/v1/agency/cancellation-cases/{CASE_ID}/manual-results",
        params={"limit": 7, "offset": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 7
    assert body["offset"] == 2
    assert body["results"][0]["id"] == str(RECORD_ID)
    assert body["results"][0]["reconciliation_outcome"] == "matched"
    assert body["results"][0]["amount"] is None
    assert body["results"][0]["currency"] is None
    _assert_no_sensitive_response_keys(body)
    assert dict(service.calls)["list_manual_results"] == {
        "actor_user_id": ACTOR_ID,
        "case_id": CASE_ID,
        "limit": 7,
        "offset": 2,
    }


def test_reconciliation_schema_requires_paired_independent_observation():
    request = AgencyManualResultReconcileRequest.model_validate(
        {
            "expected_revision": 3,
            "outcome": "matched",
            "observed_amount": "12.34",
            "observed_currency": "cny",
            "evidence_sha256": SHA_C.upper(),
        }
    )

    assert request.observed_amount == Decimal("12.34")
    assert request.observed_currency == "CNY"
    assert request.evidence_sha256 == SHA_C

    with pytest.raises(ValidationError, match="必须同时提供"):
        AgencyManualResultReconcileRequest.model_validate(
            {
                "expected_revision": 3,
                "outcome": "matched",
                "observed_amount": "12.34",
                "evidence_sha256": SHA_C,
            }
        )


def test_review_schema_requires_consistent_refund_fields_and_rejection_reason():
    with pytest.raises(ValidationError, match="必须同时提供"):
        AgencyCancellationReviewRequest.model_validate(
            {
                "expected_revision": 1,
                "decision": "approve",
                "approved_refund_amount": "12.34",
            }
        )

    with pytest.raises(ValidationError, match="必须填写 reason"):
        AgencyCancellationReviewRequest.model_validate(
            {
                "expected_revision": 1,
                "decision": "reject",
            }
        )

    with pytest.raises(ValidationError, match="ASCII"):
        AgencyCancellationReviewRequest.model_validate(
            {
                "expected_revision": 1,
                "decision": "approve",
                "approved_refund_amount": "12.34",
                "approved_refund_currency": "人民币",
            }
        )


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            f"/api/v1/agency/orders/{ORDER_ID}/cancellation-requests",
            {
                "expected_order_revision": 7,
                "reason_code": "customer_request",
            },
        ),
        (
            f"/api/v1/agency/cancellation-cases/{CASE_ID}/review",
            {"expected_revision": 1, "decision": "approve"},
        ),
        (
            f"/api/v1/agency/cancellation-cases/{CASE_ID}/manual-results",
            {
                "expected_revision": 2,
                "action_type": "supplier_cancel",
                "outcome": "succeeded",
                "external_reference_sha256": SHA_A,
                "evidence_sha256": SHA_B,
                "occurred_at": NOW.isoformat(),
            },
        ),
        (
            f"/api/v1/agency/manual-results/{RECORD_ID}/reconcile",
            {
                "expected_revision": 3,
                "outcome": "matched",
                "evidence_sha256": SHA_C,
            },
        ),
        (
            f"/api/v1/agency/cancellation-cases/{CASE_ID}/resume",
            {"expected_revision": 4},
        ),
    ],
)
def test_all_cancellation_posts_require_idempotency_key(
    path: str,
    payload: dict,
):
    response = _build_client(_FakeCancellationService()).post(
        path,
        json=payload,
    )

    assert response.status_code == 422


def test_cancellation_routes_forward_all_service_parameters_and_redact():
    service = _FakeCancellationService()
    client = _build_client(service)

    responses = [
        client.post(
            f"/api/v1/agency/orders/{ORDER_ID}/cancellation-requests",
            json={
                "expected_order_revision": 7,
                "reason_code": "customer_request",
                "reason_detail": "客户改变计划",
            },
            headers={"Idempotency-Key": "cancel-request-1"},
        ),
        client.get(
            f"/api/v1/agency/orders/{ORDER_ID}/cancellation-case"
        ),
        client.get(
            "/api/v1/agency/cancellation-cases",
            params={
                "agency_id": str(AGENCY_ID),
                "status": "manual_intervention",
                "limit": 9,
                "offset": 2,
            },
        ),
        client.post(
            f"/api/v1/agency/cancellation-cases/{CASE_ID}/review",
            json={
                "expected_revision": 1,
                "decision": "approve",
                "approved_refund_amount": "12.34",
                "approved_refund_currency": "cny",
                "reason": "  已复核  ",
            },
            headers={"Idempotency-Key": "cancel-review-1"},
        ),
        client.post(
            f"/api/v1/agency/cancellation-cases/{CASE_ID}/manual-results",
            json={
                "expected_revision": 2,
                "action_type": "refund",
                "outcome": "succeeded",
                "external_reference_sha256": SHA_A.upper(),
                "evidence_sha256": SHA_B.upper(),
                "amount": "12.34",
                "currency": "cny",
                "occurred_at": "2030-01-02T08:30:00Z",
            },
            headers={"Idempotency-Key": "cancel-result-1"},
        ),
            client.post(
                f"/api/v1/agency/manual-results/{RECORD_ID}/reconcile",
                json={
                    "expected_revision": 3,
                    "outcome": "matched",
                    "observed_amount": "12.34",
                    "observed_currency": "cny",
                    "evidence_sha256": SHA_C.upper(),
                },
                headers={"Idempotency-Key": "cancel-reconcile-1"},
        ),
        client.post(
            f"/api/v1/agency/cancellation-cases/{CASE_ID}/resume",
            json={"expected_revision": 4, "reason": "  继续处理  "},
            headers={"Idempotency-Key": "cancel-resume-1"},
        ),
        client.get(
            f"/api/v1/agency/cancellation-cases/{CASE_ID}/events",
            params={"limit": 11, "offset": 3},
        ),
    ]

    assert [response.status_code for response in responses] == [
        201,
        200,
        200,
        200,
        201,
        201,
        200,
        200,
    ]
    for response in responses:
        _assert_no_sensitive_response_keys(response.json())

    calls = dict(service.calls)
    assert calls["request_cancellation"] == {
        "actor_user_id": ACTOR_ID,
        "order_id": ORDER_ID,
        "expected_revision": 7,
        "reason_code": "customer_request",
        "reason_detail": "客户改变计划",
        "idempotency_key": "cancel-request-1",
    }
    assert calls["get_cancellation_case"] == {
        "actor_user_id": ACTOR_ID,
        "order_id": ORDER_ID,
    }
    assert calls["list_cancellation_cases"] == {
        "actor_user_id": ACTOR_ID,
        "agency_id": AGENCY_ID,
        "status_filter": "manual_intervention",
        "limit": 9,
        "offset": 2,
    }
    assert calls["review_cancellation"] == {
        "actor_user_id": ACTOR_ID,
        "case_id": CASE_ID,
        "decision": "approve",
        "expected_revision": 1,
        "approved_refund_amount": Decimal("12.34"),
        "approved_refund_currency": "CNY",
        "reason": "已复核",
        "idempotency_key": "cancel-review-1",
    }
    assert calls["record_manual_result"] == {
        "actor_user_id": ACTOR_ID,
        "case_id": CASE_ID,
        "expected_revision": 2,
        "action_type": "refund",
        "outcome": "succeeded",
        "external_reference_sha256": SHA_A,
        "evidence_sha256": SHA_B,
        "amount": Decimal("12.34"),
        "currency": "CNY",
        "occurred_at": NOW,
        "idempotency_key": "cancel-result-1",
    }
    assert calls["reconcile_manual_result"] == {
        "actor_user_id": ACTOR_ID,
            "record_id": RECORD_ID,
            "expected_revision": 3,
            "outcome": "matched",
            "observed_amount": Decimal("12.34"),
            "observed_currency": "CNY",
            "evidence_sha256": SHA_C,
            "idempotency_key": "cancel-reconcile-1",
        }
    assert calls["resume_cancellation"] == {
        "actor_user_id": ACTOR_ID,
        "case_id": CASE_ID,
        "expected_revision": 4,
        "reason": "继续处理",
        "idempotency_key": "cancel-resume-1",
    }
    assert calls["list_cancellation_events"] == {
        "actor_user_id": ACTOR_ID,
        "case_id": CASE_ID,
        "limit": 11,
        "offset": 3,
    }

    manual_body = responses[4].json()
    assert manual_body["case_id"] == str(CASE_ID)
    assert manual_body["sequence"] == 1
    assert manual_body["system_external_action_triggered"] is False
    reconciliation_body = responses[5].json()
    assert reconciliation_body["case_id"] == str(CASE_ID)
    event_body = responses[7].json()["events"][0]
    assert event_body["case_id"] == str(CASE_ID)
    assert event_body["sequence"] == 1


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (
            AgencyTransactionNotFound("cancellation_not_found", "资源不存在"),
            404,
        ),
        (
            AgencyTransactionAccessDenied(
                "cancellation_access_denied",
                "没有权限",
            ),
            403,
        ),
        (
            AgencyTransactionConflict(
                "cancellation_state_conflict",
                "状态冲突",
            ),
            409,
        ),
        (
            AgencyTransactionValidationError(
                "cancellation_invalid",
                "业务字段无效",
            ),
            422,
        ),
        (
            AgencyTransactionPersistenceError(
                "cancellation_persistence_unavailable",
                "数据服务不可用",
            ),
            503,
        ),
    ],
)
def test_cancellation_api_maps_domain_errors(error, expected_status: int):
    service = _FakeCancellationService()
    service.errors["get_cancellation_case"] = error

    response = _build_client(service).get(
        f"/api/v1/agency/orders/{ORDER_ID}/cancellation-case"
    )

    assert response.status_code == expected_status
    assert response.json()["detail"]["code"] == error.code
