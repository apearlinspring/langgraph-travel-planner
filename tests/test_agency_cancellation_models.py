from __future__ import annotations

import warnings
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy.exc import SAWarning
from sqlalchemy.orm import configure_mappers

from app.models import (
    AgencyOrder,
    AgencyOrderCancellationCase,
    AgencyOrderCancellationEvent,
    AgencyOrderCompensationRecord,
    AgencyOrderReconciliationRecord,
)
from app.models.base import Base
from app.models.migration_contract import BUSINESS_MANAGED_TABLES


CANCELLATION_MODELS = (
    AgencyOrderCancellationCase,
    AgencyOrderCancellationEvent,
    AgencyOrderCompensationRecord,
    AgencyOrderReconciliationRecord,
)
CANCELLATION_TABLES = {
    model.__tablename__ for model in CANCELLATION_MODELS
}


def _named_constraints(model, constraint_type) -> dict[str, object]:
    return {
        constraint.name: constraint
        for constraint in model.__table__.constraints
        if isinstance(constraint, constraint_type) and constraint.name
    }


def _constraint_sql(model, name: str) -> str:
    constraint = next(
        item
        for item in model.__table__.constraints
        if item.name == name
    )
    return str(constraint.sqltext)


def _foreign_key_targets(constraint: ForeignKeyConstraint) -> tuple[str, ...]:
    return tuple(element.target_fullname for element in constraint.elements)


def test_cancellation_models_are_registered_and_migration_owned():
    assert CANCELLATION_TABLES.issubset(Base.metadata.tables)
    assert CANCELLATION_TABLES.issubset(BUSINESS_MANAGED_TABLES)


def test_cancellation_relationships_configure_without_write_conflicts():
    with warnings.catch_warnings():
        warnings.simplefilter("error", SAWarning)
        configure_mappers()

    order_cases = AgencyOrder.__mapper__.relationships["cancellation_cases"]
    case_order = AgencyOrderCancellationCase.__mapper__.relationships["order"]
    assert order_cases.back_populates == "order"
    assert case_order.back_populates == "cancellation_cases"
    assert order_cases.uselist is True
    assert case_order.uselist is False

    case_relationships = AgencyOrderCancellationCase.__mapper__.relationships
    assert case_relationships["events"].back_populates == "cancellation_case"
    assert (
        case_relationships["compensation_records"].back_populates
        == "cancellation_case"
    )
    assert (
        case_relationships["reconciliation_records"].back_populates
        == "cancellation_case"
    )
    for relationship_name in (
        "events",
        "compensation_records",
        "reconciliation_records",
    ):
        assert "delete" not in case_relationships[relationship_name].cascade


def test_cancellation_model_columns_are_explicit_and_stable():
    expected = {
        "agency_order_cancellation_case": {
            "id",
            "agency_id",
            "branch_id",
            "order_id",
            "customer_id",
            "revision",
            "status",
            "order_revision_at_request",
            "reason_code",
            "reason_detail",
            "supplier_cancel_required",
            "refund_required",
            "approved_refund_amount",
            "currency",
            "requested_by_user_id",
            "requested_at",
            "review_decision",
            "reviewed_by_user_id",
            "reviewed_at",
            "review_note",
            "external_action_triggered",
            "completed_at",
            "created_at",
            "updated_at",
        },
        "agency_order_cancellation_event": {
            "id",
            "agency_id",
            "branch_id",
            "order_id",
            "customer_id",
            "cancellation_case_id",
            "event_sequence",
            "case_revision",
            "event_type",
            "actor_user_id",
            "payload_hash",
            "event_metadata",
            "created_at",
        },
        "agency_order_compensation_record": {
            "id",
            "agency_id",
            "branch_id",
            "order_id",
            "customer_id",
            "cancellation_case_id",
            "record_sequence",
            "case_revision",
            "action_type",
            "outcome",
            "external_reference_hash",
            "evidence_hash",
            "amount",
            "currency",
            "occurred_at",
            "recorded_by_user_id",
            "system_external_action_triggered",
            "created_at",
        },
        "agency_order_reconciliation_record": {
            "id",
            "agency_id",
            "branch_id",
            "order_id",
            "customer_id",
            "cancellation_case_id",
            "compensation_record_id",
            "case_revision",
            "outcome",
            "observed_amount",
            "currency",
            "reconciled_by_user_id",
            "evidence_hash",
            "reconciled_at",
            "created_at",
        },
    }
    for model in CANCELLATION_MODELS:
        assert {column.name for column in model.__table__.columns} == (
            expected[model.__tablename__]
        )


