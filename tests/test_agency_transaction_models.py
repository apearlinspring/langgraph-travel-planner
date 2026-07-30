from __future__ import annotations

import importlib.util
import warnings
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy.exc import SAWarning
from sqlalchemy.orm import Session, configure_mappers

from app.models import (
    Agency,
    AgencyBranch,
    AgencyCustomer,
    AgencyMembership,
    AgencyOrder,
    AgencyOrderEvent,
    AgencyOrderReview,
    AgencyQuote,
    FulfillmentRecord,
    IdempotencyRecord,
    PaymentAttempt,
    SupplierProduct,
    User,
)
from app.models.base import Base
from app.models.migration_contract import BUSINESS_MANAGED_TABLES


TRANSACTION_TABLES = (
    "agency",
    "agency_membership",
    "agency_customer",
    "supplier_product",
    "agency_quote",
    "agency_order",
    "agency_order_event",
    "idempotency_record",
    "payment_attempt",
    "fulfillment_record",
)


def _constraint_names(model, constraint_type) -> set[str]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, constraint_type)
    }


def _index_names(model) -> set[str]:
    return {index.name for index in model.__table__.indexes}


def test_agency_transaction_models_are_registered_and_migration_owned():
    assert set(TRANSACTION_TABLES).issubset(Base.metadata.tables)
    assert set(TRANSACTION_TABLES).issubset(BUSINESS_MANAGED_TABLES)
    assert "agency_order_review" in Base.metadata.tables
    assert "agency_order_review" in BUSINESS_MANAGED_TABLES


def test_agency_transaction_relationships_configure_without_write_conflicts():
    with warnings.catch_warnings():
        warnings.simplefilter("error", SAWarning)
        configure_mappers()


def test_quote_and_order_preserve_money_and_quote_snapshot_contract():
    quote_amount = AgencyQuote.__table__.columns["total_amount"].type
    order_amount = AgencyOrder.__table__.columns["total_amount"].type

    for amount_type in (quote_amount, order_amount):
        assert isinstance(amount_type, Numeric)
        assert amount_type.precision == 18
        assert amount_type.scale == 2
        assert amount_type.asdecimal is True
        assert amount_type.python_type is Decimal

    assert AgencyQuote.__table__.columns["currency"].type.length == 3
    assert AgencyQuote.__table__.columns["agency_id"].nullable is False
    assert AgencyQuote.__table__.columns["valid_until"].nullable is False
    assert AgencyQuote.__table__.columns["quote_snapshot"].nullable is False
    assert AgencyOrder.__table__.columns["agency_id"].nullable is False
    assert AgencyOrder.__table__.columns["quote_snapshot"].nullable is False
    assert AgencyOrder.__table__.columns["quote_id"].nullable is False
    assert AgencyQuote.__table__.columns["revision"].default.arg == 1
    assert AgencyOrder.__table__.columns["revision"].default.arg == 1
    assert AgencyQuote.__mapper__.version_id_col.name == "revision"
    assert AgencyOrder.__mapper__.version_id_col.name == "revision"
    assert AgencyQuote.__table__.columns["payload_hash"].nullable is False
    assert AgencyOrder.__table__.columns["payload_hash"].nullable is False

    assert {
        "ck_agency_quote_revision",
        "ck_agency_quote_payload_hash",
    }.issubset(_constraint_names(AgencyQuote, CheckConstraint))
    assert {
        "ck_agency_order_revision",
        "ck_agency_order_payload_hash",
    }.issubset(_constraint_names(AgencyOrder, CheckConstraint))
    assert {
        "uq_agency_quote_no",
        "uq_agency_quote_agency_idempotency",
    }.issubset(_constraint_names(AgencyQuote, UniqueConstraint))
    assert {
        "uq_agency_order_no",
        "uq_agency_order_quote",
        "uq_agency_order_agency_idempotency",
    }.issubset(_constraint_names(AgencyOrder, UniqueConstraint))
    order_status_sql = str(
        next(
            constraint
            for constraint in AgencyOrder.__table__.constraints
            if constraint.name == "ck_agency_order_status"
        ).sqltext
    )
    for status in (
        "pending_review",
        "approved",
        "review_rejected",
        "processing",
        "manual_intervention",
        "failed",
        "cancellation_pending",
    ):
        assert status in order_status_sql
    assert "pending_confirmation" not in order_status_sql
    assert "ix_agency_quote_valid_until" in _index_names(AgencyQuote)
    assert "ix_agency_order_agency_user_status" in _index_names(AgencyOrder)
    assert "ix_agency_quote_agency_status_created" in _index_names(AgencyQuote)
    assert "ix_agency_order_agency_status_created" in _index_names(AgencyOrder)


def test_agency_membership_and_transaction_tenant_boundaries_are_explicit():
    assert {
        "uq_agency_code",
    } == _constraint_names(Agency, UniqueConstraint)
    assert {
        "uq_agency_membership_agency_user",
        "uq_agency_membership_agency_id",
    }.issubset(_constraint_names(AgencyMembership, UniqueConstraint))
    assert {
        "uq_agency_customer_agency_user",
        "uq_agency_customer_branch_id",
        "uq_agency_customer_branch_no",
        "uq_agency_customer_quote_binding",
    }.issubset(_constraint_names(AgencyCustomer, UniqueConstraint))
    assert AgencyMembership.__table__.columns["agency_id"].nullable is False
    assert AgencyMembership.__table__.columns["user_id"].nullable is False
    assert AgencyCustomer.__table__.columns["agency_id"].nullable is False
    assert AgencyCustomer.__table__.columns["branch_id"].nullable is False
    assert AgencyCustomer.__table__.columns["user_id"].nullable is True
    membership_role_sql = str(
        next(
            constraint
            for constraint in AgencyMembership.__table__.constraints
            if constraint.name == "ck_agency_membership_role"
        ).sqltext
    )
    for role in (
        "travel_advisor",
        "booking_operator",
        "approver",
        "finance",
        "auditor",
        "branch_manager",
        "admin",
        "owner",
    ):
        assert role in membership_role_sql

    for model in (SupplierProduct, AgencyQuote, AgencyOrder):
        assert model.__table__.columns["agency_id"].nullable is False
    assert PaymentAttempt.__table__.columns["agency_id"].nullable is False
    assert FulfillmentRecord.__table__.columns["agency_id"].nullable is False

    supplier_unique = next(
        constraint
        for constraint in SupplierProduct.__table__.constraints
        if constraint.name == "uq_supplier_product_supplier_external"
    )
    assert [column.name for column in supplier_unique.columns] == [
        "agency_id",
        "supplier_code",
        "external_product_code",
    ]
    tenant_foreign_keys = {
        constraint.name: [column.name for column in constraint.columns]
        for model in (
            AgencyQuote,
            AgencyOrder,
            AgencyOrderEvent,
            PaymentAttempt,
            FulfillmentRecord,
        )
        for constraint in model.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint) and constraint.name
    }
    assert tenant_foreign_keys["fk_agency_quote_product_tenant"] == [
        "agency_id",
        "product_id",
    ]
    assert tenant_foreign_keys["fk_agency_quote_branch"] == [
        "agency_id",
        "branch_id",
    ]
    assert tenant_foreign_keys["fk_agency_quote_customer"] == [
        "agency_id",
        "branch_id",
        "customer_id",
        "user_id",
    ]
    assert tenant_foreign_keys["fk_agency_order_quote_binding"] == [
        "agency_id",
        "branch_id",
        "customer_id",
        "user_id",
        "quote_id",
    ]
    assert tenant_foreign_keys["fk_agency_order_customer"] == [
        "agency_id",
        "branch_id",
        "customer_id",
    ]
    assert tenant_foreign_keys["fk_agency_order_event_order_branch"] == [
        "agency_id",
        "branch_id",
        "order_id",
    ]
    assert tenant_foreign_keys["fk_payment_attempt_order_tenant"] == [
        "agency_id",
        "order_id",
    ]
    assert tenant_foreign_keys["fk_fulfillment_order_tenant"] == [
        "agency_id",
        "order_id",
    ]
    assert tenant_foreign_keys["fk_fulfillment_product_tenant"] == [
        "agency_id",
        "product_id",
    ]
    scoped_idempotency_constraints = (
        (
            AgencyQuote,
            "uq_agency_quote_agency_idempotency",
            ["agency_id", "idempotency_key"],
        ),
        (
            AgencyOrder,
            "uq_agency_order_agency_idempotency",
            ["agency_id", "idempotency_key"],
        ),
        (
            PaymentAttempt,
            "uq_payment_attempt_order_idempotency",
            ["order_id", "idempotency_key"],
        ),
        (
            FulfillmentRecord,
            "uq_fulfillment_order_idempotency",
            ["order_id", "idempotency_key"],
        ),
    )
    for model, constraint_name, expected_columns in scoped_idempotency_constraints:
        constraint = next(
            item
            for item in model.__table__.constraints
            if item.name == constraint_name
        )
        assert [column.name for column in constraint.columns] == expected_columns