def test_case_revision_status_four_eyes_and_reason_contract():
    case = AgencyOrderCancellationCase
    assert case.__mapper__.version_id_col.name == "revision"
    assert case.__table__.columns["revision"].default.arg == 1
    assert case.__table__.columns["status"].default.arg == "approval_pending"
    assert case.__table__.columns["reason_detail"].type.length == 500
    assert case.__table__.columns["review_note"].type.length == 500

    status_sql = _constraint_sql(
        case,
        "ck_agency_order_cancellation_case_status",
    )
    for status in (
        "approval_pending",
        "rejected",
        "action_pending",
        "reconciliation_pending",
        "manual_intervention",
        "completed",
    ):
        assert status in status_sql

    reason_sql = _constraint_sql(
        case,
        "ck_agency_order_cancellation_case_reason_code",
    )
    for reason in (
        "customer_request",
        "customer_consent_withdrawn",
        "agency_unable_to_fulfill",
        "supplier_unavailable",
        "duplicate_order",
        "pricing_or_booking_error",
        "force_majeure",
        "compliance_or_risk",
    ):
        assert reason in reason_sql

    assert "reviewed_by_user_id <> requested_by_user_id" in _constraint_sql(
        case,
        "ck_agency_order_cancellation_case_four_eyes",
    )
    assert "revision >= 1" in _constraint_sql(
        case,
        "ck_agency_order_cancellation_case_revision",
    )
    review_shape = _constraint_sql(
        case,
        "ck_agency_order_cancellation_case_review_shape",
    )
    assert "review_decision = 'approved'" in review_shape
    assert "review_decision = 'rejected'" in review_shape
    assert review_shape.count("review_decision IS NOT NULL") == 3
    assert "completed_at IS NOT NULL" in review_shape


def test_external_action_flags_are_boolean_false_by_default_and_checked():
    checks = (
        (
            AgencyOrderCancellationCase,
            "external_action_triggered",
            "ck_agency_order_cancellation_case_external_action",
        ),
        (
            AgencyOrderCompensationRecord,
            "system_external_action_triggered",
            "ck_agency_order_compensation_record_external_action",
        ),
    )
    for model, column_name, check_name in checks:
        column = model.__table__.columns[column_name]
        assert isinstance(column.type, Boolean)
        assert column.nullable is False
        assert column.default.arg is False
        assert str(column.server_default.arg).lower() == "false"
        assert "NOT" in _constraint_sql(model, check_name).upper()


def test_money_currency_hash_and_sequence_constraints_are_present():
    for model, column_name in (
        (AgencyOrderCancellationCase, "approved_refund_amount"),
        (AgencyOrderCompensationRecord, "amount"),
        (AgencyOrderReconciliationRecord, "observed_amount"),
    ):
        amount = model.__table__.columns[column_name].type
        assert isinstance(amount, Numeric)
        assert amount.precision == 18
        assert amount.scale == 2
        assert amount.asdecimal is True
        assert amount.python_type is Decimal

    compensation_checks = _named_constraints(
        AgencyOrderCompensationRecord,
        CheckConstraint,
    )
    assert {
        "ck_agency_order_compensation_record_sequence",
        "ck_agency_order_compensation_record_revision",
        "ck_agency_order_compensation_record_action",
        "ck_agency_order_compensation_record_outcome",
        "ck_agency_order_compensation_record_amount",
        "ck_agency_order_compensation_record_currency",
        "ck_agency_order_compensation_record_reference_hash",
        "ck_agency_order_compensation_record_evidence_hash",
        "ck_agency_order_compensation_record_supplier_amount",
    }.issubset(compensation_checks)
    reconciliation_checks = _named_constraints(
        AgencyOrderReconciliationRecord,
        CheckConstraint,
    )
    assert {
        "ck_agency_order_reconciliation_record_revision",
        "ck_agency_order_reconciliation_record_outcome",
        "ck_agency_order_reconciliation_record_evidence_hash",
        "ck_agency_order_reconciliation_record_amount",
    }.issubset(reconciliation_checks)
    reconciliation_amount_sql = str(
        reconciliation_checks[
            "ck_agency_order_reconciliation_record_amount"
        ].sqltext
    )
    assert "observed_amount IS NOT NULL" in reconciliation_amount_sql
    assert "currency IS NOT NULL" in reconciliation_amount_sql