def test_order_review_is_strongly_bound_and_enforces_four_eyes():
    amount_type = AgencyOrderReview.__table__.columns["total_amount"].type
    assert isinstance(amount_type, Numeric)
    assert (amount_type.precision, amount_type.scale) == (18, 2)
    assert amount_type.asdecimal is True
    assert AgencyOrderReview.__table__.columns["order_revision"].nullable is False
    assert AgencyOrderReview.__table__.columns["payload_hash"].nullable is False
    assert AgencyOrderReview.__table__.columns["currency"].type.length == 3

    assert {
        "ck_agency_order_review_status",
        "ck_agency_order_review_revision",
        "ck_agency_order_review_decision_revision",
        "ck_agency_order_review_payload_hash",
        "ck_agency_order_review_amount",
        "ck_agency_order_review_currency",
        "ck_agency_order_review_four_eyes",
        "ck_agency_order_review_decision_fields",
        "ck_agency_order_review_rejection_reason",
    }.issubset(_constraint_names(AgencyOrderReview, CheckConstraint))
    unique = next(
        constraint
        for constraint in AgencyOrderReview.__table__.constraints
        if constraint.name == "uq_agency_order_review_order_revision"
    )
    assert [column.name for column in unique.columns] == [
        "agency_id",
        "branch_id",
        "order_id",
        "order_revision",
    ]
    tenant_fk = next(
        constraint
        for constraint in AgencyOrderReview.__table__.constraints
        if constraint.name == "fk_agency_order_review_order_branch"
    )
    assert [column.name for column in tenant_fk.columns] == [
        "agency_id",
        "branch_id",
        "order_id",
    ]
    assert {
        "ix_agency_order_review_agency_status_created",
        "ix_agency_order_review_order_status",
    } == _index_names(AgencyOrderReview)


def test_payment_and_fulfillment_keep_idempotent_audit_ledgers():
    payment_amount = PaymentAttempt.__table__.columns["amount"].type
    assert isinstance(payment_amount, Numeric)
    assert payment_amount.precision == 18
    assert payment_amount.scale == 2
    assert payment_amount.asdecimal is True

    assert {
        "uq_payment_attempt_order_sequence",
        "uq_payment_attempt_order_idempotency",
    }.issubset(_constraint_names(PaymentAttempt, UniqueConstraint))
    assert {
        "uq_fulfillment_order_line_item",
        "uq_fulfillment_order_idempotency",
    }.issubset(_constraint_names(FulfillmentRecord, UniqueConstraint))

    for model in (
        Agency,
        AgencyMembership,
        AgencyCustomer,
        SupplierProduct,
        AgencyQuote,
        AgencyOrder,
        AgencyOrderReview,
        IdempotencyRecord,
        PaymentAttempt,
        FulfillmentRecord,
    ):
        assert model.__table__.columns["created_at"].nullable is False
        assert model.__table__.columns["updated_at"].nullable is False

    assert PaymentAttempt.__table__.columns["completed_at"].nullable is True
    assert FulfillmentRecord.__table__.columns["confirmed_at"].nullable is True
    assert FulfillmentRecord.__table__.columns["completed_at"].nullable is True
    assert "ix_payment_attempt_order_status" in _index_names(PaymentAttempt)
    assert "ix_fulfillment_order_status" in _index_names(FulfillmentRecord)


def test_order_event_is_append_only_and_generic_idempotency_is_scoped():
    assert "updated_at" not in AgencyOrderEvent.__table__.columns
    assert AgencyOrderEvent.__table__.columns["created_at"].nullable is False
    assert AgencyOrderEvent.__table__.columns["agency_id"].nullable is False
    assert {
        "uq_agency_order_event_sequence",
    }.issubset(_constraint_names(AgencyOrderEvent, UniqueConstraint))
    assert {
        "ck_agency_order_event_sequence",
        "ck_agency_order_event_revision",
        "ck_agency_order_event_payload_hash",
    }.issubset(_constraint_names(AgencyOrderEvent, CheckConstraint))

    idempotency_unique = next(
        constraint
        for constraint in IdempotencyRecord.__table__.constraints
        if constraint.name == "uq_idempotency_agency_scope_key"
    )
    assert [column.name for column in idempotency_unique.columns] == [
        "agency_id",
        "scope",
        "key",
    ]
    assert IdempotencyRecord.__table__.columns["request_hash"].nullable is False
    assert IdempotencyRecord.__table__.columns["resource_type"].nullable is True
    assert IdempotencyRecord.__table__.columns["resource_id"].nullable is True


def test_real_external_transaction_actions_default_to_disabled_without_db_lock():
    models = (AgencyOrder, PaymentAttempt, FulfillmentRecord)

    for model in models:
        enabled_column = model.__table__.columns["external_action_enabled"]
        assert enabled_column.nullable is False
        assert enabled_column.default.arg is False
        assert enabled_column.server_default is not None
        assert str(enabled_column.server_default.arg).lower() == "false"

        checks = {
            constraint.name
            for constraint in model.__table__.constraints
            if isinstance(constraint, CheckConstraint)
        }
        assert not any(
            name and name.endswith("external_actions_disabled")
            for name in checks
        )

    order_checks = _constraint_names(AgencyOrder, CheckConstraint)
    assert "ck_agency_order_status" in order_checks
    assert "ck_agency_order_payment_status" in order_checks
    assert "ck_agency_order_fulfillment_status" in order_checks
    assert "ck_payment_attempt_status" in _constraint_names(
        PaymentAttempt,
        CheckConstraint,
    )
    assert "ck_fulfillment_status" in _constraint_names(
        FulfillmentRecord,
        CheckConstraint,
    )


class _MigrationOperationRecorder:
    def __init__(self) -> None:
        self.created_tables: list[str] = []
        self.table_elements: dict[str, tuple[object, ...]] = {}
        self.created_indexes: list[tuple[str, str]] = []
        self.created_index_columns: dict[tuple[str, str], tuple[str, ...]] = {}
        self.dropped_indexes: list[tuple[str, str]] = []
        self.dropped_tables: list[str] = []
        self.executed_sql: list[str] = []

    def create_table(self, table_name: str, *args, **kwargs) -> None:
        self.created_tables.append(table_name)
        self.table_elements[table_name] = args

    def create_index(
        self,
        index_name: str,
        table_name: str,
        *args,
        **kwargs,
    ) -> None:
        self.created_indexes.append((index_name, table_name))
        self.created_index_columns[(index_name, table_name)] = tuple(
            args[0] if args else ()
        )

    def drop_index(self, index_name: str, *, table_name: str) -> None:
        self.dropped_indexes.append((index_name, table_name))

    def drop_table(self, table_name: str) -> None:
        self.dropped_tables.append(table_name)

    def execute(self, statement: str) -> None:
        self.executed_sql.append(statement)