def test_open_case_partial_unique_index_is_order_scoped():
    index = next(
        item
        for item in AgencyOrderCancellationCase.__table__.indexes
        if item.name == "uq_agency_order_cancellation_case_open"
    )
    assert index.unique is True
    assert tuple(column.name for column in index.columns) == (
        "agency_id",
        "order_id",
    )
    where = str(index.dialect_options["postgresql"]["where"])
    for open_status in (
        "approval_pending",
        "action_pending",
        "reconciliation_pending",
        "manual_intervention",
    ):
        assert open_status in where
    assert "completed" not in where
    assert "rejected" not in where


def test_composite_bindings_prevent_cross_tenant_branch_order_or_case_links():
    case_fks = _named_constraints(
        AgencyOrderCancellationCase,
        ForeignKeyConstraint,
    )
    case_order = case_fks["fk_agency_order_cancellation_case_order"]
    assert tuple(case_order.column_keys) == (
        "agency_id",
        "branch_id",
        "customer_id",
        "order_id",
    )
    assert _foreign_key_targets(case_order) == (
        "agency_order.agency_id",
        "agency_order.branch_id",
        "agency_order.customer_id",
        "agency_order.id",
    )

    expected_case_columns = (
        "agency_id",
        "branch_id",
        "order_id",
        "customer_id",
        "cancellation_case_id",
    )
    expected_case_targets = (
        "agency_order_cancellation_case.agency_id",
        "agency_order_cancellation_case.branch_id",
        "agency_order_cancellation_case.order_id",
        "agency_order_cancellation_case.customer_id",
        "agency_order_cancellation_case.id",
    )
    for model, name in (
        (
            AgencyOrderCancellationEvent,
            "fk_agency_order_cancellation_event_case",
        ),
        (
            AgencyOrderCompensationRecord,
            "fk_agency_order_compensation_record_case",
        ),
        (
            AgencyOrderReconciliationRecord,
            "fk_agency_order_reconciliation_record_case",
        ),
    ):
        constraint = _named_constraints(model, ForeignKeyConstraint)[name]
        assert tuple(constraint.column_keys) == expected_case_columns
        assert _foreign_key_targets(constraint) == expected_case_targets

    compensation_fk = _named_constraints(
        AgencyOrderReconciliationRecord,
        ForeignKeyConstraint,
    )["fk_agency_order_reconciliation_record_compensation"]
    assert tuple(compensation_fk.column_keys) == (
        *expected_case_columns,
        "compensation_record_id",
    )
    assert _foreign_key_targets(compensation_fk)[-1] == (
        "agency_order_compensation_record.id"
    )


def test_sequence_and_one_reconciliation_uniqueness_are_explicit():
    event_uniques = _named_constraints(
        AgencyOrderCancellationEvent,
        UniqueConstraint,
    )
    event_sequence = event_uniques[
        "uq_agency_order_cancellation_event_sequence"
    ]
    assert tuple(column.name for column in event_sequence.columns)[-1] == (
        "event_sequence"
    )

    compensation_uniques = _named_constraints(
        AgencyOrderCompensationRecord,
        UniqueConstraint,
    )
    record_sequence = compensation_uniques[
        "uq_agency_order_compensation_record_sequence"
    ]
    assert tuple(column.name for column in record_sequence.columns)[-1] == (
        "record_sequence"
    )

    reconciliation_unique = _named_constraints(
        AgencyOrderReconciliationRecord,
        UniqueConstraint,
    )["uq_agency_order_reconciliation_compensation"]
    assert tuple(
        column.name for column in reconciliation_unique.columns
    ) == ("compensation_record_id",)


def test_order_exposes_request_timestamp_and_composite_case_parent_key():
    cancellation_requested_at = AgencyOrder.__table__.columns[
        "cancellation_requested_at"
    ]
    assert cancellation_requested_at.nullable is True

    order_unique = _named_constraints(AgencyOrder, UniqueConstraint)[
        "uq_agency_order_branch_customer_id"
    ]
    assert tuple(column.name for column in order_unique.columns) == (
        "agency_id",
        "branch_id",
        "customer_id",
        "id",
    )