def test_agency_transaction_migration_has_reversible_dependency_order():
    revision_path = Path(
        "alembic/versions/20260726_0002_agency_transaction_schema.py"
    )
    spec = importlib.util.spec_from_file_location(
        "agency_transaction_schema_revision",
        revision_path,
    )
    assert spec and spec.loader
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)

    assert revision.revision == "20260726_0002"
    assert revision.down_revision == "20260511_0001"

    recorder = _MigrationOperationRecorder()
    revision.op = recorder
    revision.upgrade()

    assert recorder.created_tables == list(TRANSACTION_TABLES)
    assert {
        table_name for _, table_name in recorder.created_indexes
    } == set(TRANSACTION_TABLES)
    models_by_table = {
        model.__tablename__: model
        for model in (
            Agency,
            AgencyMembership,
            AgencyCustomer,
            SupplierProduct,
            AgencyQuote,
            AgencyOrder,
            AgencyOrderEvent,
            IdempotencyRecord,
            PaymentAttempt,
            FulfillmentRecord,
        )
    }
    columns_added_by_0004 = {
        "agency_customer": {
            "branch_id",
            "customer_no",
            "source_type",
            "source_reference",
            "consent_status",
            "consent_version",
            "consent_evidence_hash",
            "consent_updated_at",
            "lifecycle_revision",
            "invited_at",
            "deactivated_at",
        },
        "agency_quote": {"branch_id", "customer_id"},
        "agency_order": {"branch_id", "customer_id"},
        "agency_order_event": {"branch_id"},
    }
    indexes_added_by_0004 = {
        "agency_customer": {"ix_agency_customer_branch_status"},
        "agency_quote": {"ix_agency_quote_branch_customer_status"},
        "agency_order": {"ix_agency_order_branch_customer_status"},
    }
    constraints_added_by_0004 = {
        "agency_membership": {"uq_agency_membership_agency_id"},
        "agency_customer": {
            "uq_agency_customer_branch_id",
            "uq_agency_customer_branch_no",
            "uq_agency_customer_quote_binding",
            "fk_agency_customer_branch",
            "ck_agency_customer_no",
            "ck_agency_customer_source",
            "ck_agency_customer_consent_status",
            "ck_agency_customer_consent_evidence_hash",
            "ck_agency_customer_consent_evidence",
            "ck_agency_customer_lifecycle_revision",
            "ck_agency_customer_deactivated",
        },
        "agency_quote": {
            "uq_agency_quote_order_binding",
            "fk_agency_quote_branch",
            "fk_agency_quote_customer",
        },
        "agency_order": {
            "uq_agency_order_branch_id",
            "fk_agency_order_quote_binding",
            "fk_agency_order_branch",
            "fk_agency_order_customer",
        },
        "agency_order_event": {"fk_agency_order_event_order_branch"},
    }
    constraints_replaced_by_0004 = {
        "agency_quote": {"uq_agency_quote_agency_user_id"},
        "agency_order": {"fk_agency_order_quote_tenant_user"},
        "agency_order_event": {"fk_agency_order_event_order_tenant"},
    }
    for table_name, model in models_by_table.items():
        migrated_elements = recorder.table_elements[table_name]
        migrated_columns = {
            element.name
            for element in migrated_elements
            if isinstance(element, Column)
        }
        assert migrated_columns == (
            {column.name for column in model.__table__.columns}
            - columns_added_by_0004.get(table_name, set())
        )

        migrated_indexes = {
            index_name
            for index_name, indexed_table in recorder.created_indexes
            if indexed_table == table_name
        }
        assert migrated_indexes == (
            _index_names(model) - indexes_added_by_0004.get(table_name, set())
        )

        migrated_named_constraints = {
            element.name
            for element in migrated_elements
            if isinstance(
                element,
                (CheckConstraint, ForeignKeyConstraint, UniqueConstraint),
            )
            and element.name
        }
        model_named_constraints = {
            constraint.name
            for constraint in model.__table__.constraints
            if isinstance(
                constraint,
                (CheckConstraint, ForeignKeyConstraint, UniqueConstraint),
            )
            and constraint.name
        }
        expected_baseline_constraints = (
            model_named_constraints
            - constraints_added_by_0004.get(table_name, set())
        ) | constraints_replaced_by_0004.get(table_name, set())
        assert migrated_named_constraints == expected_baseline_constraints

    membership_elements = recorder.table_elements["agency_membership"]
    membership_role_check = next(
        element
        for element in membership_elements
        if isinstance(element, CheckConstraint)
        and element.name == "ck_agency_membership_role"
    )
    assert "branch_manager" not in str(membership_role_check.sqltext)

    customer_elements = recorder.table_elements["agency_customer"]
    legacy_customer_user = next(
        element
        for element in customer_elements
        if isinstance(element, Column) and element.name == "user_id"
    )
    assert legacy_customer_user.nullable is False
    legacy_customer_status = next(
        element
        for element in customer_elements
        if isinstance(element, CheckConstraint)
        and element.name == "ck_agency_customer_status"
    )
    assert "invited" not in str(legacy_customer_status.sqltext)

    migrated_constraint_names = {
        element.name
        for elements in recorder.table_elements.values()
        for element in elements
        if isinstance(
            element,
            (CheckConstraint, ForeignKeyConstraint, UniqueConstraint),
        )
        and element.name
    }
    assert {
        "uq_agency_membership_agency_user",
        "uq_agency_customer_agency_user",
        "uq_agency_quote_agency_idempotency",
        "uq_agency_order_agency_idempotency",
        "uq_agency_order_event_sequence",
        "uq_idempotency_agency_scope_key",
        "uq_payment_attempt_order_idempotency",
        "uq_fulfillment_order_idempotency",
    }.issubset(migrated_constraint_names)

    revision.downgrade()

    assert recorder.dropped_tables == list(reversed(TRANSACTION_TABLES))
    assert {
        table_name for _, table_name in recorder.dropped_indexes
    } == set(TRANSACTION_TABLES)
    executed_sql = "\n".join(recorder.executed_sql)
    assert "CREATE TRIGGER trg_agency_order_event_append_only" in executed_sql
    assert "BEFORE UPDATE OR DELETE ON agency_order_event" in executed_sql
    assert "DROP TRIGGER trg_agency_order_event_append_only" in executed_sql


def test_order_review_migration_matches_the_strongly_typed_model():
    revision_path = Path(
        "alembic/versions/20260726_0003_agency_order_review.py"
    )
    spec = importlib.util.spec_from_file_location(
        "agency_order_review_revision",
        revision_path,
    )
    assert spec and spec.loader
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)

    assert revision.revision == "20260726_0003"
    assert revision.down_revision == "20260726_0002"

    recorder = _MigrationOperationRecorder()
    revision.op = recorder
    revision.upgrade()

    assert recorder.created_tables == ["agency_order_review"]
    migrated_elements = recorder.table_elements["agency_order_review"]
    migrated_columns = {
        element.name
        for element in migrated_elements
        if isinstance(element, Column)
    }
    assert migrated_columns == {
        column.name
        for column in AgencyOrderReview.__table__.columns
        if column.name != "branch_id"
    }
    migrated_indexes = {
        index_name
        for index_name, table_name in recorder.created_indexes
        if table_name == "agency_order_review"
    }
    assert migrated_indexes == _index_names(AgencyOrderReview)
    migrated_constraints = {
        element.name
        for element in migrated_elements
        if isinstance(
            element,
            (CheckConstraint, ForeignKeyConstraint, UniqueConstraint),
        )
        and element.name
    }
    model_constraints = {
        constraint.name
        for constraint in AgencyOrderReview.__table__.constraints
        if isinstance(
            constraint,
            (CheckConstraint, ForeignKeyConstraint, UniqueConstraint),
        )
        and constraint.name
    }
    assert migrated_constraints == (
        model_constraints
        - {"fk_agency_order_review_order_branch"}
    ) | {"fk_agency_order_review_order_tenant"}

    legacy_unique = next(
        element
        for element in migrated_elements
        if isinstance(element, UniqueConstraint)
        and element.name == "uq_agency_order_review_order_revision"
    )
    assert list(legacy_unique._pending_colargs) == [
        "agency_id",
        "order_id",
        "order_revision",
    ]
    legacy_tenant_fk = next(
        element
        for element in migrated_elements
        if isinstance(element, ForeignKeyConstraint)
        and element.name == "fk_agency_order_review_order_tenant"
    )
    assert list(legacy_tenant_fk.column_keys) == [
        "agency_id",
        "order_id",
    ]
    legacy_queue_index = next(
        element
        for element in recorder.created_indexes
        if element[0] == "ix_agency_order_review_agency_status_created"
    )
    assert legacy_queue_index == (
        "ix_agency_order_review_agency_status_created",
        "agency_order_review",
    )
    assert recorder.created_index_columns[legacy_queue_index] == (
        "agency_id",
        "status",
        "created_at",
        "id",
    )

    revision.downgrade()
    assert recorder.dropped_tables == ["agency_order_review"]
    assert {
        table_name for _, table_name in recorder.dropped_indexes
    } == {"agency_order_review"}
    executed_sql = "\n".join(recorder.executed_sql)
    assert "CREATE TRIGGER trg_agency_order_review_mutation_guard" in executed_sql
    assert "agency_order_review binding is immutable" in executed_sql
    assert "terminal agency_order_review is immutable" in executed_sql
    assert "DROP TRIGGER trg_agency_order_review_mutation_guard" in executed_sql


def test_initial_migration_skips_legacy_probe_for_offline_mock_connection(
    monkeypatch: pytest.MonkeyPatch,
):
    revision_path = Path(
        "alembic/versions/20260511_0001_initial_business_schema.py"
    )
    spec = importlib.util.spec_from_file_location(
        "initial_business_schema_revision",
        revision_path,
    )
    assert spec and spec.loader
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)

    monkeypatch.setattr(revision.op, "get_bind", lambda: object())

    def _raise_no_inspection(_bind):
        raise sa.exc.NoInspectionAvailable(
            "offline Alembic MockConnection cannot be inspected"
        )

    monkeypatch.setattr(revision.sa, "inspect", _raise_no_inspection)

    assert revision._bootstrap_legacy_create_all_schema() is False


def test_initial_migration_legacy_bootstrap_does_not_create_later_tables(
    monkeypatch: pytest.MonkeyPatch,
):
    revision_path = Path(
        "alembic/versions/20260511_0001_initial_business_schema.py"
    )
    spec = importlib.util.spec_from_file_location(
        "legacy_initial_business_schema_revision",
        revision_path,
    )
    assert spec and spec.loader
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)

    class _Inspector:
        @staticmethod
        def get_table_names():
            return ["user", "conversation", "message"]

    from app.models.base import Base

    captured: dict[str, object] = {}

    def _capture_create_all(*, bind, tables, checkfirst):
        captured["bind"] = bind
        captured["tables"] = [table.name for table in tables]
        captured["checkfirst"] = checkfirst

    bind = object()
    monkeypatch.setattr(revision.op, "get_bind", lambda: bind)
    monkeypatch.setattr(revision.sa, "inspect", lambda _bind: _Inspector())
    monkeypatch.setattr(Base.metadata, "create_all", _capture_create_all)

    assert revision._bootstrap_legacy_create_all_schema() is True
    assert captured == {
        "bind": bind,
        "tables": [
            "user",
            "conversation",
            "message",
            "approval_request",
            "approval_event",
            "tool_audit_event",
        ],
        "checkfirst": True,
    }


def test_sqlite_schema_blocks_relationship_driven_cross_tenant_reassignment():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")

    @sa.event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)

    with Session(engine, expire_on_commit=False) as session:
        user = User(
            username="tenant-boundary-user",
            email="tenant-boundary@example.test",
            password_hash="not-a-real-password-hash",
        )
        agency_a = Agency(
            agency_code="TENANT-A",
            name="旅行社 A",
            status="active",
        )
        agency_b = Agency(
            agency_code="TENANT-B",
            name="旅行社 B",
            status="active",
        )
        session.add_all([user, agency_a, agency_b])
        session.flush()
        branch_a = AgencyBranch(
            agency_id=agency_a.id,
            branch_code="MAIN",
            name="旅行社 A 总店",
            status="active",
        )
        session.add(branch_a)
        session.flush()
        customer_a = AgencyCustomer(
            agency_id=agency_a.id,
            branch_id=branch_a.id,
            customer_no="CUSTOMER-A",
            user_id=user.id,
            source_type="test",
            status="prospect",
            consent_status="unknown",
        )
        session.add(customer_a)
        session.flush()
        product_a = SupplierProduct(
            agency_id=agency_a.id,
            supplier_code="SUPPLIER-A",
            external_product_code="PRODUCT-A",
            name="A 租户产品",
            product_type="package",
            status="active",
        )
        product_b = SupplierProduct(
            agency_id=agency_b.id,
            supplier_code="SUPPLIER-B",
            external_product_code="PRODUCT-B",
            name="B 租户产品",
            product_type="package",
            status="active",
        )
        session.add_all([product_a, product_b])
        session.flush()
        quote = AgencyQuote(
            quote_no="QUOTE-TENANT-BOUNDARY",
            idempotency_key="quote-tenant-boundary",
            agency_id=agency_a.id,
            branch_id=branch_a.id,
            customer_id=customer_a.id,
            user_id=user.id,
            product_id=product_a.id,
            status="draft",
            revision=1,
            payload_hash="a" * 64,
            total_amount=Decimal("100.00"),
            currency="CNY",
            quote_snapshot={"version": "test"},
            valid_until=now + timedelta(days=1),
        )
        session.add(quote)
        session.commit()

        agency_a_id = agency_a.id
        quote_id = quote.id
        product_b_id = product_b.id

    with Session(engine) as session:
        quote = session.get(AgencyQuote, quote_id)
        product_b = session.get(SupplierProduct, product_b_id)
        assert quote is not None
        assert product_b is not None
        assert quote.agency_id == agency_a_id

        quote.product = product_b

        with pytest.raises(sa.exc.IntegrityError):
            session.flush()

    engine.dispose()
